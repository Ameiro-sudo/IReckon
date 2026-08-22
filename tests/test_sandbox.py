"""沙箱与扫描器沙箱路径测试。

覆盖：enabled 总闸（默认关闭零副作用）、env 白名单、引擎参数组装差异
（docker 全量 / udocker 仅受支持参数）、超时杀树、扫描器容器内优先+失败回退。
"""

import asyncio
import importlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import app.security.scanner as scanner_mod
from app.security.sandbox import Sandbox, filter_env

# ⚠️ app/security/__init__.py 里 `from .sandbox import sandbox` 会把单例实例名
# 遮盖在包子空间上——`import app.security.sandbox as m` 拿到的是实例而非模块。
# 这里必须经 sys.modules 取真正的模块对象才能 monkeypatch 模块级成员。
sandbox_mod = importlib.import_module("app.security.sandbox")


def _sb(**overrides) -> Sandbox:
    """构造测试沙箱实例（绕开本机真实 config 的不确定性）。"""
    sb = Sandbox()
    sb.enabled = True
    sb.engine = "docker"
    sb.image = "test-image"
    sb.network = "none"
    sb.memory_limit = "256m"
    sb.cpu_limit = 0.5
    sb.env_whitelist = ["ALLOWED_VAR"]
    for k, v in overrides.items():
        setattr(sb, k, v)
    return sb


# ---------- env 白名单 ----------


def test_filter_env_keeps_only_whitelisted():
    env = {"ALLOWED_VAR": "1", "SECRET_TOKEN": "x", "PATH": "/bin"}
    assert filter_env(env, ["ALLOWED_VAR"]) == {"ALLOWED_VAR": "1"}


def test_filter_env_empty_whitelist_drops_all():
    assert filter_env({"A": "1", "B": "2"}, []) == {}
    assert filter_env(None, None) == {}


# ---------- 容器参数组装 ----------


def test_container_args_docker_full_hardening():
    sb = _sb()
    args = sb._container_args(
        mounts={"/scan": ("/tmp/work", "ro")},
        env={"ALLOWED_VAR": "v", "SECRET": "s"},
    )
    assert "--network=none" in args
    assert "--memory=256m" in args
    assert "--cpus=0.5" in args
    assert "--user=65534" in args
    assert "--volume=/tmp/work:/scan:ro" in args
    assert "--env=ALLOWED_VAR=v" in args
    # 白名单外的变量绝不出现在容器参数里
    assert not any("SECRET" in a for a in args)
    assert "--rm" in args


def test_container_args_docker_network_opt_out():
    sb = _sb(network="")
    args = sb._container_args()
    assert not any(a.startswith("--network") for a in args)


def test_container_args_udocker_omits_unsupported_flags():
    # udocker 无 cgroup/netns：资源与网络参数必须缺席（原实现潜伏必失败缺陷）
    sb = _sb(engine="udocker")
    args = sb._container_args(mounts={"/w": ("C:\\host", None)}, env={})
    assert not any(a.startswith("--network") for a in args)
    assert not any(a.startswith("--memory") for a in args)
    assert not any(a.startswith("--cpus") for a in args)
    assert "--user=65534" in args
    assert "--volume=C:\\host:/w" in args
    assert "--rm" in args


# ---------- run() 门禁与执行 ----------


class _FakeProc:
    def __init__(self, stdout=b"", stderr=b"", returncode=0, hang=False):
        self.pid = 4242
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._hang = hang
        self.killed = False
        self.waited = False

    async def communicate(self):
        if self._hang:
            await asyncio.sleep(50)
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True

    async def wait(self):
        self.waited = True


async def test_disabled_rejects_without_touching_runtime(monkeypatch):
    async def _boom(*a, **kw):
        raise AssertionError("未启用时不得启动任何子进程")

    monkeypatch.setattr(sandbox_mod.asyncio, "create_subprocess_exec", _boom)
    sb = _sb(enabled=False)
    res = await sb.run("echo hi")
    assert res == {"stdout": "", "stderr": "sandbox disabled", "returncode": -1}


async def test_engine_unavailable_degrades(monkeypatch):
    def fake_check(engine):
        return False

    monkeypatch.setattr(sandbox_mod, "_check_engine", fake_check)
    res = await _sb().run("echo hi")
    assert res["returncode"] == -1
    assert res["stderr"] == "sandbox unavailable"


async def test_image_missing_degrades(monkeypatch):
    def fake_check(engine):
        return True

    def fake_ensure():
        return False

    monkeypatch.setattr(sandbox_mod, "_check_engine", fake_check)
    sb = _sb()
    sb._ensure_image = fake_ensure
    res = await sb.run("echo hi")
    assert res["returncode"] == -1
    assert res["stderr"] == "sandbox image unavailable"


