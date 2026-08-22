"""StateManager 快照与 RoleRegistry 角色注册测试(补覆盖率盲区)。"""

import asyncio
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest

import app.agents  # noqa: F401  # 触发装饰器注册全部内置角色
from app.core.state import StateManager
from app.engine.registry import RoleRegistry, role_registry


# ---------- StateManager ----------


def _sm(tid="task-snap01"):
    return StateManager(tid)


class _Room:
    room_id = "room-xyz"


class _Color(Enum):
    RED = "red"


async def test_snapshot_roundtrip(session_db):
    sm = _sm()
    await sm.save_snapshot({"task_id": sm.task_id, "progress": 0.5})
    state = await sm.load_latest_snapshot()
    assert state is not None
    assert state["task_id"] == sm.task_id and state["progress"] == 0.5
    assert state["_meta"]["task_id"] == sm.task_id


async def test_snapshot_room_replaced_by_room_id(session_db):
    sm = _sm()
    await sm.save_snapshot({"room": _Room()})
    state = await sm.load_latest_snapshot()
    assert state["room_id"] == "room-xyz"
    assert "room" not in state


async def test_snapshot_serializes_enum_datetime_path(session_db):
    sm = _sm()
    await sm.save_snapshot(
        {
            "status": TaskStatusLike.EXECUTING,
            "when": datetime(2026, 8, 21, 12, 0, 0),
            "where": Path("a/b"),
        }
    )
    state = await sm.load_latest_snapshot()
    assert state["status"] == "executing"
    assert state["when"] == "2026-08-21T12:00:00"
    assert state["where"] == str(Path("a/b"))


class TaskStatusLike(Enum):
    EXECUTING = "executing"


async def test_snapshot_unserializable_falls_back_to_error_doc(session_db):
    class Weird:
        __slots__ = ()  # 无 __dict__，无 to_dict

    sm = _sm()
    await sm.save_snapshot({"bad": Weird()})
    state = await sm.load_latest_snapshot()
    assert state is not None and state.get("error") == "State serialization failed"


async def test_max_snapshots_trims_oldest(session_db):
    sm = _sm("task-trim01")
    sm.max_snapshots = 3
    for i in range(5):
        await sm.save_snapshot({"i": i})
        await asyncio.sleep(0.002)  # 保证时间戳文件名递增
    files = sorted(sm.states_dir.glob("snapshot_*.json"))
    assert len(files) == 3
    latest = await sm.load_latest_snapshot()
    assert latest["i"] == 4  # 保留的是最新


async def test_load_latest_empty_dir_returns_none():
    sm = _sm("task-empty01")
    assert await sm.load_latest_snapshot() is None


async def test_load_latest_corrupted_returns_none(session_db):
    sm = _sm("task-bad01")
    sm.states_dir.mkdir(parents=True, exist_ok=True)
    (sm.states_dir / "snapshot_99999999_000000_000.json").write_text(
        "{broken", encoding="utf-8"
    )
    assert await sm.load_latest_snapshot() is None


async def test_cleanup_keeps_only_latest(session_db):
    sm = _sm("task-clean01")
    for i in range(3):
        await sm.save_snapshot({"i": i})
        await asyncio.sleep(0.002)
    await sm.cleanup()
    files = list(sm.states_dir.glob("snapshot_*.json"))
    assert len(files) == 1
    assert (await sm.load_latest_snapshot())["i"] == 2


# ---------- RoleRegistry ----------


def test_register_rejects_non_baseagent_subclass():
    class NotAgent:
        pass

    with pytest.raises(TypeError):
        role_registry.register("bad_role", NotAgent)  # type: ignore[arg-type]


def test_register_unregister_roundtrip():
    from app.agents.base import BaseAgent

    class TempAgent(BaseAgent):
        __role_name__ = "temp_role"

    reg = RoleRegistry()
    reg.register("temp_x", TempAgent, {"description": "临时"})
    assert "temp_x" in reg.list_roles()
    assert reg.get_agent_class("temp_x") is TempAgent
    meta = reg.get_metadata("temp_x")
    meta["injected"] = True  # 返回的是副本，不应影响内部状态
    assert "injected" not in reg.get_metadata("temp_x")
    reg.unregister("temp_x")
    assert "temp_x" not in reg.list_roles()


