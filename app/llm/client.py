"""
LLM 客户端模块 (๑•̀ᴗ-)✧
负责调用各种 LLM API，支持重试、熔断、流式输出等功能～
"""

import asyncio, random, time
from typing import List, Dict, Any, Optional, Union, AsyncGenerator
from enum import Enum
from dataclasses import dataclass
import litellm
from litellm import acompletion
import httpx
from loguru import logger
from app.core.config import config_manager
from app.llm.pool import AICapability, CapabilityPool, capability_pool

# 可以重试的异常类型～
RETRYABLE_EXCEPTIONS = (
    litellm.exceptions.APIConnectionError, 
    litellm.exceptions.APIError, 
    litellm.exceptions.Timeout, 
    litellm.exceptions.RateLimitError, 
    litellm.exceptions.ServiceUnavailableError, 
    ConnectionError, 
    TimeoutError
)

class LLMCallError(Exception):
    """LLM 调用错误～"""
    def __init__(self, m, orig=None): 
        super().__init__(m)
        self.original_error = orig

class StopReason(Enum):
    """调用停止原因枚举～"""
    SUCCESS = "success"           # 成功完成
    USER_CANCELLED = "user_cancelled"  # 用户取消
    MAX_RETRIES = "max_retries"   # 重试次数用完
    UNRECOVERABLE = "unrecoverable"  # 无法恢复的错误
    FALLBACK = "fallback"         # 降级到备用模型
    STREAM_FALLBACK = "stream_fallback"  # 流式降级到非流式

@dataclass
class LLMResponse:
    """LLM 响应数据类～"""
    content: str           # 响应内容
    model: str             # 使用的模型
    usage: Dict[str, int] # token 使用量
    finish_reason: str     # 结束原因
    stop_reason: StopReason  # 停止原因
    retry_count: int = 0   # 重试次数
    raw_response: Any = None  # 原始响应


class EndpointHealth:
    """
    端点健康状态管理器～
    记录失败次数，实施冷却机制，防止频繁调用不健康的端点！
    """
    def __init__(self):
        self.failures = {}         # 失败次数
        self.last_success = {}     # 上次成功时间
        self.cooldown_until = {}   # 冷却截止时间
        self._lock = asyncio.Lock()

    async def record_success(self, ep):
        """记录成功，恢复健康～"""
        async with self._lock:
            self.failures[ep] = 0
            self.last_success[ep] = time.time()
            self.cooldown_until.pop(ep, None)

    async def record_failure(self, ep):
        """记录失败，连续失败3次就进入冷却期～"""
        async with self._lock:
            self.failures[ep] = self.failures.get(ep, 0) + 1
            if self.failures[ep] >= 3:
                self.cooldown_until[ep] = time.time() + 30  # 冷却30秒～

    async def is_available(self, ep):
        """检查端点是否可用～"""
        async with self._lock:
            # 还在冷却中？
            if ep in self.cooldown_until and time.time() < self.cooldown_until[ep]:
                return False
            # 冷却结束，清除记录～
            if ep in self.cooldown_until:
                del self.cooldown_until[ep]
                self.failures[ep] = 0
            return True


