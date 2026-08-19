"""LLM 客户端测试:mock litellm 验证重试、故障转移、健康状态、取消。"""

import asyncio
from types import SimpleNamespace

import pytest

import app.llm.client as client_mod
from app.llm.client import LLMClient, LLMCallError, StopReason
from conftest import make_cap


def fake_response(content="hi", finish="stop"):
    return SimpleNamespace(
        model="fake-model",
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish)
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


def _timeout():
    return client_mod.litellm.exceptions.Timeout("boom", model="m", llm_provider="openai")


def _api_error():
    return client_mod.litellm.exceptions.APIError(
        status_code=500, message="down", llm_provider="openai", model="m"
    )


def test_ensure_model_prefix():
    c = LLMClient()
    cap = make_cap()
    assert c._ensure_model_prefix(cap, "auto") == "openai/auto"
    assert c._ensure_model_prefix(cap, "openai/auto") == "openai/auto"


async def test_call_success_non_stream(client, monkeypatch):
    async def fake_acompletion(**kw):
        return fake_response(content="hello world")

    monkeypatch.setattr(client_mod, "acompletion", fake_acompletion)
    res = await client.call(make_cap(), [{"role": "user", "content": "x"}])
    assert res.content == "hello world"
    assert res.stop_reason == StopReason.SUCCESS
    assert res.usage["total_tokens"] == 2


async def test_call_retries_then_success(client, monkeypatch):
    calls = {"n": 0}

    async def flaky_acompletion(**kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _timeout()
        return fake_response(content="recovered")

    monkeypatch.setattr(client_mod, "acompletion", flaky_acompletion)
    res = await client.call(make_cap(), [{"role": "user", "content": "x"}])
    assert res.content == "recovered"
    assert res.retry_count == 2


async def test_call_fails_after_max_retries(client, monkeypatch):
    async def always_fail(**kw):
        raise _timeout()

    monkeypatch.setattr(client_mod, "acompletion", always_fail)
    with pytest.raises(LLMCallError):
        await client.call(make_cap(), [{"role": "user", "content": "x"}])
    # 健康状态按 capability.id 记录
    assert client.health.failures["t1"] >= 1


async def test_fallback_to_secondary(client, monkeypatch):
    cap1 = make_cap(id="p", endpoint="http://e1/v1")
    cap2 = make_cap(id="s", endpoint="http://e2/v1")

    async def fake_acompletion(**kw):
        if kw["api_base"] == "http://e2/v1":
            return fake_response(content="from fallback")
        raise _api_error()

    monkeypatch.setattr(client_mod, "acompletion", fake_acompletion)
    res = await client.call(
        cap1, [{"role": "user", "content": "x"}], fallback_capabilities=[cap2]
    )
    assert res.content == "from fallback"
    assert res.stop_reason == StopReason.FALLBACK


async def test_cancellation_raises(client, monkeypatch):
    async def never_called(**kw):
        return fake_response()

    monkeypatch.setattr(client_mod, "acompletion", never_called)
    evt = asyncio.Event()
    evt.set()
    with pytest.raises(LLMCallError):
        await client.call(make_cap(), [{"role": "user", "content": "x"}], cancellation_event=evt)


async def test_unhealthy_endpoint_skipped(client, monkeypatch):
    cap1 = make_cap(id="p", endpoint="http://e1/v1")
    cap2 = make_cap(id="s", endpoint="http://e2/v1")
    # 健康状态按 capability.id 记录；连续 3 次失败进入冷却
    for _ in range(3):
        await client.health.record_failure("p")

    seen = []

    async def fake_acompletion(**kw):
        seen.append(kw["api_base"])
        if kw["api_base"] == "http://e2/v1":
            return fake_response(content="ok from healthy")
        raise _api_error()

    monkeypatch.setattr(client_mod, "acompletion", fake_acompletion)
    res = await client.call(
        cap1, [{"role": "user", "content": "x"}], fallback_capabilities=[cap2]
    )
    assert "ok from healthy" in res.content
    assert "http://e1/v1" not in seen