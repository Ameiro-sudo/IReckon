"""
配置管理器 (修复版)
- 线程安全
- 环境变量展开 ${VAR} 和 ${VAR:-default}
- 热加载（watchdog 或手动）
- 配置文件缺失时自动使用空配置，防止导入崩溃
"""

import os
import re
import yaml
import threading
import atexit
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    logger.warning("watchdog 未安装，配置文件热加载不可用，将使用手动重载")


class ConfigManager:
    _instance: Optional["ConfigManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "ConfigManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = True
        self._config_lock = threading.RLock()
        self._observer: Optional[Observer] = None

        base_dir = Path(os.environ.get("IRECKON_HOME", ".")).resolve()
        self.config_path = base_dir / "config" / "config.yaml"
        if not self.config_path.exists():
            self.config_path = Path("config/config.yaml")

        self.config: Dict[str, Any] = {}
        self._load_config()
        self._start_watcher()
        atexit.register(self.shutdown)

    def _load_config(self) -> None:
        """加载配置文件，若文件不存在则使用空配置并记录警告。"""
        if not self.config_path.exists():
            logger.warning(f"配置文件不存在: {self.config_path}，使用空配置")
            with self._config_lock:
                self.config = {}
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"配置文件读取失败: {e}，使用空配置")
            raw = {}

        with self._config_lock:
            self.config = self._expand_env_vars(raw)

        logger.info(f"配置加载成功: {self.config_path}")

    def _expand_env_vars(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: self._expand_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._expand_env_vars(item) for item in obj]
        elif isinstance(obj, str):
            def replacer(match: re.Match) -> str:
                expr = match.group(1)
                if ":-" in expr:
                    var_name, default = expr.split(":-", 1)
                    return os.environ.get(var_name, default)
                return os.environ.get(expr, "")
            return re.sub(r"\$\{([^}]+)\}", replacer, obj)
        else:
            return obj

    def _start_watcher(self) -> None:
        if not WATCHDOG_AVAILABLE:
            logger.info("热加载不可用，使用手动重载")
            return

        try:
            event_handler = ConfigChangeHandler(self)
            self._observer = Observer()
            self._observer.schedule(
                event_handler,
                path=str(self.config_path.parent),
                recursive=False
            )
            self._observer.start()
            logger.info("配置文件热加载监视器已启动")
        except Exception as e:
            logger.warning(f"无法启动文件监视器（可能在 Termux 环境）: {e}")
            self._observer = None

    def shutdown(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=1.0)
            logger.debug("配置文件监视器已停止")

    def reload(self) -> None:
        self._load_config()
        logger.info("配置文件已手动重载")

    def get(self, key: str, default: Any = None) -> Any:
        with self._config_lock:
            value = self.config
            try:
                for k in key.split("."):
                    value = value[k]
                return value
            except (KeyError, TypeError, AttributeError):
                return default

    def get_all(self) -> Dict[str, Any]:
        import copy
        with self._config_lock:
            return copy.deepcopy(self.config)


class ConfigChangeHandler(FileSystemEventHandler):
    def __init__(self, config_manager: ConfigManager):
        self.cm = config_manager
        super().__init__()

    def on_modified(self, event: Any) -> None:
        if event.src_path.endswith("config.yaml"):
            logger.info("检测到配置文件变化，重新加载...")
            self.cm._load_config()


config_manager = ConfigManager()