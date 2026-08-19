"""main.py 入口测试的公共助手：外部依赖打桩与流程构造。"""

import asyncio
from types import SimpleNamespace

import main as main_mod


async def hang_forever():
    await asyncio.Event().wait()


class ProcStub:
    """terminate/kill 计数的子进程替身（terminate 不退出、kill 生效）。"""

    def __init__(self):
        self.terminated = 0
        self.killed = 0

    def terminate(self):
        self.terminated += 1

    def wait(self, timeout=None):
        raise RuntimeError("never exits")

    def kill(self):
        self.killed += 1


async def _noop(*_args, **_kwargs):
    pass


def patch_main_externals(monkeypatch, rec):
    """打桩 main() 依赖的外部组件：db/能力池/更新检查/后台任务等。"""
    monkeypatch.setattr(main_mod, "logger", rec)
    monkeypatch.setattr(main_mod, "_check_update", _noop)
    monkeypatch.setattr(main_mod.db, "connect", _noop)
    monkeypatch.setattr(main_mod.db, "close", _noop)
    monkeypatch.setattr(main_mod.capability_pool, "refresh", _noop)
    monkeypatch.setattr(main_mod, "register_builtin_tools", _noop)
    monkeypatch.setattr(main_mod.idle_loop, "run", hang_forever)
    monkeypatch.setattr(main_mod, "log_consumer", hang_forever)


async def prepare_main_app(monkeypatch, rec=None, frontend_calls=None):
    """打桩后初始化 IReckonApp，返回 (app, rec, frontend_calls)。"""
    from conftest import LogRecorder

    rec = rec if rec is not None else LogRecorder()
    frontend_calls = frontend_calls if frontend_calls is not None else []

    def _record_frontend(self):
        frontend_calls.append(self)

    patch_main_externals(monkeypatch, rec)
    monkeypatch.setattr(main_mod.IReckonApp, "_start_frontend", _record_frontend)
    app = main_mod.IReckonApp()
    await app.initialize()
    return app, rec, frontend_calls


def fake_server_factory(serve_impl):
    """构造 uvicorn 替身（Config/Server），serve 时调用 serve_impl(server)。"""

    class FakeServer:
        served = []

        def __init__(self, config):
            self.config = config
            self.should_exit = False

        async def serve(self):
            FakeServer.served.append(self.config)
            await serve_impl(self)

    class FakeConfig:
        def __init__(self, app_path, host=None, port=None, **kwargs):
            self.app = app_path
            self.host = host
            self.port = port
            self.kwargs = kwargs

    return SimpleNamespace(Config=FakeConfig, Server=FakeServer)
