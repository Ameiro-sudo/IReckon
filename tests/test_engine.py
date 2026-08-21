"""引擎测试:工作流图结构、路由决策、成本/死循环检测、mock LLM 全流程。"""

import asyncio
import json
import sqlite3
from pathlib import Path

from app.agents import base as base_agents
from app.core.database import db
from app.engine.cost import CostTracker, _current_month
from app.engine.detector import LoopDetector
from app.engine.machine import WorkflowEngine, review_router, revise_router
from app.engine.tasks import TaskStatus, task_manager


def make_engine():
    return WorkflowEngine()


# ---------- 工作流图结构 ----------


def test_engine_graph_has_all_nodes():
    names = {n for n in make_engine().graph.get_graph().nodes}
    assert {
        "planning",
        "execute",
        "review",
        "revise",
        "deliver",
        "handle_error",
    } <= names


def test_engine_edges():
    graph = make_engine().graph.get_graph()
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("planning", "execute") in edges
    assert ("execute", "review") in edges
    assert ("deliver", "__end__") in edges
    assert ("handle_error", "__end__") in edges


# ---------- 路由决策 ----------


def test_review_router_pass_last_phase():
    state = {
        "task_id": "t",
        "review_passed_this_round": True,
        "current_phase": 1,
        "phases": [{"phase": "a"}, {"phase": "b"}],
    }
    assert review_router(state) == "pass"


def test_review_router_pass_more_phases():
    state = {
        "task_id": "t",
        "review_passed_this_round": True,
        "current_phase": 0,
        "phases": [{"phase": "a"}, {"phase": "b"}],
    }
    assert review_router(state) == "revise"


def test_review_router_rounds_exhausted():
    state = {
        "task_id": "t",
        "review_passed_this_round": False,
        "review_rounds": 5,
        "max_review_rounds": 5,
        "current_phase": 0,
        "phases": [{"phase": "a"}],
    }
    assert review_router(state) == "fail"


def test_review_router_retry():
    state = {
        "task_id": "t",
        "review_passed_this_round": False,
        "review_rounds": 2,
        "max_review_rounds": 5,
        "current_phase": 0,
        "phases": [{"phase": "a"}],
    }
    assert review_router(state) == "revise"


def test_revise_router():
    make_engine()
    assert revise_router({"status": TaskStatus.EXECUTING}) == "execute"
    assert revise_router({"status": TaskStatus.REVIEWING}) == "review"


# ---------- 成本追踪 ----------


async def test_cost_tracker_budget_exceeded():
    ct = CostTracker()
    ct.max_task_tokens = 100
    assert not (await ct.add_usage("t1", 60, 0.0))
    assert await ct.add_usage("t1", 60, 0.0) is True
    assert ct.get_task_usage("t1") == 120


async def test_cost_tracker_monthly_warning():
    ct = CostTracker()
    ct.monthly_warning_threshold = 50
    await ct.add_usage("t2", 100, 0.0)
    assert ct._monthly_usage[_current_month()] >= 100


async def test_cost_tracker_is_over_budget():
    ct = CostTracker()
    ct.max_task_tokens = 100
    ct._task_usage["t3"] = 150
    assert await ct.is_over_budget("t3") is True
    assert await ct.is_over_budget("t-other") is False


# ---------- 死循环检测 ----------


async def test_loop_detector_short_history():
    assert await LoopDetector().check_loop("t", ["a", "b"]) is False


async def test_loop_detector_identical_outputs():
    ld = LoopDetector()
    ld.max_rounds = 3
    ld.similarity_threshold = 0.9
    assert await ld.check_loop("t", ["same output"] * 5) is True


async def test_loop_detector_distinct_outputs():
    ld = LoopDetector()
    ld.max_rounds = 3
    outputs = ["alpha", "beta", "gamma", "delta"]
    assert await ld.check_loop("t", outputs) is False


# ---------- mock LLM 全流程 ----------

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
        "reviewer_correctness": {
            "count": 1,
            "required_tags": ["python"],
            "prefer_cheap": True,
        },
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


async def test_full_pipeline_with_mocked_llm(session_db, monkeypatch):
    monkeypatch.setattr(base_agents.BaseAgent, "think", _fake_think)

    tid = await task_manager.create_task("写一个 hello.py 打印 hello world")
    assert tid

    await task_manager._execute_task(tid, None, asyncio.Event())

    row = await db.fetch_one("SELECT status FROM tasks WHERE task_id=?", (tid,))
    assert row[0] == TaskStatus.COMPLETED.value

    con = sqlite3.connect(str(Path.cwd() / "data" / "db" / "ireckon.db"))
    row2 = con.execute("SELECT status FROM tasks WHERE task_id=?", (tid,)).fetchone()
    con.close()
    assert row2[0] == TaskStatus.COMPLETED.value

    output_dir = Path.cwd() / "data" / "outputs" / tid
    assert (output_dir / "hello.py").exists()
    content = (output_dir / "hello.py").read_text(encoding="utf-8")
    assert "hello world" in content
    assert "```" not in content
    assert (output_dir / "READY.txt").exists()


async def test_full_pipeline_review_fail_then_pass(session_db, monkeypatch):
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
    await task_manager._execute_task(tid, None, asyncio.Event())

    row = await db.fetch_one("SELECT status FROM tasks WHERE task_id=?", (tid,))
    assert row[0] == TaskStatus.COMPLETED.value
    assert calls["review"] >= 2
