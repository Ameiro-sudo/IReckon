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

RETRYABLE_EXCEPTIONS = (litellm.exceptions.APIConnectionError, litellm.exceptions.APIError, litellm.exceptions.Timeout, litellm.exceptions.RateLimitError, litellm.exceptions.ServiceUnavailableError, ConnectionError, TimeoutError)
class LLMCallError(Exception):
    def __init__(self, m, orig=None): super().__init__(m); self.original_error=orig
class StopReason(Enum):
    SUCCESS="success"; USER_CANCELLED="user_cancelled"; MAX_RETRIES="max_retries"; UNRECOVERABLE="unrecoverable"; FALLBACK="fallback"; STREAM_FALLBACK="stream_fallback"
@dataclass
class LLMResponse:
    content: str; model: str; usage: Dict[str,int]; finish_reason: str; stop_reason: StopReason; retry_count: int=0; raw_response: Any=None

class EndpointHealth:
    def __init__(self): self.failures={}; self.last_success={}; self.cooldown_until={}; self._lock=asyncio.Lock()
    async def record_success(self, ep):
        async with self._lock: self.failures[ep]=0; self.last_success[ep]=time.time(); self.cooldown_until.pop(ep,None)
    async def record_failure(self, ep):
        async with self._lock: self.failures[ep]=self.failures.get(ep,0)+1
        if self.failures[ep]>=3: self.cooldown_until[ep]=time.time()+30
    async def is_available(self, ep):
        async with self._lock:
            if ep in self.cooldown_until and time.time()<self.cooldown_until[ep]: return False
            if ep in self.cooldown_until: del self.cooldown_until[ep]; self.failures[ep]=0
            return True

