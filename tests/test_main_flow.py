"""main.py 主流程测试：main() 生命周期、优雅停机、SystemExit、KeyboardInterrupt、
run_cli、__main__ 守卫。"""

import asyncio
import runpy
from pathlib import Path
from types import SimpleNamespace


import main as main_mod  # noqa: E402 — 依赖 conftest 注入的 sys.path

from conftest import LogRecorder
from helpers import patch_main_externals

ROOT = Path(__file__).parent.parent.resolve()


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
