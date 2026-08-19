"""dsh (DeepSeek Harness) 集成测试:客户端逻辑、SDK/CLI 通道、executor 路径。"""

import asyncio
import sys
from pathlib import Path

from conftest import make_cap
from app.agents.executor import ExecutorAgent
from app.harness.dsh_client import DSHClient

ROOT = Path(__file__).parent.parent.resolve()


class FakeConfig:
    base_dir = Path(ROOT)

    def get(self, key, default=None):
        cfg = {
            "harness.enabled": True,
            "harness.mode": "sdk",
            "harness.model": "deepseek-v4-flash",
            "harness.max_tokens": 4096,
            "harness.timeout_seconds": 30,
            "harness.provider": "deepseek-official",
            "harness.cordis_config": "config/harness/minimal.cordis.yml",
            "harness.session_root": "/tmp/ireckon-test/sessions",
            "harness.workspace_root": "/tmp/ireckon-test/workspaces",
            "harness.cli_command": "npx @deepseek-ai/dsh",
        }
        return cfg.get(key, default)


def make_client():
    c = DSHClient(cfg=FakeConfig())
    c._sdk_checked = False
    c._cli_checked = False
    return c


def test_disabled_harness_returns_error():
    cfg = FakeConfig()
    cfg.get = lambda k, d=None: False if k == "harness.enabled" else d
    result = asyncio.run(DSHClient(cfg=cfg).run("随便一个任务"))
    assert result.ok is False
    assert "未启用" in result.error


def test_empty_task_returns_error():
    result = asyncio.run(make_client().run("   "))
    assert result.ok is False
    assert "任务描述为空" in result.error


def test_no_channel_returns_error(monkeypatch):
    client = make_client()
    monkeypatch.setattr(client, "sdk_available", lambda: False)
    monkeypatch.setattr(client, "cli_available", lambda: False)
    result = asyncio.run(client.run("写一个 hello world"))
    assert result.ok is False
    assert "无可用通道" in result.error


def test_available_mode_prefers_sdk():
    client = make_client()
    client._sdk_checked = True
    client._cli_checked = False
    assert client.sdk_available() is True
    assert client.cli_available() is False
    assert client.available_mode() == "sdk"


def test_cordis_config_generated(monkeypatch, tmp_path):
    cfg = FakeConfig()
    cfg.get = lambda k, d=None: (
        str(tmp_path / "minimal.cordis.yml") if k == "harness.cordis_config" else d
    )
    client = DSHClient(cfg=cfg)
    p = client._cordis_config()
    assert p is not None
    assert p.exists()
    content = p.read_text(encoding="utf-8")
    assert "dsh-llm-deepseek" in content
    assert "DEEPSEEK_API_KEY" in content


def test_sdk_channel_success(monkeypatch):
    client = make_client()
    monkeypatch.setattr(client, "sdk_available", lambda: True)
    calls = {}

    class FakeHarness:
        def __init__(self, **kw):
            calls["kwargs"] = kw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def run(self, task, session_id=None):
            calls["run"] = (task, session_id)
            return type("R", (), {"final_response": "完成!"})()

    monkeypatch.setitem(
        sys.modules, "deepseek_harness", type("m", (), {"DeepSeekHarness": FakeHarness})
    )
    result = asyncio.run(client.run("修复测试", session_id="sid-1"))
    assert result.ok is True
    assert result.mode == "sdk"
    assert result.final_response == "完成!"
    assert calls["run"] == ("修复测试", "sid-1")
    assert calls["kwargs"]["model"] == "deepseek-v4-flash"
    assert calls["kwargs"]["max_tokens"] == 4096
    assert "sid-1" in calls["kwargs"]["cwd"]


def test_cli_channel_success(monkeypatch):
    client = make_client()
    monkeypatch.setattr(client, "sdk_available", lambda: False)
    monkeypatch.setattr(client, "cli_available", lambda: True)
    client._get = lambda k, d=None: (
        "auto" if k == "mode" else FakeConfig().get(f"harness.{k}", d)
    )

    class FakeProc:
        returncode = 0
        stdout = b"final answer here"
        stderr = b""

        async def communicate(self):
            return self.stdout, self.stderr

    async def fake_exec(*cmd, **kw):
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    result = asyncio.run(client.run("跑个任务", session_id="cli-1"))
    assert result.ok is True
    assert result.mode == "cli"
    assert result.final_response == "final answer here"


def test_cli_channel_failure(monkeypatch):
    client = make_client()
    monkeypatch.setattr(client, "sdk_available", lambda: False)
    monkeypatch.setattr(client, "cli_available", lambda: True)
    client._get = lambda k, d=None: (
        "auto" if k == "mode" else FakeConfig().get(f"harness.{k}", d)
    )

    class FakeProc:
        returncode = 1
        stdout = b""
        stderr = b"boom"

        async def communicate(self):
            return self.stdout, self.stderr

    async def fake_exec(*cmd, **kw):
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    result = asyncio.run(client.run("跑个任务"))
    assert result.ok is False
    assert "boom" in result.error


def test_harness_disabled_executor_skips(monkeypatch):
    from app.harness import dsh_client as harness_module
    from app.harness.dsh_client import DSHResult as RealDSHResult

    monkeypatch.setattr(harness_module, "available_mode", lambda: "")
    monkeypatch.setattr(
        harness_module, "run", lambda *a, **kw: RealDSHResult(ok=False, error="unused")
    )
    ex = ExecutorAgent(make_cap())
    result = asyncio.run(ex.execute({"description": "任务", "use_harness": True}))
    assert "harness_error" in result
    assert "dsh 运行时不可用" in result["harness_error"]