async def test_run_success_passthrough_and_argv_shape(monkeypatch):
    captured = {}

    async def fake_comm():
        return b'{"ok": true}', b"warning line"

    proc = _FakeProc()
    proc.communicate = fake_comm

    async def fake_exec(*argv, **kwargs):
        captured["argv"] = list(argv)
        return proc

    def fake_check(engine):
        return True

    def fake_ensure():
        return True

    monkeypatch.setattr(sandbox_mod.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(sandbox_mod, "_check_engine", fake_check)
    sb = _sb()
    sb._ensure_image = fake_ensure
    res = await sb.run("bandit -f json /scan/x.py", mounts={"/scan": ("/h", "ro")})
    assert res == {
        "stdout": '{"ok": true}',
        "stderr": "warning line",
        "returncode": 0,
    }
    argv = captured["argv"]
    assert argv[0] == "docker"
    assert "test-image" in argv and "bash" in argv and "-c" in argv
    assert argv[-1] == "bandit -f json /scan/x.py"
    assert "--volume=/h:/scan:ro" in argv


async def test_timeout_kills_process_tree(monkeypatch):
    killed = {"children": []}

    def fake_process(pid):
        children = []
        for cpid in (11, 22):
            child = SimpleNamespace(pid=cpid)
            child.kill = lambda c=child: killed["children"].append(c.pid)
            children.append(child)
        return SimpleNamespace(children=lambda recursive=True: children)

    monkeypatch.setattr(sandbox_mod.psutil, "Process", fake_process)
    proc = _FakeProc(hang=True)

    async def fake_exec(*argv, **kwargs):
        return proc

    def fake_check(engine):
        return True

    def fake_ensure():
        return True

    monkeypatch.setattr(sandbox_mod.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(sandbox_mod, "_check_engine", fake_check)
    sb = _sb()
    sb._ensure_image = fake_ensure
    res = await asyncio.wait_for(sb.run("sleep 999", timeout=1), timeout=8)
    assert res == {"stdout": "", "stderr": "timeout", "returncode": -1}
    # 先杀子进程树再杀主进程
    assert sorted(killed["children"]) == [11, 22]
    assert proc.killed is True
    assert proc.waited is True


async def test_exec_spawn_failure_returns_negative(monkeypatch):
    async def boom(*a, **kw):
        raise OSError("spawn failed")

    def fake_check(engine):
        return True

    def fake_ensure():
        return True

    monkeypatch.setattr(sandbox_mod.asyncio, "create_subprocess_exec", boom)
    monkeypatch.setattr(sandbox_mod, "_check_engine", fake_check)
    sb = _sb()
    sb._ensure_image = fake_ensure
    res = await sb.run("echo hi")
    assert res["returncode"] == -1
    assert "spawn failed" in res["stderr"]


# ---------- 扫描器接线：容器内优先 + 失败回退宿主机 ----------


def _force_sandbox_flag(monkeypatch, value):
    real_get = scanner_mod.get

    def fake_get(key, default=None):
        if key == "security.sandbox.enabled":
            return value
        return real_get(key, default)

    monkeypatch.setattr(scanner_mod, "get", fake_get)


class _StubSandbox:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def run(self, command, timeout=30, mounts=None, env=None):
        self.calls.append({"command": command, "mounts": mounts})
        return self.result


async def test_scanner_uses_sandbox_when_enabled(monkeypatch):
    _force_sandbox_flag(monkeypatch, True)
    stub = _StubSandbox(
        {
            "stdout": '{"results": [{"issue_severity": "HIGH"}]}',
            "stderr": "",
            "returncode": 0,
        }
    )
    monkeypatch.setattr(scanner_mod, "sandbox", stub)

    async def _boom(*a, **kw):
        raise AssertionError("沙箱成功时不得回退宿主机执行")

    monkeypatch.setattr(scanner_mod.asyncio, "create_subprocess_exec", _boom)
    s = scanner_mod.CodeScanner(tool="bandit")
    s._available = True
    findings = await s.scan("assert True")
    assert len(findings) == 1
    assert findings[0]["issue_severity"] == "HIGH"
    assert len(stub.calls) == 1
    # 目标目录以只读方式挂载到固定容器路径
    mounts = stub.calls[0]["mounts"]
    assert list(mounts.values())[0][1] == "ro"
    assert stub.calls[0]["command"].startswith("bandit -f json /scan/")


async def test_scanner_bandit_rc1_still_parses_in_sandbox(monkeypatch):
    _force_sandbox_flag(monkeypatch, True)
    stub = _StubSandbox(
        {
            "stdout": '{"results": [{"issue_text": "B101"}]}',
            "stderr": "",
            "returncode": 1,
        }
    )
    monkeypatch.setattr(scanner_mod, "sandbox", stub)
    s = scanner_mod.CodeScanner(tool="bandit")
    s._available = True
    findings = await s.scan("assert True")
    assert findings and findings[0]["issue_text"].startswith("B101")


async def test_scanner_sandbox_failure_falls_back_to_host(monkeypatch):
    _force_sandbox_flag(monkeypatch, True)
    stub = _StubSandbox({"stdout": "", "stderr": "engine broke", "returncode": 125})
    monkeypatch.setattr(scanner_mod, "sandbox", stub)

    called = []

    async def fake_exec(*args, **kwargs):
        called.append(args)
        return _FakeProc(stdout=b'{"results": [{"host": true}]}')

    monkeypatch.setattr(scanner_mod.asyncio, "create_subprocess_exec", fake_exec)
    s = scanner_mod.CodeScanner(tool="bandit")
    s._available = True
    findings = await s.scan("print(1)")
    assert findings == [{"host": True}]
    assert len(called) == 1


async def test_scanner_sandbox_bad_json_falls_back_to_host(monkeypatch):
    _force_sandbox_flag(monkeypatch, True)
    stub = _StubSandbox({"stdout": "not-json", "stderr": "", "returncode": 0})
    monkeypatch.setattr(scanner_mod, "sandbox", stub)

    async def fake_exec(*args, **kwargs):
        return _FakeProc(stdout=b'{"results": []}')

    monkeypatch.setattr(scanner_mod.asyncio, "create_subprocess_exec", fake_exec)
    s = scanner_mod.CodeScanner(tool="semgrep")
    s._available = True
    assert await s.scan("x = 1") == []


async def test_scanner_host_path_when_sandbox_disabled(monkeypatch):
    _force_sandbox_flag(monkeypatch, False)
    stub = _StubSandbox(None)

    async def _boom_run(*a, **kw):
        raise AssertionError("总闸关闭时不得触碰沙箱")

    stub.run = _boom_run
    monkeypatch.setattr(scanner_mod, "sandbox", stub)

    async def fake_exec(*args, **kwargs):
        return _FakeProc(stdout=b'{"results": [{"via": "host"}]}')

    monkeypatch.setattr(scanner_mod.asyncio, "create_subprocess_exec", fake_exec)
    s = scanner_mod.CodeScanner(tool="bandit")
    s._available = True
    findings = await s.scan("print(2)")
    assert findings == [{"via": "host"}]


# ---------- 深水区补测：引擎探测 / 镜像保障 / 杀树 / run 全路径 ----------


def test_check_engine_ok(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = list(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(sandbox_mod.subprocess, "run", fake_run)
    assert sandbox_mod._check_engine("docker") is True
    assert seen["cmd"] == ["docker", "--version"]


def test_check_engine_failure_modes(monkeypatch):
    cases = [
        subprocess.CalledProcessError(1, "docker"),
        FileNotFoundError(),
        subprocess.TimeoutExpired("docker", 15),
    ]
    for exc in cases:
        monkeypatch.setattr(
            sandbox_mod.subprocess,
            "run",
            lambda *a, **kw: (_ for _ in ()).throw(exc),
        )
        assert sandbox_mod._check_engine("docker") is False


def _install_run_sequence(monkeypatch, results):
    """按顺序吐 subprocess.run 结果/异常的桩。"""
    seq = list(results)

    def fake_run(*a, **kw):
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(sandbox_mod.subprocess, "run", fake_run)


def test_ensure_image_present_skips_pull(monkeypatch):
    sb = _sb()
    calls = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(sandbox_mod.subprocess, "run", fake_run)
    assert sb._ensure_image() is True
    assert calls == [["docker", "inspect", "test-image"]]  # 镜像在位不拉取


def test_ensure_image_pull_success(monkeypatch):
    sb = _sb()
    _install_run_sequence(
        monkeypatch,
        [SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)],
    )
    assert sb._ensure_image() is True


def test_ensure_image_pull_failure(monkeypatch):
    sb = _sb()
    fail = SimpleNamespace(returncode=1, stderr=b"no such image: x")
    _install_run_sequence(monkeypatch, [fail, fail])
    assert sb._ensure_image() is False


def test_ensure_image_pull_timeout_and_missing_binary(monkeypatch):
    sb = _sb()
    _install_run_sequence(
        monkeypatch,
        [
            subprocess.TimeoutExpired("inspect", 10),
            subprocess.TimeoutExpired("pull", 300),
        ],
    )
    assert sb._ensure_image() is False
    _install_run_sequence(
        monkeypatch,
        [FileNotFoundError(), FileNotFoundError()],
    )
    assert sb._ensure_image() is False


async def test_kill_tree_kills_children_then_main(monkeypatch):
    killed = []

    class FakeChild:
        def kill(self):
            killed.append("child")

    class FakePsutilProc:
        def __init__(self, pid):
            pass

        def children(self, recursive=True):
            return [FakeChild()]

    monkeypatch.setattr(sandbox_mod.psutil, "Process", FakePsutilProc)
    proc = _FakeProc()
    await _sb()._kill_tree(proc)
    assert killed == ["child"]
    assert proc.killed and proc.waited


async def test_kill_tree_swallows_every_error(monkeypatch):
    class ExplodingProc:
        def __init__(self, pid):
            raise RuntimeError("process gone")

    monkeypatch.setattr(sandbox_mod.psutil, "Process", ExplodingProc)
    proc = _FakeProc()

    def boom_kill():
        raise RuntimeError("already dead")

    async def boom_wait():
        raise RuntimeError("cannot wait")

    proc.kill = boom_kill
    proc.wait = boom_wait
    await _sb()._kill_tree(proc)  # 三段异常全部吞掉，不向上抛


async def test_run_engine_unavailable_short_circuits():
    sb = _sb(enabled=True)
    sb._available = False
    r = await sb.run("echo hi")
    assert r["stderr"] == "sandbox unavailable" and r["returncode"] == -1


async def test_run_image_unavailable_short_circuits(monkeypatch):
    sb = _sb(enabled=True)
    sb._available = True
    sb._image_ready = None

    def no_image():
        return False

    monkeypatch.setattr(sb, "_ensure_image", no_image)
    r = await sb.run("x")
    assert r["stderr"] == "sandbox image unavailable" and r["returncode"] == -1


async def test_run_success_assembles_args_and_filters_env(monkeypatch):
    sb = _sb(enabled=True)
    sb._available = True
    sb._image_ready = True
    captured = {}

    async def fake_exec(*cmd, **kw):
        captured["cmd"] = list(cmd)
        return _FakeProc(stdout=b'{"ok": 1}', stderr=b"warn line")

    monkeypatch.setattr(sandbox_mod.asyncio, "create_subprocess_exec", fake_exec)
    r = await sb.run(
        'echo {"ok": 1}',
        mounts={"/work": ("/host/work", "ro")},
        env={"ALLOWED_VAR": "v", "SECRET": "s"},
    )
    assert r["returncode"] == 0 and '{"ok": 1}' in r["stdout"]
    cmd = captured["cmd"]
    assert cmd[0] == "docker"
    assert "--network=none" in cmd and "--memory=256m" in cmd and "--cpus=0.5" in cmd
    assert "--user=65534" in cmd
    assert "--volume=/host/work:/work:ro" in cmd
    assert "--env=ALLOWED_VAR=v" in cmd
    assert not any(c.startswith("--env=SECRET") for c in cmd)  # 白名单外被滤
    assert cmd[-3:] == ["bash", "-c", 'echo {"ok": 1}']


async def test_run_timeout_kills_tree(monkeypatch):
    sb = _sb(enabled=True)
    sb._available = True
    sb._image_ready = True
    proc = _FakeProc(hang=True)  # communicate 挂起 → 触发 run 内部超时

    class ExplodingProc:
        def __init__(self, pid):
            raise RuntimeError("gone")

    monkeypatch.setattr(sandbox_mod.psutil, "Process", ExplodingProc)

    async def fake_exec(*a, **kw):
        return proc

    monkeypatch.setattr(sandbox_mod.asyncio, "create_subprocess_exec", fake_exec)
    r = await asyncio.wait_for(sb.run("long task", timeout=1), timeout=5)
    assert r == {"stdout": "", "stderr": "timeout", "returncode": -1}
    assert proc.killed  # 超时杀树兜底执行


async def test_run_generic_exception_returns_error(monkeypatch):
    sb = _sb(enabled=True)
    sb._available = True
    sb._image_ready = True

    async def fake_exec(*a, **kw):
        raise RuntimeError("spawn failed")

    monkeypatch.setattr(sandbox_mod.asyncio, "create_subprocess_exec", fake_exec)
    r = await sb.run("anything")
    assert r["returncode"] == -1 and "spawn failed" in r["stderr"]
