from typing import Dict, Any, List, Optional
from .base import BaseAgent
from app.llm.pool import AICapability
from app.engine.registry import register_role
from app.knowledge.files import FileKnowledgeBase
from app.tools.library import parts_library


@register_role("learner", {
    "description": "学习AI，抓取高星项目，提炼模式，生成工具",
    "default_required_tags": ["learning", "cheap"],
})
class LearnerAgent(BaseAgent):
    __role_name__ = "learner"

    def __init__(self, capability: AICapability):
        system_prompt = """你是一位技术学习者，负责从 GitHub 高星项目中提取设计模式和可复用代码。

任务：
1. 阅读提供的项目摘要或代码片段
2. 提炼出跨语言的优化模式和最佳实践
3. 若发现通用功能，生成一个独立的可复用工具零件（包含代码和说明）

输出格式：
- 学习要点：简短的要点列表
- 提炼的模式：名称 + 描述 + 代码示例
- 工具零件：名称 + 语言 + 完整代码
"""
        super().__init__(role="learner", capability=capability, system_prompt=system_prompt)
        self.kb = FileKnowledgeBase()

    async def learn_from_source(self, url: str, content: str) -> Dict[str, Any]:
        prompt = f"""分析以下开源项目内容：
URL: {url}
内容摘要：
{content[:5000]}

请输出：
1. 学习要点总结（2-3 条）
2. 如果发现有价值的可复用工具，给出工具的名称、描述、语言和代码。
"""
        response = await self.think(prompt, temperature=0.4)
        return {
            "summary": response,
            "source": url,
            "tool_suggestions": self._extract_tool_suggestions(response)
        }

    def _extract_tool_suggestions(self, response: str) -> List[Dict[str, str]]:
        suggestions = []
        lines = response.split('\n')
        current = {}
        in_code = False
        code_lines = []
        for line in lines:
            if line.startswith('工具名称：') or line.startswith('名称：'):
                if current:
                    if code_lines:
                        current['code'] = '\n'.join(code_lines)
                    suggestions.append(current)
                current = {'name': line.split('：', 1)[1].strip()}
                in_code = False
                code_lines = []
            elif line.startswith('描述：'):
                if current is not None:
                    current['description'] = line.split('：', 1)[1].strip()
            elif line.startswith('语言：'):
                if current is not None:
                    current['language'] = line.split('：', 1)[1].strip()
            elif '```' in line and not in_code:
                in_code = True
                code_lines = []
            elif '```' in line and in_code:
                in_code = False
                if current is not None:
                    current['code'] = '\n'.join(code_lines)
                code_lines = []
            elif in_code:
                code_lines.append(line)
        if current:
            if code_lines and 'code' not in current:
                current['code'] = '\n'.join(code_lines)
            suggestions.append(current)
        return suggestions

    async def save_pattern(self, title: str, content: str, source: str) -> str:
        return await self.kb.add_entry(
            entry_type="patterns",
            title=title,
            content=content,
            source=source
        )

    async def extract_tool(
        self,
        name: str,
        description: str,
        language: str,
        code: str,
        tags: List[str]
    ) -> str:
        return await parts_library.add_part(
            name=name,
            description=description,
            language=language,
            code=code,
            input_schema={},
            output_schema={},
            tags=tags,
            created_by="learner"
        )

    async def execute(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        action = task_data.get("action", "learn")
        if action == "learn":
            result = await self.learn_from_source(
                task_data.get("url", ""),
                task_data.get("content", "")
            )
            if result.get("tool_suggestions"):
                for tool in result["tool_suggestions"]:
                    if tool.get("name") and tool.get("code"):
                        await self.extract_tool(
                            name=tool.get("name", ""),
                            description=tool.get("description", ""),
                            language=tool.get("language", "python"),
                            code=tool.get("code", ""),
                            tags=["auto-generated", "learned"]
                        )
            await self.save_pattern(
                title=f"学习笔记: {task_data.get('url', '')[:50]}",
                content=result.get("summary", ""),
                source=task_data.get("url", "")
            )
            return result
        return {"status": "unknown action", "action": action}