class LLMClient:
    def __init__(self):
        self.default_retry = config_manager.get("ai_pool.retry", {"max_retries":10,"base_delay":1,"max_delay":30,"exponential_base":2})
        mc = config_manager.get("ai_pool.concurrency.max_concurrent_calls", 10)
        self._global_sem = asyncio.Semaphore(mc)
        self._ep_sems = {ep: asyncio.Semaphore(lim) for ep, lim in config_manager.get("ai_pool.concurrency.per_endpoint_limit", {}).items()}
        self.health = EndpointHealth()
        self._http_client = None; self._client_lock = asyncio.Lock()
        self._global_cancel_event = None
        try:
            litellm._async_client = httpx.AsyncClient(limits=httpx.Limits(max_keepalive_connections=20,max_connections=100), timeout=httpx.Timeout(30,connect=10))
        except: pass

    def set_global_cancel_event(self, ev): self._global_cancel_event = ev

    async def call(self, capability, messages, temperature=None, max_tokens=None, cancellation_event=None, max_retries=None, infinite_retry=False, stream=False, fallback_capabilities=None, **kwargs):
        cancel_evt = cancellation_event or self._global_cancel_event
        if stream: return self._call_stream(capability, messages, temperature, max_tokens, cancel_evt, max_retries, infinite_retry, fallback_capabilities, **kwargs)
        else: return await self._call_non_stream(capability, messages, temperature, max_tokens, cancel_evt, max_retries, infinite_retry, fallback_capabilities, **kwargs)

    def _ensure_model_prefix(self, model: str) -> str:
        if "/" not in model: return f"openai/{model}"
        return model

    async def _try_call(self, cap, messages, temp, max_tok, cancel_evt, max_retries, infinite_retry, **kwargs):
        model = self._ensure_model_prefix(cap.model)
        params = {"model": model, "messages": messages, "api_base": cap.endpoint or None, "api_key": cap.api_key or None, **(cap.parameters)}
        if temp is not None: params["temperature"] = temp
        if max_tok is not None: params["max_tokens"] = max_tok
        params.update(kwargs)
        limit = float("inf") if infinite_retry else (max_retries or self.default_retry["max_retries"])
        attempt, base, mx, exp = 0, self.default_retry["base_delay"], self.default_retry["max_delay"], self.default_retry["exponential_base"]
        while True:
            if cancel_evt and cancel_evt.is_set(): raise LLMCallError("用户取消")
            try:
                resp = await acompletion(**params)
                usage = {"prompt_tokens": resp.usage.prompt_tokens, "completion_tokens": resp.usage.completion_tokens, "total_tokens": resp.usage.total_tokens}
                content = resp.choices[0].message.content or ""
                await self.health.record_success(cap.endpoint)
                return LLMResponse(content=content, model=resp.model, usage=usage, finish_reason=resp.choices[0].finish_reason, stop_reason=StopReason.SUCCESS, retry_count=attempt, raw_response=resp)
            except Exception as e:
                attempt += 1; await self.health.record_failure(cap.endpoint)
                if not isinstance(e, RETRYABLE_EXCEPTIONS): raise LLMCallError(f"不可重试错误: {e}", e)
                if not infinite_retry and attempt > limit: raise LLMCallError(f"重试{limit}次仍失败", e)
                delay = min(base*(exp**(attempt-1)), mx) + random.uniform(0, min(base*(exp**(attempt-1)), mx)*0.1)
                logger.warning(f"LLM调用失败(尝试{attempt}): {e}. {delay:.2f}s后重试...")
                try: await self._interruptible_sleep(delay, cancel_evt)
                except LLMCallError: raise

    async def _call_non_stream(self, cap, messages, temp, max_tok, cancel_evt, max_retries, infinite_retry, fallback_caps=None, **kwargs):
        sem = self._ep_sems.get(cap.endpoint, self._global_sem)
        async with sem:
            caps = [cap]; 
            if fallback_caps: caps.extend(fallback_caps)
            last_exc = None
            for idx, c in enumerate(caps):
                if not await self.health.is_available(c.endpoint): continue
                try:
                    res = await self._try_call(c, messages, temp, max_tok, cancel_evt, max_retries, infinite_retry=infinite_retry, **kwargs)
                    if idx>0: res.stop_reason = StopReason.FALLBACK
                    return res
                except LLMCallError as e:
                    last_exc = e
                    if "不可重试" in str(e): raise
            raise last_exc or LLMCallError("所有端点均失败")

    async def _call_stream(self, cap, messages, temp, max_tok, cancel_evt, max_retries, infinite_retry, fallback_caps, **kwargs):
        if infinite_retry: max_retries = 10
        model = self._ensure_model_prefix(cap.model)
        params = {"model": model, "messages": messages, "api_base": cap.endpoint or None, "api_key": cap.api_key or None, "stream": True, **(cap.parameters)}
        if temp is not None: params["temperature"] = temp
        if max_tok is not None: params["max_tokens"] = max_tok
        params.update(kwargs)
        retry_limit = max_retries or self.default_retry["max_retries"]
        attempt = 0
        while True:
            if cancel_evt and cancel_evt.is_set(): break
            resp = None
            try:
                resp = await acompletion(**params)
                async for chunk in resp:
                    if cancel_evt and cancel_evt.is_set(): break
                    if chunk.choices[0].delta.content: yield chunk.choices[0].delta.content
                return
            except Exception as e:
                attempt += 1
                if not isinstance(e, RETRYABLE_EXCEPTIONS) or attempt > retry_limit:
                    logger.warning(f"流式失败，降级为非流式: {e}")
                    try:
                        nr = await self._call_non_stream(cap, messages, temp, max_tok, cancel_evt, max_retries=5, infinite_retry=False, fallback_capabilities=fallback_caps, **kwargs)
                        nr.stop_reason = StopReason.STREAM_FALLBACK
                        yield nr.content; return
                    except Exception as fe: raise LLMCallError(f"流式及回退均失败: {fe}", e)
                delay = min(1.0*(2**(attempt-1)), 10)
                logger.warning(f"流式中断，{delay:.2f}s后重试({attempt}/{retry_limit})")
                await self._interruptible_sleep(delay, cancel_evt)
            finally:
                if resp: 
                    try: await resp.aclose()
                    except: pass

    async def _interruptible_sleep(self, duration, cancel_event):
        if not cancel_event: await asyncio.sleep(duration); return
        try: await asyncio.wait_for(cancel_event.wait(), timeout=duration); raise LLMCallError("用户取消")
        except asyncio.TimeoutError: pass

llm_client = LLMClient()
