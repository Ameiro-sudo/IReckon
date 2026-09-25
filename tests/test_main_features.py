"""main.py 附加功能 + 主流程测试：_get_lan_ip、_check_update、initialize 前端分支、
_start_frontend 各启动路径、start_backend（正常/退出/异常/自动开浏览器）、
shutdown 清理与幂等；以及 main() 生命周期、优雅停机、SystemExit、KeyboardInterrupt、
run_cli、__main__ 守卫。"""

import asyncio
import re
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import main as main_mod  # noqa: E402 — 依赖 conftest 注入的 sys.path

from app.core.config import get

from conftest import LogRecorder
from helpers import (
    ProcStub,
    fake_server_factory,
    hang_forever,
    patch_main_externals,
    prepare_main_app,
)

ROOT = Path(__file__).parent.parent.resolve()


def _cfg(key, default=None):
    return get(key, default)


def _install_fake_uvicorn(monkeypatch, serve_impl):
    fake_uvicorn = fake_server_factory(serve_impl)
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    return fake_uvicorn.Server


def getsockname():
    return "192.168.1.5", 0


class TestMainFeatures:
    # ---------- _get_lan_ip ----------

    def test_get_lan_ip_real(self):
        ip = main_mod._get_lan_ip()
        assert ip is None or re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip)

    def test_get_lan_ip_success(self, monkeypatch):
        class Sock:
            def __init__(self, *a, **k):
                pass

            def settimeout(self, t):
                pass

            def connect(self, addr):
                pass

            def getsockname(self):
                return "192.168.1.5", 0

            def close(self):
                pass

        monkeypatch.setattr(main_mod.socket, "socket", Sock)
        assert main_mod._get_lan_ip() == "192.168.1.5"

    def test_get_lan_ip_network_error(self, monkeypatch):
        class Sock:
            def __init__(self, *a, **k):
                pass

            def settimeout(self, t):
                pass

            def connect(self, addr):
                raise OSError("network unreachable")

            def close(self):
                pass

        monkeypatch.setattr(main_mod.socket, "socket", lambda *a, **k: Sock())
        assert main_mod._get_lan_ip() is None

    # ---------- _check_update ----------

    async def test_check_update_skip_when_not_due(self, monkeypatch):
        rec = LogRecorder()
        monkeypatch.setattr(main_mod, "logger", rec)
        calls = []
        monkeypatch.setattr(main_mod.updater, "should_check", lambda: False)

        async def _check():
            calls.append("check")

        monkeypatch.setattr(main_mod.updater, "check", _check)
        monkeypatch.setattr(
            main_mod.updater, "mark_checked", lambda: calls.append("marked")
        )

        await main_mod._check_update()

        assert calls == []

    async def test_check_update_finds_version(self, monkeypatch):
        rec = LogRecorder()
        monkeypatch.setattr(main_mod, "logger", rec)
        calls = []
        monkeypatch.setattr(main_mod.updater, "should_check", lambda: True)

        async def _check():
            return "1.2.3"

        monkeypatch.setattr(main_mod.updater, "check", _check)
        monkeypatch.setattr(
            main_mod.updater, "mark_checked", lambda: calls.append("marked")
        )

        await main_mod._check_update()

        assert calls == ["marked"]
        assert rec.has("发现新版本", "v1.2.3")

    async def test_check_update_no_version(self, monkeypatch):
        rec = LogRecorder()
        monkeypatch.setattr(main_mod, "logger", rec)
        calls = []
        monkeypatch.setattr(main_mod.updater, "should_check", lambda: True)

        async def _check():
            return None

        monkeypatch.setattr(main_mod.updater, "check", _check)
        monkeypatch.setattr(
            main_mod.updater, "mark_checked", lambda: calls.append("marked")
        )

        await main_mod._check_update()

        assert calls == ["marked"]
        assert not rec.has("发现新版本")

    # ---------- initialize 前端分支 ----------

    async def test_initialize_default_no_dev_frontend(self, monkeypatch):
        monkeypatch.delenv("IRECKON_DEV_FRONTEND", raising=False)
        dist_dir = str(ROOT / "frontend" / "dist")
        _orig_isdir = main_mod.os.path.isdir
        monkeypatch.setattr(
            main_mod.os.path,
            "isdir",
            lambda p: True if p == dist_dir else _orig_isdir(p),
        )
        app, rec, fc = await prepare_main_app(monkeypatch)
        try:
            assert len(app._tasks) == 2  # idle_loop + log_consumer
            assert fc == []  # 有 frontend/dist 且非开发模式 → 不启动 dev server
            assert rec.has("系统初始化完成")
        finally:
            await app.shutdown()

    async def test_initialize_dev_mode_starts_frontend(self, monkeypatch):
        monkeypatch.setenv("IRECKON_DEV_FRONTEND", "1")
        app, rec, fc = await prepare_main_app(monkeypatch)
        try:
            assert len(fc) == 1
        finally:
            await app.shutdown()

    async def test_initialize_missing_dist_starts_frontend(self, monkeypatch):
        monkeypatch.delenv("IRECKON_DEV_FRONTEND", raising=False)
        dist_dir = str(ROOT / "frontend" / "dist")
        _orig_isdir = main_mod.os.path.isdir

        def _isdir(p):
            return False if p == dist_dir else _orig_isdir(p)

        monkeypatch.setattr(main_mod.os.path, "isdir", _isdir)
        app, rec, fc = await prepare_main_app(monkeypatch)
        try:
            assert len(fc) == 1
        finally:
            await app.shutdown()

    async def test_initialize_frozen_missing_dist_warns(self, monkeypatch):
        dist_dir = str(ROOT / "frontend" / "dist")
        _orig_isdir = main_mod.os.path.isdir

        def _isdir(p):
            return False if p == dist_dir else _orig_isdir(p)

        monkeypatch.setattr(main_mod.os.path, "isdir", _isdir)
        monkeypatch.setattr(main_mod.sys, "frozen", True, raising=False)
        app, rec, fc = await prepare_main_app(monkeypatch)
        try:
            assert fc == []
            assert rec.has("frontend/dist 不存在")
        finally:
            await app.shutdown()

    # ---------- _start_frontend ----------

    def test_start_frontend_no_npm_npx(self, monkeypatch):
        rec = LogRecorder()
        monkeypatch.setattr(main_mod, "logger", rec)
        monkeypatch.setattr(main_mod.shutil, "which", lambda name: None)

        app = main_mod.IReckonApp()
        app._start_frontend()

        assert app._frontend_proc is None
        assert rec.has("npm/npx 未安装")

    def test_start_frontend_install_failed(self, monkeypatch):
        rec = LogRecorder()
        monkeypatch.setattr(main_mod, "logger", rec)
        monkeypatch.setattr(
            main_mod.shutil,
            "which",
            lambda name: "C:/npm/npm.cmd" if name == "npm" else None,
        )
        monkeypatch.setattr(main_mod.os.path, "exists", lambda p: False)

        def _run(*_args, **_kwargs):
            raise subprocess.CalledProcessError(1, "npm install")

        monkeypatch.setattr(main_mod.subprocess, "run", _run)

        app = main_mod.IReckonApp()
        app._start_frontend()

        assert app._frontend_proc is None
        assert rec.has("前端依赖安装失败")

    def test_start_frontend_popen_success(self, monkeypatch):
        rec = LogRecorder()
        monkeypatch.setattr(main_mod, "logger", rec)
        monkeypatch.setattr(
            main_mod.shutil,
            "which",
            lambda name: {"npm": "C:/npm/npm.cmd", "npx": "C:/npm/npx.cmd"}.get(name),
        )
        monkeypatch.setattr(main_mod.os.path, "exists", lambda p: True)
        launched = []

        def _popen(cmd, **_kwargs):
            launched.append(cmd)
            return ProcStub()

        monkeypatch.setattr(main_mod.subprocess, "Popen", _popen)

        app = main_mod.IReckonApp()
        app._start_frontend()

        assert app._frontend_proc is not None
        assert launched == [["npm", "run", "dev"]]
        assert rec.has("前端已启动")

    def test_start_frontend_all_commands_fail(self, monkeypatch):
        rec = LogRecorder()
        monkeypatch.setattr(main_mod, "logger", rec)
        monkeypatch.setattr(
            main_mod.shutil,
            "which",
            lambda name: {"npm": "C:/npm/npm.cmd", "npx": "C:/npm/npx.cmd"}.get(name),
        )
        monkeypatch.setattr(main_mod.os.path, "exists", lambda p: True)

        def _popen(cmd, **_kwargs):
            raise FileNotFoundError(cmd[0])

        monkeypatch.setattr(main_mod.subprocess, "Popen", _popen)

        app = main_mod.IReckonApp()
        app._start_frontend()

        assert app._frontend_proc is None
        assert rec.has("前端启动失败")

    def test_start_frontend_vite_js_fallback(self, monkeypatch):
        rec = LogRecorder()
        monkeypatch.setattr(main_mod, "logger", rec)
        monkeypatch.setattr(
            main_mod.shutil,
            "which",
            lambda name: {"node": "C:/node/node.exe", "npm": "C:/npm/npm.cmd"}.get(
                name
            ),
        )
        bin_vite = str(ROOT / "frontend" / "node_modules" / ".bin" / "vite")

        def _exists(p):
            return str(p) != bin_vite

        monkeypatch.setattr(main_mod.os.path, "exists", _exists)
        launched = []

        def _popen(cmd, **_kwargs):
            launched.append(cmd)
            return ProcStub()

        monkeypatch.setattr(main_mod.subprocess, "Popen", _popen)

        app = main_mod.IReckonApp()
        app._start_frontend()

        assert app._frontend_proc is not None
        assert launched[0][0] == "node"
        assert "--port" in launched[0] and "3000" in launched[0]

    # ---------- start_backend ----------

    async def _serve_ok(self, _server):
        pass

    async def test_start_backend_normal(self, monkeypatch):
        rec = LogRecorder()
        monkeypatch.setattr(main_mod, "logger", rec)
        monkeypatch.setattr(
            main_mod,
            "log_banner",
            lambda title, lines, level="INFO": rec.info(f"{title} | {lines}"),
        )
        FakeServer = _install_fake_uvicorn(monkeypatch, self._serve_ok)

        app = main_mod.IReckonApp()
        await main_mod.start_backend(app)

        assert app._server is not None
        assert app._shutdown_event.is_set()
        assert len(FakeServer.served) == 1
        config = FakeServer.served[0]
        assert config.app == "app.web.api:app"
        assert config.host == _cfg("server.host", "0.0.0.0")
        assert config.port == _cfg("server.port", 8000)
        assert config.kwargs["access_log"] is False
        assert rec.has("已启动")

    async def test_start_backend_system_exit(self, monkeypatch):
        rec = LogRecorder()
        monkeypatch.setattr(main_mod, "logger", rec)

        async def _exit(_server):
            raise SystemExit(3)

        _install_fake_uvicorn(monkeypatch, _exit)

        app = main_mod.IReckonApp()
        await main_mod.start_backend(app)

        assert app._shutdown_event.is_set()
        assert rec.has("uvicorn exited with code 3")

    async def test_start_backend_exception(self, monkeypatch):
        rec = LogRecorder()
        monkeypatch.setattr(main_mod, "logger", rec)

        async def _boom(_server):
            raise RuntimeError("port in use")

        _install_fake_uvicorn(monkeypatch, _boom)

        app = main_mod.IReckonApp()
        await main_mod.start_backend(app)

        assert app._shutdown_event.is_set()
        assert rec.has("启动后端服务时发生异常")

    async def test_start_backend_open_browser(self, monkeypatch):
        rec = LogRecorder()
        monkeypatch.setattr(main_mod, "logger", rec)
        _install_fake_uvicorn(monkeypatch, self._serve_ok)
        orig_get = main_mod.config_manager.get

        def _get(key, default=None):
            if key == "server.open_browser":
                return True
            return orig_get(key, default)

        monkeypatch.setattr(main_mod.config_manager, "get", _get)
        opened = []
        monkeypatch.setattr(main_mod.webbrowser, "open", lambda url: opened.append(url))

        app = main_mod.IReckonApp()
        await main_mod.start_backend(app)

        assert len(opened) == 1
        assert str(_cfg("server.port", 8000)) in opened[0]

    # ---------- shutdown ----------

    async def test_shutdown_cleanup_and_idempotent(self, monkeypatch):
        rec = LogRecorder()
        monkeypatch.setattr(main_mod, "logger", rec)
        closed = []

        async def _close():
            closed.append(1)

        monkeypatch.setattr(main_mod.db, "close", _close)

        app = main_mod.IReckonApp()
        app._tasks.append(asyncio.create_task(hang_forever()))
        app._tasks.append(asyncio.create_task(hang_forever()))
        proc = ProcStub()
        app._frontend_proc = proc

        await app.shutdown()

        assert app._shutdown_event.is_set()
        assert closed == [1]
        assert all(t.cancelled() for t in app._tasks)
        assert proc.terminated == 1 and proc.killed == 1
        assert rec.has("系统已关闭")

        await app.shutdown()  # 幂等：重复调用不重复清理
        assert proc.terminated == 1
        assert closed == [1]


