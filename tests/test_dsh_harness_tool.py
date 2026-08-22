"""dsh_task 工具深水区补测：workspace 越界校验、双事件循环回退、check_available 探测。"""

import asyncio

import pytest

import app.tools.builtin.dsh_harness.dsh_harness as dh
from app.harness import dsh_client


class _FakeResult:
    ok = True
    final_response = "任务完成"
    session_id = "sess-1"
    workspace = "ws"
    mode = "sdk"
    error = None


@pytest.fixture
def stub_dsh(monkeypatch):
    captured = {}

    async def fake_run(**kwargs):
        captured.update(kwargs)
        return _FakeResult()

    monkeypatch.setattr(dsh_client, "run", fake_run)
    return captured


def test_workspace_outside_root_rejected(tmp_path, stub_dsh):
    # 默认 workspace_root 锚定仓库 data/harness/workspaces，tmp_path 必然在其外
    result = dh.dsh_task("做点事", workspace=str(tmp_path / "outside"))
    assert result["ok"] is False
    assert "workspace 必须位于" in result["error"]
    # 未通过校验前不应发起执行
    assert stub_dsh == {}


def test_workspace_under_root_normalized(tmp_path, monkeypatch, stub_dsh):
    root = tmp_path / "workspaces"
    ws = root / "sess-1"
    ws.mkdir(parents=True)
    monkeypatch.setattr(dh, "get", lambda k, d=None: str(root))
    result = dh.dsh_task("任务", workspace=str(ws))
    assert result["ok"] is True
    assert stub_dsh["workspace"] == str(ws.resolve())


def test_happy_path_result_shaping(stub_dsh):
    result = dh.dsh_task("写个脚本", model="m1", max_tokens=100)
    assert result == {
        "ok": True,
        "final_response": "任务完成",
        "session_id": "sess-1",
        "workspace": "ws",
        "mode": "sdk",
        "error": None,
    }
    assert stub_dsh["task"] == "写个脚本"
    assert stub_dsh["model"] == "m1"
    assert stub_dsh["max_tokens"] == 100
    assert stub_dsh["session_id"] is None


def test_runtime_error_falls_back_to_thread_pool(monkeypatch, stub_dsh):
    real_run = asyncio.run
    calls = {"n": 0}

    def flaky_run(coro):
        calls["n"] += 1
        if calls["n"] == 1:
            coro.close()
            raise RuntimeError("loop already running")
        return real_run(coro)

    monkeypatch.setattr(dh.asyncio, "run", flaky_run)
    result = dh.dsh_task("任务")
    assert result["ok"] is True
    assert calls["n"] == 2


# ---------- check_available ----------


def test_check_available_with_sdk(monkeypatch):
    monkeypatch.setattr(dsh_client, "available_mode", lambda: "sdk")
    monkeypatch.setattr(dsh_client, "sdk_available", lambda: True)
    monkeypatch.setattr(dsh_client, "cli_available", lambda: False)
    monkeypatch.setattr(dsh_client, "_enabled", lambda: True)
    out = dh.check_available()
    assert out == {
        "available": True,
        "mode": "sdk",
        "sdk_installed": True,
        "cli_available": False,
        "enabled": True,
    }


def test_check_available_none_when_unavailable(monkeypatch):
    monkeypatch.setattr(dsh_client, "available_mode", lambda: None)
    monkeypatch.setattr(dsh_client, "sdk_available", lambda: False)
    monkeypatch.setattr(dsh_client, "cli_available", lambda: False)
    monkeypatch.setattr(dsh_client, "_enabled", lambda: False)
    out = dh.check_available()
    assert out["available"] is False
    assert out["mode"] == "none"
