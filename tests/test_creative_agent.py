"""CreativeAgent 补测：suggest 提示词围栏与温度、execute 分派与默认值、角色注册。"""

from conftest import make_cap

from app.agents.creative import CreativeAgent
from app.engine.registry import role_registry


def _agent_with_think(captured):
    agent = CreativeAgent(make_cap())

    async def fake_think(prompt, temperature=None):
        captured.update(prompt=prompt, temperature=temperature)
        return "# 建议正文"

    agent.think = fake_think
    return agent


async def test_suggest_wraps_inputs_in_untrusted_data():
    captured = {}
    agent = _agent_with_think(captured)
    out = await agent.suggest("<script>项目A</script>", "已有登录页")
    assert out == "# 建议正文"
    p = captured["prompt"]
    assert "<untrusted_data>\n<script>项目A</script>\n</untrusted_data>" in p
    assert "<untrusted_data>\n已有登录页\n</untrusted_data>" in p
    assert p.count("<untrusted_data>") == 2
    assert "2-3 个惊喜功能" in p


async def test_suggest_passes_creative_temperature():
    captured = {}
    agent = _agent_with_think(captured)
    await agent.suggest("P", "C")
    assert captured["temperature"] == 0.7


async def test_execute_returns_suggestion_payload():
    captured = {}
    agent = _agent_with_think(captured)
    r = await agent.execute({"project_description": "P", "current_state": "C"})
    assert r == {"suggestion": "# 建议正文"}
    assert "P" in captured["prompt"] and "C" in captured["prompt"]


async def test_execute_defaults_missing_context_to_empty():
    captured = {}
    agent = _agent_with_think(captured)
    r = await agent.execute({})
    assert r == {"suggestion": "# 建议正文"}
    # 缺省字段以空串注入，不抛 KeyError
    assert captured["prompt"].count("<untrusted_data>") == 2


def test_creative_role_registered():
    assert role_registry.get_agent_class("creative") is CreativeAgent
