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


def test_builtin_roles_registered_via_decorator_imports():
    # agents 包被导入后，装饰器应已登记全部内置角色
    for role in ("executor", "learner", "content_filter", "tool_manager"):
        assert role in role_registry.list_roles(), role
