"""
工具管理 AI
管理零件库，响应工具组装请求，提供工具模板
"""

from typing import Dict, Any, List, Optional
import json

from ai.roles.base_agent import BaseAgent
from ai.capability_pool import AICapability
from workflow.role_registry import register_role
from core.db import db
from tools.assembler import ToolAssembler
from loguru import logger


@register_role("tool_manager", {
    "description": "工具管理AI，管理零件库，响应工具组装请求",
    "default_required_tags": ["tooling"],
})
class ToolManagerAgent(BaseAgent):
    __role_name__ = "tool_manager"

    def __init__(self, capability: AICapability):
        system_prompt = """你是一个工具库管理员，负责管理和提供可复用的代码零件。

你的能力：
1. 根据需求描述，从零件库中检索合适的代码片段
2. 将多个零件组装成一个临时工具
3. 接收执行 AI 提交的优秀代码，提炼并存入零件库

零件库中的每个零件都有：
- 名称、描述、语言、代码、输入输出规范、标签
"""
        super().__init__(role="tool_manager", capability=capability, system_prompt=system_prompt)

    async def search_parts(self, query: str, tags: Optional[List[str]] = None) -> List[Dict]:
        """搜索零件（数据库查询）"""
        sql = "SELECT * FROM tool_parts WHERE 1=1"
        params = []
        if tags:
            for tag in tags:
                sql += " AND tags LIKE ?"
                params.append(f"%{tag}%")
        if query:
            sql += " AND (name LIKE ? OR description LIKE ?)"
            params.extend([f"%{query}%", f"%{query}%"])
        rows = await db.fetch_all(sql, tuple(params))
        parts = []
        for row in rows:
            parts.append({
                "part_id": row[0],
                "name": row[1],
                "description": row[2],
                "language": row[3],
                "code": row[4],
                "input_schema": json.loads(row[5]) if row[5] else {},
                "output_schema": json.loads(row[6]) if row[6] else {},
                "tags": json.loads(row[7]) if row[7] else []
            })
        return parts

    async def assemble_tool(self, requirement: str, parts: List[Dict]) -> str:
        """使用 LLM 将多个零件组装成工具"""
        parts_desc = "\n".join([f"- {p['name']}: {p['description']}" for p in parts])
        prompt = f"""需求：{requirement}

可用零件：
{parts_desc}

请编写一个完整的工具代码，整合这些零件（或选择最合适的）以满足需求。
"""
        return await self.think(prompt, temperature=0.2)

    async def assemble_tool_simple(self, requirement: str, parts: List[Dict]) -> Optional[str]:
        """尝试用确定性方式组装，失败返回 None"""
        # 分析需求决定组装模式
        if "如果" in requirement or "条件" in requirement or "分支" in requirement:
            if len(parts) >= 3:
                return ToolAssembler.assemble_condition(parts[0], parts[1], parts[2])
        elif "循环" in requirement or "重复" in requirement or "500次" in requirement:
            if len(parts) >= 1:
                return ToolAssembler.assemble_loop(parts[0])
        elif len(parts) >= 1:
            # 默认顺序组合
            return ToolAssembler.assemble_sequence(parts)
        return None

    async def add_part(self, name: str, description: str, language: str, code: str,
                       input_schema: Dict, output_schema: Dict, tags: List[str],
                       created_by: str) -> str:
        """添加新零件到库"""
        import uuid
        part_id = f"part-{uuid.uuid4().hex[:8]}"
        await db.execute("""
            INSERT INTO tool_parts
            (part_id, name, description, language, code, input_schema, output_schema, tags, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            part_id, name, description, language, code,
            json.dumps(input_schema), json.dumps(output_schema),
            json.dumps(tags), created_by
        ))
        logger.info(f"零件入库: {name} ({part_id})")
        return part_id

    async def execute(self, request: Dict[str, Any]) -> Dict[str, Any]:
        action = request.get("action", "search")
        if action == "search":
            parts = await self.search_parts(request.get("query", ""), request.get("tags"))
            return {"parts": parts}
        elif action == "assemble":
            parts = request.get("parts", [])
            requirement = request.get("requirement", "")
            # 优先确定性组装
            simple_code = await self.assemble_tool_simple(requirement, parts)
            if simple_code:
                logger.info("使用确定性组装成功")
                return {"code": simple_code, "method": "deterministic"}
            # 回退到 LLM 组装
            logger.info("确定性组装无法匹配，使用 LLM 组装")
            code = await self.assemble_tool(requirement, parts)
            return {"code": code, "method": "llm"}
        return {"error": "unknown action"}