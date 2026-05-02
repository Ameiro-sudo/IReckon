import asyncio, threading, time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Set
from loguru import logger
from core.db import db
from core.config_manager import config_manager

@dataclass
class AICapability:
    id: str; name: str; endpoint: str; model: str; api_key: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    cost_per_1k_tokens: float = 0.0
    max_context: int = 4096
    enabled: bool = True

    def to_dict(self):
        return {"id":self.id,"name":self.name,"endpoint":self.endpoint,"model":self.model,"api_key":self.api_key,
                "parameters":self.parameters,"tags":self.tags,"cost_per_1k_tokens":self.cost_per_1k_tokens,
                "max_context":self.max_context,"enabled":self.enabled}

class CapabilityPool:
    _instance=None; _lock=threading.Lock()
    def __new__(cls):
        with cls._lock:
            if cls._instance is None: cls._instance=super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self,"_init") and self._init: return
        self._init=True; self.capabilities:Dict[str,AICapability]={}
        self._refresh_lock=asyncio.Lock(); self._last_refresh=0; self.refresh_interval=60

    async def _init_from_config_if_empty(self):
        rows = await db.fetch_all("SELECT COUNT(*) FROM ai_instances")
        if rows and rows[0][0]>0: return
        for inst in config_manager.get("ai_pool.instances",[]):
            cap = AICapability(id=inst["id"],name=inst["name"],endpoint=inst["endpoint"],model=inst["model"],
                               api_key=inst.get("api_key",""),parameters=inst.get("parameters",{}),tags=inst.get("tags",[]),
                               cost_per_1k_tokens=inst.get("cost_per_1k_tokens",0.0),max_context=inst.get("max_context",4096),
                               enabled=inst.get("enabled",True))
            await db.save_ai_instance(cap.to_dict())
        logger.info("从配置文件初始化 AI 实例到数据库")

    async def refresh(self, force=False):
        async with self._refresh_lock:
            now=time.monotonic()
            if not force and now-self._last_refresh<self.refresh_interval: return
            await self._init_from_config_if_empty()
            instances = await db.get_all_ai_instances(enabled_only=True)
            self.capabilities = {i["id"]: AICapability(**i) for i in instances}
            self._last_refresh=now

    async def get_all(self, refresh=False):
        if refresh or not self.capabilities: await self.refresh(force=refresh)
        return list(self.capabilities.values())

    async def get_by_id(self, iid):
        if not self.capabilities: await self.refresh()
        return self.capabilities.get(iid)

    async def find_best_match(self, required_tags=None, exclude_tags=None, exclude_ids=None, min_context=None, max_cost=None, prefer_cheapest=False):
        await self.refresh(); exclude_ids=exclude_ids or set()
        candidates=[c for c in self.capabilities.values() if c.id not in exclude_ids]
        if required_tags: candidates=[c for c in candidates if all(t in c.tags for t in required_tags)]
        if exclude_tags: candidates=[c for c in candidates if not any(t in c.tags for t in exclude_tags)]
        if min_context: candidates=[c for c in candidates if c.max_context>=min_context]
        if max_cost is not None: candidates=[c for c in candidates if c.cost_per_1k_tokens<=max_cost]
        if not candidates: return None
        if prefer_cheapest: candidates.sort(key=lambda x: x.cost_per_1k_tokens)
        return candidates[0]

    async def add_instance(self, cap): await db.save_ai_instance(cap.to_dict()); await self.refresh(force=True)
    async def update_instance(self, cap): await db.save_ai_instance(cap.to_dict()); await self.refresh(force=True)
    async def remove_instance(self, iid):
        cap = await self.get_by_id(iid)
        if cap: cap.enabled=False; await db.save_ai_instance(cap.to_dict()); await self.refresh(force=True)

    async def get_fallback_instances(self, primary_id, count=2):
        cap = await self.get_by_id(primary_id)
        if not cap: return []
        all_caps = [c for c in (await self.get_all()) if c.id!=primary_id and set(cap.tags)&set(c.tags)]
        all_caps.sort(key=lambda x: x.cost_per_1k_tokens)
        return all_caps[:count]

capability_pool = CapabilityPool()