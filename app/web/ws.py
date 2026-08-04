import asyncio
import json
from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Set, Optional
from loguru import logger
from app.core.logger import _log_queue
from app.web.push import manager


async def push_log_to_websocket(level: str, message: str, task_id: Optional[str] = None):
    from datetime import datetime, timezone
    log_msg = {"type": "log", "level": level, "message": message, "timestamp": datetime.now(timezone.utc).isoformat(), "task_id": task_id}
    if task_id:
        await manager.broadcast_to_task(task_id, log_msg)
    await manager.broadcast_global(log_msg)


async def websocket_endpoint(websocket: WebSocket, task_id: str = None):
    await manager.connect(websocket, task_id)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, task_id)


async def log_consumer():
    try:
        while True:
            await asyncio.sleep(0.5)
            while not _log_queue.empty():
                try:
                    raw = _log_queue.get_nowait()
                    level, msg = raw.split("|", 1)
                    await push_log_to_websocket(level, msg)
                except Exception:
                    pass
    except asyncio.CancelledError:
        pass