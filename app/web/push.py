"""WebSocket 推送与连接管理：并发安全广播、心跳保活、日志消费者。"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from app.core.logger import _log_queue

_HEARTBEAT_INTERVAL = 30  # 服务端心跳发送间隔（秒）
_STALE_TIMEOUT = 90  # 超过该时长未收到客户端消息即判定僵尸连接
_SEND_TIMEOUT = 5  # 单次广播发送超时（秒）


async def _send_batch(ws: WebSocket, messages: List[dict]):
    for msg in messages:
        await ws.send_json(msg)


class ConnectionManager:
    def __init__(self):
        self.task_connections: Dict[str, Set[WebSocket]] = {}
        self.global_connections: Set[WebSocket] = set()
        self._ws_task: Dict[WebSocket, Optional[str]] = {}  # 连接 -> 所属任务
        self._send_locks: Dict[str, asyncio.Lock] = {}
        self._last_recv: Dict[WebSocket, float] = {}  # 连接最近一次收包时间
        self._mutex = asyncio.Lock()  # 连接集合/心跳表修改与广播迭代共用一把全局锁
        self._batch_queues: Dict[str, List[dict]] = {}
        self._batch_timers: Dict[str, asyncio.Task] = {}
        self._batch_interval = 0.05  # 50ms 批量发送间隔

    async def connect(self, websocket: WebSocket, task_id: Optional[str] = None):
        await websocket.accept()
        async with self._mutex:
            self._last_recv[websocket] = asyncio.get_running_loop().time()
            if task_id:
                self.task_connections.setdefault(task_id, set()).add(websocket)
                self._send_locks.setdefault(task_id, asyncio.Lock())
                self._ws_task[websocket] = task_id
                logger.debug(f"WebSocket 连接任务 {task_id}")
            else:
                self.global_connections.add(websocket)
                self._ws_task[websocket] = None
                logger.debug("WebSocket 全局连接")

    def touch(self, websocket: WebSocket):
        """记录一次收包时间，用于僵尸连接判定。"""
        self._last_recv[websocket] = asyncio.get_running_loop().time()

    async def disconnect(self, websocket: WebSocket, task_id: Optional[str] = None):
        async with self._mutex:
            self._last_recv.pop(websocket, None)
            task_id = task_id or self._ws_task.pop(websocket, None)
            if task_id and task_id in self.task_connections:
                self.task_connections[task_id].discard(websocket)
                if not self.task_connections[task_id]:
                    del self.task_connections[task_id]
                    # 连接数为 0 时清理不再使用的锁与批量队列
                    self._send_locks.pop(task_id, None)
                    self._batch_queues.pop(task_id, None)
                    if task_id in self._batch_timers:
                        self._batch_timers[task_id].cancel()
                        del self._batch_timers[task_id]
            self.global_connections.discard(websocket)

    async def broadcast_to_task(self, task_id: str, message: dict):
        # 锁内取快照，避免迭代中集合被 disconnect/connect 修改
        async with self._mutex:
            targets = list(self.task_connections.get(task_id, ()))
        if not targets:
            return
        async with self._send_locks.setdefault(task_id, asyncio.Lock()):
            dead = []
            for ws in targets:
                try:
                    await asyncio.wait_for(ws.send_json(message), timeout=_SEND_TIMEOUT)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                await self.disconnect(ws, task_id)

    async def broadcast_to_task_batch(self, task_id: str, messages: List[dict]):
        async with self._mutex:
            targets = list(self.task_connections.get(task_id, ()))
        if not targets:
            return
        async with self._send_locks.setdefault(task_id, asyncio.Lock()):
            dead = []
            for ws in targets:
                try:
                    # 单条连接整批发送限时 5s，超时视为死连接
                    await asyncio.wait_for(_send_batch(ws, messages), timeout=_SEND_TIMEOUT)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                await self.disconnect(ws, task_id)

    async def broadcast_global(self, message: dict):
        async with self._mutex:
            targets = list(self.global_connections)
        if not targets:
            return
        dead = []
        for ws in targets:
            try:
                await asyncio.wait_for(ws.send_json(message), timeout=_SEND_TIMEOUT)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)

    async def broadcast_global_batch(self, messages: List[dict]):
        async with self._mutex:
            targets = list(self.global_connections)
        if not targets:
            return
        dead = []
        for ws in targets:
            try:
                await asyncio.wait_for(_send_batch(ws, messages), timeout=_SEND_TIMEOUT)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


manager = ConnectionManager()


async def push_message_to_websocket(task_id: str, msg: dict):
    await manager.broadcast_to_task(task_id, msg)


async def push_progress(task_id: str, progress: float, status: str):
    await manager.broadcast_to_task(
        task_id, {"type": "progress", "progress": progress, "status": status}
    )


async def push_log_to_websocket(
    level: str, message: str, task_id: Optional[str] = None
):
    log_msg = {
        "type": "log",
        "level": level,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_id": task_id,
    }
    if task_id:
        await manager.broadcast_to_task(task_id, log_msg)
    await manager.broadcast_global(log_msg)


async def websocket_endpoint(websocket: WebSocket, task_id: Optional[str] = None):
    await manager.connect(websocket, task_id)
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                # 服务端心跳：30s 无消息则发送 JSON ping，客户端无需应答
                await websocket.send_json(
                    {"type": "ping", "ts": datetime.now(timezone.utc).isoformat()}
                )
                continue
            # 收到任何客户端消息（含 pong 心跳）都视为连接存活
            manager.touch(websocket)
            if data == "ping":
                await websocket.send_json(
                    {"type": "pong", "ts": datetime.now(timezone.utc).isoformat()}
                )
    except WebSocketDisconnect:
        await manager.disconnect(websocket, task_id)
    except Exception:
        await manager.disconnect(websocket, task_id)


async def heartbeat_loop():
    """每 30s 扫描一次：距上次收包超过 90s 的连接视为僵尸，主动关闭并清理。"""
    if getattr(heartbeat_loop, "_started", False):
        return
    heartbeat_loop._started = True
    try:
        while True:
            await asyncio.sleep(_HEARTBEAT_INTERVAL)
            now = asyncio.get_running_loop().time()
            # 快照迭代，避免扫描期间心跳表被修改
            for ws, last in list(manager._last_recv.items()):
                if now - last > _STALE_TIMEOUT:
                    logger.warning("检测到僵尸 WebSocket 连接，主动断开")
                    try:
                        await ws.close(code=1001)
                    except Exception:
                        pass
                    await manager.disconnect(ws)
    except asyncio.CancelledError:
        pass


_log_consumer_started = False


async def log_consumer():
    """日志队列消费者：定时把批量日志推送到所有全局连接。"""
    global _log_consumer_started
    if _log_consumer_started:
        return
    _log_consumer_started = True
    try:
        while True:
            await asyncio.sleep(0.5)
            messages = []
            while not _log_queue.empty():
                try:
                    raw = _log_queue.get_nowait()
                    level, _, msg = raw.partition("|")
                    log_msg = {
                        "type": "log",
                        "level": level.strip(),
                        "message": msg.strip(),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    messages.append(log_msg)
                except Exception:
                    pass
            if messages:
                await manager.broadcast_global_batch(messages)
    except asyncio.CancelledError:
        pass
