"""
日志模块 (๑•̀ᴗ-)✧
记录系统运行的各种信息，帮助调试和问题排查～
"""

import sys, threading, queue
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from loguru import logger

# 线程安全锁，防止重复初始化～
_setup_lock = threading.Lock()
_setup_done = False
_log_queue = queue.Queue(maxsize=5000)  # 日志队列，防止阻塞～

# 控制台输出格式，美美的绿色～
_LOG_FORMAT = "<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <level>{message}</level>"
# 文件写入格式，清晰工整～
_FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"

def setup_logging():
    """
    设置日志系统～调用一次就好，会自动配置控制台输出和文件日志～
    """
    global _setup_done
    with _setup_lock:
        if _setup_done: return  # 只需要初始化一次就好～
        _setup_done = True

        # 从配置读取日志级别～
        from .config import config_manager
        log_level = config_manager.get("system.log_level", "INFO")
        
        # 创建日志目录～
        data_dir = Path(config_manager.get("system.data_dir", "./data"))
        log_dir = data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        # 移除默认处理器，重新配置～
        logger.remove()
        
        # 控制台输出（带颜色超好看！）
        logger.add(sys.stdout, format=_LOG_FORMAT, level=log_level, colorize=True)
        
        # 应用日志文件（保留30天，滚动存储～）
        logger.add(log_dir / "app_{time:YYYY-MM-DD}.log", format=_FILE_FORMAT, level="DEBUG", rotation="10 MB", retention="30 days", encoding="utf-8")
        
        # 对话日志（JSON格式，方便分析～）
        def conversation_filter(record):
            extra = record.get("extra")
            if not isinstance(extra, dict): return False
            return extra.get("log_type") == "conversation"
        logger.add(log_dir / "conversation_{time:YYYY-MM-DD}.json", level="INFO", filter=conversation_filter, serialize=True, rotation="50 MB", encoding="utf-8")
        
        # 日志队列（给WebSocket推送用～）
        def enqueue_log(message):
            try: _log_queue.put_nowait(message.record["level"].name + "|" + str(message))
            except queue.Full: pass
        logger.add(enqueue_log, level="INFO", format="{message}")

def log_conversation(role: str, content: str, metadata: Optional[dict] = None):
    """
    记录 AI 对话内容～
    方便后续分析 AI 的思考过程哦～
    """
    record = {
        "role": role, 
        "content": content, 
        "metadata": metadata or {}, 
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    logger.bind(log_type="conversation").info(record)