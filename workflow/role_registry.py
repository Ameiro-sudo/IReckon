"""
动态角色注册机制
允许灵活添加自定义 AI 角色
"""

import importlib
import inspect
import sys
from pathlib import Path
from typing import Dict, Type, Optional, List, Any
from loguru import logger

from ai.roles.base_agent import BaseAgent


class RoleRegistry:
    _instance: Optional["RoleRegistry"] = None

    def __new__(cls) -> "RoleRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = True
        self._roles: Dict[str, Type[BaseAgent]] = {}
        self._role_metadata: Dict[str, Dict[str, Any]] = {}

    def register(self, role_name: str, agent_class: Type[BaseAgent], metadata: Optional[Dict] = None) -> None:
        if not issubclass(agent_class, BaseAgent):
            raise TypeError(f"{agent_class} 必须继承 BaseAgent")
        self._roles[role_name] = agent_class
        self._role_metadata[role_name] = metadata or {}
        logger.info(f"注册角色: {role_name} -> {agent_class.__name__}")

    def unregister(self, role_name: str) -> None:
        if role_name in self._roles:
            del self._roles[role_name]
            del self._role_metadata[role_name]
            logger.info(f"注销角色: {role_name}")

    def get_agent_class(self, role_name: str) -> Optional[Type[BaseAgent]]:
        return self._roles.get(role_name)

    def list_roles(self) -> List[str]:
        return list(self._roles.keys())

    def get_metadata(self, role_name: str) -> Dict[str, Any]:
        return self._role_metadata.get(role_name, {}).copy()

    def create_agent(self, role_name: str, capability, **kwargs) -> Optional[BaseAgent]:
        agent_class = self.get_agent_class(role_name)
        if agent_class is None:
            logger.error(f"未注册的角色: {role_name}")
            return None
        try:
            return agent_class(capability=capability, **kwargs)
        except Exception as e:
            logger.error(f"创建 Agent 失败 ({role_name}): {e}")
            return None

    def discover_from_directory(self, directory: Path) -> int:
        count = 0
        if not directory.exists():
            return 0
        # 避免污染 sys.path，使用 importlib.util
        import importlib.util
        for file in directory.glob("*.py"):
            if file.name.startswith("_"):
                continue
            module_name = file.stem
            spec = importlib.util.spec_from_file_location(module_name, file)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception as e:
                logger.error(f"加载自定义角色 {file} 失败: {e}")
                continue
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if not issubclass(obj, BaseAgent) or obj is BaseAgent:
                    continue
                role_name = getattr(obj, "__role_name__", name.lower())
                metadata = getattr(obj, "__role_metadata__", {})
                self.register(role_name, obj, metadata)
                count += 1
        return count


role_registry = RoleRegistry()


def register_role(role_name: str, metadata: Optional[Dict] = None):
    def decorator(cls: Type[BaseAgent]) -> Type[BaseAgent]:
        role_registry.register(role_name, cls, metadata)
        return cls
    return decorator