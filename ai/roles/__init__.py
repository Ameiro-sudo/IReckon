"""
AI 角色模块
自动注册所有内置角色，并支持从自定义目录加载
"""

from pathlib import Path
from workflow.role_registry import role_registry

# 导入内置角色（触发装饰器注册）
from .executor import ExecutorAgent
from .reviewer import EfficiencyReviewerAgent, CorrectnessReviewerAgent
from .creative import CreativeAgent
from .tool_manager import ToolManagerAgent
from .deliverer import DelivererAgent


def load_custom_roles():
    """加载自定义角色目录"""
    custom_dir = Path(__file__).parent / "custom"
    if custom_dir.exists():
        count = role_registry.discover_from_directory(custom_dir)
        if count > 0:
            from loguru import logger
            logger.info(f"从 custom 目录加载了 {count} 个自定义角色")


load_custom_roles()

__all__ = [
    "ExecutorAgent",
    "EfficiencyReviewerAgent",
    "CorrectnessReviewerAgent",
    "CreativeAgent",
    "ToolManagerAgent",
    "DelivererAgent",
]