"""push 深水区补测：websocket_endpoint 收发循环、僵尸清扫、日志消费者、模块级推送函数。"""

import asyncio
from contextlib import suppress

import pytest
from fastapi import WebSocketDisconnect

import app.web.push as push_mod
from app.web.push import (
    ConnectionManager,
    heartbeat_loop,
    log_consumer,
    push_log_to_websocket,
    push_message_to_websocket,
    push_progress,
    websocket_endpoint,
)


class FakeWS:
    """脚本化 WebSocket 替身：send 记录/receive 按脚本吐词/close 记录码。"""

    def __init__(self, script=None, dead=False):
        self.sent = []
        self.accepted = False
        self.accepted_subprotocol = None
        self.closed_codes = []
        self._script = list(script or [])
        self._dead = dead

    async def accept(self, subprotocol=None):
        self.accepted = True
        self.accepted_subprotocol = subprotocol

    async def send_json(self, msg):
        if self._dead:
            raise RuntimeError("connection gone")
        self.sent.append(msg)

    async def receive_text(self):
        if self._script:
            item = self._script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        await asyncio.sleep(3600)  # 脚本耗尽即挂起，交由外层 wait_for 处置

    async def close(self, code=1000):
        self.closed_codes.append(code)


@pytest.fixture
def mgr_env(monkeypatch):
    """独立 ConnectionManager 注入模块单例位。"""
    mgr = ConnectionManager()
    monkeypatch.setattr(push_mod, "manager", mgr)
    return mgr


# ---------- websocket_endpoint ----------


async def test_endpoint_echoes_subprotocol_and_answers_ping(mgr_env, monkeypatch):
    ws = FakeWS(script=["ping"])
    await mgr_env.connect(ws, task_id="t1")  # 预登记，断言退出时清理
    real_wait_for = asyncio.wait_for
    state = {"idle_pings": 1, "passed_through": False}

    async def fast_wait_for(aw, timeout):
        if timeout == 30:
            # 第 1 次空闲 → 服务端 ping；第 2 次放行真实 receive 吃掉脚本；
            # 之后空闲 → 结束会话
            if state["idle_pings"] > 0:
                state["idle_pings"] -= 1
                aw.close()
                raise asyncio.TimeoutError()
            if not state["passed_through"]:
                state["passed_through"] = True
                return await real_wait_for(aw, timeout)
            aw.close()
            raise WebSocketDisconnect()
        return await real_wait_for(aw, timeout)

    monkeypatch.setattr(push_mod.asyncio, "wait_for", fast_wait_for)
    await websocket_endpoint(ws, task_id="t1", subprotocol="ireckon.v1")
    assert ws.accepted_subprotocol == "ireckon.v1"
    assert ws.sent and ws.sent[0]["type"] == "ping"
    # 客户端 ping 得到 pong 应答
    assert any(m.get("type") == "pong" for m in ws.sent)
    # 会话结束后连接簿记清空
    assert ws not in mgr_env.task_connections.get("t1", set())
    assert ws not in mgr_env._last_recv


async def test_endpoint_generic_exception_disconnects_cleanly(mgr_env):
    ws = FakeWS(script=[RuntimeError("boom")])
    await mgr_env.connect(ws)
    await websocket_endpoint(ws, task_id=None)
    assert ws not in mgr_env.global_connections


async def test_endpoint_client_touch_updates_liveness(mgr_env, monkeypatch):
    ws = FakeWS(script=["ping", WebSocketDisconnect()])
    await mgr_env.connect(ws)
    touched = []
    real_touch = mgr_env.touch

    def spy_touch(w):
        touched.append(w)
        real_touch(w)

    monkeypatch.setattr(mgr_env, "touch", spy_touch)
    await websocket_endpoint(ws)
    # 客户端每条消息触发一次 touch 刷新存活时间戳
    assert touched == [ws]


# ---------- heartbeat_loop ----------


