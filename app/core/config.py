"""
配置管理模块
负责加载、解析、热重载配置文件。
"""

import atexit
import hashlib
import os
import re
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

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


class ConfigManager:
    _instance: Optional["ConfigManager"] = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "ConfigManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._config_lock = threading.RLock()
        self._observer: Optional[Any] = None
        self._config_hash: Optional[str] = None

        self.base_dir = Path(os.environ.get("IRECKON_HOME", ".")).resolve()
        self.config_path = (self.base_dir / "config" / "config.yaml").resolve()
        if not self.config_path.exists():
            self.config_path = (Path.cwd() / "config" / "config.yaml").resolve()

        self.config: Dict[str, Any] = {}
        self._load_config()
        self._start_watcher()
        atexit.register(self.shutdown)

    def _load_config(self) -> None:
        if not self.config_path.exists():
            logger.warning(f"配置文件不存在: {self.config_path}，使用空配置")
            with self._config_lock:
                self.config = {}
            return

        # 计算配置文件哈希
        current_hash = hashlib.md5(self.config_path.read_bytes()).hexdigest()
        if current_hash == self._config_hash:
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

            def replacer(match: re.Match) -> str:
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
            self._observer = Observer()
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
        self._load_config()
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


# 全局配置管理器实例～
config_manager = ConfigManager()
