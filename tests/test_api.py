"""API 层测试：路由注册、健康检查、实例管理、配置、主题（不触发真实流水线）。"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest
import pytest_asyncio
import httpx

from app.web.api import app
from app.core.database import db

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
        json={"name": "Renamed", "endpoint": "http://localhost:9999/v1", "model": "auto", "tags": ["general"]},
    )
    assert r.status_code == 200

    r = await client.delete(f"/api/ai-instances/{iid}")
    assert r.status_code == 200
    insts = (await client.get("/api/ai-instances")).json()
    inst = next(i for i in insts if i["id"] == iid)
    assert inst["enabled"] is False


async def test_ai_instance_missing_model_field(client):
    r = await client.post("/api/ai-instances", json={"id": "bad", "endpoint": "http://x"})
    assert r.status_code in (200, 422)


async def test_capabilities_endpoint(client):
    r = await client.get("/api/capabilities")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