class TestMainFlow:
    def test_main_end_to_end(self, monkeypatch):
        """整个主流程：initialize → 启动后端 → 等待关闭事件 → 优雅 shutdown。"""
        rec = LogRecorder()
        patch_main_externals(monkeypatch, rec)
        frontend_calls = []
        monkeypatch.setattr(
            main_mod.IReckonApp,
            "_start_frontend",
            lambda self: frontend_calls.append(self),
        )
        dist_dir = str(ROOT / "frontend" / "dist")
        _orig_isdir = main_mod.os.path.isdir
        monkeypatch.setattr(
            main_mod.os.path,
            "isdir",
            lambda p: True if p == dist_dir else _orig_isdir(p),
        )
        backend_apps = []

        async def _fake_start_backend(app):
            backend_apps.append(app)
            app.shutdown_event.set()

        monkeypatch.setattr(main_mod, "start_backend", _fake_start_backend)

        asyncio.run(main_mod.main())

        assert len(backend_apps) == 1
        assert (
            frontend_calls == []
        )  # 存在 frontend/dist 且非开发模式时不启动 dev server
        assert rec.has("系统初始化完成")
        assert rec.has("系统已关闭")

    def test_main_graceful_shutdown(self, monkeypatch):
        """后端未及时退出时走 should_exit → 超时 → 强杀路径。"""
        rec = LogRecorder()
        patch_main_externals(monkeypatch, rec)

        async def _fake_start_backend(app):
            app._server = SimpleNamespace(should_exit=False)
            app.shutdown_event.set()
            await asyncio.Event().wait()

        async def _timeout(*_args, **_kwargs):
            raise asyncio.TimeoutError()

        monkeypatch.setattr(main_mod, "start_backend", _fake_start_backend)
        monkeypatch.setattr(main_mod.asyncio, "wait_for", _timeout)

        asyncio.run(main_mod.main())

        assert rec.has("10 秒内未退出")
        assert rec.has("系统已关闭")

    def test_main_backend_system_exit(self, monkeypatch):
        """后端以 SystemExit 退出时被捕获并继续优雅关闭。"""
        rec = LogRecorder()
        patch_main_externals(monkeypatch, rec)

        async def _fake_start_backend(app):
            app._server = SimpleNamespace(should_exit=False)
            app.shutdown_event.set()
            raise SystemExit(1)

        monkeypatch.setattr(main_mod, "start_backend", _fake_start_backend)

        try:
            asyncio.run(main_mod.main())
        except SystemExit:
            # Python 3.13 的 asyncio 会把任务内抛出的 SystemExit 在 run 收尾时
            # 再次抛出（即使 main() 已正常捕获处理），此处仅为兼容运行时行为。
            pass

        assert rec.has("SystemExit")
        assert rec.has("系统已关闭")

    def test_main_keyboard_interrupt(self, monkeypatch):
        """等待关闭信号时收到 Ctrl+C → 记录退出日志并清理。"""
        rec = LogRecorder()
        patch_main_externals(monkeypatch, rec)

        async def _fake_start_backend(app):
            app._server = SimpleNamespace(should_exit=False)

        class KIBoomEvent:
            def __init__(self):
                self._set = False

            async def wait(self):
                raise KeyboardInterrupt()

            def is_set(self):
                return self._set

            def set(self):
                self._set = True

        async def _timeout(*_args, **_kwargs):
            raise asyncio.TimeoutError()

        # main() 等待的是 app._shutdown_event（实例属性），shutdown_event 属性
        # 仅在其上取值——因此必须替换 __init__ 创建的真实 Event
        def _init_no_event(self):
            self._shutdown_event = KIBoomEvent()
            self._tasks = []
            self._frontend_proc = None
            self._shutdown_started = False
            self._server = None

        monkeypatch.setattr(main_mod, "start_backend", _fake_start_backend)
        monkeypatch.setattr(main_mod.IReckonApp, "__init__", _init_no_event)
        monkeypatch.setattr(main_mod.asyncio, "wait_for", _timeout)

        asyncio.run(main_mod.main())

        assert rec.has("收到退出信号")

    def test_run_cli(self, monkeypatch):
        """run_cli 通过 asyncio.run 启动 main()。"""
        got = []

        def _fake_run(coro):
            got.append(coro)

        monkeypatch.setattr(main_mod.asyncio, "run", _fake_run)

        main_mod.run_cli()

        assert len(got) == 1
        assert asyncio.iscoroutine(got[0])
        got[0].close()

    def test_run_cli_keyboard_interrupt(self, monkeypatch):
        """run_cli 捕获 KeyboardInterrupt，不向上抛出。"""

        def _fake_run(coro):
            coro.close()
            raise KeyboardInterrupt()

        monkeypatch.setattr(main_mod.asyncio, "run", _fake_run)

        main_mod.run_cli()  # 不应抛异常

    def test_main_guard_runs_cli(self, monkeypatch):
        """以 `python main.py` 方式执行时（__name__ == '__main__'）触发 run_cli。"""
        got = []

        def _fake_run(coro):
            got.append(coro)
            coro.close()

        monkeypatch.setattr(main_mod.asyncio, "run", _fake_run)

        runpy.run_path(str(ROOT / "main.py"), run_name="__main__")

        assert len(got) == 1
        assert asyncio.iscoroutine(got[0])
