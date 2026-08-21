"""
LLM 客户端模块
负责调用各种 LLM API，支持重试、熔断、流式输出、并发控制、故障转移等功能。
"""

import asyncio, atexit, random, re, time
from collections import deque
from typing import Dict, Any, Optional
from enum import Enum
from dataclasses import dataclass
import httpx
from loguru import logger


from app.core.config import get


_llm = None
_retryable_exceptions_cache = None


def _get_litellm():
    """惰性加载 litellm（重依赖，首次导入需数秒，仅实际调用 LLM 时才加载）。"""
    global _llm
    if _llm is None:
        import litellm as _lm

        _llm = _lm
    return _llm


def __getattr__(name: str):
    """PEP 562：litellm / acompletion 按需提供，兼容 monkeypatch。"""
    if name == "litellm":
        lm = _get_litellm()
        globals()["litellm"] = lm
        return lm
    if name == "acompletion":
        lm = _get_litellm()
        globals()["acompletion"] = lm.acompletion
        return lm.acompletion
    raise AttributeError(name)


def _get_acompletion():
    """返回 acompletion 可调用对象。

    优先取模块 dict（兼容测试 monkeypatch），否则惰性加载 litellm 并缓存。
    注意：函数体内的裸名走 LOAD_GLOBAL，不会触发模块级 __getattr__（PEP 562 仅对
    ``module.attr`` 属性访问生效），因此调用点必须经此函数解析。
    """
    fn = globals().get("acompletion")
    if fn is None:
        lm = _get_litellm()
        fn = lm.acompletion
        globals()["acompletion"] = fn
    return fn


def _retryable_exceptions():
    """返回可重试异常类型元组（缓存结果，避免每次调用都重新构建）。"""
    global _retryable_exceptions_cache
    if _retryable_exceptions_cache is None:
        lm = _get_litellm()
        _retryable_exceptions_cache = (
            lm.exceptions.APIConnectionError,
            lm.exceptions.APIError,
            lm.exceptions.Timeout,
            lm.exceptions.RateLimitError,
            lm.exceptions.ServiceUnavailableError,
            lm.exceptions.BadGatewayError,
            lm.exceptions.InternalServerError,
            ConnectionError,
            TimeoutError,
        )
    return _retryable_exceptions_cache


class LLMCallError(Exception):
    """LLM 调用错误"""

    def __init__(self, m, orig=None):
        super().__init__(m)
        self.original_error = orig


class StopReason(Enum):
    """调用停止原因枚举"""

    SUCCESS = "success"  # 成功完成
    USER_CANCELLED = "user_cancelled"  # 用户取消
    MAX_RETRIES = "max_retries"  # 重试次数用完
    UNRECOVERABLE = "unrecoverable"  # 无法恢复的错误
    FALLBACK = "fallback"  # 降级到备用模型
    STREAM_FALLBACK = "stream_fallback"  # 流式降级到非流式


@dataclass
class LLMResponse:
    """LLM 响应数据类"""

    content: str  # 响应内容
    model: str  # 使用的模型
    usage: Dict[str, int]  # token 使用量
    finish_reason: str  # 结束原因
    stop_reason: StopReason  # 停止原因
    retry_count: int = 0  # 重试次数
    raw_response: Any = None  # 原始响应


def _truncate(text: str, limit: int = 400) -> str:
    """截断长文本用于日志，避免刷屏（上限默认 400，可配置）。"""
    if limit is None:
        limit = get("ai_pool.log_truncate_chars", 400)
    if text is None:
        return ""
    text = str(text).replace("\n", "\\n")
    return (
        text
        if len(text) <= limit
        else text[:limit] + f"...[+{len(text) - limit} chars]"
    )


