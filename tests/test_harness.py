"""dsh (DeepSeek Harness) 集成测试:客户端逻辑、SDK/CLI 通道、executor 路径。"""

import asyncio
import sys
from pathlib import Path

from app.agents.executor import ExecutorAgent
from app.harness.dsh_client import DSHClient, DSHResult
from conftest import make_cap

ROOT = Path(__file__).parent.parent.resolve()

CFG = {
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
    # 通道测试使用真实 cordis（danger-full-access），显式开启安全门
    "harness.allow_full_access": True,
}


class FakeConfig:
    base_dir = Path(ROOT)

    def get(self, key, default=None):
        return CFG.get(key, default)


def make_client():
    return DSHClient(cfg=FakeConfig())


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


def test_workspace_escape_rejected():
    """workspace 逃逸 workspace_root 必须被拒绝。"""
    client = make_client()
    result = asyncio.run(
        client.run("任务", workspace="/etc")  # 绝对路径且不在 workspace_root 之下
    )
    assert result.ok is False
    assert "workspace_root" in result.error


def test_full_access_gate_blocks_by_default():
    """安全门：cordis 为 danger-full-access 且未显式允许时必须拒绝。"""
    cfg = FakeConfig()
    # allow_full_access 未配置（返回默认 False）→ 安全门生效
    cfg.get = lambda k, d=None: (
        d if k == "harness.allow_full_access" else CFG.get(k, d)
    )
    client = DSHClient(cfg=cfg)
    result = asyncio.run(client.run("写一个 hello world"))
    assert result.ok is False
    assert "danger-full-access" in result.error
    assert "allow_full_access" in result.error


def test_command_filter_blocks_dangerous_task():
    """命令过滤接入点：任务文本内嵌高危 shell 构造时拒绝执行。"""
    client = make_client()
    client._get = lambda k, d=None: (
        True if k == "allow_full_access" else CFG.get(f"harness.{k}", d)
    )
    result = asyncio.run(client.run("执行 `rm -rf /` 清理环境"))
    assert result.ok is False
    assert "命令过滤" in result.error


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


def make_fake_proc(rc, out=b"", err=b""):
    class FakeProc:
        def __init__(self):
            self.returncode = rc
            self.stdout = asyncio.StreamReader()
            self.stdout.feed_data(out)
            self.stdout.feed_eof()
            self.stderr = asyncio.StreamReader()
            self.stderr.feed_data(err)
            self.stderr.feed_eof()
            self.killed = False

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            return self.returncode

    return FakeProc()


def _patch_cli_mode(client):
    client._get = lambda k, d=None: (
        "auto" if k == "mode" else CFG.get(f"harness.{k}", d)
    )


def test_cli_channel_success(monkeypatch):
    client = make_client()
    monkeypatch.setattr(client, "sdk_available", lambda: False)
    monkeypatch.setattr(client, "cli_available", lambda: True)
    _patch_cli_mode(client)

    async def fake_exec(*args, **kwargs):
        return make_fake_proc(0, out=b"final answer here\n")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    result = asyncio.run(client.run("跑个任务", session_id="cli-1"))
    assert result.ok is True
    assert result.mode == "cli"
    assert result.final_response == "final answer here"


def test_cli_channel_failure(monkeypatch):
    client = make_client()
    monkeypatch.setattr(client, "sdk_available", lambda: False)
    monkeypatch.setattr(client, "cli_available", lambda: True)
    _patch_cli_mode(client)

    async def fake_exec(*args, **kwargs):
        return make_fake_proc(1, err=b"boom\n")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    result = asyncio.run(client.run("跑个任务"))
    assert result.ok is False
    assert "boom" in result.error


def test_harness_disabled_executor_skips(monkeypatch):
    from app.harness import dsh_client

    monkeypatch.setattr(dsh_client, "available_mode", lambda: "")
    monkeypatch.setattr(
        dsh_client,
        "run",
        lambda *a, **kw: DSHResult(ok=False, error="unused"),
    )
    ex = ExecutorAgent(make_cap())
    result = asyncio.run(ex.execute({"description": "任务", "use_harness": True}))
    assert "harness_error" in result
    assert "dsh 运行时不可用" in result["harness_error"]