async def test_heartbeat_sweeps_only_stale_connections(mgr_env, monkeypatch):
    monkeypatch.setattr(push_mod, "_HEARTBEAT_INTERVAL", 0.02)
    live = FakeWS()
    stale = FakeWS(dead=True)  # close 不依赖 send，dead 标志不影响 close
    await mgr_env.connect(live)
    await mgr_env.connect(stale)
    loop = asyncio.get_running_loop()
    mgr_env._last_recv[stale] = loop.time() - 10_000  # 人为老化超过 90s 阈值

    heartbeat_loop._started = False
    task = asyncio.create_task(heartbeat_loop())
    await asyncio.sleep(0.09)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    heartbeat_loop._started = False  # 卫生复位（取消路径本身不复位，生产中终生运行）

    assert stale.closed_codes == [1001]
    assert stale not in mgr_env._last_recv
    assert live in mgr_env._last_recv


async def test_heartbeat_single_flight_guard():
    heartbeat_loop._started = True
    try:
        await asyncio.wait_for(heartbeat_loop(), timeout=0.2)  # 立即返回不进入循环
    finally:
        heartbeat_loop._started = False


# ---------- log_consumer ----------


async def test_log_consumer_parses_batch_and_broadcasts(mgr_env, monkeypatch):
    gws = FakeWS()
    await mgr_env.connect(gws)
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put("12:34:56|INFO|任务启动")
    await queue.put(None)  # 非字符串载荷触发跳过分支
    monkeypatch.setattr(push_mod, "_log_queue", queue)

    push_mod._log_consumer_started = False
    task = asyncio.create_task(log_consumer())
    await asyncio.sleep(0.75)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    push_mod._log_consumer_started = False

    logs = [m for m in gws.sent if m.get("type") == "log"]
    assert len(logs) == 1
    assert logs[0]["level"] == "INFO"
    assert logs[0]["message"] == "任务启动"
    assert logs[0]["time"] == "12:34:56"
    assert "timestamp" in logs[0]


async def test_log_consumer_single_flight_guard():
    push_mod._log_consumer_started = True
    try:
        await asyncio.wait_for(log_consumer(), timeout=0.2)
    finally:
        push_mod._log_consumer_started = False


# ---------- 广播批量与模块级函数 ----------


async def test_broadcast_global_batch_order_and_dead_drop(mgr_env):
    live = FakeWS()
    dead = FakeWS(dead=True)
    for ws in (live, dead):
        await mgr_env.connect(ws)
    msgs = [{"i": i} for i in range(3)]
    await mgr_env.broadcast_global_batch(msgs)
    assert [m["i"] for m in live.sent] == [0, 1, 2]
    assert dead not in mgr_env.global_connections


async def test_module_level_push_helpers_delegate(mgr_env):
    tws = FakeWS()
    gws = FakeWS()
    await mgr_env.connect(tws, task_id="t1")
    await mgr_env.connect(gws)

    await push_message_to_websocket("t1", {"type": "text"})
    await push_progress("t1", 0.4, "reviewing")
    await push_log_to_websocket("WARN", "注意", task_id="t1")

    assert tws.sent[0] == {"type": "text"}
    assert {
        "type": "progress",
        "progress": 0.4,
        "status": "reviewing",
    } in tws.sent
    log_msg = tws.sent[-1]
    assert log_msg["type"] == "log"
    assert log_msg["level"] == "WARN" and log_msg["message"] == "注意"
    assert log_msg["task_id"] == "t1" and "timestamp" in log_msg
    # 带 task_id 的日志同时进全局流
    assert any(m.get("type") == "log" and m.get("task_id") == "t1" for m in gws.sent)


async def test_push_log_without_task_only_global(mgr_env):
    tws = FakeWS()
    gws = FakeWS()
    await mgr_env.connect(tws, task_id="t1")
    await mgr_env.connect(gws)

    await push_log_to_websocket("INFO", "系统级消息")
    assert tws.sent == []  # 无 task_id 不进任务通道
    assert len(gws.sent) == 1 and gws.sent[0]["task_id"] is None
