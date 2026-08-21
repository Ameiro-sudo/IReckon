"""
配置管理模块
负责加载、解析、热重载配置文件。
"""

import atexit
import hashlib
import json
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
    FileSystemEventHandler = object
    Observer = None
    WATCHDOG_AVAILABLE = False
    logger.warning("watchdog 未安装，配置文件热加载不可用，将使用手动重载")

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)}")


def _load_dotenv_file(path: Path) -> int:
    """极简 .env 加载器（零依赖）：KEY=VALUE 逐行解析。

    - 已存在的环境变量不覆盖（真实 shell 环境优先）；
    - 注释/空行/无等号的行跳过；值两侧成对引号会被剥掉；
    - 返回新载入的变量数。文件不存在时静默返回 0。
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return 0
    loaded = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not key or " " in key:
            logger.warning(f".env 行格式非法已跳过: {raw_line[:50]}")
            continue
        if key not in os.environ:
            os.environ[key] = value
            loaded += 1
    if loaded:
        logger.debug(f"已从 {path.name} 载入 {loaded} 个环境变量")
    return loaded


class ConfigManager:
    _instance: Optional["ConfigManager"] = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "ConfigManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            instance = cls._instance
        return instance

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
        # .env 必须在首次展开 ${VAR} 之前载入（零依赖，已有环境变量优先）
        _load_dotenv_file(self.base_dir / ".env")
        self.config_path = (self.base_dir / "config" / "config.yaml").resolve()
        if not self.config_path.exists():
            self.config_path = (Path.cwd() / "config" / "config.yaml").resolve()
        self.example_path = self.config_path.with_name("config.example.yaml")
        self._source_note = ""

        self.config: Dict[str, Any] = {}
        self._load_config()
        self._start_watcher()
        atexit.register(self.shutdown)

    def _load_config(self, force: bool = False) -> None:
        # config.yaml 缺失时回退 example 模板：全新克隆/打包解压即可运行，
        # 且本地 config.yaml 仍然优先（example 不含真实密钥，仅模板占位）
        # 主配置重新出现（如 auth 模块回写 token）时切回，避免一直停留在 example
        if self.config_path.name != "config.yaml":
            main = self.example_path.with_name("config.yaml")
            if main.exists():
                self.config_path = main
        if not self.config_path.exists():
            if self.example_path.exists():
                if self._source_note != "example":
                    logger.info(
                        f"config.yaml 不存在，回退模板 {self.example_path.name}"
                    )
                self._source_note = "example"
                self.config_path = self.example_path
            else:
                logger.warning(f"配置文件不存在: {self.config_path}，使用空配置")
                self._source_note = ""
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
            # 解析失败（如编辑器半写入状态）时保留上一份好配置，避免空配置
            # 覆盖运行时导致 LLM 端点/密钥/预算全部丢失
            if self.config:
                logger.error(f"配置文件解析失败，保留上一份有效配置: {exc}")
                return
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

            def replacer(match: re.Match[str]) -> str:
                expr = match.group(1)
                if ":-" in expr:
                    var_name, default = expr.split(":-", 1)
                    return os.environ.get(var_name, default) or ""
                return os.environ.get(expr, "")

            return _ENV_VAR_PATTERN.sub(replacer, value)
        return value

    def _start_watcher(self) -> None:
        if not WATCHDOG_AVAILABLE:
            logger.info("热加载不可用，使用手动重载")
            return

        try:
            handler = ConfigChangeHandler(self)
            observer = Observer()
            observer.schedule(
                handler, path=str(self.config_path.parent), recursive=False
            )
            observer.start()
            self._observer = observer
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

    def save_value(self, key: str, value: Any) -> bool:
        """将 section.key 形式的二级标量键写回 YAML（行级替换，保留注释与格式）。

        找不到目标行或写入失败时返回 False，调用方需自行兜底。
        """
        parts = key.split(".")
        if len(parts) != 2:
            raise ValueError("save_value 仅支持 section.key 形式的一级嵌套键")
        section, name = parts
        # 只写 config.yaml：缺失（正在使用 example 回退）时先物化出一份副本，
        # 避免把运行时生成的密钥写进被 git 跟踪的 config.example.yaml
        if self.config_path.name != "config.yaml":
            main = self.example_path.with_name("config.yaml")
            try:
                main.write_text(
                    self.example_path.read_text(encoding="utf-8"), encoding="utf-8"
                )
                self.config_path = main
                logger.info("config.yaml 不存在，已从模板物化一份用于持久化")
            except Exception as exc:
                logger.warning(f"无法物化 config.yaml，跳过持久化 {key}: {exc}")
                return False
        try:
            text = self.config_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning(f"读取配置文件失败，无法写回 {key}: {exc}")
            return False

        lines = text.splitlines(keepends=True)
        in_section = False
        pattern = re.compile(rf"^(\s*){re.escape(name)}\s*:\s*(.*?)\s*(#.*)?$")
        for i, line in enumerate(lines):
            stripped = line.rstrip("\r\n")
            if not stripped.strip() or stripped.strip().startswith("#"):
                continue
            indent = len(stripped) - len(stripped.lstrip(" "))
            if indent == 0:
                in_section = stripped.split(":", 1)[0].strip() == section
                continue
            if not in_section or indent != 2:
                continue
            m = pattern.match(stripped)
            if not m:
                continue
            new_value = json.dumps(str(value), ensure_ascii=False)
            rebuilt = f"{m.group(1)}{name}: {new_value}"
            if m.group(3):
                rebuilt += f"  {m.group(3)}"
            lines[i] = rebuilt + ("\n" if line.endswith("\n") else "")
            tmp_path = self.config_path.with_suffix(".yaml.tmp")
            try:
                tmp_path.write_text("".join(lines), encoding="utf-8")
                tmp_path.replace(self.config_path)
            except Exception as exc:
                logger.warning(f"配置文件写入失败，无法持久化 {key}: {exc}")
                return False
            self._load_config(force=True)
            logger.info(f"配置项已写回: {key}")
            return True
        logger.warning(f"配置文件中未找到 {key} 行，跳过持久化")
        return False

    def get_redacted(self) -> Dict[str, Any]:
        """深拷贝后掩码所有敏感键（api_key/token/secret/password/credential）为 "***"。"""

        _SENSITIVE_MARKERS = ("api_key", "token", "secret", "password", "credential")

        def _mask(node: Any) -> Any:
            if isinstance(node, dict):
                return {
                    k: (
                        "***"
                        if any(m in str(k).lower() for m in _SENSITIVE_MARKERS)
                        else _mask(v)
                    )
                    for k, v in node.items()
                }
            if isinstance(node, list):
                return [_mask(item) for item in node]
            return node

        with self._config_lock:
            masked = _mask(self.get_all())
        return masked if isinstance(masked, dict) else {}


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
