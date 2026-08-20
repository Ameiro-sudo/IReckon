import json
import re
from pathlib import Path
from typing import List, Dict, Optional
import aiofiles
from app.core.database import db
from app.core.logger import logger
from .vector import vector_store

from app.core.config import get

_ENTRY_TYPE_RE = re.compile(r"^[a-z_][a-z0-9_]{0,31}$")
_MAX_CONTENT_BYTES = 2 * 1024 * 1024


def _validate_entry_type(entry_type: str) -> str:
    if not entry_type or not _ENTRY_TYPE_RE.match(entry_type):
        raise ValueError(f"非法知识类型: {entry_type!r}")
    return entry_type


class FileKnowledgeBase:
    def __init__(self):
        data_dir = Path(get("system.data_dir", "./data"))
        self.base_dir = (data_dir / "knowledge_base").resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def add_entry(
        self,
        entry_type: str,
        title: str,
        content: str,
        source: str = "",
        tags: Optional[List[str]] = None,
    ):
        import uuid

        entry_type = _validate_entry_type(entry_type)
        if len(content.encode("utf-8")) > _MAX_CONTENT_BYTES:
            raise ValueError("知识条目内容超过 2MB 限制")

        entry_id = uuid.uuid4().hex
        target = (self.base_dir / entry_type / f"{entry_id}.txt").resolve()
        if target.parent != (self.base_dir / entry_type).resolve():
            raise ValueError("知识条目路径非法")
        target.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(target, "w", encoding="utf-8") as f:
            await f.write(content)

        await db.execute(
            "INSERT INTO knowledge_entries (entry_id, type, title, content, source) VALUES (?,?,?,?,?)",
            (entry_id, entry_type, title, content, source),
        )

        await vector_store.add_documents(
            collection=f"kb_{entry_type}",
            ids=[entry_id],
            documents=[content],
            metadatas=[
                {"title": title, "source": source, "tags": json.dumps(tags or [])}
            ],
        )
        logger.info(f"知识条目添加成功: {title}")
        return entry_id

    async def search(
        self, query: str, entry_type: Optional[str] = None, n_results: int = 5
    ) -> List[Dict]:
        if entry_type:
            _validate_entry_type(entry_type)
        collection = f"kb_{entry_type}" if entry_type else "kb_patterns"
        return await vector_store.search(collection, query, n_results)
