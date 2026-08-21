"""计费通道路由 + 响应缓存测试。

覆盖：
- ResponseCache：命中/未命中/TTL 过期/容量淘汰/统计
- 通道路由：light→执行通道、heavy→主通道、无执行实例时回退与关闭回退
- ask()：缓存命中不产生新调用（调用次数套利的核心断言）
"""

import asyncio

import pytest

from conftest import make_cap


# ---------- ResponseCache ----------


async def _make_cache(**overrides):
    from app.llm.cache import ResponseCache

    c = ResponseCache()
    c.enabled = overrides.get("enabled", True)
    c.ttl = overrides.get("ttl", 3600)
    c.max_entries = overrides.get("max_entries", 512)
    return c


async def test_cache_hit_and_miss():
    c = await _make_cache()
    key = c.make_key("m1", [{"role": "user", "content": "hi"}], 0.0, None)
    assert await c.get(key) is None
    assert c.misses == 1

    await c.set(key, {"content": "hello"})
    got = await c.get(key)
    assert got == {"content": "hello"}
    assert c.hits == 1
    assert c.stats()["saved_calls"] == 1


async def test_cache_ttl_expiry():
    c = await _make_cache(ttl=0.01)
    key = c.make_key("m1", [{"role": "user", "content": "hi"}])
    await c.set(key, "v")
    await asyncio.sleep(0.02)
    assert await c.get(key) is None
    assert c.evictions == 1


async def test_cache_max_entries_eviction():
    c = await _make_cache(max_entries=2)
    for i in range(3):
        k = c.make_key(f"m{i}", [{"role": "user", "content": f"p{i}"}])
        await c.set(k, f"v{i}")
        await asyncio.sleep(0.001)  # 保证时间戳可区分
    assert len(c._store) == 2
    # 最旧的 v0 被淘汰
    k0 = c.make_key("m0", [{"role": "user", "content": "p0"}])
    assert await c.get(k0) is None


async def test_cache_disabled():
    c = await _make_cache(enabled=False)
    key = c.make_key("m1", [])
    await c.set(key, "v")
    assert await c.get(key) is None
    assert c.stats()["entries"] == 0


# ---------- 通道路由 ----------


async def _reset_pool(session_db, *caps):
    """清空实例表后写入指定实例，强制刷新池（单例有 60s 刷新间隔，必须 force）。"""
    from app.llm.pool import capability_pool

    await session_db.execute("DELETE FROM ai_instances")
    for c in caps:
        await capability_pool.add_instance(c)
    await capability_pool.refresh(force=True)


async def test_channel_of():
    from app.llm.router import channel_of

    assert channel_of(make_cap(id="a", tags=["python"])) == "primary"
    assert channel_of(make_cap(id="b", tags=["channel:execution"])) == "execution"


async def test_acquire_light_prefers_execution_channel(session_db):
    from app.llm.router import acquire

    primary = make_cap(id="p1", tags=["code"], cost_per_1k_tokens=0.0)
    executor = make_cap(
        id="e1", tags=["code", "channel:execution"], cost_per_1k_tokens=0.28
    )
    await _reset_pool(session_db, primary, executor)

    cap = await acquire("light")
    assert cap is not None and cap.id == "e1"
    cap = await acquire("heavy")
    assert cap is not None and cap.id == "p1"


async def test_acquire_execution_fallback(session_db, monkeypatch):
    import app.llm.router as router

    primary = make_cap(id="p1", tags=["code"])
    await _reset_pool(session_db, primary)

    # 默认允许回退 → 回到主通道实例
    cap = await router.acquire("light")
    assert cap is not None and cap.id == "p1"

    # 关闭回退 → 返回 None（宁可失败也不烧按次调用）
    monkeypatch.setattr(
        router,
        "get",
        lambda key, default=None: (
            False if key == "ai_pool.routing.execution_fallback_to_primary" else default
        ),
    )
    assert await router.acquire("light") is None


# ---------- ask()：缓存命中不产生新调用 ----------


class _FakeResp:
    def __init__(self, content="ok"):
        from app.llm.client import StopReason

        self.content = content
        self.model = "fake-model"
        self.usage = {"total_tokens": 7}
        self.finish_reason = "stop"
        self.stop_reason = StopReason.SUCCESS