class EndpointHealth:
    """
    端点健康状态管理器（以 capability.id 为 key）
    记录失败次数，连续失败 max_failures 次进入冷却期；
    冷却期结束进入半开状态（放行一次探测），成功即恢复健康。
    """

    def __init__(self, max_failures: int = 3, cooldown_seconds: int = 30):
        self.max_failures = max_failures  # 连续失败多少次进入冷却
        self.cooldown_seconds = cooldown_seconds  # 冷却时长(秒)
        self.failures: Dict[str, int] = {}  # 失败次数
        self.last_success: Dict[str, float] = {}  # 上次成功时间
        self.cooldown_until: Dict[str, float] = {}  # 冷却截止时间
        self._lock = asyncio.Lock()

    async def record_success(self, ep):
        """记录成功，清零失败计数并解除冷却"""
        async with self._lock:
            self.failures[ep] = 0
            self.last_success[ep] = time.time()
            self.cooldown_until.pop(ep, None)

    async def record_failure(self, ep):
        """记录失败，连续失败 max_failures 次就进入冷却期"""
        async with self._lock:
            self.failures[ep] = self.failures.get(ep, 0) + 1
            if self.failures[ep] >= self.max_failures:
                self.cooldown_until[ep] = time.time() + self.cooldown_seconds

    async def is_available(self, ep):
        """检查端点是否可用（半开探测：冷却期返回 False，冷却结束放行一次）"""
        async with self._lock:
            if ep in self.cooldown_until:
                if time.time() < self.cooldown_until[ep]:
                    return False
                # 冷却结束 → 半开状态：放行一次探测，由 record_success/failure 决定后续
                self.cooldown_until.pop(ep, None)
            return True


class _RateLimiter:
    """简单滑动窗口限流器：窗口(秒)内最多放行 capacity 次请求。"""

    def __init__(self, capacity: int, window: float = 60.0):
        self._capacity = max(1, int(capacity or 60))
        self._window = float(window or 60.0)
        self._times: deque = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """等待直到窗口内有额度。"""
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._times and now - self._times[0] >= self._window:
                    self._times.popleft()
                if len(self._times) < self._capacity:
                    self._times.append(now)
                    return
                wait = self._window - (now - self._times[0])
            await asyncio.sleep(min(wait, 0.5))


async def _interruptible_sleep(duration, cancel_event):
    """
    可中断的睡眠
    如果取消事件触发，会提前结束睡眠。
    """
    if not cancel_event:
        await asyncio.sleep(duration)
        return
    try:
        await asyncio.wait_for(cancel_event.wait(), timeout=duration)
        raise LLMCallError("用户取消")
    except asyncio.TimeoutError:
        pass


def _ensure_model_prefix(cap, model: str) -> str:
    """确保模型名称有前缀（比如 openai/xxx, deepseek/xxx）"""
    if "/" not in model:
        # 自定义端点（OpenAI 兼容代理）走 openai 前缀最稳妥
        if cap and cap.endpoint:
            return f"openai/{model}"
        # 官方 DeepSeek 端点识别 DeepSeek 系列模型（含 V4）
        if re.match(r"^deepseek[-/]", model):
            return f"deepseek/{model}"
        return f"openai/{model}"
    return model


