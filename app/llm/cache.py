"""LLM 响应缓存：相同请求直接命中，不产生新的 API 调用。

背景：按次计费的通道里，重复/幂等请求（摘要、分类、模板化生成）每次都
真实调用会白白消耗调用次数。本缓存以 (model, messages, temperature,
max_tokens) 的哈希为键，TTL 内命中直接返回上次结果。

仅用于非流式、低温度（确定性）调用；流式路径不接入。
"""

import asyncio
import hashlib
import json
import time
from typing import Any, Dict, Optional, Tuple

from loguru import logger

from app.core.config import get


class ResponseCache:
    """内存级 LRU+TTL 响应缓存（进程内，单事件循环场景）。"""

    def __init__(self):
        self.enabled = bool(get("ai_pool.response_cache.enabled", True))
        self.ttl = float(get("ai_pool.response_cache.ttl_seconds", 3600))
        self.max_entries = int(get("ai_pool.response_cache.max_entries", 512))
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._lock = asyncio.Lock()
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    @staticmethod
    def make_key(
        model: str,
        messages: Any,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        scope: str = "",
    ) -> str:
        payload = json.dumps(
            {
                "m": model,
                "msgs": messages,
                "t": temperature,
                "mt": max_tokens,
                "s": scope,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def get(self, key: str) -> Optional[Any]:
        if not self.enabled:
            return None
        async with self._lock:
            item = self._store.get(key)
            if item is None:
                self.misses += 1
                return None
            ts, value = item
            if time.monotonic() - ts > self.ttl:
                del self._store[key]
                self.evictions += 1
                self.misses += 1
                return None
            # 命中后刷新时间戳，实现"访问即续期"的 LRU 语义
            self._store[key] = (time.monotonic(), value)
            self.hits += 1
            return value

    async def set(self, key: str, value: Any) -> None:
        if not self.enabled:
            return
        async with self._lock:
            if len(self._store) >= self.max_entries and key not in self._store:
                # 淘汰最旧的一条（按写入/访问时间戳）
                oldest = min(self._store, key=lambda k: self._store[k][0])
                del self._store[oldest]
                self.evictions += 1
            self._store[key] = (time.monotonic(), value)

    def stats(self) -> Dict[str, Any]:
        total = self.hits + self.misses
        return {
            "enabled": self.enabled,
            "entries": len(self._store),
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate": round(self.hits / total, 4) if total else 0.0,
            "saved_calls": self.hits,
        }


response_cache = ResponseCache()
logger.debug("LLM 响应缓存已初始化")
