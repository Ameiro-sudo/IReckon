"""命令过滤器与 WebSocket 推送测试。"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest

from app.security.filter import CommandFilter, CommandLevel
from app.web.push import ConnectionManager, push_message_to_websocket


def test_classify_levels():
    cf = CommandFilter()
    assert cf.classify("rm -rf /") == CommandLevel.L3
    assert cf.classify("dd if=/dev/zero of=/dev/sda") == CommandLevel.L3
    assert cf.classify("pip install requests") == CommandLevel.L2
    assert cf.classify("apt-get update") == CommandLevel.L2
    assert cf.classify("echo hello") == CommandLevel.L1


def test_filter_l1_auto():
    cf = CommandFilter()
    cf.l1_auto = True
    assert cf.filter("echo hi") == {"executable": True, "level": "L1"}


def test_filter_l2_needs_votes():
    cf = CommandFilter()
    cf.l2_threshold = 0.5
    assert cf.filter("pip install x", votes=[True, True])["executable"] is True
    assert cf.filter("pip install x", votes=[False])["executable"] is False
    assert cf.filter("pip install x")["executable"] is False


def test_filter_l3_blocked():
    cf = CommandFilter()
    cf.l3_block = True
    assert cf.filter("rm -rf /")["executable"] is False


def test_filter_l3_block_disabled():
    cf = CommandFilter()
    cf.l3_block = False
    r = cf.filter("rm -rf /")
    assert r["executable"] is False  # 仍未通过，但没有 L3 标记


class FakeWS:
    def __init__(self):
        self.sent = []
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, msg):
        self.sent.append(msg)


@pytest.mark.asyncio
async def test_connection_manager_task_broadcast():
    m = ConnectionManager()
    ws1, ws2 = FakeWS(), FakeWS()
    await m.connect(ws1, "t1")
    await m.connect(ws2, "t1")
    await m.broadcast_to_task("t1", {"x": 1})
    assert len(ws1.sent) == 1
    assert len(ws2.sent) == 1
    m.disconnect(ws1, "t1")
    await m.broadcast_to_task("t1", {"x": 2})
    assert len(ws1.sent) == 1
    assert len(ws2.sent) == 2


@pytest.mark.asyncio
async def test_connection_manager_global_and_dead_ws():
    m = ConnectionManager()
    good, bad = FakeWS(), FakeWS()
    await m.connect(good)
    await m.connect(bad)
    bad.send_json = None

    async def failing(msg):
        raise RuntimeError("dead")

    bad.send_json = failing
    await m.broadcast_global({"x": 1})
    assert len(good.sent) == 1
    assert bad not in m.global_connections


@pytest.mark.asyncio
async def test_push_message_helper():
    from app.web.push import manager

    manager.task_connections.clear()
    ws = FakeWS()
    await manager.connect(ws, "t9")
    await push_message_to_websocket("t9", {"y": 2})
    assert ws.sent == [{"y": 2}]
