import sys, threading, queue
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from loguru import logger

_setup_lock = threading.Lock()
_setup_done = False
_log_queue = queue.Queue(maxsize=5000)
logger.remove()
logger.add(sys.stderr, level="DEBUG", colorize=True)

def setup_logging():
    global _setup_done
    with _setup_lock:
        if _setup_done: return
        _setup_done = True
        from core.config_manager import config_manager
        log_level = config_manager.get("system.log_level", "INFO")
        data_dir = Path(config_manager.get("system.data_dir", "./data"))
        log_dir = data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.remove()
        logger.add(sys.stdout, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>", level=log_level, colorize=True)
        logger.add(log_dir / "app_{time:YYYY-MM-DD}.log", format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}", level="DEBUG", rotation="10 MB", retention="30 days", encoding="utf-8")
        def conversation_filter(record):
            extra = record.get("extra")
            if not isinstance(extra, dict): return False
            return extra.get("log_type") == "conversation"
        logger.add(log_dir / "conversation_{time:YYYY-MM-DD}.json", level="INFO", filter=conversation_filter, serialize=True, rotation="50 MB", encoding="utf-8")
        def enqueue_log(message):
            try: _log_queue.put_nowait(message.record["level"].name + "|" + str(message))
            except queue.Full: pass
        logger.add(enqueue_log, level="INFO", format="{message}")
        logger.info("日志系统初始化完成")

def log_conversation(role: str, content: str, metadata: Optional[dict] = None):
    record = {"role": role, "content": content, "metadata": metadata or {}, "timestamp": datetime.now(timezone.utc).isoformat()}
    logger.bind(log_type="conversation").info(record)
