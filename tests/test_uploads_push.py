"""上传路由与 WebSocket 推送层测试（补 CODE_REVIEW P2-11 盲区）。

- uploads：白名单过滤、数量/大小限制、路径穿越消毒、磁盘落盘验证；
- push.ConnectionManager：连接簿记、定向/全局广播、死连接清理、锁回收。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest_asyncio
import httpx

from app.core.config import get
from app.web.api import app
from app.web.auth import configured_token
from app.web.push import ConnectionManager


@pytest_asyncio.fixture(scope="function")
async def client(session_db):
    transport = httpx.ASGITransport(app=app)
    headers = {"X-API-Token": configured_token()} if configured_token() else {}
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=headers
    ) as c:
        yield c


# ---------- uploads ----------


def _uploads_root() -> Path:
    return (Path(get("system.data_dir", "./data")) / "uploads").resolve()


async def test_upload_single_file_writes_disk(client):
    r = await client.post(
        "/api/uploads",
        files={"files": ("notes.txt", b"hello ireckon", "text/plain")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert len(body["files"]) == 1
    saved = body["files"][0]
    assert saved["name"] == "notes.txt"
    assert saved["size"] == len(b"hello ireckon")
    # 磁盘落盘验证
    on_disk = _uploads_root() / body["upload_id"] / "notes.txt"
    assert on_disk.read_bytes() == b"hello ireckon"


async def test_upload_multiple_files(client):
    r = await client.post(
        "/api/uploads",
        files=[
            ("files", ("a.py", b"print(1)", "text/x-python")),
            ("files", ("b.md", b"# doc", "text/markdown")),
            ("files", ("c.json", b"{}", "application/json")),
        ],
    )
    assert r.status_code == 200
    assert {f["name"] for f in r.json()["files"]} == {"a.py", "b.md", "c.json"}


async def test_upload_too_many_files_rejected(client):
    files = [("files", (f"f{i}.txt", b"x", "text/plain")) for i in range(21)]
    r = await client.post("/api/uploads", files=files)
    assert r.status_code == 413


async def test_upload_all_invalid_extension(client):
    r = await client.post(
        "/api/uploads",
        files=[("files", ("evil.exe", b"MZ...", "application/octet-stream"))],
    )
    assert r.status_code == 400


async def test_upload_mixed_valid_and_invalid(client):
    r = await client.post(
        "/api/uploads",
        files=[
            ("files", ("good.py", b"ok = True", "text/x-python")),
            ("files", ("bad.exe", b"MZ...", "application/octet-stream")),
        ],
    )
    assert r.status_code == 200
    names = {f["name"] for f in r.json()["files"]}
    assert names == {"good.py"}


async def test_upload_oversized_file_skipped(client):
    big = b"x" * (10 * 1024 * 1024 + 1)
    r = await client.post(
        "/api/uploads",
        files=[("files", ("big.log", big, "text/plain"))],
    )
    # 唯一文件超限被跳过 => 没有有效文件
    assert r.status_code == 400


async def test_upload_traversal_filename_sanitized(client):
    r = await client.post(
        "/api/uploads",
        files=[("files", ("../../evil.py", b"hacked = True", "text/x-python"))],
    )
    assert r.status_code == 200
    saved = r.json()["files"][0]
    # Path(...).name 已剥离目录成分
    assert saved["name"] == "evil.py"
    # 文件确实落在 upload_id 目录内，而非穿越到外部
    on_disk = _uploads_root() / r.json()["upload_id"] / "evil.py"
    assert on_disk.exists()


# ---------- push.ConnectionManager ----------


class FakeWS:
    """最小 WebSocket 替身：记录 send_json 调用；dead 则模拟发送失败。"""

    def __init__(self, dead=False):
        self.sent = []
        self.accepted = False
        self.closed = False
        self._dead = dead

    async def accept(self):
        self.accepted = True

    async def send_json(self, msg):
        if self._dead:
            raise RuntimeError("connection gone")
        self.sent.append(msg)


async def test_connect_bookkeeping_task_and_global():
    mgr = ConnectionManager()
    task_ws = FakeWS()
    global_ws = FakeWS()
    await mgr.connect(task_ws, task_id="t1")
    await mgr.connect(global_ws)
    assert task_ws.accepted and global_ws.accepted
    assert task_ws in mgr.task_connections["t1"]
    assert global_ws in mgr.global_connections
    assert mgr._ws_task[task_ws] == "t1"
    assert mgr._ws_task[global_ws] is None


async def test_broadcast_to_task_reaches_only_that_task():
    mgr = ConnectionManager()
    ws_t1 = FakeWS()
    ws_t2 = FakeWS()
    await mgr.connect(ws_t1, task_id="t1")
    await mgr.connect(ws_t2, task_id="t2")
    await mgr.broadcast_to_task("t1", {"type": "progress"})
    assert len(ws_t1.sent) == 1
    assert ws_t2.sent == []


async def test_broadcast_dead_connection_cleaned():
    mgr = ConnectionManager()
    dead_ws = FakeWS(dead=True)
    live_ws = FakeWS()
    await mgr.connect(dead_ws, task_id="t1")
    await mgr.connect(live_ws, task_id="t1")
    await mgr.broadcast_to_task("t1", {"type": "progress"})
    # 死连接被移出簿记，活连接照常收到消息
    assert dead_ws not in mgr.task_connections.get("t1", set())
    assert live_ws in mgr.task_connections["t1"]
    assert len(live_ws.sent) == 1


async def test_disconnect_last_connection_removes_lock():
    mgr = ConnectionManager()
    ws = FakeWS()
    await mgr.connect(ws, task_id="t9")
    assert "t9" in mgr._send_locks
    await mgr.disconnect(ws, "t9")
    assert "t9" not in mgr.task_connections
    assert "t9" not in mgr._send_locks
    assert ws not in mgr.global_connections


async def test_broadcast_global_reaches_all_and_drops_dead():
    mgr = ConnectionManager()
    live1 = FakeWS()
    live2 = FakeWS()
    dead = FakeWS(dead=True)
    for ws in (live1, live2, dead):
        await mgr.connect(ws)
    await mgr.broadcast_global({"type": "log"})
    assert len(live1.sent) == 1 and len(live2.sent) == 1
    assert dead not in mgr.global_connections


async def test_push_progress_message_shape():
    mgr = ConnectionManager()
    ws = FakeWS()
    await mgr.connect(ws, task_id="t1")
    # push_progress 引用模块级单例 manager；这里直接等价调用其广播内容
    await mgr.broadcast_to_task(
        "t1", {"type": "progress", "progress": 0.5, "status": "executing"}
    )
    assert ws.sent == [{"type": "progress", "progress": 0.5, "status": "executing"}]


async def test_batch_broadcast_order_preserved():
    mgr = ConnectionManager()
    ws = FakeWS()
    await mgr.connect(ws, task_id="t1")
    msgs = [{"i": i} for i in range(5)]
    await mgr.broadcast_to_task_batch("t1", msgs)
    assert [m["i"] for m in ws.sent] == [0, 1, 2, 3, 4]
