import asyncio
import re
from typing import List, Dict, Optional
import chromadb
from chromadb.utils import embedding_functions
from pathlib import Path

from app.core.config import get

_COLLECTION_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_MAX_RESULTS = 100


def _validate_collection(name: str) -> str:
    if not name or not _COLLECTION_RE.match(name):
        raise ValueError(f"非法 collection 名: {name!r}")
    return name


class VectorStore:
    def __init__(self):
        data_dir = Path(get("system.data_dir", "./data"))
        self.persist_dir = data_dir / "chromadb"
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.persist_dir))
        self._ef = embedding_functions.DefaultEmbeddingFunction()
        self._collections = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def _get_lock(self, name: str) -> asyncio.Lock:
        if name not in self._locks:
            self._locks[name] = asyncio.Lock()
        return self._locks[name]

    def _get_collection(self, name: str):
        _validate_collection(name)
        if name not in self._collections:
            try:
                self._collections[name] = self._client.get_collection(
                    name, embedding_function=self._ef
                )
            except Exception:
                self._collections[name] = self._client.create_collection(
                    name, embedding_function=self._ef
                )
        return self._collections[name]

    async def add_documents(
        self,
        collection: str,
        ids: List[str],
        documents: List[str],
        metadatas: Optional[List[Dict]] = None,
    ):
        lock = self._get_lock(collection)
        async with lock:
            col = self._get_collection(collection)
            await asyncio.to_thread(
                col.add, ids=ids, documents=documents, metadatas=metadatas
            )

    async def search(
        self, collection: str, query: str, n_results: int = 5
    ) -> List[Dict]:
        n_results = max(1, min(int(n_results), _MAX_RESULTS))
        lock = self._get_lock(collection)
        async with lock:
            col = self._get_collection(collection)
            results = await asyncio.to_thread(
                col.query, query_texts=[query], n_results=n_results
            )
        mapped = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                mapped.append(
                    {
                        "id": doc_id,
                        "document": results["documents"][0][i]
                        if results["documents"]
                        else "",
                        "metadata": results["metadatas"][0][i]
                        if results["metadatas"]
                        else {},
                        "distance": results["distances"][0][i]
                        if results["distances"]
                        else 0,
                    }
                )
        return mapped


vector_store = VectorStore()
