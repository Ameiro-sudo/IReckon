"""API 层测试：路由注册、健康检查、实例管理、配置、主题（不触发真实流水线）。"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest_asyncio
import httpx

from app.web.api import app
from app.web.auth import configured_token


@pytest_asyncio.fixture(scope="function")
async def client(session_db):
    transport = httpx.ASGITransport(app=app)
    headers = {"X-API-Token": configured_token()} if configured_token() else {}
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=headers
    ) as c:
        yield c


@pytest_asyncio.fixture(scope="function")
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
    # 免鉴权端点：未携带有效 token 时只暴露存活状态，不泄露内部信息
    if configured_token():
        assert "version" in body
        assert "active_tasks" in body
    else:
        assert set(body.keys()) == {"status"}


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
    r = await client.post("/api/config/update", json={"updates": {"ui.theme": "cyber"}})
    assert r.status_code == 200
    r2 = await client.get("/api/config")
    assert r2.json()["ui"]["theme"] == "cyber"
    await client.post("/api/config/update", json={"updates": {"ui.theme": "catgirl"}})


async def test_config_update_forbidden_key(client):
    """白名单之外的 key（如 server.port、ai_pool.*）应被拒绝。"""
    r = await client.post("/api/config/update", json={"updates": {"server.port": 8888}})
    assert r.status_code == 403


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
    # 物理删除：删除后不应再出现在列表中
    insts = (await client.get("/api/ai-instances")).json()
    assert not any(i["id"] == iid for i in insts)
    # 重复删除应 404
    r = await client.delete(f"/api/ai-instances/{iid}")
    assert r.status_code == 404


async def test_ai_instance_missing_model_field(client):
    r = await client.post(
        "/api/ai-instances", json={"id": "bad", "endpoint": "http://x"}
    )
    assert r.status_code in (200, 422)


async def test_ai_instance_duplicate_id_rejected(client, seed_instance):
    """同 ID 重复创建必须 409，防止实例被覆盖劫持。"""
    payload = {
        "id": seed_instance,
        "name": "Hijacked",
        "endpoint": "http://evil.example/v1",
        "model": "x",
        "tags": [],
        "enabled": False,
    }
    r = await client.post("/api/ai-instances", json=payload)
    assert r.status_code == 409
    insts = (await client.get("/api/ai-instances")).json()
    mine = next(i for i in insts if i["id"] == seed_instance)
    assert mine["name"] != "Hijacked"


async def test_ai_instance_auto_generated_id(client):
    """不传 id 时自动生成 ai- 前缀 ID。"""
    r = await client.post(
        "/api/ai-instances",
        json={
            "name": "Auto",
            "endpoint": "http://localhost:9999/v1",
            "model": "auto",
            "tags": ["general"],
        },
    )
    assert r.status_code == 200
    iid = r.json()["id"]
    assert iid.startswith("ai-")
    await client.delete(f"/api/ai-instances/{iid}")


async def test_ai_instance_api_key_masked_and_roundtrip(client):
    """列表接口不泄露明文密钥；空 key 更新保留原密钥，新 key 更新替换。"""
    from app.llm.pool import capability_pool

    iid = "test-inst-key"
    r = await client.post(
        "/api/ai-instances",
        json={
            "id": iid,
            "name": "Keyed",
            "endpoint": "http://localhost:9999/v1",
            "model": "auto",
            "api_key": "sk-super-secret",
            "tags": ["general"],
        },
    )
    assert r.status_code == 200

    insts = (await client.get("/api/ai-instances")).json()
    item = next(i for i in insts if i["id"] == iid)
    assert "api_key" not in item
    assert item["has_key"] is True

    cap = await capability_pool.get_by_id(iid)
    assert cap.api_key == "sk-super-secret"

    r = await client.put(
        f"/api/ai-instances/{iid}",
        json={"endpoint": "http://localhost:9999/v1", "model": "auto"},
    )
    assert r.status_code == 200
    cap = await capability_pool.get_by_id(iid)
    assert cap.api_key == "sk-super-secret"

    await client.put(
        f"/api/ai-instances/{iid}",
        json={
            "endpoint": "http://localhost:9999/v1",
            "model": "auto",
            "api_key": "sk-new-key",
        },
    )
    cap = await capability_pool.get_by_id(iid)
    assert cap.api_key == "sk-new-key"

    await client.delete(f"/api/ai-instances/{iid}")


async def test_ai_instance_test_reachable(client, monkeypatch):
    from app.web.routers import instances as instances_router

    iid = "test-inst-reach"

    class FakeResponse:
        status_code = 200
        text = '{"data":[{"id":"auto"}]}'

    class FakeClient:
        async def get(self, url, headers=None):
            assert url.endswith("/models")
            return FakeResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(
        instances_router.httpx, "AsyncClient", lambda **kw: FakeClient()
    )

    await client.post(
        "/api/ai-instances",
        json={
            "id": iid,
            "endpoint": "http://8.8.8.8/v1",
            "model": "auto",
        },
    )
    r = await client.post(f"/api/ai-instances/{iid}/test")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "reachable"
    assert body["http_status"] == 200
    assert isinstance(body["latency_ms"], int)
    await client.delete(f"/api/ai-instances/{iid}")


async def test_ai_instance_test_unreachable(client, monkeypatch):
    from app.web.routers import instances as instances_router

    iid = "test-inst-dead"

    class FakeClient:
        async def get(self, url, headers=None):
            raise httpx.ConnectError("connection refused")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(
        instances_router.httpx, "AsyncClient", lambda **kw: FakeClient()
    )

    await client.post(
        "/api/ai-instances",
        json={
            "id": iid,
            "endpoint": "http://8.8.8.8:1/v1",
            "model": "auto",
        },
    )
    r = await client.post(f"/api/ai-instances/{iid}/test")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "unreachable"
    assert "error" in body
    await client.delete(f"/api/ai-instances/{iid}")


async def test_ai_instance_test_not_found(client):
    r = await client.post("/api/ai-instances/ai-no-such-id/test")
    assert r.status_code == 404


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

    # 路径穿越（SSRF 防护升级后返回 403）
    r = await client.get(f"/api/tasks/{tid}/artifact", params={"path": "../secret.txt"})
    assert r.status_code == 403

    r = await client.get(f"/api/tasks/{tid}/artifact", params={"path": "nope.py"})
    assert r.status_code == 404

    r = await client.get(f"/api/tasks/{tid}/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
