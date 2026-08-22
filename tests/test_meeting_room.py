"""MeetingRoom 补测：分层历史裁剪、私聊路由、推送旁路与容错、持久化、管理器生命周期。"""

import asyncio
import json

import pytest

import app.web.push as push_mod
from app.engine.room import (
    MeetingRoom,
    MeetingRoomManager,
    Message,
    MessageLayer,
)


@pytest.fixture
def clean_manager():
    """单例管理器状态隔离。"""
    mgr = MeetingRoomManager()
    mgr._rooms = {}
    yield mgr
    mgr._rooms = {}


@pytest.fixture
def push_spy(monkeypatch):
    """拦截 websocket 推送（room 内函数级 import 每次解析最新属性）。"""
    pushed = []

    async def fake_push(task_id, msg):
        pushed.append({"task_id": task_id, **msg})

    monkeypatch.setattr(push_mod, "push_message_to_websocket", fake_push)
    return pushed


# ---------- Message 基础 ----------


def test_message_defaults_unique_ids():
    a, b = Message(), Message()
    assert a.msg_id != b.msg_id
    assert len(a.msg_id) == 32  # uuid4().hex
    assert a.layer is MessageLayer.L2_MEETING
    assert a.sender_role == "system"
    assert a.metadata == {}
    assert a.timestamp.tzinfo is not None


# ---------- broadcast 主路径 ----------


async def test_broadcast_appends_layer_and_returns_message(push_spy):
    room = MeetingRoom("t-1")
    msg = await room.broadcast(
        MessageLayer.L1_PUBLIC,
        "executor",
        "exec-1",
        "你好",
        msg_type="code",
        metadata={"k": "v"},
        persist=False,
    )
    assert room.history[MessageLayer.L1_PUBLIC] == [msg]
    assert msg.sender_role == "executor" and msg.content == "你好"
    assert msg.metadata == {"k": "v"}
    # L1/L2 实时推送，L3 才跳过
    assert len(push_spy) == 1
    assert push_spy[0]["layer"] == "L1"
    assert push_spy[0]["task_id"] == "t-1"


async def test_broadcast_history_trim_keeps_latest(monkeypatch):
    monkeypatch.setattr(MeetingRoom, "MAX_HISTORY", 3)
    room = MeetingRoom("t-trim")
    for i in range(5):
        await room.broadcast(
            MessageLayer.L2_MEETING, "s", "sid", f"m{i}", persist=False
        )
    layer_msgs = room.history[MessageLayer.L2_MEETING]
    assert [m.content for m in layer_msgs] == ["m2", "m3", "m4"]


async def test_push_timeout_swallowed_broadcast_survives(monkeypatch):
    async def slow_push(task_id, msg):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(push_mod, "push_message_to_websocket", slow_push)
    room = MeetingRoom("t-timeout")
    msg = await room.broadcast(
        MessageLayer.L2_MEETING, "s", "sid", "内容", persist=False
    )
    assert msg.content == "内容"  # 推送超时不阻塞会议主流程


async def test_push_generic_exception_swallowed(monkeypatch):
    async def broken_push(task_id, msg):
        raise RuntimeError("连接炸了")

    monkeypatch.setattr(push_mod, "push_message_to_websocket", broken_push)
    room = MeetingRoom("t-broken")
    msg = await room.broadcast(
        MessageLayer.L2_MEETING, "s", "sid", "内容", persist=False
    )
    assert msg.msg_id  # 异常被吞，广播照常完成


# ---------- send_private ----------


async def test_send_private_routes_recipient_metadata(push_spy):
    room = MeetingRoom("t-priv")
    msg = await room.send_private(
        "executor", "exec-1", "tool_manager", "tm-1", "借个工具", persist=False
    )
    assert msg.layer is MessageLayer.L3_PRIVATE
    assert msg.msg_type == "tool_request"
    # 私聊推送携带收件人元数据（在推送载荷的 metadata 键内）
    assert push_spy[0]["metadata"]["recipient_role"] == "tool_manager"
    assert push_spy[0]["metadata"]["recipient_id"] == "tm-1"
    assert push_spy[0]["layer"] == "L3"


async def test_send_private_timeout_swallowed(monkeypatch):
    async def slow_push(task_id, msg):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(push_mod, "push_message_to_websocket", slow_push)
    room = MeetingRoom("t-priv-timeout")
    msg = await room.send_private("a", "a1", "b", "b1", "密信", persist=False)
    assert msg.content == "密信"


# ---------- 持久化 ----------


async def _seed_task(db, task_id):
    """conversation_messages.task_id 外键引用 tasks——持久化用例先落主表行。"""
    await db.execute(
        "INSERT INTO tasks(task_id, user_request, status) VALUES (?, ?, ?)",
        (task_id, "测试需求", "executing"),
    )


async def test_broadcast_persists_row(session_db, push_spy):
    await _seed_task(session_db, "t-db")
    room = MeetingRoom("t-db")
    msg = await room.broadcast(
        MessageLayer.L2_MEETING,
        "reviewer",
        "rev-1",
        "审查意见",
        metadata={"verdict": "pass"},
    )
    row = await session_db.fetch_one(
        "SELECT * FROM conversation_messages WHERE msg_id = ?", (msg.msg_id,)
    )
    assert row is not None
    # fetch_one 返回元组：列序 msg_id,task_id,layer,...,metadata,...
    assert row[1] == "t-db"
    assert json.loads(row[6]) == {"verdict": "pass"}


async def test_persist_false_skips_write(session_db, push_spy):
    room = MeetingRoom("t-nodb")
    msg = await room.broadcast(
        MessageLayer.L2_MEETING, "s", "sid", "不留痕", persist=False
    )
    # 按 msg_id 定向断言：库文件同轮全量共享，COUNT(*) 会数进别的用例的行
    row = await session_db.fetch_one(
        "SELECT msg_id FROM conversation_messages WHERE msg_id = ?", (msg.msg_id,)
    )
    assert row is None


async def test_send_private_persists_l3_row(session_db, push_spy):
    await _seed_task(session_db, "t-l3db")
    room = MeetingRoom("t-l3db")
    msg = await room.send_private("a", "a1", "b", "b1", "私货")
    row = await session_db.fetch_one(
        "SELECT layer FROM conversation_messages WHERE msg_id = ?", (msg.msg_id,)
    )
    assert row[0] == "L3"


# ---------- 管理器生命周期 ----------


async def test_create_room_idempotent(clean_manager):
    r1 = await clean_manager.create_room("task-a")
    r2 = await clean_manager.create_room("task-a")
    assert r1 is r2
    assert r1.room_id == "room-task-a"


async def test_get_room_missing_returns_none(clean_manager):
    assert await clean_manager.get_room("从未创建") is None


async def test_close_room_removes_and_missing_noop(clean_manager):
    await clean_manager.create_room("task-b")
    await clean_manager.close_room("task-b")
    assert await clean_manager.get_room("task-b") is None
    await clean_manager.close_room("task-b")  # 二次关闭 no-op
