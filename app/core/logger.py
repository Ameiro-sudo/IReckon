"""日志模块：控制台对齐输出、文件滚动、WebSocket 推送队列。"""

import logging
import os
import queue
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

# 线程安全锁，防止重复初始化
_setup_lock = threading.Lock()
_setup_done = False
# 日志队列，供 WebSocket 推送 / logs API 消费，防止阻塞
_log_queue: "queue.Queue[str]" = queue.Queue(maxsize=5000)

# ANSI 颜色（仅控制台使用）
_TIME_COLOR = "\x1b[38;5;245m"  # 时间：灰
_LOC_COLOR = "\x1b[38;5;81m"  # 位置：青
_LEVEL_COLORS = {
    "TRACE": "\x1b[38;5;244m",
    "DEBUG": "\x1b[38;5;244m",
    "INFO": "\x1b[38;5;114m",
    "SUCCESS": "\x1b[38;5;114m",
    "WARNING": "\x1b[38;5;221m",
    "ERROR": "\x1b[38;5;203m",
    "CRITICAL": "\x1b[38;5;196m",
}
_RESET = "\x1b[0m"

# 文件写入：纯文本，便于机器解析，含完整模块定位
_FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
)
# 队列载荷：`LEVEL|message`，与 WebSocket 推送 / logs API 解析约定一致
_QUEUE_FORMAT = "{level}|{message}"


def _should_colorize() -> bool:
    """是否输出 ANSI 颜色：默认跟随终端，可用 IRECKON_LOG_COLOR=1/0 强制开关。"""
    env = os.environ.get("IRECKON_LOG_COLOR", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    if env in ("0", "false", "no", "off"):
        return False
    try:
        return bool(sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


_console_color = _should_colorize()


def _short_module(name: str) -> str:
    """模块名精简：去掉 app. 前缀，最多保留两段，如 app.engine.machine -> engine.machine"""
    parts = [p for p in name.split(".") if p]
    if parts and parts[0] == "app":
        parts = parts[1:]
    if len(parts) > 2:
        parts = parts[-2:]
    return ".".join(parts) or "-"


def _console_sink(message):
    """控制台 sink：手动格式化，多行消息自动缩进对齐；重定向到文件时自动去掉颜色。"""
    record = message.record
    level_name = record["level"].name
    when = record["time"].strftime("%H:%M:%S.%f")[:-3]
    std_logger = record["extra"].get("std_logger")
    if std_logger:
        loc = std_logger
    else:
        loc = f"{_short_module(record['name'])}:{record['line']}"
    visible = f"{when} | {level_name: <8} | {loc} - "
    body = str(record["message"])
    lines = body.splitlines() or [""]
    pad = " " * len(visible)

    if _console_color:
        color = _LEVEL_COLORS.get(level_name, "")
        head = (
            f"{_TIME_COLOR}{when}{_RESET} | {color}{level_name: <8}{_RESET}"
            f" | {_LOC_COLOR}{loc}{_RESET} - {color}"
        )
        out = head + lines[0] + _RESET
        for line in lines[1:]:
            out += "\n" + pad + color + line + _RESET
    else:
        out = visible + lines[0]
        for line in lines[1:]:
            out += "\n" + pad + line

    try:
        sys.stdout.write(out + "\n")
        sys.stdout.flush()
    except (ValueError, OSError):
        pass


# 模块导入即启用统一控制台格式：任何模块（含导入期日志）都不再走 loguru 默认格式
# 优化：仅在非测试环境立即配置 sink，测试环境由 conftest 统一管理
import os as _os

if not _os.environ.get("PYTEST_CURRENT_TEST"):
    logger.remove()
    logger.add(_console_sink, level="DEBUG")


class _InterceptHandler(logging.Handler):
    """把标准库 logging 桥接到 loguru，第三方库日志格式统一。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(exception=record.exc_info).bind(std_logger=record.name).log(
            level, record.getMessage()
        )


def setup_logging():
    """初始化日志系统（幂等）：控制台 + 文件 + 对话JSON + 推送队列。"""
    global _setup_done, _console_color
    with _setup_lock:
        if _setup_done:
            return
        _setup_done = True

        from .config import get

        log_level = get("system.log_level", "INFO")

        data_dir = Path(get("system.data_dir", "./data"))
        log_dir = data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        _console_color = _should_colorize()
        logger.remove()

        # 控制台输出（多行对齐，按等级着色，非 TTY 自动去色）
        logger.add(_console_sink, level=log_level)

        # 应用日志文件（保留30天，滚动）
        logger.add(
            log_dir / "app_{time:YYYY-MM-DD}.log",
            format=_FILE_FORMAT,
            level="DEBUG",
            rotation="10 MB",
            retention="30 days",
            encoding="utf-8",
            enqueue=True,
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
            enqueue=True,
        )

        # 日志队列（供 WebSocket 推送 / logs API 消费）
        def enqueue_log(message):
            try:
                _log_queue.put_nowait(message.record["level"].name + "|" + str(message))
            except queue.Full:
                pass

        logger.add(enqueue_log, level="INFO", format=_QUEUE_FORMAT)

        # 标准库 logging -> loguru，第三方库日志格式统一
        logging.basicConfig(
            handlers=[_InterceptHandler()], level=logging.DEBUG, force=True
        )


def log_banner(title: str, lines, level: str = "INFO"):
    """以多条独立日志输出一组信息（如启动信息），避免单条多行消息破坏对齐。"""
    logger.log(level, title)
    for line in lines:
        if line:
            logger.log(level, line)


def log_conversation(role: str, content: str, metadata: Optional[dict] = None):
    """记录 AI 对话内容，便于后续分析。"""
    record = {
        "role": role,
        "content": content,
        "metadata": metadata or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    logger.bind(log_type="conversation").info(record)
