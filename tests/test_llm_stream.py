"""LLM 客户端流式路径与基础设施补测。

既有 test_llm.py 覆盖非流式主干；本文件专攻覆盖率薄弱区：
_call_stream 全分支（成功/用量/中断/重试/降级/取消）、_record/_last_stream_usage、
EndpointHealth 半开探测、_RateLimiter、_truncate、_interruptible_sleep、
_ensure_http_client 幂等与异常路径。
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import app.llm.client as client_mod
from app.llm.client import (
    EndpointHealth,
    LLMCallError,
    LLMClient,
    _truncate,
    _interruptible_sleep,
)


def make_chunk(content=None, usage=None, empty_choices=False):
    if empty_choices:
        return SimpleNamespace(choices=[], usage=usage)
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))],
        usage=usage,
    )


def make_stream(script):
    """script: [("chunk", ns) | ("raise", exc), ...] —— 按序回放的异步流。"""

    class _S:
        async def aclose(self):
            pass

        def __aiter__(self):
            return self

        async def __anext__(self):
            while script:
                kind, payload = script.pop(0)
                if kind == "raise":
                    raise payload
                return payload
            raise StopAsyncIteration

    return _S()


def fake_response(content="nr-fallback"):
    return SimpleNamespace(
        model="fake-model",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content), finish_reason="stop"
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )


@pytest.fixture
def client():
    c = LLMClient()
    c.default_retry = {
        "max_retries": 3,
        "base_delay": 0.01,
        "max_delay": 0.05,
        "exponential_base": 2,
    }
    return c


def _timeout_exc():
    return client_mod.litellm.exceptions.Timeout(
        "boom", model="m", llm_provider="openai"
    )


async def collect(gen):
    outs = []
    async for piece in gen:
        outs.append(piece)
    return outs


# ---------- 流式成功与用量 ----------


async def test_stream_success_joins_pieces_and_records_usage(client, monkeypatch):
    calls = []

    async def fake_acompletion(**kw):
        calls.append(kw)
        return make_stream(
            [
                ("chunk", make_chunk("你")),
                ("chunk", make_chunk("好")),
                # 空 choices 的 usage-only 尾块（litellm 常见形态）
                (
                    "chunk",
                    make_chunk(
                        empty_choices=True,
                        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=7),
                    ),
                ),
            ]
        )

    monkeypatch.setattr(client_mod, "acompletion", fake_acompletion)
    cap = SimpleNamespace(
        id="c1", endpoint=None, model="m", api_key=None, parameters={}
    )
    gen = await client.call(
        cap, [{"role": "user", "content": "x"}], stream=True, usage_key="k1"
    )
    outs = await collect(gen)
    assert "".join(outs) == "你好"
    assert client.last_stream_usage("k1") == {
        "prompt_tokens": 5,
        "completion_tokens": 7,
        "total_tokens": 12,
    }
    # 流式标记进入请求参数
    assert calls[0]["stream"] is True


async def test_stream_without_usage_key_records_nothing(client, monkeypatch):
    async def fake_acompletion(**kw):
        return make_stream(
            [
                (
                    "chunk",
                    make_chunk(
                        "a", usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1)
                    ),
                )
            ]
        )

    monkeypatch.setattr(client_mod, "acompletion", fake_acompletion)
    cap = SimpleNamespace(
        id="c1", endpoint=None, model="m", api_key=None, parameters={}
    )
    outs = await collect(await client.call(cap, [], stream=True))
    assert outs == ["a"]
    assert client.last_stream_usage() == {}


async def test_last_stream_usage_isolation_and_copy_semantics(client):
    client._stream_usages["k"] = {
        "prompt_tokens": 1,
        "completion_tokens": 2,
        "total_tokens": 3,
    }
    client._last_stream_usage_key = "k"
    got = client.last_stream_usage()
    got["prompt_tokens"] = 999
    # 返回的是副本，内部状态不被外部改动
    assert client._stream_usages["k"]["prompt_tokens"] == 1
    assert client.last_stream_usage("missing") == {}
    assert client.last_stream_usage() == {
        "prompt_tokens": 1,
        "completion_tokens": 2,
        "total_tokens": 3,
    }


async def test_stream_usage_cap_evicts_oldest(client):
    client._max_stream_usages = 2
    u = SimpleNamespace(prompt_tokens=1, completion_tokens=0)
    for key in ("k1", "k2", "k3"):
        client._record_stream_usage(make_chunk(usage=u), key)
    assert set(client._stream_usages) == {"k2", "k3"}
    assert client._last_stream_usage_key == "k3"


async def test_record_stream_usage_ignores_zero_and_none(client):
    client._max_stream_usages = 10
    client._record_stream_usage(make_chunk(usage=None), "k")
    client._record_stream_usage(
        make_chunk(usage=SimpleNamespace(prompt_tokens=None, completion_tokens=None)),
        "k",
    )
    assert client._stream_usages == {}


# ---------- 流式中断 / 重试 / 降级 / 取消 ----------


async def test_midstream_failure_after_yield_no_retry(client, monkeypatch):
    calls = []

    async def fake_acompletion(**kw):
        calls.append(kw)
        return make_stream(
            [
                ("chunk", make_chunk("partial")),
                ("raise", RuntimeError("connection lost")),
            ]
        )

    monkeypatch.setattr(client_mod, "acompletion", fake_acompletion)
    cap = SimpleNamespace(
        id="c1", endpoint=None, model="m", api_key=None, parameters={}
    )
    with pytest.raises(LLMCallError, match="流式输出中断"):
        await collect(await client.call(cap, [], stream=True, usage_key="k"))
    # 已产出内容不重试不降级：只调用一次
    assert len(calls) == 1
    assert client.last_stream_usage("k") == {}


async def test_preyield_retryable_failure_retries_then_streams(client, monkeypatch):
    calls = {"n": 0}

    async def fake_acompletion(**kw):
        calls["n"] += 1
        if calls["n"] < 2:
            return make_stream([("raise", _timeout_exc())])
        return make_stream([("chunk", make_chunk("recovered"))])

    monkeypatch.setattr(client_mod, "acompletion", fake_acompletion)
    cap = SimpleNamespace(
        id="c1", endpoint=None, model="m", api_key=None, parameters={}
    )
    outs = await collect(await client.call(cap, [], stream=True))
    assert outs == ["recovered"]
    assert calls["n"] == 2


async def test_nonretryable_degrades_to_non_stream(client, monkeypatch):
    class NotRetryable(ValueError):
        pass

    async def fake_acompletion(**kw):
        if kw.get("stream"):
            return make_stream([("raise", NotRetryable("bad request shape"))])
        return fake_response(content="nr-fallback")

    monkeypatch.setattr(client_mod, "acompletion", fake_acompletion)
    cap = SimpleNamespace(
        id="c1", endpoint=None, model="m", api_key=None, parameters={}
    )
    outs = await collect(await client.call(cap, [], stream=True))
    # 回归：降级调用曾因 fallback_capabilities/fallback_caps 形参名不匹配
    # 恒抛 TypeError 被宽 except 吞掉——流式降级从未真正工作过
    assert outs == ["nr-fallback"]


async def test_stream_and_fallback_both_fail_raises_combined(client, monkeypatch):
    async def fake_acompletion(**kw):
        if kw.get("stream"):
            return make_stream([("raise", ValueError("unrecoverable"))])
        raise RuntimeError("fallback host down")

    monkeypatch.setattr(client_mod, "acompletion", fake_acompletion)
    cap = SimpleNamespace(
        id="c1", endpoint=None, model="m", api_key=None, parameters={}
    )
    with pytest.raises(LLMCallError, match="流式及回退均失败"):
        await collect(await client.call(cap, [], stream=True))


async def test_cancel_before_stream_returns_quietly(client, monkeypatch):
    async def never(*kw):
        raise AssertionError("取消态不得发起调用")

    monkeypatch.setattr(client_mod, "acompletion", never)
    evt = asyncio.Event()
    evt.set()
    cap = SimpleNamespace(
        id="c1", endpoint=None, model="m", api_key=None, parameters={}
    )
    outs = await collect(
        await client.call(cap, [], stream=True, cancellation_event=evt)
    )
    assert outs == []


async def test_infinite_retry_lifts_stream_retry_ceiling(client, monkeypatch):
    calls = {"n": 0}
    sleeps = {"total": 0.0}

    async def fake_acompletion(**kw):
        calls["n"] += 1
        if kw.get("stream"):
            return make_stream([("raise", _timeout_exc())])
        return fake_response(content="nr-fallback")

    async def instant_sleep(duration, cancel_event):
        sleeps["total"] += duration

    monkeypatch.setattr(client_mod, "acompletion", fake_acompletion)
    monkeypatch.setattr(client_mod, "_interruptible_sleep", instant_sleep)
    cap = SimpleNamespace(
        id="c1", endpoint=None, model="m", api_key=None, parameters={}
    )
    # infinite_retry 把流式上限抬到 max(default=3, 50)=50：
    # 51 次流式尝试耗尽后才降级 + 1 次非流式 = 52 次调用
    outs = await collect(await client.call(cap, [], stream=True, infinite_retry=True))
    assert outs == ["nr-fallback"]
    assert calls["n"] == 52
    # 指数退避封顶在 10s（真实语义），桩只累计不等待
    assert sleeps["total"] > 100


# ---------- EndpointHealth 半开探测 ----------


async def test_health_half_open_probe_after_cooldown():
    h = EndpointHealth(max_failures=2, cooldown_seconds=30)
    for _ in range(2):
        await h.record_failure("ep")
    assert await h.is_available("ep") is False
    # 冷却期结束 → 半开放行一次，且放行后冷却记录被清除
    h.cooldown_until["ep"] = __import__("time").time() - 1
    assert await h.is_available("ep") is True
    assert "ep" not in h.cooldown_until
    await h.record_success("ep")
    assert h.failures["ep"] == 0


# ---------- 基础设施 ----------


def test_truncate_edges():
    assert _truncate(None) == ""
    assert _truncate("short") == "short"
    long = "x" * 500
    out = _truncate(long, limit=100)
    assert out.startswith("x" * 100)
    assert "[+400 chars]" in out
    assert "\n" not in _truncate("a\nb")


async def test_interruptible_sleep_cancel_raises():
    evt = asyncio.Event()
    evt.set()
    with pytest.raises(LLMCallError, match="用户取消"):
        await _interruptible_sleep(5, evt)


async def test_interruptible_sleep_passes_on_timeout():
    # 无事件 → 直接睡眠；有事件但未触发 → 等满时长后静默通过
    await _interruptible_sleep(0.01, None)
    evt = asyncio.Event()
    await _interruptible_sleep(0.01, evt)


async def test_ensure_http_client_idempotent_and_failure_tolerant(monkeypatch):
    constructions = {"n": 0}

    class FakeAsyncClient:
        def __init__(self, **kw):
            constructions["n"] += 1

    SimpleNamespace(
        AsyncClient=FakeAsyncClient,
        Limits=lambda **kw: None,
        Timeout=lambda *a, **kw: None,
    )
    monkeypatch.setattr(client_mod.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(client_mod.httpx, "Limits", lambda **kw: None, raising=False)
    monkeypatch.setattr(
        client_mod.httpx, "Timeout", lambda *a, **kw: None, raising=False
    )
    lm = SimpleNamespace(_async_client=None)

    import app.llm.client as cm

    monkeypatch.setattr(cm, "_get_litellm", lambda: lm)
    c = LLMClient()
    await c._ensure_http_client()
    n_first = constructions["n"]
    await c._ensure_http_client()  # 第二次必须幂等
    assert constructions["n"] == n_first == 1
    assert c._http_configured is True

    # 异常路径：构造失败也要落 configured 标记，避免每次调用反复重试
    def boom(**kw):
        raise RuntimeError("no http2")

    monkeypatch.setattr(client_mod.httpx, "AsyncClient", boom)
    c2 = LLMClient()
    await c2._ensure_http_client()
    assert c2._http_configured is True
