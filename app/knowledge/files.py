import json
from pathlib import Path
from typing import List, Dict, Any, Optional
import aiofiles
from app.core.database import db
from app.core.logger import logger
from app.core.config import config_manager
from .vector import vector_store


class FileKnowledgeBase:
    def __init__(self):
        data_dir = Path(config_manager.get("system.data_dir", "./data"))
        self.base_dir = data_dir / "knowledge_base"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def add_entry(self, entry_type: str, title: str, content: str, source: str = "", tags: Optional[List[str]] = None):
        import uuid
        entry_id = uuid.uuid4().hex
        path = self.base_dir / entry_type / f"{entry_id}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(content)

        await db.execute(
            "INSERT INTO knowledge_entries (entry_id, type, title, content, source) VALUES (?,?,?,?,?)",
            (entry_id, entry_type, title, content, source)
        )

        await vector_store.add_documents(
            collection=f"kb_{entry_type}",
            ids=[entry_id],
            documents=[content],
            metadatas=[{"title": title, "source": source, "tags": json.dumps(tags or [])}]
        )
        logger.info(f"知识条目添加成功: {title}")
        return entry_id

    async def search(self, query: str, entry_type: Optional[str] = None, n_results: int = 5) -> List[Dict]:
        collection = f"kb_{entry_type}" if entry_type else "kb_patterns"
        return await vector_store.search(collection, query, n_results)
