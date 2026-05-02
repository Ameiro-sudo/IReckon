"""
AI 模块
提供能力池管理、LLM 调用封装、Agent 角色定义
"""

from .lite_llm import CapabilityPool, AICapability
from .capability_pool import LLMClient, LLMCallError
from .roles.base_agent import BaseAgent
from .roles.scheduler import SchedulerAgent

__all__ = [
    "CapabilityPool",
    "AICapability",
    "LLMClient",
    "LLMCallError",
    "BaseAgent",
    "SchedulerAgent",
]