"""
工具零件库管理
"""

import json
import uuid
from typing import List, Dict, Any, Optional
from app.core.database import db
from app.core.logger import logger


class PartsLibrary:
    async def add_part(
        self,
        name: str,
        description: str,
        language: str,
        code: str,
        input_schema: Dict[str, Any],
        output_schema: Dict[str, Any],
        tags: List[str],
        created_by: str
    ) -> str:
        part_id = f"part-{uuid.uuid4().hex[:8]}"
        await db.execute(
            """INSERT INTO tool_parts
               (part_id, name, description, language, code,
                input_schema, output_schema, tags, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                part_id, name, description, language, code,
                json.dumps(input_schema), json.dumps(output_schema),
                json.dumps(tags), created_by
            )
        )
        logger.info(f"零件入库: {name} ({part_id})")
        return part_id

    async def search(
        self,
        query: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM tool_parts WHERE 1=1"
        params: List[str] = []

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
                "tags": json.loads(row[7]) if row[7] else [],
                "created_by": row[8]
            })
        return parts

    async def get_part(self, part_id: str) -> Optional[Dict[str, Any]]:
        row = await db.fetch_one(
            "SELECT * FROM tool_parts WHERE part_id = ?",
            (part_id,)
        )
        if not row:
            return None
        return {
            "part_id": row[0],
            "name": row[1],
            "description": row[2],
            "language": row[3],
            "code": row[4],
            "input_schema": json.loads(row[5]) if row[5] else {},
            "output_schema": json.loads(row[6]) if row[6] else {},
            "tags": json.loads(row[7]) if row[7] else [],
            "created_by": row[8]
        }

    async def delete_part(self, part_id: str) -> bool:
        row = await db.fetch_one(
            "SELECT part_id FROM tool_parts WHERE part_id = ?",
            (part_id,)
        )
        if not row:
            return False
        await db.execute(
            "DELETE FROM tool_parts WHERE part_id = ?",
            (part_id,)
        )
        logger.info(f"零件已删除: {part_id}")
        return True


parts_library = PartsLibrary()
