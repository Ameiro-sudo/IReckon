import asyncio
from fastapi import WebSocket
from typing import Dict, Set, Optional
from loguru import logger


class ConnectionManager:
    def __init__(self):
        self.task_connections: Dict[str, Set[WebSocket]] = {}
        self.global_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket, task_id: Optional[str] = None):
        await websocket.accept()
        if task_id:
            if task_id not in self.task_connections:
                self.task_connections[task_id] = set()
            self.task_connections[task_id].add(websocket)
            logger.debug(f"WebSocket 连接任务 {task_id}")
        else:
            self.global_connections.add(websocket)
            logger.debug("WebSocket 全局连接")

    def disconnect(self, websocket: WebSocket, task_id: Optional[str] = None):
        if task_id and task_id in self.task_connections:
            self.task_connections[task_id].discard(websocket)
            if not self.task_connections[task_id]:
                del self.task_connections[task_id]
        self.global_connections.discard(websocket)

    async def broadcast_to_task(self, task_id: str, message: dict):
        if task_id in self.task_connections:
            dead = set()
            for ws in self.task_connections[task_id]:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.add(ws)
            for ws in dead:
                self.disconnect(ws, task_id)

    async def broadcast_global(self, message: dict):
        dead = set()
        for ws in self.global_connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws)

manager = ConnectionManager()


async def push_message_to_websocket(task_id: str, msg: dict):
    await manager.broadcast_to_task(task_id, msg)


async def push_progress(task_id: str, progress: float, status: str):
    await manager.broadcast_to_task(task_id, {"type": "progress", "progress": progress, "status": status})