"""AI 实例管理 API：端点注册、更新、删除、连通性测试、能力池查询。"""

import asyncio
import ipaddress
import socket
import time
import uuid
from typing import Any, Dict, List
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.database import db
from app.llm.pool import capability_pool, AICapability

router = APIRouter(prefix="/api", tags=["ai-instances"])


class AIInstanceRequest(BaseModel):
    id: str = ""
    name: str = ""
    endpoint: str = ""
    model: str = ""
    api_key: str = ""
    parameters: Dict[str, Any] = {}
    tags: List[str] = []
    cost_per_1k_tokens: float = 0.0
    max_context: int = 4096
    enabled: bool = True


def _mask_instance(inst: dict) -> dict:
    """列表接口不返回明文 API Key，只暴露是否已配置。"""
    masked = {**inst}
    masked["has_key"] = bool(inst.get("api_key"))
    masked.pop("api_key", None)
    return masked


@router.get("/ai-instances")
async def list_ai_instances():
    insts = await db.get_all_ai_instances(enabled_only=False)
    return [_mask_instance(i) for i in insts]


@router.post("/ai-instances")
async def create_ai_instance(inst: AIInstanceRequest):
    data = inst.model_dump()
    if not data.get("endpoint") or not data.get("model"):
        raise HTTPException(422, "endpoint 和 model 为必填项")
    if not data.get("id"):
        data["id"] = f"ai-{uuid.uuid4().hex[:12]}"
    data.setdefault("api_key", "")
    cap = AICapability(**data)
    await capability_pool.add_instance(cap)
    return {"status": "ok", "id": data["id"]}


@router.put("/ai-instances/{instance_id}")
async def update_ai_instance(instance_id: str, inst: AIInstanceRequest):
    existing = await capability_pool.get_by_id(instance_id)
    if not existing:
        raise HTTPException(404, "Instance not found")
    # 以现有实例为基础做部分更新（exclude_unset 只覆盖传入字段）
    data = existing.to_dict()
    patch = inst.model_dump(exclude_unset=True)
    patch.pop("id", None)
    # api_key 为空串时保留已有密钥（前端编辑不填视为不变更）
    if not patch.get("api_key"):
        patch.pop("api_key", None)
    data.update(patch)
    cap = AICapability(**data)
    await capability_pool.update_instance(cap)
    return {"status": "ok"}


@router.delete("/ai-instances/{instance_id}")
async def delete_ai_instance(instance_id: str):
    await capability_pool.remove_instance(instance_id)
    return {"status": "ok"}


async def _reject_ssrf_target(url: str) -> None:
    """SSRF 防护：仅允许 http/https，且解析出的所有 IP 都不得是私网/环回/链路本地/保留地址。"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(400, "仅支持 http/https 端点")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = await asyncio.to_thread(
            socket.getaddrinfo, parsed.hostname, port, proto=socket.IPPROTO_TCP
        )
    except Exception:
        raise HTTPException(400, "无法解析端点主机名")
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise HTTPException(400, "禁止访问内网/环回/保留地址")


@router.post("/ai-instances/{instance_id}/test")
async def test_ai_instance(instance_id: str):
    inst = await capability_pool.get_by_id(instance_id)
    if not inst:
        raise HTTPException(404, "Instance not found")
    base = inst.endpoint.rstrip("/")
    url = base if base.endswith("/health") else f"{base}/models"
    await _reject_ssrf_target(url)
    try:
        headers = {"Authorization": f"Bearer {inst.api_key}"} if inst.api_key else {}
        # 禁止重定向（防止跟随跳转到内网地址），超时 5s
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
            start = time.monotonic()
            await client.get(url, headers=headers)
            latency_ms = int((time.monotonic() - start) * 1000)
            # 不回显远端响应内容，避免信息泄露
            return {"status": "ok", "latency_ms": latency_ms}
    except Exception as e:
        return {"status": "unreachable", "error": str(e)}


@router.get("/capabilities")
async def list_capabilities():
    caps = await capability_pool.get_all(refresh=True)
    return [c.to_dict() for c in caps]
