"""
配置管理模块
负责加载、解析、热重载配置文件。
"""

import atexit
import hashlib
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

# 导入 logger 模块以尽早统一日志格式（logger 内部对 config 是惰性导入，无循环依赖）
from app.core.logger import logger

# watchdog 是文件监视器，可以自动检测配置文件变化～
try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    WATCHDOG_AVAILABLE = True
except ImportError:
    FileSystemEventHandler = object  # type: ignore[misc,assignment]  # 降级：无 watchdog 时用空基类避免导入失败
    Observer = None  # type: ignore[assignment]
    WATCHDOG_AVAILABLE = False
    logger.warning("watchdog 未安装，配置文件热加载不可用，将使用手动重载")

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)}")


class ConfigManager:
    _instance: Optional["ConfigManager"] = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> Optional["ConfigManager"]:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    @staticmethod
    def _resolve_base_dir() -> Path:
        """定位运行时根目录：IRECKON_HOME 环境变量 > PyInstaller 打包目录 > 当前工作目录。"""
        env_home = os.environ.get("IRECKON_HOME")
        if env_home:
            return Path(env_home).resolve()
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass).resolve()
        return Path.cwd().resolve()

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._config_lock = threading.RLock()
        self._observer: Optional[Any] = None
        self._config_hash: Optional[str] = None

        self.base_dir = self._resolve_base_dir()
        self.config_path = (self.base_dir / "config" / "config.yaml").resolve()
        if not self.config_path.exists():
            self.config_path = (Path.cwd() / "config" / "config.yaml").resolve()

        self.config: Dict[str, Any] = {}
        self._load_config()
        self._start_watcher()
        atexit.register(self.shutdown)

    def _load_config(self, force: bool = False) -> None:
        if not self.config_path.exists():
            logger.warning(f"配置文件不存在: {self.config_path}，使用空配置")
            with self._config_lock:
                self.config = {}
            return

        # 计算配置文件哈希（仅用于变更检测，非安全用途）
        current_hash = hashlib.md5(  # nosec B324: 非安全用途，仅变更检测
            self.config_path.read_bytes(), usedforsecurity=False
        ).hexdigest()
        # force=True（手动 reload）时跳过哈希短路，确保环境变量变更后重新展开
        if not force and current_hash == self._config_hash:
            return  # 配置未变化，跳过加载

        try:
            with self.config_path.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        except Exception as exc:
            logger.error(f"配置文件读取失败: {exc}，使用空配置")
            raw = {}

        with self._config_lock:
            self.config = self._expand_env_vars(raw)

        self._config_hash = current_hash
        logger.debug(f"配置加载成功: {self.config_path}")

    def _expand_env_vars(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: self._expand_env_vars(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._expand_env_vars(item) for item in value]
        if isinstance(value, str):

            def replacer(match: re.Match) -> str | None:
                expr = match.group(1)
                if ":-" in expr:
                    var_name, default = expr.split(":-", 1)
                    return os.environ.get(var_name, default)
                return os.environ.get(expr, "")

            return _ENV_VAR_PATTERN.sub(replacer, value)
        return value

    def _start_watcher(self) -> None:
        if not WATCHDOG_AVAILABLE:
            logger.info("热加载不可用，使用手动重载")
            return

        try:
            handler = ConfigChangeHandler(self)
            self._observer = Observer
            self._observer.schedule(
                handler, path=str(self.config_path.parent), recursive=False
            )
            self._observer.start()
            logger.info("配置文件热加载监视器已启动")
        except Exception as exc:
            logger.warning(f"无法启动文件监视器: {exc}")
            self._observer = None

    def shutdown(self) -> None:
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join(timeout=1.0)
        logger.debug("配置文件监视器已停止")

    def reload(self) -> None:
        self._load_config(force=True)
        logger.info("配置文件已手动重载")

    def get(self, key: str, default: Any = None) -> Any:
        with self._config_lock:
            node = self.config
            for part in key.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return node

    def get_all(self) -> Dict[str, Any]:
        import copy

        with self._config_lock:
            return copy.deepcopy(self.config)

    def get_redacted(self) -> Dict[str, Any]:
        """深拷贝后掩码所有键名含 api_key 的值为 "***"，防止 API Key 泄露。"""

        def _mask(node: Any) -> Any:
            if isinstance(node, dict):
                return {
                    k: ("***" if "api_key" in str(k).lower() else _mask(v))
                    for k, v in node.items()
                }
            if isinstance(node, list):
                return [_mask(item) for item in node]
            return node

        with self._config_lock:
            return _mask(self.get_all())


class ConfigChangeHandler(FileSystemEventHandler):
    def __init__(self, config_manager: ConfigManager):
        super().__init__()
        self.config_manager = config_manager

    def on_modified(self, event: Any) -> None:
        if getattr(event, "is_directory", False):
            return
        if Path(event.src_path).name != "config.yaml":
            return
        logger.info("检测到配置文件变化，重新加载...")
        self.config_manager._load_config()


# 全局配置管理器实例（延迟初始化，避免模块导入时触发 YAML 加载和 watchdog 启动）
_config_manager: Optional[ConfigManager] = None


def _get_config_manager() -> ConfigManager | None:
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


# 兼容性属性：直接访问 config_manager 等同于调用 _get_config_manager()
class _ConfigManagerProxy:
    """延迟初始化代理：首次访问属性时才创建 ConfigManager 实例。"""

    def __getattr__(self, name: str) -> Any:
        return getattr(_get_config_manager(), name)


config_manager = _ConfigManagerProxy()


def get(key: str, default: Any = None) -> Any:
    """模块级配置读取快捷方式：读不到返回默认值（默认值全部内置于代码）。"""
    return config_manager.get(key, default)
