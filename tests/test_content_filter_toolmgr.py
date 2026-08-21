"""内容过滤与工具管理 Agent 测试(补覆盖率盲区)。

- content_filter：解析校验/重试/fail-closed(二次解析失败按不通过)；
- tool_manager：确定性组装三分支/LLM回退/execute 分派。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from conftest import make_cap

from app.agents.content_filter import ContentFilterAgent, _parse_filter_response
from app.agents.tool_manager import (
    ToolManagerAgent,
    assemble_tool_simple,
)


def _part(name="p1"):
    return {
        "name": name,
        "description": f"{name} 零件",
        "language": "python",
        "code": "def run(x):\n    return x\n",
    }


# ---------- content_filter._parse_filter_response ----------


def test_parse_filter_valid():
    r = _parse_filter_response('{"passed": true, "reason": "干净"}')
    assert r == {"passed": True, "reason": "干净"}


def test_parse_filter_missing_reason_defaults_empty():
    r = _parse_filter_response('{"passed": false}')
    assert r == {"passed": False, "reason": ""}


def test_parse_filter_garbage_returns_none():
    assert _parse_filter_response("这不是JSON") is None


def test_parse_filter_passed_not_bool_returns_none():
    assert _parse_filter_response('{"passed": "yes"}') is None
    assert _parse_filter_response('{"reason": "缺passed"}') is None


# ---------- content_filter.filter 行为 ----------


def _filter_agent(responses):
    """构造 think 按序吐 responses 的过滤 Agent。"""
    agent = ContentFilterAgent(make_cap())
    queue = list(responses)

    async def fake_think(prompt, temperature=None):
        return queue.pop(0) if queue else "兜底"

    agent.think = fake_think
    return agent


async def test_filter_pass_immediate():
    agent = _filter_agent(['{"passed": true, "reason": ""}'])
    r = await agent.filter("普通文本")
    assert r["passed"] is True


async def test_filter_retry_second_parse_ok():
    agent = _filter_agent(["垃圾输出", '{"passed": false, "reason": "发现密钥"}'])
    r = await agent.filter("内容")
    assert r == {"passed": False, "reason": "发现密钥"}


async def test_filter_fail_closed_on_double_parse_failure():
    agent = _filter_agent(["乱码A", "乱码B"])
    r = await agent.filter("内容")
    # 二次解析失败必须 fail-closed：宁可误拦不可漏放
    assert r["passed"] is False
    assert "解析失败" in r["reason"]


async def test_filter_execute_dispatch():
    agent = ContentFilterAgent(make_cap())

    async def fake_filter(content, context=""):
        return {"passed": content != "敏感", "reason": ""}

    agent.filter = fake_filter
    r = await agent.execute({"content": "敏感"})
    assert r["passed"] is False


# ---------- tool_manager 确定性组装分支 ----------


async def test_assemble_condition_branch():
    code = await assemble_tool_simple(
        "如果参数为真就走A流程", [_part("a"), _part("b"), _part("c")]
    )
    assert isinstance(code, str) and "条件零件" in code


async def test_assemble_loop_branch():
    code = await assemble_tool_simple("重复执行这个动作500次", [_part("loop")])
    assert isinstance(code, str) and code.strip()


async def test_assemble_sequence_default_branch():
    code = await assemble_tool_simple("把这两步串起来", [_part("x"), _part("y")])
    assert isinstance(code, str) and "零件1" in code


async def test_assemble_no_match_no_parts_returns_none():
    assert await assemble_tool_simple("简单需求", []) is None


# ---------- tool_manager.execute 分派 ----------


def _tm_agent():
    return ToolManagerAgent(make_cap())


async def test_execute_search_delegates():
    agent = _tm_agent()
    seen = {}

    async def fake_search(query, tags=None):
        seen["q"] = query
        return [{"part_id": "p1"}]

    import app.agents.tool_manager as tm

    tm.search_parts, orig = fake_search, tm.search_parts
    try:
        r = await agent.execute({"action": "search", "query": "哈希"})
    finally:
        tm.search_parts = orig
    assert seen["q"] == "哈希"
    assert r == {"parts": [{"part_id": "p1"}]}


async def test_execute_assemble_deterministic_priority():
    agent = _tm_agent()

    async def fake_llm(requirement, parts):
        raise AssertionError("确定性组装成功时不应调用 LLM")

    agent.assemble_tool = fake_llm
    r = await agent.execute(
        {
            "action": "assemble",
            "requirement": "如果出错就重试",
            "parts": [_part(), _part(), _part()],
        }
    )
    assert r["method"] == "deterministic"


async def test_execute_assemble_llm_fallback():
    agent = _tm_agent()

    async def fake_llm(requirement, parts):
        return "def tool():\n    pass\n"

    agent.assemble_tool = fake_llm
    r = await agent.execute({"action": "assemble", "requirement": "任意", "parts": []})
    assert r["method"] == "llm"
    assert r["code"].startswith("def ")


async def test_execute_unknown_action():
    r = await _tm_agent().execute({"action": "不存在的"})
    assert "error" in r