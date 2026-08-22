"""system 路由测试(补覆盖率盲区)：auth/check、stats、logs 读取与 DEBUG 过滤。"""

import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest_asyncio
import httpx

from app.core.config import get
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


def _write_today_log(lines):
    log_dir = Path(get("system.data_dir", "./data")) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    f = log_dir / f"app_{datetime.now().strftime('%Y-%m-%d')}.log"
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f


async def test_auth_check_no_token_loopback_trusted(client, monkeypatch):
    """未配置 token 且绑定回环时，本机请求被信任(设计语义)。"""
    monkeypatch.delenv("IRECKON_API_TOKEN", raising=False)
    r = await client.get("/api/auth/check")
    assert r.status_code == 200


async def test_auth_check_valid_token_body(client, monkeypatch):
    monkeypatch.setenv("IRECKON_API_TOKEN", "irk_strict_test")
    r = await client.get("/api/auth/check", headers={"X-API-Token": "irk_strict_test"})
    # 免鉴权路径：恒 200，用布尔回答是否通过
    assert r.status_code == 200
    assert r.json() == {"authenticated": True, "required": True}


async def test_auth_check_wrong_token_reports_not_authenticated(client, monkeypatch):
    monkeypatch.setenv("IRECKON_API_TOKEN", "irk_strict_test")
    r = await client.get("/api/auth/check", headers={"X-API-Token": "definitely-wrong"})
    assert r.status_code == 200
    assert r.json() == {"authenticated": False, "required": True}


async def test_stats_shape(client):
    r = await client.get("/api/stats")
    assert r.status_code == 200
    body = r.json()
    for key in (
        "total_tasks",
        "by_status",
        "active_tasks",
        "ai_instances",
        "uptime_seconds",
    ):
        assert key in body


async def test_logs_returns_parsed_entries(client):
    _write_today_log(
        [
            "2026-08-21 12:00:00 | INFO | 服务启动完成",
            "2026-08-21 12:00:01 | DEBUG | SELECT * FROM tasks",
            "坏行没有管道分隔",
        ]
    )
    r = await client.get("/api/logs?limit=50")
    assert r.status_code == 200
    entries = r.json()
    assert isinstance(entries, list)
    for e in entries:
        assert set(e.keys()) == {"time", "level", "message"}
    by_msg = {e["message"]: e for e in entries}

    info = by_msg.get("服务启动完成")
    assert info is not None
    assert info["level"] == "INFO"
    assert info["time"] == "12:00:00"

    # DEBUG 行仅 strict token 可见；无 token 环境下被过滤
    debug = by_msg.get("SELECT * FROM tasks")
    if debug is not None:
        assert debug["level"] == "DEBUG"
        assert debug["time"] == "12:00:01"

    # 坏行(无管道分隔)按 INFO 容错保留，时间为空
    bad = by_msg.get("坏行没有管道分隔")
    if bad is not None:
        assert bad["time"] == ""


async def test_logs_level_filter(client):
    _write_today_log(
        [
            "2026-08-21 12:00:00 | INFO | 信息一",
            "2026-08-21 12:00:01 | WARNING | 警告一",
        ]
    )
    r = await client.get("/api/logs?limit=50&level=warning")
    assert r.status_code == 200
    entries = r.json()
    assert all(e["level"] == "WARNING" for e in entries)
    if entries:
        assert entries[0]["level"] == "WARNING"
        assert "警告一" in entries[0]["message"]
        assert entries[0]["time"] == "12:00:01"


# ---------- health / usage / update（无人值守轮4 补测） ----------

import app.web.routers.system as sys_mod


def _reset_update_cache():
    sys_mod._update_cache.update({"latest": None, "checked_at": 0.0})


async def test_health_unauthenticated_returns_minimal(client, monkeypatch):
    from app.web import auth as auth_mod

    monkeypatch.delenv("IRECKON_API_TOKEN", raising=False)
    # 双重隔离：套件早段用例（app 装配/ensure_token 物化路径）会把随机 token
    # 留在模块级 _runtime_token 与 config_manager 内存态——configured_token
    # 三级回退全部打空，锁定"未携带有效令牌 → 仅存活应答"语义不受用例顺序影响
    monkeypatch.setattr(auth_mod, "_runtime_token", "")
    monkeypatch.setattr(auth_mod, "get", lambda k, d=None: d)
    r = await client.get("/api/health")
    # 免鉴权降级：只回答存活，不泄露版本/任务数等内部信息
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_health_authenticated_full_shape_and_cache(client, monkeypatch):
    monkeypatch.setenv("IRECKON_API_TOKEN", "irk_strict_test")
    _reset_update_cache()

    class Cap:
        enabled = True

    async def fake_get_all(refresh=False):
        return [Cap()]

    calls = {"n": 0}

    async def fake_check():
        calls["n"] += 1
        return None

    monkeypatch.setattr(sys_mod.capability_pool, "get_all", fake_get_all)
    monkeypatch.setattr(sys_mod.updater, "check", fake_check)

    h = {"X-API-Token": "irk_strict_test"}
    body = (await client.get("/api/health", headers=h)).json()
    assert body["status"] == "ok"
    assert body["ai_instances"] == 1
    assert body["update_available"] is False
    assert "uptime_seconds" in body and "ws_connections" in body

    # 10 分钟缓存窗口内第二次健康检查不再请求 GitHub
    await client.get("/api/health", headers=h)
    assert calls["n"] == 1


