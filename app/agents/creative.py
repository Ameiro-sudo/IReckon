from typing import Dict, Any
from .base import BaseAgent
from app.llm.pool import AICapability
from app.engine.registry import register_role


@register_role(
    "creative",
    {
        "description": "创意AI，提供惊喜功能、交互设计、补全设计留白",
        "default_required_tags": ["creative", "design"],
    },
)
class CreativeAgent(BaseAgent):
    __role_name__ = "creative"

    def __init__(self, capability: AICapability):
        system_prompt = """你是一位创意设计师，为项目增添令人愉悦的小特性与人性化细节，但不改变核心功能。

【职责】
1. 提出 2~3 个低成本、高感知的惊喜特性或交互优化。
2. 补全设计留白：边界场景、空状态、错误提示、加载反馈。
3. 每条建议给出实现思路与成本，便于执行者直接落地。

【输出格式】
每条建议按如下结构：
1. 特性名称
   - 解决的问题
   - 实现思路
   - 成本评估（低/中/高）

【边界】
- 不改变核心功能与既有接口。
- 不提出需要新增第三方服务的建议，除非需求明确允许。
"""
        super().__init__(
            role="creative", capability=capability, system_prompt=system_prompt
        )

    async def suggest(self, project_description: str, current_state: str) -> str:
        prompt = f"""项目：{project_description}
当前状态：{current_state}

请提出 2-3 个惊喜功能或交互优化建议。
"""
        return await self.think(prompt, temperature=0.7)

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        suggestion = await self.suggest(
            context.get("project_description", ""), context.get("current_state", "")
        )
        return {"suggestion": suggestion}
