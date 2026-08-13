"""调度员 JSON 解析与招募逻辑测试（不调用真实 LLM）。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest

from app.agents.scheduler import SchedulerAgent
from app.llm.pool import AICapability


class FakeCapabilityPool:
    def __init__(self, caps):
        self._caps = {c.id: c for c in caps}

    async def find_best_match(
        self, required_tags=None, exclude_ids=None, prefer_cheapest=False, **kw
    ):
        exclude_ids = exclude_ids or set()
        cands = [c for c in self._caps.values() if c.id not in exclude_ids]
        if required_tags:
            cands = [c for c in cands if all(t in c.tags for t in required_tags)]
        return cands[0] if cands else None


def make_agent():
    cap = AICapability(
        id="t1",
        name="Test",
        endpoint="http://localhost:1/v1",
        model="auto",
        api_key="",
        tags=["python", "general"],
        max_context=4096,
    )
    return SchedulerAgent(cap)


@pytest.mark.asyncio
async def test_parse_requirement_with_json_fence(monkeypatch):
    agent = make_agent()
    plan = {
        "task_name": "T",
        "summary": "S",
        "complexity": "simple",
        "phases": [{"phase": "dev", "required_roles": ["executor"]}],
        "recruitment_plan": {"executor": {"count": 1}},
    }
    response = f"以下是计划：\n```json\n{json.dumps(plan, ensure_ascii=False)}\n```"

    async def fake_think(prompt, **kw):
        return response

    monkeypatch.setattr(agent, "think", fake_think)
    result = await agent.parse_requirement("写个脚本")
    assert result["task_name"] == "T"
    assert result["phases"][0]["required_roles"] == ["executor"]


@pytest.mark.asyncio
async def test_parse_requirement_bare_json(monkeypatch):
    agent = make_agent()
    plan = {"task_name": "T2", "summary": "S", "complexity": "simple", "phases": [], "recruitment_plan": {}}

    async def fake_think(prompt, **kw):
        return json.dumps(plan)

    monkeypatch.setattr(agent, "think", fake_think)
    result = await agent.parse_requirement("需求")
    assert result["task_name"] == "T2"


@pytest.mark.asyncio
async def test_parse_requirement_invalid_falls_back(monkeypatch):
    agent = make_agent()

    async def fake_think(prompt, **kw):
        return "不是 JSON 的回复"

    monkeypatch.setattr(agent, "think", fake_think)
    result = await agent.parse_requirement("需求")
    assert result["task_name"] == "未命名任务"
    assert result["phases"]


def test_recruit_team_single_instance_reuse():
    agent = make_agent()
    pool = FakeCapabilityPool([agent.capability])
    agent.capability_pool = pool
    plan = {
        "executor": {"count": 1, "required_tags": ["python"]},
        "reviewer_correctness": {"count": 1, "required_tags": ["python"]},
        "deliverer": {"count": 1, "required_tags": ["python"]},
    }

    import asyncio

    team = asyncio.run(agent.recruit_team(plan))
    assert len(team["executor"]) == 1
    assert len(team["reviewer_correctness"]) == 1
    assert len(team["deliverer"]) == 1
