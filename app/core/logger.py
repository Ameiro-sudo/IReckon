"""日志模块：控制台彩色输出、文件滚动、WebSocket 推送队列。"""

import sys, threading, queue
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from loguru import logger

# 线程安全锁，防止重复初始化
_setup_lock = threading.Lock()
_setup_done = False
# 日志队列，供 WebSocket 推送 / logs API 消费，防止阻塞
_log_queue: "queue.Queue[str]" = queue.Queue(maxsize=5000)

# 控制台输出：时间(绿) | 等级(按等级着色, 8列对齐) | 位置(青) - 消息(按等级着色)
_LOG_FORMAT = (
    "<green>{time:HH:mm:ss.SSS}</green> "
    "| <level>{level: <8}</level> "
    "| <cyan>{name}:{line}</cyan> - <level>{message}</level>"
)
# 文件写入：纯文本，便于机器解析
_FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
# 队列载荷：`LEVEL|message`，与 WebSocket 推送 / logs API 解析约定一致
_QUEUE_FORMAT = "{level}|{message}"


def setup_logging():
    """初始化日志系统（幂等）：控制台 + 文件 + 对话JSON + 推送队列。"""
    global _setup_done
    with _setup_lock:
        if _setup_done:
            return
        _setup_done = True

        from .config import config_manager

        log_level = config_manager.get("system.log_level", "INFO")

        data_dir = Path(config_manager.get("system.data_dir", "./data"))
        log_dir = data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        logger.remove()

        # 控制台输出（按等级着色，彩色高亮前缀）
        logger.add(sys.stdout, format=_LOG_FORMAT, level=log_level, colorize=True)

        # 应用日志文件（保留30天，滚动）
        logger.add(
            log_dir / "app_{time:YYYY-MM-DD}.log",
            format=_FILE_FORMAT,
            level="DEBUG",
            rotation="10 MB",
            retention="30 days",
            encoding="utf-8",
        )

        # 对话日志（JSON 格式，便于分析）
        def conversation_filter(record):
            extra = record.get("extra")
            if not isinstance(extra, dict):
                return False
            return extra.get("log_type") == "conversation"

        logger.add(
            log_dir / "conversation_{time:YYYY-MM-DD}.json",
            level="INFO",
            filter=conversation_filter,
            serialize=True,
            rotation="50 MB",
            encoding="utf-8",
        )

        # 日志队列（供 WebSocket 推送 / logs API 消费）
        def enqueue_log(message):
            try:
                _log_queue.put_nowait(message.record["level"].name + "|" + str(message))
            except queue.Full:
                pass

        logger.add(enqueue_log, level="INFO", format=_QUEUE_FORMAT)


def log_conversation(role: str, content: str, metadata: Optional[dict] = None):
    """记录 AI 对话内容，便于后续分析。"""
    record = {
        "role": role,
        "content": content,
        "metadata": metadata or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    logger.bind(log_type="conversation").info(record)
