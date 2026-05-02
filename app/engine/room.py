import asyncio
import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from loguru import logger
from app.core.database import db
from app.core.logger import log_conversation
from app.web.push import push_message_to_websocket


class MessageLayer(Enum):
    L1_PUBLIC = "L1"
    L2_MEETING = "L2"
    L3_PRIVATE = "L3"


@dataclass
class Message:
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    layer: MessageLayer = MessageLayer.L2_MEETING
    sender_role: str = "system"
    sender_id: str = ""
    content: str = ""
    msg_type: str = "text"
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MeetingRoom:
    MAX_HISTORY = 1000

    def __init__(self, task_id):
        self.task_id = task_id
        self.room_id = f"room-{task_id}"
        self.members = {}
        self.history = {layer: [] for layer in MessageLayer}
        self._private_queues = {}
        self._broadcast_queues = {MessageLayer.L1_PUBLIC: [], MessageLayer.L2_MEETING: []}
        self._lock = asyncio.Lock()

    def add_member(self, role, agent_id):
        self.members.setdefault(role, []).append(agent_id)

    async def broadcast(self, layer, sender_role, sender_id, content, msg_type="text", metadata=None, persist=True):
        msg = Message(layer=layer, sender_role=sender_role, sender_id=sender_id, content=content, msg_type=msg_type, metadata=metadata or {})
        async with self._lock:
            self.history[layer].append(msg)
            if len(self.history[layer]) > self.MAX_HISTORY:
                self.history[layer] = self.history[layer][-self.MAX_HISTORY:]
        if persist:
            await self._persist(msg)
        log_conversation(role=f"{sender_role}@{layer.value}", content=content, metadata={"task_id": self.task_id, "room_id": self.room_id, **msg.metadata})
        for q in self._broadcast_queues.get(layer, []):
            await q.put(msg)
        return msg

    async def send_private(self, sender_role, sender_id, recipient_role, recipient_id, content, msg_type="tool_request", metadata=None, persist=True):
        msg = Message(layer=MessageLayer.L3_PRIVATE, sender_role=sender_role, sender_id=sender_id, content=content, msg_type=msg_type, metadata=metadata or {})
        async with self._lock:
            self.history[MessageLayer.L3_PRIVATE].append(msg)
            if len(self.history[MessageLayer.L3_PRIVATE]) > self.MAX_HISTORY:
                self.history[MessageLayer.L3_PRIVATE] = self.history[MessageLayer.L3_PRIVATE][-self.MAX_HISTORY:]
        if persist:
            await self._persist(msg)
        log_conversation(role=f"{sender_role}->{recipient_role}@L3", content=content, metadata={"task_id": self.task_id, "room_id": self.room_id, **msg.metadata})
        try:
            await push_message_to_websocket(self.task_id, {
                "msg_id": msg.msg_id, "layer": msg.layer.value, "sender_role": msg.sender_role,
                "sender_id": msg.sender_id, "content": msg.content, "msg_type": msg.msg_type,
                "metadata": {**msg.metadata, "recipient_role": recipient_role, "recipient_id": recipient_id},
                "timestamp": msg.timestamp.isoformat(),
            })
        except Exception as e:
            logger.warning(f"WebSocket 私聊推送失败: {e}")
        return msg

    async def _persist(self, msg):
        await db.execute(
            "INSERT INTO conversation_messages(msg_id,task_id,layer,sender_role,sender_id,content,metadata,timestamp) VALUES(?,?,?,?,?,?,?,?)",
            (msg.msg_id, self.task_id, msg.layer.value, msg.sender_role, msg.sender_id, msg.content, str(msg.metadata), msg.timestamp.isoformat())
        )


class MeetingRoomManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_init") and self._init:
            return
        self._init = True
        self._rooms = {}
        self._lock = asyncio.Lock()

    async def create_room(self, tid):
        async with self._lock:
            if tid in self._rooms:
                return self._rooms[tid]
            room = MeetingRoom(tid)
            self._rooms[tid] = room
            logger.info(f"创建会议室: {room.room_id}")
            return room

    async def get_room(self, tid):
        return self._rooms.get(tid)

    async def close_room(self, tid):
        async with self._lock:
            if tid in self._rooms:
                del self._rooms[tid]
                logger.info(f"关闭会议室: room-{tid}")


meeting_room_manager = MeetingRoomManager()