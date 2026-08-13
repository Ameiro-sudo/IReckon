"""内置工具注册与引擎决策逻辑测试。"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest
import pytest_asyncio

from app.core.database import db
from app.tools.registry import register_builtin_tools
from app.engine.machine import WorkflowEngine
from app.engine.tasks import TaskStatus

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(scope="module")
async def seeded_db(session_db):
    yield session_db


async def test_register_builtin_tools(seeded_db):
    count_before = await db.fetch_one("SELECT COUNT(*) FROM tool_parts")
    await register_builtin_tools(str(ROOT / "app" / "tools" / "builtin"))
    count_after = await db.fetch_one("SELECT COUNT(*) FROM tool_parts")
    assert count_after[0] >= count_before[0]
    assert count_after[0] >= 8


async def test_register_builtin_tools_idempotent(seeded_db):
    await register_builtin_tools(str(ROOT / "app" / "tools" / "builtin"))
    count1 = (await db.fetch_one("SELECT COUNT(*) FROM tool_parts"))[0]
    await register_builtin_tools(str(ROOT / "app" / "tools" / "builtin"))
    count2 = (await db.fetch_one("SELECT COUNT(*) FROM tool_parts"))[0]
    assert count1 == count2


async def test_register_missing_dir(seeded_db):
    await register_builtin_tools("/nonexistent/dir")
    assert True


def test_review_router_pass_last_phase():
    engine = WorkflowEngine()
    r = engine.review_router(
        {
            "task_id": "t",
            "review_passed_this_round": True,
            "current_phase": 1,
            "phases": [{"phase": "a"}, {"phase": "b"}],
        }
    )
    assert r == "pass"


def test_review_router_pass_more_phases():
    engine = WorkflowEngine()
    r = engine.review_router(
        {
            "task_id": "t",
            "review_passed_this_round": True,
            "current_phase": 0,
            "phases": [{"phase": "a"}, {"phase": "b"}],
        }
    )
    assert r == "revise"


def test_review_router_rounds_exhausted():
    engine = WorkflowEngine()
    r = engine.review_router(
        {
            "task_id": "t",
            "review_passed_this_round": False,
            "review_rounds": 5,
            "max_review_rounds": 5,
            "current_phase": 0,
            "phases": [{"phase": "a"}],
        }
    )
    assert r == "fail"


def test_review_router_retry():
    engine = WorkflowEngine()
    r = engine.review_router(
        {
            "task_id": "t",
            "review_passed_this_round": False,
            "review_rounds": 2,
            "max_review_rounds": 5,
            "current_phase": 0,
            "phases": [{"phase": "a"}],
        }
    )
    assert r == "revise"


def test_revise_router_executing_goes_execute():
    engine = WorkflowEngine()
    assert engine.revise_router({"status": TaskStatus.EXECUTING}) == "execute"
    assert engine.revise_router({"status": TaskStatus.REVIEWING}) == "review"
