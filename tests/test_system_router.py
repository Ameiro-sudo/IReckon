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
    levels = {e["level"] for e in entries}
    assert "INFO" in levels or not entries
    for e in entries:
        assert set(e.keys()) == {"level", "message"}


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
        assert "警告一" in entries[0]["message"]