class LLMClient:
    """
    LLM 客户端核心类
    支持：重试、熔断、流式输出、并发控制、限流、故障转移等功能。
    """

    def __init__(self):
        # 重试配置
        self.default_retry = get(
            "ai_pool.retry",
            {
                "max_retries": 5,
                "base_delay": 1.0,
                "max_delay": 30.0,
                "exponential_base": 2,
            },
        )

        # 并发控制
        mc = get("ai_pool.concurrency.max_concurrent_calls", 10)
        self._global_sem = asyncio.Semaphore(mc)  # 全局信号量
        # 每个端点的限制
        self._ep_sems = {
            ep: asyncio.Semaphore(lim)
            for ep, lim in get("ai_pool.concurrency.per_endpoint_limit", {}).items()
        }
        self._unlimited_sem = asyncio.Semaphore(10**6)  # 未配置端点限流时用无上限信号量

        # 每端点滑动窗口限流（容量=rate_limit_per_minute，窗口 60s）
        self._rate_limiters: Dict[str, _RateLimiter] = {}
        self._rate_limit_capacity = get("ai_pool.rate_limit_per_minute", 60)
        self._rate_limit_window = get("ai_pool.rate_limit_window_seconds", 60)

        self.health = EndpointHealth(
            max_failures=get("ai_pool.max_failures", 3),
            cooldown_seconds=get("ai_pool.cooldown_seconds", 30),
        )  # 健康检查
        self._http_client = None
        self._http_configured = False
        self._client_lock = asyncio.Lock()
        self._global_cancel_event = None  # 全局取消事件
        self._stream_usages: Dict[str, dict] = {}  # 按 usage_key 隔离的流式用量
        self._last_stream_usage_key: Optional[str] = None
        self._max_stream_usages = 100

    async def _ensure_http_client(self):
        """首次真实调用时再配置 litellm 的 httpx 客户端（避免导入期加载 litellm）。"""
        if self._http_configured:
            return
        try:
            _get_litellm()._async_client = httpx.AsyncClient(
                limits=httpx.Limits(
                    max_keepalive_connections=50,
                    max_connections=200,
                    keepalive_expiry=30,
                ),
                timeout=httpx.Timeout(60, connect=10),
                http2=True,
            )
        except Exception as e:
            logger.warning(f"httpx 客户端配置失败: {e}")
        self._http_configured = True

    def set_global_cancel_event(self, ev):
        """设置全局取消事件"""
        self._global_cancel_event = ev

    def _endpoint_sem(self, cap):
        """端点信号量：未配置 per-endpoint 限制时用无上限信号量。"""
        return self._ep_sems.get(cap.endpoint, self._unlimited_sem)

    def _rate_limiter(self, cap) -> _RateLimiter:
        """每个端点一个滑动窗口限流器（懒创建，key=endpoint）。"""
        key = cap.endpoint or "default"
        rl = self._rate_limiters.get(key)
        if rl is None:
            rl = _RateLimiter(self._rate_limit_capacity, self._rate_limit_window)
            self._rate_limiters[key] = rl
        return rl

    def _stream_guard(self, gen, cap):
        """流式路径的并发控制包装：进入生成器时统一获取全局+端点信号量与限流。"""

        async def _wrapped():
            async with self._global_sem:
                async with self._endpoint_sem(cap):
                    await self._rate_limiter(cap).acquire()
                    async for chunk in gen:
                        yield chunk

        return _wrapped()

    async def call(
        self,
        capability,
        messages,
        temperature=None,
        max_tokens=None,
        cancellation_event=None,
        max_retries=None,
        infinite_retry=False,
        stream=False,
        fallback_capabilities=None,
        usage_key: Optional[str] = None,
        **kwargs,
    ):
        """
        统一的调用入口
        流式/非流式两条路径都在这里统一获取并发信号量与限流，内部不再重复获取。
        """
        await self._ensure_http_client()
        cancel_evt = cancellation_event or self._global_cancel_event
        if stream:
            gen = self._call_stream(
                capability,
                messages,
                temperature,
                max_tokens,
                cancel_evt,
                max_retries,
                infinite_retry,
                fallback_capabilities,
                usage_key=usage_key,
                **kwargs,
            )
            return self._stream_guard(gen, capability)
        async with self._global_sem:
            async with self._endpoint_sem(capability):
                await self._rate_limiter(capability).acquire()
                return await self._call_non_stream(
                    capability,
                    messages,
                    temperature,
                    max_tokens,
                    cancel_evt,
                    max_retries,
                    infinite_retry,
                    fallback_capabilities,
                    **kwargs,
                )

    async def _try_call(
        self,
        cap,
        messages,
        temp,
        max_tok,
        cancel_evt,
        max_retries,
        infinite_retry,
        **kwargs,
    ):
        """
        尝试调用单个端点，包含重试逻辑
        使用指数退避策略，不会一开始就放弃治疗。
        """
        model = _ensure_model_prefix(cap, cap.model)
        params = {
            "model": model,
            "messages": messages,
            "api_base": cap.endpoint or None,
            "api_key": cap.api_key or None,
            **cap.parameters,
        }
        if temp is not None:
            params["temperature"] = temp
        if max_tok is not None:
            params["max_tokens"] = max_tok
        params.update(kwargs)

        # 请求入参（DEBUG）：记录模型/端点/消息，不含 api_key
        try:
            logger.debug(
                f"[LLM] -> POST {model} (endpoint={cap.endpoint or 'default'} "
                f"temperature={temp} max_tokens={max_tok})"
            )
            for m in messages:
                role = m.get("role", "?")
                content = _truncate(m.get("content", ""))
                logger.debug(f"[LLM]   {role}: {content}")
        except Exception:
            pass

        # 重试参数
        limit = (
            float("inf")
            if infinite_retry
            else (max_retries or self.default_retry["max_retries"])
        )
        attempt, base, mx, exp = (
            0,
            self.default_retry["base_delay"],
            self.default_retry["max_delay"],
            self.default_retry["exponential_base"],
        )

        while True:
            # 检查是否取消
            if cancel_evt and cancel_evt.is_set():
                raise LLMCallError("用户取消")

            try:
                resp = await _get_acompletion()(**params)
                # usage / choices 缺省安全处理（usage 为 None 时按 0 计）
                usage_obj = getattr(resp, "usage", None)
                usage = {
                    "prompt_tokens": (
                        getattr(usage_obj, "prompt_tokens", 0) if usage_obj else 0
                    ),
                    "completion_tokens": (
                        getattr(usage_obj, "completion_tokens", 0) if usage_obj else 0
                    ),
                    "total_tokens": (
                        getattr(usage_obj, "total_tokens", 0) if usage_obj else 0
                    ),
                }
                choices = getattr(resp, "choices", None) or []
                if not choices:
                    raise LLMCallError(f"响应缺少 choices: {resp}")
                message = getattr(choices[0], "message", None)
                # content 为 None 时回退 reasoning_content（thinking 模式）
                content = (
                    getattr(message, "content", None)
                    or getattr(message, "reasoning_content", None)
                    or ""
                )
                finish_reason = getattr(choices[0], "finish_reason", "")
                await self.health.record_success(cap.id)
                logger.debug(
                    f"[LLM] <- {getattr(resp, 'model', cap.model)} "
                    f"finish={finish_reason} usage={usage} retry={attempt} "
                    f"content={_truncate(content)}"
                )
                return LLMResponse(
                    content=content,
                    model=getattr(resp, "model", cap.model),
                    usage=usage,
                    finish_reason=finish_reason,
                    stop_reason=StopReason.SUCCESS,
                    retry_count=attempt,
                    raw_response=resp,
                )
            except Exception as e:
                attempt += 1
                await self.health.record_failure(cap.id)

                # 不可重试的错误直接抛出
                if not isinstance(e, _retryable_exceptions()):
                    raise LLMCallError(f"不可重试错误: {e}", e)

                # 重试次数用完
                if not infinite_retry and attempt > limit:
                    raise LLMCallError(f"重试{limit}次仍失败", e)

                # 计算延迟（指数退避 + 随机抖动）
                delay = min(base * (exp ** (attempt - 1)), mx) + random.uniform(
                    0, min(base * (exp ** (attempt - 1)), mx) * 0.1
                )
                logger.warning(
                    f"LLM调用失败(尝试{attempt}): {e}. {delay:.2f}s后重试..."
                )

                try:
                    await _interruptible_sleep(delay, cancel_evt)
                except LLMCallError:
                    raise

    async def _call_non_stream(
        self,
        cap,
        messages,
        temp,
        max_tok,
        cancel_evt,
        max_retries,
        infinite_retry,
        fallback_caps=None,
        **kwargs,
    ):
        """
        非流式调用
        支持故障转移：主端点失败（含不可重试类错误）也会尝试 fallback 端点一次，
        全部失败才抛出。
        """
        caps = [cap]
        if fallback_caps:
            caps.extend(fallback_caps)

        last_exc = None
        skipped = []
        for idx, c in enumerate(caps):
            # 不健康的端点跳过（冷却中）
            if not await self.health.is_available(c.id):
                skipped.append(f"{c.id}({c.endpoint})")
                continue
            try:
                res = await self._try_call(
                    c,
                    messages,
                    temp,
                    max_tok,
                    cancel_evt,
                    max_retries,
                    infinite_retry=infinite_retry,
                    **kwargs,
                )
                if idx > 0:
                    res.stop_reason = StopReason.FALLBACK  # 标记为降级调用
                return res
            except LLMCallError as e:
                last_exc = e
                # 不可重试错误也继续尝试 fallback 端点，全部失败再 raise
                logger.warning(
                    f"端点 {c.id} 调用失败: {_truncate(str(e), 300)}，尝试下一端点"
                )

        if last_exc is None:
            # 全部端点被冷却跳过：构造带端点明细的异常信息
            detail = "、".join(skipped) or "无可用端点"
            raise LLMCallError(f"所有端点均不可用（被冷却跳过）: {detail}")
        raise last_exc

    async def _call_stream(
        self,
        cap,
        messages,
        temp,
        max_tok,
        cancel_evt,
        max_retries,
        infinite_retry,
        fallback_caps,
        usage_key: Optional[str] = None,
        **kwargs,
    ):
        """
        流式调用
        - 未产出任何内容时失败 → 重试/降级到非流式；
        - 已产出内容后中断 → 直接抛 LLMCallError（调用方已知内容不完整），
          不重试不降级，避免内容重复。
        """
        if infinite_retry:
            # 流式无限重试：以配置 max_retries 的大值（50）兜底，避免固定 10 次限制
            max_retries = max(self.default_retry["max_retries"], 50)

        model = _ensure_model_prefix(cap, cap.model)
        params = {
            "model": model,
            "messages": messages,
            "api_base": cap.endpoint or None,
            "api_key": cap.api_key or None,
            "stream": True,
            **cap.parameters,
        }
        if temp is not None:
            params["temperature"] = temp
        if max_tok is not None:
            params["max_tokens"] = max_tok
        params.update(kwargs)

        retry_limit = max_retries or self.default_retry["max_retries"]
        attempt = 0
        yielded = False

        while True:
            if cancel_evt and cancel_evt.is_set():
                self._clear_stream_usage(usage_key)
                return

            resp = None
            try:
                resp = await _get_acompletion()(**params)
                async for chunk in resp:
                    if cancel_evt and cancel_evt.is_set():
                        self._clear_stream_usage(usage_key)
                        return
                    # 每次 yield 前记录用量（最终 chunk 常为 usage-only）
                    self._record_stream_usage(chunk, usage_key)
                    if not chunk.choices:
                        continue
                    piece = getattr(chunk.choices[0].delta, "content", None) or ""
                    if piece:
                        yielded = True
                        yield piece
                # 正常结束：保留最后记录的用量
                return
            except LLMCallError:
                # 用户取消等业务异常：不重试
                self._clear_stream_usage(usage_key)
                raise
            except Exception as e:
                attempt += 1
                if yielded:
                    # 已产出内容：不重试不降级，避免内容重复
                    self._clear_stream_usage(usage_key)
                    raise LLMCallError(f"流式输出中断: {e}", e)
                # 未产出任何内容 → 可重试或降级
                if not isinstance(e, _retryable_exceptions()) or attempt > retry_limit:
                    logger.warning(f"流式失败，降级为非流式: {e}")
                    try:
                        nr = await self._call_non_stream(
                            cap,
                            messages,
                            temp,
                            max_tok,
                            cancel_evt,
                            max_retries=5,
                            infinite_retry=False,
                            fallback_caps=fallback_caps,
                            **kwargs,
                        )
                        nr.stop_reason = StopReason.STREAM_FALLBACK
                        self._clear_stream_usage(usage_key)
                        yield nr.content
                        return
                    except Exception as fe:
                        self._clear_stream_usage(usage_key)
                        raise LLMCallError(f"流式及回退均失败: {fe}", e)

                delay = min(1.0 * (2 ** (attempt - 1)), 10)
                logger.warning(f"流式中断，{delay:.2f}s后重试({attempt}/{retry_limit})")
                await _interruptible_sleep(delay, cancel_evt)
            finally:
                if resp:
                    try:
                        await resp.aclose()
                    except Exception:
                        pass

    def _clear_stream_usage(self, usage_key: Optional[str]) -> None:
        """清除指定 usage_key 的流式用量（异常/取消路径）。"""
        if usage_key is not None:
            self._stream_usages.pop(usage_key, None)

    def _record_stream_usage(self, chunk, usage_key: Optional[str]) -> None:
        """记录流式 chunk 的 token 用量（litellm 通常在最终 chunk 的 usage 字段给出）。

        usage_key 用于并发流式调用间的用量隔离，避免互相覆盖。
        """
        usage = getattr(chunk, "usage", None)
        if usage is None:
            return
        prompt = getattr(usage, "prompt_tokens", None)
        completion = getattr(usage, "completion_tokens", None)
        if prompt is None and completion is None:
            return
        total = (prompt or 0) + (completion or 0)
        if total > 0 and usage_key is not None:
            self._stream_usages[usage_key] = {
                "prompt_tokens": prompt or 0,
                "completion_tokens": completion or 0,
                "total_tokens": total,
            }
            self._last_stream_usage_key = usage_key
            if len(self._stream_usages) > self._max_stream_usages:
                # 修剪最老的 key，防止长驻进程内存无界增长
                self._stream_usages.pop(next(iter(self._stream_usages)))

    def last_stream_usage(self, usage_key: Optional[str] = None) -> dict:
        """返回指定 usage_key（默认最近一次）流式调用的 token 用量；异常/取消后为空。"""
        if usage_key is not None:
            d = self._stream_usages.get(usage_key)
            return dict(d) if d else {}
        key = self._last_stream_usage_key
        if key is None:
            return {}
        d = self._stream_usages.get(key)
        return dict(d) if d else {}


def _close_llm_http_client() -> None:
    """atexit 兜底关闭 litellm 的 httpx 客户端（进程退出时避免挂起）。"""
    if _llm is None:
        return
    client = getattr(_llm, "_async_client", None)
    if client is None:
        return
    try:
        asyncio.run(client.aclose())
    except Exception:
        pass


# 全局 LLM 客户端实例
llm_client = LLMClient()
atexit.register(_close_llm_http_client)