class LLMClient:
    """
    LLM 客户端核心类～
    支持：重试、熔断、流式输出、并发控制、故障转移等功能！
    """
    def __init__(self):
        # 重试配置
        self.default_retry = config_manager.get("ai_pool.retry", {
            "max_retries": 10, 
            "base_delay": 1, 
            "max_delay": 30, 
            "exponential_base": 2
        })
        
        # 并发控制
        mc = config_manager.get("ai_pool.concurrency.max_concurrent_calls", 10)
        self._global_sem = asyncio.Semaphore(mc)  # 全局信号量
        # 每个端点的限制～
        self._ep_sems = {
            ep: asyncio.Semaphore(lim) 
            for ep, lim in config_manager.get("ai_pool.concurrency.per_endpoint_limit", {}).items()
        }
        
        self.health = EndpointHealth()  # 健康检查
        self._http_client = None
        self._client_lock = asyncio.Lock()
        self._global_cancel_event = None  # 全局取消事件
        
        # 配置 httpx 客户端
        try:
            litellm._async_client = httpx.AsyncClient(
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=100), 
                timeout=httpx.Timeout(30, connect=10)
            )
        except: pass

    def set_global_cancel_event(self, ev):
        """设置全局取消事件～"""
        self._global_cancel_event = ev

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
        **kwargs
    ):
        """
        统一的调用入口～
        根据 stream 参数决定走流式还是非流式路径～
        """
        cancel_evt = cancellation_event or self._global_cancel_event
        if stream:
            return self._call_stream(capability, messages, temperature, max_tokens, cancel_evt, max_retries, infinite_retry, fallback_capabilities, **kwargs)
        else:
            return await self._call_non_stream(capability, messages, temperature, max_tokens, cancel_evt, max_retries, infinite_retry, fallback_capabilities, **kwargs)

    def _ensure_model_prefix(self, model: str) -> str:
        """确保模型名称有前缀（比如 openai/xxx）"""
        if "/" not in model:
            return f"openai/{model}"
        return model

    async def _try_call(self, cap, messages, temp, max_tok, cancel_evt, max_retries, infinite_retry, **kwargs):
        """
        尝试调用单个端点，包含重试逻辑～
        使用指数退避策略，不会一开始就放弃治疗！
        """
        model = self._ensure_model_prefix(cap.model)
        params = {
            "model": model, 
            "messages": messages, 
            "api_base": cap.endpoint or None, 
            "api_key": cap.api_key or None, 
            **(cap.parameters)
        }
        if temp is not None: params["temperature"] = temp
        if max_tok is not None: params["max_tokens"] = max_tok
        params.update(kwargs)
        
        # 重试参数
        limit = float("inf") if infinite_retry else (max_retries or self.default_retry["max_retries"])
        attempt, base, mx, exp = 0, self.default_retry["base_delay"], self.default_retry["max_delay"], self.default_retry["exponential_base"]
        
        while True:
            # 检查是否取消～
            if cancel_evt and cancel_evt.is_set(): 
                raise LLMCallError("用户取消")
            
            try:
                resp = await acompletion(**params)
                usage = {
                    "prompt_tokens": resp.usage.prompt_tokens, 
                    "completion_tokens": resp.usage.completion_tokens, 
                    "total_tokens": resp.usage.total_tokens
                }
                content = resp.choices[0].message.content or ""
                await self.health.record_success(cap.endpoint)
                return LLMResponse(
                    content=content, 
                    model=resp.model, 
                    usage=usage, 
                    finish_reason=resp.choices[0].finish_reason, 
                    stop_reason=StopReason.SUCCESS, 
                    retry_count=attempt, 
                    raw_response=resp
                )
            except Exception as e:
                attempt += 1
                await self.health.record_failure(cap.endpoint)
                
                # 不可重试的错误直接抛出～
                if not isinstance(e, RETRYABLE_EXCEPTIONS):
                    raise LLMCallError(f"不可重试错误: {e}", e)
                
                # 重试次数用完～
                if not infinite_retry and attempt > limit:
                    raise LLMCallError(f"重试{limit}次仍失败", e)
                
                # 计算延迟（指数退避 + 随机抖动）
                delay = min(base * (exp ** (attempt - 1)), mx) + random.uniform(0, min(base * (exp ** (attempt - 1)), mx) * 0.1)
                logger.warning(f"LLM调用失败(尝试{attempt}): {e}. {delay:.2f}s后重试...")
                
                try: 
                    await self._interruptible_sleep(delay, cancel_evt)
                except LLMCallError: 
                    raise

    async def _call_non_stream(self, cap, messages, temp, max_tok, cancel_evt, max_retries, infinite_retry, fallback_caps=None, **kwargs):
        """
        非流式调用～
        支持故障转移，如果第一个端点失败，会尝试备用的！
        """
        sem = self._ep_sems.get(cap.endpoint, self._global_sem)
        async with sem:
            caps = [cap]
            if fallback_caps:
                caps.extend(fallback_caps)
            
            last_exc = None
            for idx, c in enumerate(caps):
                # 不健康的端点跳过～
                if not await self.health.is_available(c.endpoint):
                    continue
                try:
                    res = await self._try_call(c, messages, temp, max_tok, cancel_evt, max_retries, infinite_retry=infinite_retry, **kwargs)
                    if idx > 0:
                        res.stop_reason = StopReason.FALLBACK  # 标记为降级调用
                    return res
                except LLMCallError as e:
                    last_exc = e
                    if "不可重试" in str(e):
                        raise
            
            raise last_exc or LLMCallError("所有端点均失败")

    async def _call_stream(self, cap, messages, temp, max_tok, cancel_evt, max_retries, infinite_retry, fallback_caps, **kwargs):
        """
        流式调用～
        如果流式失败，会降级到非流式！
        """
        if infinite_retry:
            max_retries = 10
        
        model = self._ensure_model_prefix(cap.model)
        params = {
            "model": model, 
            "messages": messages, 
            "api_base": cap.endpoint or None, 
            "api_key": cap.api_key or None, 
            "stream": True, 
            **(cap.parameters)
        }
        if temp is not None: params["temperature"] = temp
        if max_tok is not None: params["max_tokens"] = max_tok
        params.update(kwargs)
        
        retry_limit = max_retries or self.default_retry["max_retries"]
        attempt = 0
        
        while True:
            if cancel_evt and cancel_evt.is_set():
                break
            
            resp = None
            try:
                resp = await acompletion(**params)
                async for chunk in resp:
                    if cancel_evt and cancel_evt.is_set():
                        break
                    if chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                return
            except Exception as e:
                attempt += 1
                # 不可重试的错误 或 达到重试上限 → 降级！
                if not isinstance(e, RETRYABLE_EXCEPTIONS) or attempt > retry_limit:
                    logger.warning(f"流式失败，降级为非流式: {e}")
                    try:
                        nr = await self._call_non_stream(
                            cap, messages, temp, max_tok, cancel_evt, 
                            max_retries=5, infinite_retry=False, 
                            fallback_capabilities=fallback_caps, **kwargs
                        )
                        nr.stop_reason = StopReason.STREAM_FALLBACK
                        yield nr.content
                        return
                    except Exception as fe:
                        raise LLMCallError(f"流式及回退均失败: {fe}", e)
                
                delay = min(1.0 * (2 ** (attempt - 1)), 10)
                logger.warning(f"流式中断，{delay:.2f}s后重试({attempt}/{retry_limit})")
                await self._interruptible_sleep(delay, cancel_evt)
            finally:
                if resp:
                    try: 
                        await resp.aclose()
                    except: 
                        pass

    async def _interruptible_sleep(self, duration, cancel_event):
        """
        可中断的睡眠～
        如果取消事件触发，会提前结束睡眠！
        """
        if not cancel_event:
            await asyncio.sleep(duration)
            return
        try:
            await asyncio.wait_for(cancel_event.wait(), timeout=duration)
            raise LLMCallError("用户取消")
        except asyncio.TimeoutError:
            pass


# 全局 LLM 客户端实例～
llm_client = LLMClient()