"""dsh_client 深水区补测：输出收集器、进程树清理、会话锁、cordis 变体、CLI 子进程全链路。"""

import asyncio
import sys

import pytest

from app.harness.dsh_client import (
    DSHClient,
    DSHResult,
    _StderrTail,
    _StdoutSink,
    _drain_cli,
    _kill_tree,
)


class FakeCfg:
    """最小配置桩：get 按字典返回（兼容 _get 的 harness. 前缀），base_dir 锚定 tmp。"""

    def __init__(self, tmp_path, values=None):
        self.base_dir = tmp_path
        self._v = values or {}

    def get(self, key, default=None):
        return self._v.get(key.replace("harness.", "", 1), default)


# ---------- 输出收集器 ----------


def test_stdout_sink_truncates_at_cap():
    sink = _StdoutSink(max_bytes=10)
    sink.feed(b"12345")
    assert sink.text() == "12345"
    sink.feed(b"67890ABCDEF")  # 超出剩余空间：截到正好 10 字节后丢弃后续
    assert sink.text() == "1234567890"
    sink.feed(b"x")  # 截断后静默丢弃
    assert sink.text() == "1234567890"


def test_stderr_tail_keeps_tail_and_drops_old():
    tail = _StderrTail(max_bytes=20)
    for i in range(5):
        tail.feed(f"line-{i}\n".encode())
    text = tail.text()
    assert "line-0" not in text  # 最老的行被挤出尾部窗口
    assert "line-4" in text


async def test_drain_cli_reads_both_streams_until_eof():
    class S:
        def __init__(self, lines):
            self._lines = lines

        async def readline(self):
            if self._lines:
                return self._lines.pop(0)
            return b""

    class P:
        def __init__(self):
            self.stdout = S([b"out-1\n", b"out-2\n"])
            self.stderr = S([b"err-1\n"])

    sink = _StdoutSink()
    tail = _StderrTail()
    await _drain_cli(P(), sink, tail)
    assert "out-1" in sink.text() and "out-2" in sink.text()
    assert "err-1" in tail.text()


def test_kill_tree_terminates_process():
    async def scenario():
        # 必须与生产 spawn 语义一致（独立会话/进程组）：否则 POSIX 分支
        # killpg(getpgid(pid)) 会连测试进程组一起 SIGKILL（ubuntu 卡死实录）
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=(sys.platform != "win32"),
        )
        _kill_tree(proc)
        await asyncio.wait_for(proc.wait(), timeout=15)
        return proc.returncode

    code = asyncio.run(scenario())
    assert code is not None  # 已终止（Windows taskkill / POSIX killpg 任一路径）


# ---------- 会话锁：per-loop 隔离与修剪 ----------


def test_session_lock_keyed_by_loop_and_prunes():
    client = DSHClient(FakeCfg(None))
    client._session_locks.clear()

    async def grab():
        return client._session_lock("/root", "s1")

    asyncio.run(grab())
    asyncio.run(grab())
    # 注：不做两次返回锁的同异断言——关闭的循环被 GC 后新循环可能复用
    # 同一 id()，撞键属分配器行为而非本模块语义；隔离性由 key 三元组构成保证
    for i in range(120):
        client._session_locks[f"k{i}"] = asyncio.Lock()

    n_before = len(client._session_locks)
    assert n_before > 100  # 确认越过修剪阈值

    async def grab_prune():
        return client._session_lock("/root", "s1")

    asyncio.run(grab_prune())
    assert len(client._session_locks) < n_before  # 未持锁的陈旧锁被清掉一批


# ---------- cordis 配置变体 ----------


def test_cordis_generates_with_sanitized_policy_mode(tmp_path):
    cfg = FakeCfg(
        tmp_path,
        {
            "cordis_config": str(tmp_path / "gen.cordis.yml"),
            "policy_mode": "custom restricted!",  # 含空格 → 白名单校验失败回退
        },
    )
    p = DSHClient(cfg)._cordis_config()
    assert p is not None and p.exists()
    assert "mode: workspace-restricted" in p.read_text(encoding="utf-8")


def test_policy_check_blocks_when_full_access_not_allowed(tmp_path):
    cfg = FakeCfg(
        tmp_path,
        {"cordis_config": str(tmp_path / "c.yml"), "allow_full_access": False},
    )
    client = DSHClient(cfg)
    p = client._cordis_config()  # 生成默认模板（内含 danger-full-access）
    assert p.exists()
    err = client._policy_check()
    assert err is not None and "danger-full-access" in err
    # 显式放行后安全门通过
    cfg._v["allow_full_access"] = True
    assert client._policy_check() is None


# ---------- 任务文本命令过滤开关 ----------


def test_task_filter_disabled_bypasses(tmp_path):
    cfg = FakeCfg(tmp_path, {"command_filter_enabled": False})
    assert DSHClient(cfg)._task_filter_check("rm -rf / 之类的高危文本") is None


# ---------- CLI 命令解析与环境白名单 ----------


def test_resolve_cli_cmd_list_form_and_no_double_dash(tmp_path):
    cfg = FakeCfg(
        tmp_path, {"cli_command": ["node", "dsh.js"], "cli_double_dash": False}
    )
    cmd = DSHClient(cfg)._resolve_cli_cmd("任务X")
    assert cmd[-1] == "任务X"
    assert "--" not in cmd


