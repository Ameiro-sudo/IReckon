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


# ---------- tool_manager 补盲区：LIKE 转义 / 零件库检索 / LLM 组装提示词 ----------

import json  # noqa: E402

from app.agents.tool_manager import (  # noqa: E402
    _like_literal,
    search_parts,
)
from app.core.database import db  # noqa: E402


def test_like_literal_escapes_wildcards():
    assert _like_literal("a%b_c\\d") == "a\\%b\\_c\\\\d"
    assert _like_literal("plain") == "plain"  # 无通配符原样通过


async def _seed_part(part_id, name, description="零件描述", tags=("util",)):
    await db.execute(
        "INSERT INTO tool_parts"
        "(part_id,name,description,language,code,input_schema,output_schema,tags)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (
            part_id,
            name,
            description,
            "python",
            f"def run_{part_id}():\n    pass\n",
            json.dumps({"type": "object"}),
            json.dumps({"type": "object"}),
            json.dumps(list(tags)),
        ),
    )


async def test_search_parts_matches_name_and_description(session_db):
    await _seed_part("t1", "哈希助手", "计算文件哈希")
    await _seed_part("t2", "压缩器", "zip 打包")
    by_name = await search_parts("哈希")
    assert [p["part_id"] for p in by_name] == ["t1"]
    by_desc = await search_parts("打包")
    assert [p["part_id"] for p in by_desc] == ["t2"]
    # 双字段联合命中
    both = await search_parts("哈希 助手不存在词")  # 无单一字段同时含两词
    assert both == [] or all(p["part_id"] == "t1" for p in both)


async def test_search_parts_percent_literal_not_wildcard(session_db):
    await _seed_part("p100", "成功率100x统计")
    await _seed_part("pliteral", "成功率100%统计")
    # % 已被转义：只命中字面含 "100%" 的名字，不再当任意串通配
    hits = await search_parts("100%")
    assert [p["part_id"] for p in hits] == ["pliteral"]
    # 下划线同理：字面匹配而非单字符占位
    hits2 = await search_parts("率100_")
    assert hits2 == []


async def test_search_parts_tags_filter(session_db):
    await _seed_part("tag1", "零件甲", tags=("util", "hash"))
    await _seed_part("tag2", "零件乙", tags=("net",))
    got = await search_parts("", tags=["hash"])
    assert [p["part_id"] for p in got] == ["tag1"]
    got_none = await search_parts("", tags=["不存在的标签"])
    assert got_none == []


async def test_search_parts_shapes_json_fields_and_null_schemas(session_db):
    await db.execute(
        "INSERT INTO tool_parts"
        "(part_id,name,description,language,code,input_schema,output_schema,tags)"
        " VALUES (?,?,?,?,?,?,?,?)",
        ("shape1", "裸零件", "无 schema", "python", "x=1\n", None, None, None),
    )
    parts = await search_parts("裸零件")
    assert len(parts) == 1
    p = parts[0]
    assert p["input_schema"] == {} and p["output_schema"] == {}
    assert p["tags"] == []
    assert p["language"] == "python" and "x=1" in p["code"]


async def test_assemble_tool_simple_insufficient_parts_fall_through():
    # 条件语义但零件不足三个 → 整条链不命中返回 None（14->21 分支）
    p = {"name": "a", "description": "a 零件"}
    assert await assemble_tool_simple("如果出错就重试", [p, p]) is None
    # 循环语义但无零件 → None（17->21 分支）
    assert await assemble_tool_simple("循环500次", []) is None
    # 无关键词且无零件 → None
    assert await assemble_tool_simple("随便做点事", []) is None


async def test_assemble_tool_llm_prompt_wraps_untrusted_data():
    agent = _tm_agent()
    captured = {}

    async def fake_think(prompt, temperature=None):
        captured["prompt"] = prompt
        captured["temperature"] = temperature
        return "# llm 组装结果"

    agent.think = fake_think
    parts = [
        {"name": "reader", "description": "读文件"},
        {"name": "writer", "description": "写文件"},
    ]
    out = await agent.assemble_tool("把 A 拼到 B", parts)
    assert out == "# llm 组装结果"
    assert captured["prompt"].count("<untrusted_data>") == 2  # 需求与零件都被围栏
    assert "- reader: 读文件" in captured["prompt"]
    assert captured["temperature"] == 0.2
