"""
创意 AI
"""

from typing import Dict, Any
from ai.roles.base_agent import BaseAgent
from ai.capability_pool import AICapability
from workflow.role_registry import register_role


@register_role("creative", {
    "description": "创意AI，提供惊喜功能、交互设计、补全设计留白",
    "default_required_tags": ["creative", "design"],
})
class CreativeAgent(BaseAgent):
    __role_name__ = "creative"

    def __init__(self, capability: AICapability):
        system_prompt = """你是一位创意设计师，负责为项目增添惊喜功能和人性化设计。

职责：
1. 提出令人愉悦的小特性
2. 补全设计留白
3. 交互细节优化建议

注意：不改变核心功能。
"""
        super().__init__(role="creative", capability=capability, system_prompt=system_prompt)

    async def suggest(self, project_description: str, current_state: str) -> str:
        prompt = f"""项目：{project_description}
当前状态：{current_state}

请提出 2-3 个惊喜功能或交互优化建议。
"""
        return await self.think(prompt, temperature=0.7)

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        suggestion = await self.suggest(
            context.get("project_description", ""),
            context.get("current_state", "")
        )
        return {"suggestion": suggestion}