"""工作流引擎全图测试：以 mock LLM 驱动 planning→execute→review→deliver 完整流水线。"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest
import pytest_asyncio

from app.core.database import db
from app.engine.tasks import task_manager, TaskStatus
from app.agents import base as base_agents

pytestmark = pytest.mark.asyncio

PLAN = {
    "task_name": "测试任务",
    "summary": "集成测试",
    "complexity": "simple",
    "estimated_budget_usd": 0.0,
    "phases": [
        {
            "phase": "implementation",
            "description": "编写 hello.py 打印 hello world",
            "expected_artifacts": ["hello.py"],
            "required_roles": ["executor", "reviewer_correctness"],
            "skill_tags": ["python"],
            "estimated_tokens": 100,
        }
    ],
    "recruitment_plan": {
        "executor": {"count": 1, "required_tags": ["python"], "prefer_cheap": True},
        "reviewer_correctness": {"count": 1, "required_tags": ["python"], "prefer_cheap": True},
    },
}

EXECUTOR_OUTPUT = '//// filename: hello.py\n```python\nprint("hello world")\n```'


async def _fake_think(self, prompt, **kwargs):
    role = getattr(self, "role", "?")
    if role == "scheduler":
        return json.dumps(PLAN, ensure_ascii=False)
    if role == "executor":
        return EXECUTOR_OUTPUT
    if role in ("reviewer_correctness", "reviewer_efficiency"):
        return json.dumps({"passed": True, "issues": [], "suggestions": []})
    return "ok"


@pytest_asyncio.fixture(scope="module")
async def flow_db(session_db):
    yield session_db


async def test_full_pipeline_with_mocked_llm(flow_db, monkeypatch):
    monkeypatch.setattr(base_agents.BaseAgent, "think", _fake_think)

    tid = await task_manager.create_task("写一个 hello.py 打印 hello world")
    assert tid

    ce = asyncio.Event()
    await task_manager._execute_task(tid, None, ce)

    row = await db.fetch_one("SELECT status FROM tasks WHERE task_id=?", (tid,))
    assert row[0] == TaskStatus.COMPLETED.value

    import sqlite3

    con = sqlite3.connect(str(Path.cwd() / "data" / "db" / "ireckon.db"))
    row2 = con.execute("SELECT status FROM tasks WHERE task_id=?", (tid,)).fetchone()
    assert row2[0] == TaskStatus.COMPLETED.value
    con.close()

    output_dir = Path.cwd() / "data" / "outputs" / tid
    assert (output_dir / "hello.py").exists()
    content = (output_dir / "hello.py").read_text(encoding="utf-8")
    assert "hello world" in content
    assert "```" not in content
    assert (output_dir / "READY.txt").exists()


async def test_full_pipeline_review_fail_then_pass(flow_db, monkeypatch):
    calls = {"review": 0}

    async def fake_think_retry(self, prompt, **kwargs):
        role = getattr(self, "role", "?")
        if role == "scheduler":
            return json.dumps(PLAN, ensure_ascii=False)
        if role == "executor":
            return EXECUTOR_OUTPUT
        if role in ("reviewer_correctness", "reviewer_efficiency"):
            calls["review"] += 1
            if calls["review"] == 1:
                return json.dumps(
                    {"passed": False, "issues": ["缺少参数校验"], "suggestions": []}
                )
            return json.dumps({"passed": True, "issues": [], "suggestions": []})
        return "ok"

    monkeypatch.setattr(base_agents.BaseAgent, "think", fake_think_retry)

    tid = await task_manager.create_task("写一个 hello.py")
    ce = asyncio.Event()
    await task_manager._execute_task(tid, None, ce)

    row = await db.fetch_one("SELECT status FROM tasks WHERE task_id=?", (tid,))
    assert row[0] == TaskStatus.COMPLETED.value
    assert calls["review"] >= 2
