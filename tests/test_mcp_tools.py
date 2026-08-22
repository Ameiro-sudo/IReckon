"""MCP Server 工具面补测：参数透传/结果整形/endpoint 掩码安全回归/_ensure_db 幂等。

mcp_server 是对外暴露的模型池入口（opencode/Claude Code 等注册调用）；
pool_status 的 endpoint 掩码是 PR#13 安全修复的一部分，此前无显式回归断言。
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import app.llm.router as router_mod
import app.mcp_server as srv
from conftest import make_cap


@pytest.fixture(autouse=True)
def _reset_db_ready(monkeypatch):
    # _db_ready 是模块级全局，逐用例复位保证幂等断言有效
    monkeypatch.setattr(srv, "_db_ready", False)


def _fake_database(connect_counter=None):
    async def connect():
        if connect_counter is not None:
            connect_counter["n"] += 1

    return SimpleNamespace(connect=connect)


async def test_ensure_db_connects_once_and_idempotent(monkeypatch):
    counter = {"n": 0}
    monkeypatch.setattr("app.core.database.db", _fake_database(counter))
    await srv._ensure_db()
    await srv._ensure_db()
    assert counter["n"] == 1
    assert srv._db_ready is True


# ---------- tool_ask / tool_review / tool_delegate 参数透传 ----------


@pytest.fixture
def ask_spy(monkeypatch):
    calls = []

    async def fake_ask(prompt, **kw):
        calls.append({"prompt": prompt, **kw})
        return {"content": "ok"}

    monkeypatch.setattr(router_mod, "ask", fake_ask)
    return calls


async def test_tool_ask_passes_params(ask_spy, monkeypatch):
    monkeypatch.setattr("app.core.database.db", _fake_database())
    out = await srv.tool_ask(
        "总结这段话", system_prompt="你是摘要器", tier="heavy", max_tokens=128
    )
    assert out == {"content": "ok"}
    kw = ask_spy[0]
    assert kw["prompt"] == "总结这段话"
    assert kw["system_prompt"] == "你是摘要器"
    assert kw["tier"] == "heavy"
    assert kw["temperature"] == 0.0
    assert kw["max_tokens"] == 128
    assert kw["use_cache"] is True


async def test_tool_ask_empty_system_prompt_becomes_none(ask_spy, monkeypatch):
    monkeypatch.setattr("app.core.database.db", _fake_database())
    await srv.tool_ask("hi")
    kw = ask_spy[0]
    assert kw["system_prompt"] is None
    assert kw["tier"] == "light"
    assert kw["max_tokens"] is None


async def test_tool_review_uses_heavy_channel_and_prompt_shape(ask_spy, monkeypatch):
    monkeypatch.setattr("app.core.database.db", _fake_database())
    await srv.tool_review("x = 1", language="python", focus="注入风险")
    kw = ask_spy[0]
    assert kw["tier"] == "heavy"
    assert kw["system_prompt"] == srv.REVIEW_SYSTEM_PROMPT
    assert "python" in kw["prompt"]
    assert "注入风险" in kw["prompt"]
    assert "x = 1" in kw["prompt"]


async def test_tool_delegate_shapes_result(monkeypatch):
    monkeypatch.setattr("app.core.database.db", _fake_database())

    import app.harness.dsh_client as dsh_mod

    async def fake_run(task, workspace=None, session_id=None):
        return SimpleNamespace(
            ok=True,
            session_id=session_id or "gen-sid",
            workspace=workspace or "gen-ws",
            mode="portable",
            final_response="done",
            error=None,
        )

    monkeypatch.setattr(dsh_mod, "run", fake_run)
    out = await srv.tool_delegate("写个爬虫", session_id="s1", workspace="w1")
    assert out == {
        "ok": True,
        "session_id": "s1",
        "workspace": "w1",
        "mode": "portable",
        "final_response": "done",
        "error": None,
    }


async def test_tool_delegate_error_passthrough(monkeypatch):
    monkeypatch.setattr("app.core.database.db", _fake_database())

    import app.harness.dsh_client as dsh_mod

    async def fake_run(task, workspace=None, session_id=None):
        return SimpleNamespace(
            ok=False,
            session_id="s",
            workspace="w",
            mode="docker",
            final_response="",
            error="boom",
        )

    monkeypatch.setattr(dsh_mod, "run", fake_run)
    out = await srv.tool_delegate("任务")
    assert out["ok"] is False
    assert out["error"] == "boom"


# ---------- pool_status endpoint 掩码（PR#13 安全语义回归） ----------


def _pool_stub(caps):
    class _P:
        async def get_all(self):
            return list(caps)

    return _P()


async def test_pool_status_masks_endpoint_paths_and_ports(monkeypatch):
    caps = [
        make_cap(id="cloud", endpoint="https://api.deepseek.com/v1"),
        make_cap(id="ollama", endpoint="http://localhost:11434"),
    ]
    monkeypatch.setattr("app.llm.pool.capability_pool", _pool_stub(caps))
    monkeypatch.setattr("app.llm.cache.response_cache.stats", lambda: {"hits": 3})
    monkeypatch.setattr("app.core.database.db", _fake_database())

    status = await srv.tool_pool_status()
    by_id = {i["id"]: i for i in status["instances"]}
    # scheme+host 保留，路径与端口细节掩去（显式端口以 * 标记存在性，无端口则不标）
    assert by_id["cloud"]["endpoint"] == "https://api.deepseek.com"
    assert by_id["ollama"]["endpoint"] == "http://localhost/*"
    # 任何实例字段都不得泄漏完整 endpoint 原文
    for inst in status["instances"]:
        for v in inst.values():
            assert "/v1" not in str(v)
            assert "11434" not in str(v)
    assert status["cache"] == {"hits": 3}


async def test_pool_status_unconfigured_and_invalid_endpoints(monkeypatch):
    caps = [
        make_cap(id="blank", endpoint=""),
        make_cap(id="garbage", endpoint="not-a-url"),
        make_cap(id="badport", endpoint="http://host:99999/"),
    ]
    monkeypatch.setattr("app.llm.pool.capability_pool", _pool_stub(caps))
    monkeypatch.setattr("app.llm.cache.response_cache.stats", lambda: {})
    monkeypatch.setattr("app.core.database.db", _fake_database())

    status = await srv.tool_pool_status()
    by_id = {i["id"]: i["endpoint"] for i in status["instances"]}
    assert by_id["blank"] == "(未配置)"
    assert by_id["garbage"] == "(未配置)"
    assert by_id["badport"] == "(非法)"


async def test_pool_status_includes_capability_fields(monkeypatch):
    cap = make_cap(id="c1", name="DeepSeek 主通道", model="deepseek-v4")
    monkeypatch.setattr("app.llm.pool.capability_pool", _pool_stub([cap]))
    monkeypatch.setattr("app.llm.cache.response_cache.stats", lambda: {})
    monkeypatch.setattr("app.core.database.db", _fake_database())

    status = await srv.tool_pool_status()
    inst = status["instances"][0]
    assert inst["id"] == "c1"
    assert inst["name"] == "DeepSeek 主通道"
    assert inst["model"] == "deepseek-v4"
    assert "channel" in inst and "enabled" in inst
    assert "cost_per_1k_tokens" in inst


# ---------- 传输层构建 ----------


def test_build_server_missing_sdk_exits_with_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "mcp", None)
    with pytest.raises(SystemExit, match="MCP SDK"):
        srv.build_server()


def test_build_server_returns_named_instance():
    pytest.importorskip("mcp")
    server = srv.build_server()
    assert getattr(server, "name", "") == "ireckon"