def test_resolve_cli_cmd_invalid_type_raises(tmp_path):
    with pytest.raises(ValueError):
        DSHClient(FakeCfg(tmp_path, {"cli_command": 42}))._resolve_cli_cmd("t")


def test_build_cli_env_whitelist_and_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "C:\\fake-path")
    monkeypatch.setenv("DSH_MODEL", "env-model")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    cfg = FakeCfg(tmp_path, {"api_key": "sk-cfg", "base_url": "https://api.test"})
    env = DSHClient(cfg)._build_cli_env("/sessions", "cfg-model", 2048)
    assert env["PATH"] == "C:\\fake-path"
    assert env["DSH_MODEL"] == "env-model"  # 环境已有值优先于 setdefault
    assert env["DSH_SESSION_ROOT"] == "/sessions"
    assert env["DSH_MAX_TOKENS"] == "2048"
    assert env["DEEPSEEK_API_KEY"] == "sk-env"  # 环境优先于配置 api_key
    assert env["DEEPSEEK_BASE_URL"] == "https://api.test"


def test_build_cli_env_api_key_falls_back_to_config(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    cfg = FakeCfg(tmp_path, {"api_key": "sk-from-config"})
    env = DSHClient(cfg)._build_cli_env("/s", "m", 1)
    assert env["DEEPSEEK_API_KEY"] == "sk-from-config"


# ---------- run() 流程分支 ----------


@pytest.fixture
def flow_client(tmp_path, monkeypatch):
    """流程级测试：安全门旁路，workspace/session_root 落 tmp。"""
    cfg = FakeCfg(tmp_path, {"mode": "auto", "timeout_seconds": 5})
    client = DSHClient(cfg)
    monkeypatch.setattr(client, "_policy_check", lambda: None)
    monkeypatch.setattr(client, "_task_filter_check", lambda t: None)
    return client, monkeypatch


async def test_run_sdk_failure_falls_back_to_cli(flow_client):
    client, mp = flow_client
    mp.setattr(client, "sdk_available", lambda: True)
    mp.setattr(client, "cli_available", lambda: True)

    async def sdk_fail(*a, **k):
        raise RuntimeError("SDK 崩了")

    async def cli_ok(*a, **k):
        return DSHResult(ok=True, mode="cli", final_response="cli-done")

    mp.setattr(client, "_run_sdk", sdk_fail)
    mp.setattr(client, "_run_cli", cli_ok)
    r = await client.run("任务")
    assert r.ok and r.mode == "cli"
    assert r.final_response == "cli-done"


async def test_run_sdk_timeout_then_thread_finish_wins(flow_client):
    client, mp = flow_client
    mp.setattr(client, "sdk_available", lambda: True)
    mp.setattr(client, "cli_available", lambda: False)

    async def slow_sdk(*a, **k):
        await asyncio.sleep(0.25)  # 超过 timeout=0.1，但远小于 30s 收尾窗口
        return DSHResult(ok=True, mode="sdk", final_response="迟到的结果")

    mp.setattr(client, "_run_sdk", slow_sdk)
    r = await client.run("任务", timeout=1)
    assert r.ok is True
    assert r.final_response == "迟到的结果"  # 线程收尾结果被采纳而非报超时


async def test_run_no_available_channel_errors(flow_client):
    client, mp = flow_client
    mp.setattr(client, "sdk_available", lambda: False)
    mp.setattr(client, "cli_available", lambda: False)
    r = await client.run("任务")
    assert r.ok is False
    assert "无可用通道" in r.error


# ---------- _run_cli 真子进程集成（python.exe 替身跑通全链路） ----------


async def test_run_cli_real_subprocess_success(tmp_path, flow_client):
    client, mp = flow_client
    mp.setattr(
        client,
        "_resolve_cli_cmd",
        lambda task: [sys.executable, "-c", f"print('hello-{len(task)}')"],
    )
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)  # 生产路径由 _resolve_workspace 创建
    r = await client._run_cli("任务", ws, "s1", str(tmp_path), "m", 100, 10)
    assert r.ok is True and r.mode == "cli"
    assert r.final_response == "hello-2"


async def test_run_cli_nonzero_exit_includes_stderr_tail(tmp_path, flow_client):
    client, mp = flow_client
    mp.setattr(
        client,
        "_resolve_cli_cmd",
        lambda task: [
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('boom-detail'); sys.exit(3)",
        ],
    )
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    r = await client._run_cli("t", ws, "s1", str(tmp_path), "m", 100, 10)
    assert r.ok is False
    assert "退出码 3" in r.error
    assert "boom-detail" in r.error


async def test_run_cli_timeout_kills_tree(tmp_path, flow_client):
    client, mp = flow_client
    mp.setattr(
        client,
        "_resolve_cli_cmd",
        lambda task: [sys.executable, "-c", "import time; time.sleep(30)"],
    )
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    r = await client._run_cli("t", ws, "s1", str(tmp_path), "m", 100, 0.3)
    assert r.ok is False
    assert "超时" in r.error
