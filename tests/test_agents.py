"""各 Agent 的纯逻辑测试(不调用真实 LLM):解析产物、JSON、招募、流式思考。"""

import json


from app.agents.deliverer import DelivererAgent
from app.agents.executor import ExecutorAgent
from app.agents.reviewer import CorrectnessReviewerAgent
from app.agents.scheduler import SchedulerAgent
from conftest import FakeCapabilityPool, make_cap


def make_scheduler():
    return SchedulerAgent(make_cap(tags=["python", "general"]))


def make_executor():
    return ExecutorAgent(make_cap())


def make_reviewer():
    return CorrectnessReviewerAgent(make_cap())


# ---------- scheduler:需求解析 ----------


def _plan(name, phases=(), recruitment=None):
    return {
        "task_name": name,
        "summary": "S",
        "complexity": "simple",
        "phases": list(phases),
        "recruitment_plan": recruitment or {},
    }


async def test_scheduler_parse_requirement_with_json_fence(monkeypatch):
    agent = make_scheduler()
    plan = _plan(
        "T",
        [{"phase": "dev", "required_roles": ["executor"]}],
        {"executor": {"count": 1}},
    )
    response = f"以下是计划:\n```json\n{json.dumps(plan, ensure_ascii=False)}\n```"

    async def fake_think(prompt, **kw):
        return response

    monkeypatch.setattr(agent, "think", fake_think)
    result = await agent.parse_requirement("写个脚本")
    assert result["task_name"] == "T"
    assert result["phases"][0]["required_roles"] == ["executor"]


async def test_scheduler_parse_requirement_bare_json(monkeypatch):
    agent = make_scheduler()

    async def fake_think(prompt, **kw):
        return json.dumps(_plan("T2"))

    monkeypatch.setattr(agent, "think", fake_think)
    result = await agent.parse_requirement("需求")
    assert result["task_name"] == "T2"


async def test_scheduler_parse_requirement_invalid_falls_back(monkeypatch):
    agent = make_scheduler()

    async def fake_think(prompt, **kw):
        return "不是 JSON 的回复"

    monkeypatch.setattr(agent, "think", fake_think)
    result = await agent.parse_requirement("需求")
    assert result["task_name"] == "未命名任务"
    assert result["phases"]


async def test_scheduler_recruit_team_single_instance_reuse():
    agent = make_scheduler()
    agent.capability_pool = FakeCapabilityPool([agent.capability])
    plan = {
        "executor": {"count": 1, "required_tags": ["python"]},
        "reviewer_correctness": {"count": 1, "required_tags": ["python"]},
        "deliverer": {"count": 1, "required_tags": ["python"]},
    }
    team = await agent.recruit_team(plan)
    assert len(team["executor"]) == 1
    assert len(team["reviewer_correctness"]) == 1
    assert len(team["deliverer"]) == 1


# ---------- executor:产物/补丁解析 ----------


def test_executor_parse_single_file():
    assert make_executor()._parse_artifacts("print('hello')") == {
        "main.py": "print('hello')"
    }


def test_executor_parse_multi_file():
    text = "//// filename: a.py\nprint(1)\n//// filename: b.py\nprint(2)"
    out = make_executor()._parse_artifacts(text)
    assert set(out.keys()) == {"a.py", "b.py"}
    assert out["a.py"] == "print(1)"
    assert out["b.py"] == "print(2)"


def test_executor_parse_strips_markdown_fences():
    text = "//// filename: a.py\n```python\nprint(1)\n```\n//// filename: b.py\nplain text"
    out = make_executor()._parse_artifacts(text)
    assert out["a.py"] == "print(1)"
    assert out["b.py"] == "plain text"


def test_executor_parse_cleans_filename_backticks():
    text = "//// filename: src/main.py```\n```python\nprint(1)\n```"
    out = make_executor()._parse_artifacts(text)
    assert out["src/main.py"] == "print(1)"


def test_executor_syntax_errors_detection():
    ex = make_executor()
    assert ex._syntax_errors({"ok.py": "def f():\n    pass"}) == []
    errs = ex._syntax_errors({"bad.py": "def f(:", "note.md": "## x"})
    assert len(errs) == 1
    assert "bad.py" in errs[0]


def test_executor_parse_patches_multiple_files():
    text = (
        "PATCH: a.py\n"
        "@@ -1,3 +1,3 @@\n"
        " print(1)\n"
        "-print(2)\n"
        "+print(22)\n"
        "PATCH: b.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-x = 1\n"
        "+x = 2\n"
    )
    patches = make_executor()._parse_patches(text)
    assert set(patches.keys()) == {"a.py", "b.py"}
    assert "-print(2)" in patches["a.py"]


def test_executor_apply_unified_diff():
    ex = make_executor()
    original = "a\nb\nc\n"
    patch = "@@ -1,3 +1,3 @@\n a\n-b\n+c\n"
    assert ex._apply_unified_diff(original, patch) == "a\nc\nc\n"


def test_executor_apply_diff_add_line():
    ex = make_executor()
    original = "x = 1\n"
    patch = "@@ -1,1 +1,2 @@\n x = 1\n+y = 2\n"
    assert ex._apply_unified_diff(original, patch) == "x = 1\ny = 2\n"


# ---------- reviewer:审查响应解析 ----------


def test_reviewer_parse_json():
    text = json.dumps({"passed": True, "issues": ["i1"], "suggestions": ["s1"]})
    out = make_reviewer()._parse_review_response(text)
    assert out["passed"] is True
    assert "i1" in out["issues"]


def test_reviewer_parse_with_fence():
    text = '```json\n{"passed": false, "issues": ["x"]}\n```'
    out = make_reviewer()._parse_review_response(text)
    assert out["passed"] is False
    assert out["issues"] == ["x"]


def test_reviewer_parse_invalid_fallback():
    out = make_reviewer()._parse_review_response("随便说点什么")
    assert out["passed"] is False


# ---------- deliverer:文件名净化 ----------


def test_deliverer_safe_filename():
    assert DelivererAgent._safe_filename("src/models/todo.py") == "src/models/todo.py"
    assert DelivererAgent._safe_filename("tests/unit/test_a.py") == "tests/unit/test_a.py"
    assert DelivererAgent._safe_filename("../evil/x.py") == "evil/x.py"
    assert DelivererAgent._safe_filename("a:b.py") == "a_b.py"
    assert DelivererAgent._safe_filename("") == "unnamed.txt"


# ---------- think_stream ----------


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def call(self, *args, **kwargs):
        async def gen():
            for piece in ("hello", " world"):
                yield piece

        self.calls.append((args, kwargs))
        return gen()


async def test_think_stream_awaits_call():
    agent = ExecutorAgent(make_cap())
    agent.llm = FakeLLM()
    agent.bind_context("task-stream-1")
    chunks = [chunk async for chunk in agent.think_stream()]
    assert "".join(chunks) == "hello world"
    assert agent.messages[-1]["role"] == "assistant"
    assert "hello world" in agent.messages[-1]["content"]


async def test_think_stream_adds_user_message():
    agent = ExecutorAgent(make_cap())
    agent.llm = FakeLLM()
    agent.bind_context("task-stream-2")
    async for _ in agent.think_stream(user_message="请输出代码"):
        pass
    assert any(
        m["role"] == "user" and m["content"] == "请输出代码" for m in agent.messages
    )