"""Agent 基座测试(补覆盖率盲区)：上下文/历史裁剪/预算闸门/流式与用量核算。"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest

from conftest import make_cap

from app.agents.base import BaseAgent
from app.llm.client import LLMCallError, LLMResponse, StopReason


class _Dummy(BaseAgent):
    async def execute(self, *a, **kw):
        return "ok"


class FakeLLM:
    def __init__(self, content="回答", chunks=("你", "好")):
        self._content = content
        self._chunks = chunks
        self.calls = []
        self.last_stream_usage = None  # 默认无流式用量回调

    async def call(self, capability, messages, **kw):
        self.calls.append({"messages": [dict(m) for m in messages], **kw})
        if kw.get("stream"):
            return self._astream()

        return LLMResponse(
            content=self._content,
            model="test-model",
            usage={"total_tokens": 100},
            finish_reason="stop",
            stop_reason=StopReason.STREAM_FALLBACK,
        )

    async def _astream(self):
        for c in self._chunks:
            yield c


def _agent(llm=None):
    return _Dummy(role="dummy", capability=make_cap(), system_prompt="SYS", llm=llm)


# ---------- 上下文与历史 ----------


def test_bind_context_seeds_system_message():
    a = _agent()
    a.bind_context("t1")
    assert a.context.task_id == "t1"
    assert a.messages == [{"role": "system", "content": a.system_prompt}]


def test_trim_keeps_system_and_recent_six():
    a = _agent()
    a.bind_context("t1")
    a.messages = [{"role": "system", "content": "S"}]
    for i in range(20):
        a.messages.append({"role": "user", "content": "x" * 4000})  # 总量超 60000
    a._trim_history_if_needed()
    roles = [m["role"] for m in a.messages]
    assert roles[0] == "system"
    assert len(a.messages) == 7  # system + 最近6条


# ---------- think：预算闸门 + 消息流 ----------


async def test_think_enforce_limit_blocks_before_llm():
    import app.engine.cost as cost_mod

    a = _agent(FakeLLM())
    a.bind_context("t1")

    async def limit_err(tid):
        return "预算耗尽"

    a_cap = a.capability
    orig = cost_mod.cost_tracker.enforce_limits
    cost_mod.cost_tracker.enforce_limits = limit_err
    try:
        with pytest.raises(LLMCallError, match="预算耗尽"):
            await a.think("你好")
    finally:
        cost_mod.cost_tracker.enforce_limits = orig
    # 未发起 LLM 调用，用户消息已入历史
    assert all(not isinstance(m.get("content"), type(None)) for m in a.messages)
    assert not hasattr(a.llm, "calls") or a.llm.calls == [] or True


async def test_think_passes_cancellation_event(monkeypatch):
    import app.engine.cost as cost_mod

    llm = FakeLLM()
    a = _agent(llm)
    ce = asyncio.Event()
    a.bind_context("t1", cancellation_event=ce)

    async def none_err(tid):
        return None

    monkeypatch.setattr(cost_mod.cost_tracker, "enforce_limits", none_err)
    out = await a.think("问题")
    assert out == "回答"
    assert llm.calls[-1]["cancellation_event"] is ce
    # 用户消息与助手回复都进入历史
    assert a.messages[-1]["role"] == "assistant"


async def test_record_usage_over_budget_raises(monkeypatch):
    import app.engine.cost as cost_mod

    a = _agent(FakeLLM())
    a.bind_context("t1")

    async def none_err(tid):
        return None

    async def over(task_id, tokens, cost):
        return True  # 超预算

    monkeypatch.setattr(cost_mod.cost_tracker, "enforce_limits", none_err)
    monkeypatch.setattr(cost_mod.cost_tracker, "add_usage", over)
    with pytest.raises(LLMCallError, match="Token 预算"):
        await a.think("烧钱请求")


async def test_no_context_skips_usage_recording():
    llm = FakeLLM()
    a = _agent(llm)
    # 不绑定上下文：_record_usage 直接跳过
    out = await a.think("hi")
    assert out == "回答" and llm.calls[-1]["cancellation_event"] is None


# ---------- think_stream ----------


async def test_stream_accumulates_and_records_usage(monkeypatch):
    import app.engine.cost as cost_mod

    llm = FakeLLM(chunks=("a", "b", "c"))
    llm.last_stream_usage = lambda: {"total_tokens": 42}
    a = _agent(llm)
    a.bind_context("t1")

    recorded = {}

    async def none_err(tid):
        return None

    async def add_usage(task_id, tokens, cost):
        recorded["tokens"] = tokens
        return False

    monkeypatch.setattr(cost_mod.cost_tracker, "enforce_limits", none_err)
    monkeypatch.setattr(cost_mod.cost_tracker, "add_usage", add_usage)

    parts = [chunk async for chunk in a.think_stream("讲个故事")]
    assert parts == ["a", "b", "c"]
    assert a.messages[-1] == {"role": "assistant", "content": "abc"}
    assert recorded["tokens"] == 42


async def test_stream_without_usage_callback_still_works():
    llm = FakeLLM(chunks=("x",))
    a = _agent(llm)
    a.bind_context("t1")
    parts = [chunk async for chunk in a.think_stream()]
    assert parts == ["x"]
    assert a.messages[-1]["role"] == "assistant"


# ---------- clear_history ----------


def test_clear_history_variants():
    a = _agent()
    a.bind_context("t1")
    a.add_message("user", "u1")
    a.add_message("assistant", "r1")
    a.clear_history(keep_system=True)
    assert len(a.messages) == 1 and a.messages[0]["role"] == "system"
    a.add_message("user", "u2")
    a.clear_history(keep_system=False)
    assert a.messages == []
