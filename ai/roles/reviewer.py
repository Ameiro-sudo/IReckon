"""
评审 AI
分为效能评审和正确性评审
"""

from typing import Dict, Any
from ai.roles.base_agent import BaseAgent
from ai.capability_pool import AICapability
from workflow.role_registry import register_role


@register_role("reviewer_efficiency", {
    "description": "效能评审AI，审查代码效率、冗余、架构合理性",
    "default_required_tags": ["architecture", "review"],
})
class EfficiencyReviewerAgent(BaseAgent):
    __role_name__ = "reviewer_efficiency"

    def __init__(self, capability: AICapability):
        system_prompt = """你是一位资深架构师，负责审查代码的效率和架构。

审查要点：
1. 时间复杂度与空间复杂度
2. 重复代码、不必要的计算
3. 模块划分与接口设计
4. 设计模式与最佳实践

输出格式：
- 总体评价：通过 / 需修改
- 具体问题列表
- 优化建议
"""
        super().__init__(role="reviewer_efficiency", capability=capability, system_prompt=system_prompt)

    async def review(self, code: str, context: str = "") -> Dict[str, Any]:
        prompt = f"""审查以下代码：

【代码】
{code}

【上下文】
{context}

请输出审查结论。
"""
        response = await self.think(prompt, temperature=0.1)
        passed = "通过" in response and "需修改" not in response
        return {"passed": passed, "feedback": response, "reviewer_type": "efficiency"}

    async def execute(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        task_context = task_data.get("task_context", "")
        code = task_data.get("code", "")
        context = task_data.get("context", "")

        if task_context:
            context = f"{task_context}\n\n{context}" if context else task_context

        return await self.review(code, context)


@register_role("reviewer_correctness", {
    "description": "正确性评审AI，审查逻辑漏洞、边界条件、潜在错误",
    "default_required_tags": ["review", "careful"],
})
class CorrectnessReviewerAgent(BaseAgent):
    __role_name__ = "reviewer_correctness"

    def __init__(self, capability: AICapability):
        system_prompt = """你是一位资深测试工程师，负责审查代码正确性。

审查要点：
1. 逻辑是否符合需求
2. 边界条件处理
3. 异常处理是否完善
4. 潜在安全漏洞
5. 可能的运行时错误

输出格式：
- 总体评价：通过 / 需修改
- 具体问题列表
- 修复建议
"""
        super().__init__(role="reviewer_correctness", capability=capability, system_prompt=system_prompt)

    async def review(self, code: str, requirements: str = "") -> Dict[str, Any]:
        prompt = f"""审查代码正确性：

【需求】
{requirements}

【代码】
{code}

请输出审查结论。
"""
        response = await self.think(prompt, temperature=0.1)
        passed = "通过" in response and "需修改" not in response
        return {"passed": passed, "feedback": response, "reviewer_type": "correctness"}

    async def execute(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        task_context = task_data.get("task_context", "")
        code = task_data.get("code", "")
        requirements = task_data.get("requirements", "")

        if task_context:
            requirements = f"{task_context}\n\n{requirements}" if requirements else task_context

        return await self.review(code, requirements)