def test_create_unknown_role_returns_none():
    assert role_registry.create_agent("不存在角色_xyz", None) is None


def test_singleton_identity():
    # __new__ 单例：任何实例化都返回同一对象（模块级 role_registry 即首个实例）
    assert RoleRegistry() is role_registry
    assert RoleRegistry() is RoleRegistry()


def test_unregister_unknown_role_is_noop():
    reg = RoleRegistry()
    reg.unregister("从未注册过的角色_xyz")  # 不抛错即通过


def test_create_agent_success_and_exception_paths():
    from app.agents.base import BaseAgent

    class OkAgent(BaseAgent):
        def __init__(self, capability, **kwargs):
            super().__init__(role="ok", capability=capability, system_prompt="s")
            self.extra = kwargs

        async def execute(self, *args, **kwargs):  # 实现抽象方法方可实例化
            return "ok"

    class BoomAgent(BaseAgent):
        def __init__(self, capability):
            raise RuntimeError("构造即炸")

    reg = RoleRegistry()
    reg.register("ok_role", OkAgent)
    reg.register("boom_role", BoomAgent)
    try:
        cap = object()
        agent = reg.create_agent("ok_role", cap, key="v")
        assert isinstance(agent, OkAgent)
        assert agent.capability is cap
        assert agent.extra == {"key": "v"}
        # 构造抛异常 → 记日志返回 None，不向上传播
        assert reg.create_agent("boom_role", None) is None
    finally:
        reg.unregister("ok_role")
        reg.unregister("boom_role")


def test_discover_missing_directory_returns_zero(tmp_path):
    reg = RoleRegistry()
    assert reg.discover_from_directory(tmp_path / "no_such_dir") == 0


def test_discover_skips_underscore_and_broken_modules(tmp_path):
    reg = RoleRegistry()
    (tmp_path / "_private.py").write_text(
        "from app.agents.base import BaseAgent\n"
        "class HiddenAgent(BaseAgent):\n"
        "    __role_name__ = 'hidden_role'\n",
        encoding="utf-8",
    )
    (tmp_path / "broken.py").write_text("这行不是合法 Python(", encoding="utf-8")
    # 下划线前缀直接跳过；坏模块加载失败记日志跳过，均不抛出
    assert reg.discover_from_directory(tmp_path) == 0
    assert "hidden_role" not in reg.list_roles()


def test_discover_registers_classes_with_role_attrs(tmp_path):
    reg = RoleRegistry()
    (tmp_path / "custom_role.py").write_text(
        "from app.agents.base import BaseAgent\n\n\n"
        "class CustomRole(BaseAgent):\n"
        "    __role_name__ = 'dir_discovered'\n"
        "    __role_metadata__ = {'description': '目录发现的角色'}\n",
        encoding="utf-8",
    )
    (tmp_path / "fallback_role.py").write_text(
        "from app.agents.base import BaseAgent\n\n\n"
        "class FallbackAgent(BaseAgent):\n"
        "    pass\n",  # 无 __role_name__ → 回退类名小写
        encoding="utf-8",
    )
    try:
        assert reg.discover_from_directory(tmp_path) == 2
        assert "dir_discovered" in reg.list_roles()
        assert reg.get_metadata("dir_discovered") == {"description": "目录发现的角色"}
        assert "fallbackagent" in reg.list_roles()
        assert reg.get_metadata("fallbackagent") == {}
    finally:
        # RoleRegistry 是单例，必须清理防污染全局
        reg.unregister("dir_discovered")
        reg.unregister("fallbackagent")


def test_register_role_decorator_registers_into_global():
    from app.agents.base import BaseAgent
    from app.engine.registry import register_role

    @register_role("deco_role_x", {"description": "装饰器注册"})
    class DecoAgent(BaseAgent):
        pass

    assert DecoAgent.__name__ == "DecoAgent"  # 装饰器须原样返回类
    try:
        assert "deco_role_x" in role_registry.list_roles()
        assert role_registry.get_metadata("deco_role_x") == {
            "description": "装饰器注册"
        }
    finally:
        role_registry.unregister("deco_role_x")


def test_builtin_roles_registered_via_decorator_imports():
    # agents 包被导入后，装饰器应已登记全部内置角色
    for role in ("executor", "learner", "content_filter", "tool_manager"):
        assert role in role_registry.list_roles(), role
