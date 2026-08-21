"""AI 实例模型扫描端点与 allow_private_endpoints 开关联动测试。

覆盖：
- POST /api/ai-instances/scan-models：OpenAI/Ollama/裸数组三种响应形态、
  去重封顶、非 200/坏 JSON/连接失败分类、密钥不回显
- security.allow_private_endpoints 开关：注册期静态校验、/test 与
  /scan-models 三条路径判定一致（默认拒绝私网，开启后放行，
  组播/未指定地址始终拒绝）
"""

import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest_asyncio  # noqa: E402

from app.web.api import app  # noqa: E402
from app.web.auth import configured_token  # noqa: E402


@pytest_asyncio.fixture(scope="function")
async def client(session_db):
    transport = httpx.ASGITransport(app=app)
    headers = {"X-API-Token": configured_token()} if configured_token() else {}
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=headers
    ) as c:
        yield c


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _install_httpx_fake(monkeypatch, recorder, response=None, exc=None):
    """把路由模块的 httpx.AsyncClient 换成记录请求的假客户端。"""
    from app.web.routers import instances as instances_router

    class FakeClient:
        def __init__(self, **kw):
            pass

        async def get(self, url, headers=None):
            recorder.append({"url": url, "headers": headers or {}})
            if exc is not None:
                raise exc
            return response

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(
        instances_router.httpx, "AsyncClient", lambda **kw: FakeClient()
    )


def _allow_private(monkeypatch, value):
    from app.web.routers import instances as instances_router

    monkeypatch.setattr(instances_router, "_private_endpoints_allowed", lambda: value)


# ---------- scan-models：响应解析 ----------


async def test_scan_models_openai_shape(client, monkeypatch):
    calls = []
    _install_httpx_fake(
        monkeypatch,
        calls,
        response=FakeResponse(200, {"data": [{"id": "m2"}, {"id": "m1"}]}),
    )
    r = await client.post(
        "/api/ai-instances/scan-models",
        json={"endpoint": "https://93.184.216.34/v1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["models"] == ["m2", "m1"]  # 保序去重，排序交给前端
    assert body["count"] == 2
    assert calls[0]["url"] == "https://93.184.216.34/v1/models"


async def test_scan_models_ollama_and_bare_list_shapes(client, monkeypatch):
    calls = []
    _install_httpx_fake(
        monkeypatch,
        calls,
        response=FakeResponse(
            200, {"models": [{"name": "qwen:7b"}, {"name": "llama3"}]}
        ),
    )
    r = await client.post(
        "/api/ai-instances/scan-models",
        json={"endpoint": "http://93.184.216.34:11434/v1"},
    )
    assert r.json()["models"] == ["qwen:7b", "llama3"]

    _install_httpx_fake(
        monkeypatch,
        calls,
        response=FakeResponse(200, [{"id": "b"}, {"name": "a"}, {"id": "b"}]),
    )
    r = await client.post(
        "/api/ai-instances/scan-models",
        json={"endpoint": "https://93.184.216.34/v1"},
    )
    assert r.json()["models"] == ["b", "a"]


async def test_scan_models_dedupes_and_caps_at_256(client, monkeypatch):
    _install_httpx_fake(
        monkeypatch,
        [],
        response=FakeResponse(200, {"data": [{"id": f"m{i}"} for i in range(300)]}),
    )
    r = await client.post(
        "/api/ai-instances/scan-models",
        json={"endpoint": "https://93.184.216.34/v1"},
    )
    body = r.json()
    assert body["count"] == 256
    assert len(body["models"]) == 256


# ---------- scan-models：失败分类 ----------


async def test_scan_models_bad_json(client, monkeypatch):
    _install_httpx_fake(monkeypatch, [], response=FakeResponse(200, ValueError("bad")))
    r = await client.post(
        "/api/ai-instances/scan-models",
        json={"endpoint": "https://93.184.216.34/v1"},
    )
    body = r.json()
    assert body["status"] == "error"
    assert body["models"] == []


async def test_scan_models_empty_list_is_error(client, monkeypatch):
    _install_httpx_fake(monkeypatch, [], response=FakeResponse(200, {"data": []}))
    r = await client.post(
        "/api/ai-instances/scan-models",
        json={"endpoint": "https://93.184.216.34/v1"},
    )
    assert r.json()["status"] == "error"


async def test_scan_models_http_error_status(client, monkeypatch):
    _install_httpx_fake(monkeypatch, [], response=FakeResponse(401, {}))
    r = await client.post(
        "/api/ai-instances/scan-models",
        json={"endpoint": "https://93.184.216.34/v1", "api_key": "sk-wrong"},
    )
    body = r.json()
    assert body["status"] == "error"
    assert body["error"] == "HTTP 401"


async def test_scan_models_connect_failure(client, monkeypatch):
    _install_httpx_fake(monkeypatch, [], exc=httpx.ConnectError("refused"))
    r = await client.post(
        "/api/ai-instances/scan-models",
        json={"endpoint": "https://93.184.216.34/v1"},
    )
    body = r.json()
    assert body["status"] == "unreachable"
    assert body["error"] == "连接失败"


async def test_scan_models_requires_endpoint(client):
    r = await client.post("/api/ai-instances/scan-models", json={})
    assert r.status_code == 422


async def test_scan_models_never_echoes_api_key(client, monkeypatch):
    _install_httpx_fake(
        monkeypatch, [], response=FakeResponse(200, {"data": [{"id": "m"}]})
    )
    secret = "sk-super-secret-value"
    r = await client.post(
        "/api/ai-instances/scan-models",
        json={"endpoint": "https://93.184.216.34/v1", "api_key": secret},
    )
    assert secret not in r.text


# ---------- scan-models：SSRF 门禁与开关联动 ----------


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://127.0.0.1:11434/v1",
        "http://192.168.1.10:8000/v1",
        "http://169.254.169.254/latest",
    ],
)
async def test_scan_models_private_blocked_by_default(client, monkeypatch, endpoint):
    """开关默认关闭：私网/环回/链路本地目标在出网前即被拦截。"""
    called = []
    _install_httpx_fake(monkeypatch, called)
    r = await client.post("/api/ai-instances/scan-models", json={"endpoint": endpoint})
    assert r.status_code == 400
    assert not called  # 门禁先于任何网络请求


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://0.0.0.0:11434/v1",
        "http://[::]/v1",
        "http://224.0.0.1/v1",
    ],
)
async def test_scan_models_multicast_unspecified_always_blocked(
    client, monkeypatch, endpoint
):
    """即使开关开启：组播/未指定地址仍拒绝（不是合法端点目标）。"""
    _allow_private(monkeypatch, True)
    r = await client.post("/api/ai-instances/scan-models", json={"endpoint": endpoint})
    assert r.status_code == 400


