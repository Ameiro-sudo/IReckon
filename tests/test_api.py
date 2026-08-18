"""API 层测试：路由注册、健康检查、实例管理、配置、主题（不触发真实流水线）。"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest
import pytest_asyncio
import httpx

from app.web.api import app

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(scope="module")
async def client(session_db):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture(scope="module")
async def seed_instance(client):
    payload = {
        "id": "test-inst-1",
        "name": "Test Inst",
        "endpoint": "http://localhost:9999/v1",
        "model": "auto",
        "api_key": "",
        "tags": ["general"],
        "max_context": 8192,
        "enabled": True,
    }
    r = await client.post("/api/ai-instances", json=payload)
    assert r.status_code == 200
    yield payload["id"]
    await client.delete(f"/api/ai-instances/{payload['id']}")


async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


async def test_tasks_list(client):
    r = await client.get("/api/tasks")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_task_detail_not_found(client):
    r = await client.get("/api/tasks/task-no-such-id")
    assert r.status_code == 404


async def test_config_get(client):
    r = await client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert "server" in body


async def test_config_update_roundtrip(client):
    r = await client.post("/api/config/update", json={"updates": {"server.port": 8888}})
    assert r.status_code == 200
    r2 = await client.get("/api/config")
    assert r2.json()["server"]["port"] == 8888
    await client.post("/api/config/update", json={"updates": {"server.port": 8000}})


async def test_themes(client):
    r = await client.get("/api/themes")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    assert "catgirl" in body
    assert "programmer" in body


async def test_ai_instance_crud(client, seed_instance):
    iid = seed_instance
    r = await client.get("/api/ai-instances")
    assert r.status_code == 200
    insts = r.json()
    assert any(i["id"] == iid for i in insts)

    r = await client.put(
        f"/api/ai-instances/{iid}",
        json={
            "name": "Renamed",
            "endpoint": "http://localhost:9999/v1",
            "model": "auto",
            "tags": ["general"],
        },
    )
    assert r.status_code == 200

    r = await client.delete(f"/api/ai-instances/{iid}")
    assert r.status_code == 200
    insts = (await client.get("/api/ai-instances")).json()
    inst = next(i for i in insts if i["id"] == iid)
    assert inst["enabled"] is False


async def test_ai_instance_missing_model_field(client):
    r = await client.post(
        "/api/ai-instances", json={"id": "bad", "endpoint": "http://x"}
    )
    assert r.status_code in (200, 422)


async def test_capabilities_endpoint(client):
    r = await client.get("/api/capabilities")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_artifact_endpoints(client, tmp_path, monkeypatch):
    """产物列表/内容/下载端点 + 路径穿越防护。"""
    from app.core.config import config_manager

    tid = "task-art-test"
    out = tmp_path / "outputs" / tid
    out.mkdir(parents=True)
    (out / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (out / "sub").mkdir()
    (out / "sub" / "x.txt").write_text("nested", encoding="utf-8")
    (out / "secret.txt").write_text("secret", encoding="utf-8")

    monkeypatch.setattr(
        config_manager,
        "get",
        lambda k, d=None: {
            "system.data_dir": str(tmp_path),
            "server.frontend_dev_url": "http://localhost:3000",
            "server.port": 8000,
        }.get(k, d),
    )

    r = await client.get(f"/api/tasks/{tid}/artifacts")
    assert r.status_code == 200
    files = r.json()["files"]
    assert {f["path"] for f in files} == {"main.py", "sub/x.txt", "secret.txt"}

    r = await client.get(f"/api/tasks/{tid}/artifact", params={"path": "main.py"})
    assert r.status_code == 200
    assert r.json()["content"] == "print('hello')\n"

    r = await client.get(f"/api/tasks/{tid}/artifact", params={"path": "sub/x.txt"})
    assert r.status_code == 200
    assert r.json()["content"] == "nested"

    # 路径穿越
    r = await client.get(f"/api/tasks/{tid}/artifact", params={"path": "../secret.txt"})
    assert r.status_code == 404

    r = await client.get(f"/api/tasks/{tid}/artifact", params={"path": "nope.py"})
    assert r.status_code == 404

    r = await client.get(f"/api/tasks/{tid}/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
