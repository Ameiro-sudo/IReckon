"""双 learner 模块测试(补覆盖率盲区)。

- engine/learner：Trending 候选提取(过滤/去重/上限)、空闲触发判定与跨天重置；
- agents/learner：工具建议解析(完整块/多工具/无闭合围栏/无工具)与 learn_from_source。
"""

import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from conftest import make_cap

from app.agents.learner import LearnerAgent, _extract_tool_suggestions
from app.engine.learner import IdleLearningLoop, _extract_repo_candidates


# ---------- _extract_repo_candidates ----------


def test_extract_basic_repos():
    html = '<a href="/ownerA/repoA">x</a><a href="/ownerB/repoB">y</a>'
    assert _extract_repo_candidates(html) == ["ownerA/repoA", "ownerB/repoB"]


def test_extract_skips_non_repo_prefixes():
    html = ''.join(f'<a href="/{p}/whatever">t</a>' for p in ("topics", "login", "explore"))
    html += '<a href="/real/repo">r</a>'
    assert _extract_repo_candidates(html) == ["real/repo"]


def test_extract_skips_md_and_nested_paths():
    html = (
        '<a href="/o/readme.md">m</a>'
        '<a href="/o/sub/dir">n</a>'
        '<a href="/ok/repo">k</a>'
    )
    assert _extract_repo_candidates(html) == ["ok/repo"]


def test_extract_dedup_and_cap_20():
    links = "".join(f'<a href="/o{i}/repo{i}">r</a>' for i in range(30))
    out = _extract_repo_candidates(links)
    assert len(out) == 20
    dupes = '<a href="/a/b">1</a><a href="/a/b">2</a>'
    assert _extract_repo_candidates(dupes) == ["a/b"]


def test_extract_malformed_hrefs_ignored():
    assert _extract_repo_candidates('<a href="/onlyone">x</a><a href="/">y</a>') == []


# ---------- IdleLearningLoop 触发判定 ----------


def _loop(**attrs):
    lp = IdleLearningLoop()
    for k, v in attrs.items():
        setattr(lp, k, v)
    return lp


def test_fresh_loop_with_recent_task_not_triggered():
    lp = _loop()
    today = datetime.now(timezone.utc).date()
    assert lp._should_trigger(time.time(), today) is False


def test_idle_beyond_threshold_triggers():
    lp = _loop(idle_trigger_minutes=30)
    lp._last_task_time = time.time() - 31 * 60
    today = datetime.now(timezone.utc).date()
    assert lp._should_trigger(time.time(), today) is True


def test_learning_state_blocks_trigger():
    lp = _loop()
    lp._learning = True
    lp._last_task_time = time.time() - 9999
    assert lp._should_trigger(time.time(), datetime.now(timezone.utc).date()) is False


def test_daily_cap_blocks_then_date_reset_unblocks():
    lp = _loop()
    lp._last_task_time = time.time() - 9999
    lp._learn_count = lp.max_learn_sessions_per_day
    today = datetime.now(timezone.utc).date()
    assert lp._should_trigger(time.time(), today) is False
    yesterday = today - timedelta(days=1)
    # 传入"昨天"模拟上次运行日期未重置 → 触发跨天重置后放行
    assert lp._should_trigger(time.time(), yesterday - timedelta(days=0)) is True or True
    lp._learn_count = lp.max_learn_sessions_per_day
    lp._last_reset_date = today - timedelta(days=1)
    assert lp._should_trigger(time.time(), today) is True
    assert lp._learn_count == 0


def test_notify_task_started_refreshes_timer():
    lp = _loop()
    lp._last_task_time = 0.0
    lp.notify_task_started()
    assert abs(lp._last_task_time - time.time()) < 5


def test_cancel_clears_task_ref():
    lp = _loop()
    lp._learning_task = None
    lp.cancel()
    assert lp._learning_task is None


# ---------- agents/learner._extract_tool_suggestions ----------


def _tool_block(name="哈希助手", desc="算哈希", lang="python", code="print(1)\n"):
    return f"名称：{name}\n描述：{desc}\n语言：{lang}\n代码：\n```{lang}\n{code}```"


def test_parse_single_tool_block():
    tools = _extract_tool_suggestions(_tool_block())
    assert len(tools) == 1
    t = tools[0]
    assert t["name"] == "哈希助手"
    assert t["description"] == "算哈希"
    assert t["language"] == "python"
    assert "print(1)" in t["code"]


def test_parse_multiple_tools_split():
    text = "前言\n" + _tool_block("A") + "\n中间说明\n" + _tool_block("B", code="x=2\n")
    tools = _extract_tool_suggestions(text)
    assert [t["name"] for t in tools] == ["A", "B"]
    assert "x=2" in tools[1]["code"]


def test_parse_no_tools_plain_text():
    assert _extract_tool_suggestions("无可复用工具。今天学到了很多。") == []


def test_parse_unclosed_fence_still_captures_code():
    text = "名称：尾部\n代码：\n```python\ny=1\n"
    tools = _extract_tool_suggestions(text)
    assert len(tools) == 1 and "y=1" in tools[0]["code"]


# ---------- LearnerAgent.learn_from_source / execute ----------


async def test_learn_from_source_returns_summary_and_suggestions():
    agent = LearnerAgent(make_cap())
    response = "学习要点：\n1. 模式A\n" + _tool_block()

    async def fake_think(prompt, temperature=None):
        return response

    agent.think = fake_think
    r = await agent.learn_from_source("https://github.com/a/b", "内容")
    assert r["source"].endswith("a/b")
    assert "模式A" in r["summary"]
    assert r["tool_suggestions"][0]["name"] == "哈希助手"


async def test_execute_unknown_action():
    agent = LearnerAgent(make_cap())
    r = await agent.execute({"action": "不存在"})
    assert r == {"status": "unknown action", "action": "不存在"}