async def test_scan_models_allows_private_when_switch_on(client, monkeypatch):
    calls = []
    _allow_private(monkeypatch, True)
    _install_httpx_fake(
        monkeypatch, calls, response=FakeResponse(200, {"data": [{"id": "local"}]})
    )
    r = await client.post(
        "/api/ai-instances/scan-models",
        json={
            "endpoint": "http://127.0.0.1:11434/v1",
            "api_key": "sk-local",
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert calls[0]["headers"] == {"Authorization": "Bearer sk-local"}


async def test_scan_models_instance_id_fallback_uses_stored_credentials(
    client, monkeypatch
):
    """编辑场景：不重填密钥时经 instance_id 复用存量端点与密钥。"""
    calls = []
    _install_httpx_fake(
        monkeypatch, calls, response=FakeResponse(200, {"data": [{"id": "m"}]})
    )
    iid = "scan-fallback-inst"
    await client.post(
        "/api/ai-instances",
        json={
            "id": iid,
            "endpoint": "https://93.184.216.34/v1",
            "model": "auto",
            "api_key": "sk-stored-key",
        },
    )
    try:
        r = await client.post(
            "/api/ai-instances/scan-models",
            json={"instance_id": iid},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert calls[0]["url"] == "https://93.184.216.34/v1/models"
        assert calls[0]["headers"] == {"Authorization": "Bearer sk-stored-key"}
    finally:
        await client.delete(f"/api/ai-instances/{iid}")


async def test_scan_models_unknown_instance_id(client):
    r = await client.post(
        "/api/ai-instances/scan-models", json={"instance_id": "ai-nope"}
    )
    assert r.status_code == 404


# ---------- 开关联动一致性：注册期静态校验与 /test ----------


async def test_register_loopback_literal_blocked_by_default(client):
    r = await client.post(
        "/api/ai-instances",
        json={
            "id": "loopback-denied",
            "endpoint": "http://127.0.0.1:11434/v1",
            "model": "auto",
        },
    )
    assert r.status_code == 400


async def test_private_endpoint_full_chain_when_switch_on(client, monkeypatch):
    """开关开启后：注册 → 连通性测试全链路放行（test/probe 判定一致）。"""
    _allow_private(monkeypatch, True)
    calls = []
    _install_httpx_fake(monkeypatch, calls, response=FakeResponse(200, {"data": []}))
    iid = "loopback-allowed"
    r = await client.post(
        "/api/ai-instances",
        json={
            "id": iid,
            "endpoint": "http://127.0.0.1:11434/v1",
            "model": "auto",
        },
    )
    assert r.status_code == 200
    try:
        r = await client.post(f"/api/ai-instances/{iid}/test")
        assert r.status_code == 200
        assert r.json()["status"] == "reachable"
        assert calls[0]["url"].startswith("http://127.0.0.1:11434/")
    finally:
        await client.delete(f"/api/ai-instances/{iid}")


async def test_extract_model_ids_rejects_scalar_payload():
    from app.web.routers.instances import _extract_model_ids

    assert _extract_model_ids("not-a-list") == []
    assert _extract_model_ids({"data": "flat-string"}) == []
    assert _extract_model_ids(None) == []
