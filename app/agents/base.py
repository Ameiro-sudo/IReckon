import uuid
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass, field
import asyncio

from loguru import logger

from app.llm.pool import AICapability
from app.llm.client import LLMClient, LLMResponse, llm_client
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
        if self.context:
            log_conversation(
                role=f"{self.context.role} ({role})",
                content=content,
                metadata={
                    "task_id": self.context.task_id,
                    "agent_id": self.context.agent_id,
                    "model": self.capability.model,
                },
            )

    async def think(
        self,
        user_message: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        infinite_retry: bool = False,
    ) -> str:
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
            return response.content

        except Exception as e:
            logger.error(f"Agent {self.role} 思考失败: {e}")
            raise

    async def _record_usage(self, response: "LLMResponse") -> None:
        if not self.context:
            return
        usage = response.usage or {}
        tokens = int(usage.get("total_tokens") or 0)
        if tokens <= 0:
            return
        cost = tokens / 1000 * self.capability.cost_per_1k_tokens
        from app.engine.cost import cost_tracker

        over = await cost_tracker.add_usage(self.context.task_id, tokens, cost)
        if over:
            from app.llm.client import LLMCallError

            raise LLMCallError(
                f"任务 {self.context.task_id} 超出 Token 预算，执行已中止"
            )

    async def think_stream(
        self,
        user_message: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
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
            )
            async for chunk in stream:
                full_response += chunk
                yield chunk

            self.add_message("assistant", full_response)

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
