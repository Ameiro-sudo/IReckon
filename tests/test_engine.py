"""审查员响应解析与工作流引擎图结构测试。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


from app.agents.reviewer import CorrectnessReviewerAgent
from app.llm.pool import AICapability
from app.engine.machine import WorkflowEngine


def make_reviewer():
    cap = AICapability(
        id="t1",
        name="Test",
        endpoint="http://localhost:1/v1",
        model="auto",
        api_key="",
        tags=["python"],
        max_context=4096,
    )
    return CorrectnessReviewerAgent(cap)


def test_parse_review_json():
    rv = make_reviewer()
    text = json.dumps({"passed": True, "issues": ["i1"], "suggestions": ["s1"]})
    out = rv._parse_review_response(text)
    assert out["passed"] is True
    assert "i1" in out["issues"]


def test_parse_review_with_fence():
    rv = make_reviewer()
    text = '```json\n{"passed": false, "issues": ["x"]}\n```'
    out = rv._parse_review_response(text)
    assert out["passed"] is False
    assert out["issues"] == ["x"]


def test_parse_review_invalid_fallback():
    rv = make_reviewer()
    out = rv._parse_review_response("随便说点什么")
    assert out["passed"] is False


def test_engine_graph_has_all_nodes():
    engine = WorkflowEngine()
    names = {n for n in engine.graph.get_graph().nodes}
    assert "planning" in names
    assert "execute" in names
    assert "review" in names
    assert "revise" in names
    assert "deliver" in names
    assert "handle_error" in names


def test_engine_edges():
    engine = WorkflowEngine()
    graph = engine.graph.get_graph()
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("planning", "execute") in edges
    assert ("execute", "review") in edges
    assert ("deliver", "__end__") in edges
    assert ("handle_error", "__end__") in edges
