import uuid
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass, field
import asyncio

from loguru import logger

from app.llm.pool import AICapability
from app.llm.client import (
    LLMClient,
    LLMResponse,
    StopReason,
    llm_client,
    LLMCallError,
)
from app.core.logger import log_conversation
from app.engine.style import style_engine


@dataclass
class AgentContext:
    task_id: str
    agent_id: str
    role: str
    capability: AICapability
    cancellation_event: asyncio.Event = field(default_factory=asyncio.Event)
    extra: Dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    def __init__(
        self,
        role: str,
        capability: AICapability,
        system_prompt: str,
        llm: Optional[LLMClient] = None,
    ):
        self.role = role
        self.capability = capability
        self.llm = llm or llm_client
        self.context: Optional[AgentContext] = None

        style_injection = style_engine.generate_agent_prompt_injection(role)
        if style_injection:
            system_prompt = f"{system_prompt}\n\n【输出风格要求】\n{style_injection}"

        self.system_prompt = system_prompt
        self.messages: List[Dict[str, str]] = []

    def bind_context(
        self, task_id: str, cancellation_event: Optional[asyncio.Event] = None, **extra
    ) -> None:
        self.context = AgentContext(
            task_id=task_id,
            agent_id=f"{self.role}-{uuid.uuid4().hex[:8]}",
            role=self.role,
            capability=self.capability,
            cancellation_event=cancellation_event or asyncio.Event(),
            extra=extra,
        )
        self.messages = [{"role": "system", "content": self.system_prompt}]

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        self._trim_history_if_needed()
        if self.context:
            # 只截断日志内容，不截断消息本身，避免记录敏感/超长内容
            log_content = content[:2000] if content else content
            log_conversation(
                role=f"{self.context.role} ({role})",
                content=log_content,
                metadata={
                    "task_id": self.context.task_id,
                    "agent_id": self.context.agent_id,
                    "model": self.capability.model,
                },
            )

    def _trim_history_if_needed(self) -> None:
        """历史总字符数超过 60000 时裁剪：保留 system 与最近 6 条消息。"""
        total = sum(len(m.get("content") or "") for m in self.messages)
        if total <= 60000:
            return
        system_msgs = [m for m in self.messages if m["role"] == "system"]
        tail = self.messages[len(system_msgs) :][-6:]
        self.messages = system_msgs + tail
        logger.debug(
            f"Agent {self.role} 历史过长({total}字符)，已裁剪为 system+最近{len(tail)}条"
        )

    async def _check_limits_or_raise(self) -> None:
        """任务入口预算检查：超限直接抛错中止，不再发起 LLM 调用。"""
        if not self.context:
            return
        from app.engine.cost import cost_tracker

        error = await cost_tracker.enforce_limits(self.context.task_id)
        if error:
            from app.llm.client import LLMCallError

            raise LLMCallError(error)

    async def think(
        self,
        user_message: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        infinite_retry: bool = False,
    ) -> str:
        await self._check_limits_or_raise()
        if user_message:
            self.add_message("user", user_message)

        try:
            response = await self.llm.call(
                self.capability,
                self.messages,
                temperature=temperature,
                max_tokens=max_tokens,
                cancellation_event=self.context.cancellation_event
                if self.context
                else None,
                infinite_retry=infinite_retry,
            )
            self.add_message("assistant", response.content)
            await self._record_usage(response)
            return response.content  # type: ignore[no-any-return]  # litellm 响应体动态类型

        except Exception as e:
            logger.error(f"Agent {self.role} 思考失败: {e}")
            raise

    async def _record_usage(self, response: "LLMResponse") -> None:
        if not self.context:
            return
        try:
            from app.engine.cost import cost_tracker
        except Exception as e:
            logger.warning(f"cost_tracker 不可用，跳过用量记录: {e}")
            return
        usage = response.usage or {}
        tokens = int(usage.get("total_tokens") or 0)
        if tokens <= 0:
            return
        cost = tokens / 1000 * self.capability.cost_per_1k_tokens
        try:
            over = await cost_tracker.add_usage(self.context.task_id, tokens, cost)
        except Exception as e:
            logger.warning(f"用量记录失败: {e}")
            return
        if over:
            raise LLMCallError(
                f"任务 {self.context.task_id} 超出 Token 预算，执行已中止"
            )

    async def think_stream(
        self,
        user_message: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        await self._check_limits_or_raise()
        if user_message:
            self.add_message("user", user_message)

        full_response = ""
        try:
            stream = await self.llm.call(
                self.capability,
                self.messages,
                temperature=temperature,
                max_tokens=max_tokens,
                cancellation_event=self.context.cancellation_event
                if self.context
                else None,
                stream=True,
                usage_key=self.context.task_id if self.context else None,
            )
            async for chunk in stream:
                full_response += chunk
                yield chunk

            self.add_message("assistant", full_response)

            # 流式调用 token 核算：客户端提供 last_stream_usage 时使用，否则跳过
            last_usage = getattr(self.llm, "last_stream_usage", None)
            if callable(last_usage):
                try:
                    usage = last_usage
                    if asyncio.iscoroutine(usage):
                        usage = await usage
                    if (
                        isinstance(usage, dict)
                        and int(usage.get("total_tokens") or 0) > 0
                    ):
                        resp = LLMResponse(
                            content=full_response,
                            model="",
                            usage=usage,
                            finish_reason="stream",
                            stop_reason=StopReason.STREAM_FALLBACK,
                        )
                        await self._record_usage(resp)
                except Exception as e:
                    logger.warning(f"流式用量核算失败: {e}")

        except Exception as e:
            logger.error(f"Agent {self.role} 流式思考失败: {e}")
            raise

    def clear_history(self, keep_system: bool = True) -> None:
        if keep_system:
            self.messages = [msg for msg in self.messages if msg["role"] == "system"]
        else:
            self.messages = []

    @abstractmethod
    async def execute(self, *args, **kwargs) -> Any:
        pass
