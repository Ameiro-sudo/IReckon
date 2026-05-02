"""
自定义角色：内容过滤 AI
"""

from ai.roles.base_agent import BaseAgent
from ai.capability_pool import AICapability
from workflow.role_registry import register_role


@register_role("content_filter", {
    "description": "内容过滤AI，检查敏感信息",
    "default_required_tags": ["security"],
})
class ContentFilterAgent(BaseAgent):
    __role_name__ = "content_filter"

    def __init__(self, capability: AICapability):
        system_prompt = """你是内容安全审查员，检查文本中是否包含：
- API密钥、密码
- 个人隐私
- 攻击性内容

输出 JSON：{"passed": true/false, "reason": "..."}
"""
        super().__init__(role="content_filter", capability=capability, system_prompt=system_prompt)

    async def filter(self, content: str, context: str = "") -> dict:
        prompt = f"""审查以下内容：
【上下文】{context}
【内容】
{content}

输出 JSON。
"""
        response = await self.think(prompt, temperature=0.0)
        import json
        try:
            return json.loads(response)
        except:
            return {"passed": False, "reason": "审查失败"}

    async def execute(self, data: dict) -> dict:
        return await self.filter(data.get("content", ""), data.get("context", ""))