async def test_usage_endpoint_delegates_to_summary(client, monkeypatch):
    async def fake_summary():
        return {"total_tokens": 42}

    monkeypatch.setattr(sys_mod, "get_summary", fake_summary)
    r = await client.get("/api/usage")
    assert r.status_code == 200
    assert r.json() == {"total_tokens": 42}


async def test_logs_invalid_level_line_locked_as_info_whole_message(client):
    # 非法级别行：级别回退 INFO 且消息保留整行原文（含时间戳前缀）——锁定现状语义
    _write_today_log(["2026-08-21 12:00:00 | TRACE | 追踪行原文"])
    entries = (await client.get("/api/logs?limit=50")).json()
    hit = [e for e in entries if "追踪行原文" in e["message"]]
    assert len(hit) == 1
    assert hit[0]["level"] == "INFO"
    assert hit[0]["time"] == "12:00:00"
    assert hit[0]["message"] == "2026-08-21 12:00:00 | TRACE | 追踪行原文"


async def test_logs_limit_clips_to_latest_n(client):
    lines = [f"2026-08-21 12:00:{i:02d} | INFO | 行{i}" for i in range(10)]
    _write_today_log(lines)
    entries = (await client.get("/api/logs?limit=3")).json()
    assert [e["message"] for e in entries] == ["行7", "行8", "行9"]


async def test_logs_debug_visible_with_strict_token(client, monkeypatch):
    monkeypatch.setenv("IRECKON_API_TOKEN", "irk_strict_test")
    h = {"X-API-Token": "irk_strict_test"}
    _write_today_log(
        [
            "2026-08-21 12:00:00 | INFO | 明文信息",
            "2026-08-21 12:00:01 | DEBUG | 敏感调试行",
        ]
    )
    entries = (await client.get("/api/logs?limit=50", headers=h)).json()
    by_msg = {e["message"]: e for e in entries}
    assert "明文信息" in by_msg
    assert by_msg["敏感调试行"]["level"] == "DEBUG"


async def test_update_check_endpoint_shape(client, monkeypatch):
    async def fake_check():
        return "0.2.0"

    monkeypatch.setattr(sys_mod.updater, "check", fake_check)
    r = await client.get("/api/update/check")
    body = r.json()
    assert body["latest_version"] == "0.2.0"
    assert body["update_available"] is True
    assert body["current_version"] == get("system.version")
    assert body["channel"] in ("installer", "portable")


async def _strict_client(monkeypatch, token="irk_strict_test"):
    monkeypatch.setenv("IRECKON_API_TOKEN", token)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Token": token},
    )


async def test_apply_unknown_channel_rejected(monkeypatch):
    c = await _strict_client(monkeypatch)
    async with c:
        r = await c.post("/api/update/apply", json={"channel": "软驱"})
    assert r.json()["status"] == "error"
    assert "未知渠道" in r.json()["error"]


async def test_apply_no_new_version_errors(monkeypatch):
    async def fake_check():
        return None

    monkeypatch.setattr(sys_mod.updater, "check", fake_check)
    c = await _strict_client(monkeypatch)
    async with c:
        r = await c.post("/api/update/apply", json={"channel": "portable"})
    body = r.json()
    assert body["status"] == "error"
    assert body["error"] == "没有新版本"


async def test_apply_installer_success_message(monkeypatch):
    async def fake_check():
        return "0.2.0"

    applied = {}

    async def fake_dl(version, channel=None, silent=False):
        applied.update(version=version, channel=channel, silent=silent)
        return True

    monkeypatch.setattr(sys_mod.updater, "check", fake_check)
    monkeypatch.setattr(sys_mod.updater, "download_and_update", fake_dl)
    c = await _strict_client(monkeypatch)
    async with c:
        r = await c.post(
            "/api/update/apply", json={"channel": "installer", "silent": True}
        )
    body = r.json()
    assert body["status"] == "ok" and body["version"] == "0.2.0"
    assert body["channel"] == "installer"
    assert "安装器已启动" in body["message"]
    # silent 与渠道如实透传下载器
    assert applied == {"version": "0.2.0", "channel": "installer", "silent": True}


async def test_apply_portable_failure_restore_message(monkeypatch):
    async def fake_check():
        return "0.2.0"

    async def fake_dl(version, channel=None, silent=False):
        return False

    monkeypatch.setattr(sys_mod.updater, "check", fake_check)
    monkeypatch.setattr(sys_mod.updater, "download_and_update", fake_dl)
    c = await _strict_client(monkeypatch)
    async with c:
        r = await c.post("/api/update/apply", json={"channel": "portable"})
    body = r.json()
    assert body["status"] == "error"
    assert "还原备份" in body["message"]
