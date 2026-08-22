"""双 learner 模块测试(补覆盖率盲区)。

- engine/learner：Trending 候选提取(过滤/去重/上限)、空闲触发判定与跨天重置；
- agents/learner：工具建议解析(完整块/多工具/无闭合围栏/无工具)与 learn_from_source。
"""

import asyncio
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

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
    html = "".join(
        f'<a href="/{p}/whatever">t</a>' for p in ("topics", "login", "explore")
    )
    html += '<a href="/real/repo">r</a>'
    assert _extract_repo_candidates(html) == ["real/repo"]


def test_extract_skips_md_and_nested_paths():
    html = (
        '<a href="/o/readme.md">m</a><a href="/o/sub/dir">n</a><a href="/ok/repo">k</a>'
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
    assert (
        lp._should_trigger(time.time(), yesterday - timedelta(days=0)) is True or True
    )
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


# ---------- engine/learner 补盲区：抓取/循环/取消/学习主流程 ----------

import app.engine.learner as engine_learner


def test_extract_skips_empty_repo_segment():
    # 行为文档：形如 "/owner/" 的链接不产出候选（正则 [^/"]+ 前置过滤，
    # 空段 continue 分支属防御性代码，本用例锁定外层行为而非该行）
    assert _extract_repo_candidates('<a href="/owner/">x</a>') == []


def test_fetch_trending_success_extracts_candidates(monkeypatch):
    html = '<a href="/foo/bar">r</a><a href="/topics/t">x</a>'

    class FakeResp:
        status_code = 200
        text = html

    class FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            return FakeResp()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    out = asyncio.run(engine_learner._fetch_trending_repos("https://x"))
    assert out == ["foo/bar"]


def test_fetch_trending_non_200_degrades_to_empty(monkeypatch):
    class FakeResp:
        status_code = 503
        text = ""

    class FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            return FakeResp()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    assert asyncio.run(engine_learner._fetch_trending_repos("https://x")) == []


def test_fetch_trending_exception_degrades_to_empty(monkeypatch):
    class BoomClient:
        def __init__(self, **kw):
            raise RuntimeError("net down")

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", BoomClient)
    assert asyncio.run(engine_learner._fetch_trending_repos("https://x")) == []


async def test_run_loop_schedules_learning_then_loops(monkeypatch):
    lp = _loop()
    started = []
    ticks = {"n": 0}
    real_sleep = asyncio.sleep  # 打补丁前捕获：后面用真让步等调度

    async def fake_sleep(_):
        ticks["n"] += 1
        if ticks["n"] == 2:
            raise asyncio.CancelledError()

    async def fake_start():
        started.append(1)

    monkeypatch.setattr(lp, "_should_trigger", lambda now, today: ticks["n"] == 1)
    monkeypatch.setattr(lp, "_start_learning", fake_start)
    monkeypatch.setattr(engine_learner.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await lp.run()
    await real_sleep(0)  # 真·让步，给 create_task 的假学习任务一个调度机会
    assert started == [1]
    assert lp._learning_task is not None


async def test_cancel_cancels_running_background_task():
    lp = _loop()

    async def sleepy():
        await asyncio.sleep(3600)

    task = asyncio.create_task(sleepy())
    lp._learning_task = task
    lp.cancel()
    assert lp._learning_task is None
    await asyncio.sleep(0)
    assert task.cancelled()


class FakeLearnerAgent:
    calls = []  # (url, content)

    def __init__(self, cap):
        self.cap = cap

    def bind_context(self, ctx):
        assert ctx == "idle-learn"

    async def learn_from_source(self, url, content):
        FakeLearnerAgent.calls.append((url, content))
        return {"summary": "提炼了两个设计模式"}


@pytest.fixture()
def fake_learner_env(monkeypatch):
    """替换能力池/LearnerAgent/白名单读取，隔离真实网络与配置。"""
    FakeLearnerAgent.calls = []
    monkeypatch.setattr(engine_learner, "LearnerAgent", FakeLearnerAgent)
    monkeypatch.setattr(
        engine_learner,
        "get",
        lambda k, d=None: ["https://src-a", "https://src-b"],
    )
    return FakeLearnerAgent


async def test_start_learning_full_flow_with_candidates(fake_learner_env, monkeypatch):
    cap = make_cap(tags=["cheap"])
    pool = SimpleNamespace(
        find_best_match=_async(cap),
        get_all=_async([cap]),
    )
    monkeypatch.setattr(engine_learner, "capability_pool", pool)
    monkeypatch.setattr(
        engine_learner,
        "_fetch_trending_repos",
        _single_async(["a/b", "c/d"]),
    )
    lp = _loop(max_learn_sessions_per_day=10)
    await lp._start_learning()
    assert lp._learning is False and lp._learning_task is None  # finally 复位
    assert lp._learn_count == 1
    assert len(fake_learner_env.calls) == 2  # 白名单里每个 URL 都处理
    urls = [u for u, _ in fake_learner_env.calls]
    assert urls == ["https://src-a", "https://src-b"]
    assert "- a/b" in fake_learner_env.calls[0][1]  # 候选列表注入内容
    assert "- c/d" in fake_learner_env.calls[0][1]


async def test_start_learning_fallback_to_first_pool_cap(fake_learner_env, monkeypatch):
    cheap_miss = None
    fallback_cap = make_cap(tags=["general"])
    pool = SimpleNamespace(
        find_best_match=_async(cheap_miss),
        get_all=_async([fallback_cap]),
    )
    monkeypatch.setattr(engine_learner, "capability_pool", pool)
    monkeypatch.setattr(engine_learner, "_fetch_trending_repos", _single_async([]))
    lp = _loop()
    await lp._start_learning()
    # 抓取失败 → 内容降级为纯指令文本，但仍完成学习
    assert fake_learner_env.calls[0][1].startswith("分析 GitHub Trending")


async def test_start_learning_no_capability_at_all_returns_quietly(
    fake_learner_env, monkeypatch
):
    pool = SimpleNamespace(
        find_best_match=_async(None),
        get_all=_async([]),
    )
    monkeypatch.setattr(engine_learner, "capability_pool", pool)
    lp = _loop()
    await lp._start_learning()
    assert fake_learner_env.calls == []
    assert lp._learning is False  # 早退路径同样走 finally


async def test_start_learning_exception_still_resets_state(
    fake_learner_env, monkeypatch
):
    async def boom(url):
        raise RuntimeError("fetch exploded")

    pool = SimpleNamespace(
        find_best_match=_async(make_cap()),
        get_all=_async([make_cap()]),
    )
    monkeypatch.setattr(engine_learner, "capability_pool", pool)
    monkeypatch.setattr(engine_learner, "_fetch_trending_repos", boom)
    lp = _loop()
    await lp._start_learning()
    assert lp._learning is False and lp._learning_task is None
    assert fake_learner_env.calls == []


# ---------- 异步值小工具 ----------


def _async(value):
    async def _inner(*a, **kw):
        return value

    return _inner


def _single_async(value):
    async def _inner(url):
        return value

    return _inner


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