async def test_ask_caches_and_routes(session_db, monkeypatch):
    from app.llm.cache import response_cache
    from app.llm.client import llm_client
    from app.llm.router import ask

    primary = make_cap(id="p1", tags=["review"])
    executor = make_cap(id="e1", tags=["code", "channel:execution"])
    await _reset_pool(session_db, primary, executor)

    calls = {"n": 0}

    async def fake_call(cap, messages, **kwargs):
        calls["n"] += 1
        calls["cap_id"] = cap.id
        return _FakeResp(f"resp-{calls['n']}")

    monkeypatch.setattr(llm_client, "call", fake_call)

    r1 = await ask("总结这段话", tier="light")
    assert r1["cached"] is False and r1["instance_id"] == "e1"
    assert r1["channel"] == "execution"

    r2 = await ask("总结这段话", tier="light")
    assert r2["cached"] is True and r2["content"] == "resp-1"
    assert calls["n"] == 1, "缓存命中不应产生第二次真实调用"

    # 不同 tier 不共享缓存键（模型不同）
    r3 = await ask("总结这段话", tier="heavy")
    assert r3["cached"] is False and r3["instance_id"] == "p1"
    assert calls["n"] == 2

    response_cache._store.clear()


async def test_ask_no_instance_raises(monkeypatch):
    """执行通道为空且关闭回退时，ask 应直接报错而非烧按次调用。

    注意不能靠清空实例表构造"空池"——refresh 会从 config.yaml 重新播种，
    这里直接 mock find_best_match 返回 None，并确保全程无真实网络调用。
    """
    import app.llm.router as router
    from app.llm.pool import capability_pool
    from app.llm.router import ask

    async def no_match(*a, **kw):
        return None

    monkeypatch.setattr(capability_pool, "find_best_match", no_match)
    monkeypatch.setattr(
        router,
        "get",
        lambda key, default=None: (
            False if key == "ai_pool.routing.execution_fallback_to_primary" else default
        ),
    )
    with pytest.raises(RuntimeError, match="无可用 AI 实例"):
        await ask("hi", tier="light")


# ---------- 审查员通道路由（判断点走主通道） ----------


async def test_reviewer_routing_uses_heavy_channel(monkeypatch):
    """招募计划未指定审查实例时，应通过通道路由取主通道（重模型）而非复用执行者实例。"""
    import app.agents  # noqa: F401  # 触发角色注册
    import app.llm.router as router
    from app.engine.machine import WorkflowEngine

    heavy = make_cap(id="p1", tags=["review"])
    executor_cap = make_cap(id="e1", tags=["code", "channel:execution"])

    async def fake_acquire(tier="light", **kw):
        return heavy if tier == "heavy" else None

    monkeypatch.setattr(router, "acquire", fake_acquire)
    eng = WorkflowEngine()
    s = {"task_id": "t-review-1", "team": {"executor": [executor_cap]}}
    reviewers = await eng._create_reviewers(s)
    assert len(reviewers) == 2
    assert all(rv.capability.id == "p1" for rv in reviewers)


async def test_reviewer_fallback_to_executor_when_no_primary(monkeypatch):
    """主通道无可用实例时降级复用执行者实例（宁可轻模型也不停摆）。"""
    import app.agents  # noqa: F401
    import app.llm.router as router
    from app.engine.machine import WorkflowEngine

    executor_cap = make_cap(id="e1", tags=["code", "channel:execution"])

    async def fake_acquire(tier="light", **kw):
        return None

    monkeypatch.setattr(router, "acquire", fake_acquire)
    eng = WorkflowEngine()
    s = {"task_id": "t-review-2", "team": {"executor": [executor_cap]}}
    reviewers = await eng._create_reviewers(s)
    assert len(reviewers) == 2
    assert all(rv.capability.id == "e1" for rv in reviewers)


# ---------- MCP Server ----------


async def test_mcp_tools_without_transport(session_db, monkeypatch):
    """工具纯函数可直接调用；已安装 mcp 包时 server 可构建。"""
    import app.mcp_server as srv

    primary = make_cap(id="p1", tags=["review"])
    executor = make_cap(id="e1", tags=["code", "channel:execution"])
    await _reset_pool(session_db, primary, executor)

    status = await srv.tool_pool_status()
    ids = {i["id"]: i["channel"] for i in status["instances"]}
    assert ids.get("e1") == "execution" and ids.get("p1") == "primary"

    try:
        import mcp  # noqa: F401
    except ImportError:
        pytest.skip("未安装 mcp 包，跳过传输层构建测试")

    server = srv.build_server()
    assert server is not None
