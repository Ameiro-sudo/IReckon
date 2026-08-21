"""tasks 路由 API 级测试(补覆盖率盲区)：创建/列表/详情/取消恢复/产物/下载。"""

import asyncio
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest_asyncio
import httpx

from app.core.config import get
from app.web.api import app
from app.web.auth import configured_token
import app.engine.tasks as tasks_mod


@pytest_asyncio.fixture(scope="function")
async def client(session_db):
    transport = httpx.ASGITransport(app=app)
    headers = {"X-API-Token": configured_token()} if configured_token() else {}
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=headers
    ) as c:
        yield c


async def _mk_task(client, req="写个测试脚本"):
    r = await client.post("/api/tasks", json={"user_request": req})
    assert r.status_code == 200
    return r.json()


async def test_create_empty_request_422(client):
    r = await client.post("/api/tasks", json={"user_request": "   "})
    assert r.status_code == 422


async def test_create_list_detail_delete_roundtrip(client, monkeypatch):
    # 梹掉后台启动：避开 LLM 重试退避，任务稳定停留在 pending 可删状态
    started = {}

    async def fake_start(tid, scid=None):
        started[tid] = True

    monkeypatch.setattr(tasks_mod.task_manager, "start_task", fake_start)
    body = await _mk_task(client, "覆盖往返测试")
    tid = body["task_id"]
    assert body["status"] == "pending"

    # 列表可见
    r = await client.get("/api/tasks", params={"limit": 50})
    assert any(t["task_id"] == tid for t in r.json())

    # 状态过滤
    r = await client.get("/api/tasks", params={"status": "pending", "limit": 50})
    assert any(t["task_id"] == tid for t in r.json())

    # 详情：plan/file_refs 缺省容错
    r = await client.get(f"/api/tasks/{tid}")
    assert r.status_code == 200
    d = r.json()
    assert d["tokens"] == 0 and d["cost"] == 0.0

    # 等后台启动失败落地(无可用 LLM 端点)，脱离运行态后再删
    for _ in range(40):
        d = (await client.get(f"/api/tasks/{tid}")).json()
        if d.get("status") == "failed":
            break
        await asyncio.sleep(0.5)
    r = await client.delete(f"/api/tasks/{tid}")
    assert r.status_code == 200
    assert (await client.get(f"/api/tasks/{tid}")).status_code == 404


async def test_detail_not_found(client):
    assert (await client.get("/api/tasks/task-nope")).status_code == 404


async def test_cancel_and_resume_invalid_targets(client):
    r = await client.post("/api/tasks/task-nope/cancel")
    assert r.status_code == 400
    r = await client.post("/api/tasks/task-nope/resume")
    assert r.status_code == 400


async def test_board_missing_404(client):
    r = await client.get("/api/tasks/task-nope/board")
    assert r.status_code == 404


async def test_messages_get_empty_post_without_room_404(client):
    body = await _mk_task(client, "消息层测试")
    tid = body["task_id"]
    r = await client.get(f"/api/tasks/{tid}/messages")
    assert r.status_code == 200 and r.json() == []
    r = await client.post(
        f"/api/tasks/{tid}/messages", json={"content": "你好", "layer": "L1"}
    )
    # 无运行中房间 => 404
    assert r.status_code == 404
    await client.delete(f"/api/tasks/{tid}")


# ---------- 产物端点 ----------


def _outputs_root() -> Path:
    return Path(get("system.data_dir", "./data")) / "outputs"


async def test_artifacts_empty_when_no_dir(client):
    r = await client.get("/api/tasks/task-noartifacts/artifacts")
    assert r.status_code == 200
    assert r.json() == {"task_id": "task-noartifacts", "files": []}


async def test_artifacts_listing_and_read(client):
    out = _outputs_root() / "task-art01"
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.py").write_text("print('done')\n", encoding="utf-8")

    r = await client.get("/api/tasks/task-art01/artifacts")
    body = r.json()
    assert body["files"][0]["path"] == "result.py"

    r = await client.get("/api/tasks/task-art01/artifact", params={"path": "result.py"})
    assert r.status_code == 200
    assert r.json()["content"] == "print('done')\n"


async def test_artifact_traversal_rejected(client):
    out = _outputs_root() / "task-art02"
    (out / "sub").mkdir(parents=True, exist_ok=True)
    (out / "secret.txt").write_text("机密", encoding="utf-8")
    for evil in ("../secret.txt", "..\\secret.txt", "sub/../../secret.txt"):
        r = await client.get("/api/tasks/task-art02/artifact", params={"path": evil})
        assert r.status_code in (403, 404), evil  # 拒绝或不存在，绝不可返回内容


async def test_artifact_missing_file_404(client):
    out = _outputs_root() / "task-art03"
    out.mkdir(parents=True, exist_ok=True)
    r = await client.get("/api/tasks/task-art03/artifact", params={"path": "ghost.py"})
    assert r.status_code == 404


async def test_download_zip_contains_files(client):
    out = _outputs_root() / "task-zip01"
    out.mkdir(parents=True, exist_ok=True)
    (out / "a.txt").write_text("A", encoding="utf-8")
    (out / "sub").mkdir(exist_ok=True)
    (out / "sub" / "b.txt").write_text("B", encoding="utf-8")

    r = await client.get("/api/tasks/task-zip01/download")
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    assert {"a.txt", "sub/b.txt"} <= names


async def test_download_no_artifacts_404(client):
    r = await client.get("/api/tasks/task-nozip/download")
    assert r.status_code == 404
