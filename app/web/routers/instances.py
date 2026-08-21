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
from loguru import logger
from pydantic import BaseModel

from app.core.config import config_manager
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


class ScanModelsRequest(BaseModel):
    """模型扫描请求：探测 OpenAI 兼容 GET {endpoint}/models。

    - 编辑已有实例且未重填密钥时，前端传 instance_id 以复用存量密钥；
    - 显式 api_key 优先于存量密钥；两者皆无则匿名探测（部分端点允许）。
    """

    endpoint: str = ""
    api_key: str = ""
    instance_id: str = ""


def _mask_instance(inst: dict) -> dict:
    """列表接口不返回明文 API Key，只暴露是否已配置。"""
    masked = {**inst, "has_key": bool(inst.get("api_key"))}
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
    _validate_endpoint_static(data.get("endpoint", ""))
    if not data.get("id"):
        data["id"] = f"ai-{uuid.uuid4().hex[:12]}"
    # 拒绝覆盖已有 ID：防止实例被同 ID 重建劫持（改指向恶意端点）
    if await db.get_ai_instance(data["id"]):
        raise HTTPException(409, f"实例 ID 已存在: {data['id']}，如需修改请用 PUT")
    cap = AICapability(**data)
    await capability_pool.add_instance(cap)
    return {"status": "ok", "id": data["id"]}


@router.put("/ai-instances/{instance_id}")
async def update_ai_instance(instance_id: str, inst: AIInstanceRequest):
    existing = await capability_pool.get_by_id(instance_id)
    if not existing:
        raise HTTPException(404, "Instance not found")
    # 以现有实例为基础做部分更新：exclude_unset 只覆盖请求中显式传入的字段
    data = existing.to_dict()
    patch = inst.model_dump(exclude_unset=True)
    patch.pop("id", None)
    if patch.get("endpoint"):
        _validate_endpoint_static(patch["endpoint"])
    # api_key 为空串时保留已有密钥（前端编辑不填视为不变更）
    if not patch.get("api_key"):
        patch.pop("api_key", None)
    data.update(patch)
    cap = AICapability(**data)
    await capability_pool.update_instance(cap)
    return {"status": "ok"}


@router.delete("/ai-instances/{instance_id}")
async def delete_ai_instance(instance_id: str):
    deleted = await capability_pool.remove_instance(instance_id)
    if not deleted:
        raise HTTPException(404, "Instance not found")
    return {"status": "ok"}


def _private_endpoints_allowed() -> bool:
    """security.allow_private_endpoints 开关：是否放行本地/内网端点。

    默认关闭（fail-closed）；仅接受布尔 true，其余一律视为关闭。
    该开关同时作用于注册期静态校验、/test 与 /scan-models 的出网前
    SSRF 门禁，保证三条路径判定一致。
    """
    return config_manager.get("security.allow_private_endpoints", False) is True


def _forbidden_ip_reason(
    ip: "ipaddress.IPv4Address | ipaddress.IPv6Address",
    allow_private: bool = False,
) -> "str | None":
    """返回拒绝理由字符串；None 表示放行。

    覆盖：私网/环回/链路本地/保留/组播/未指定地址，并先展开
    IPv6-mapped-IPv4（如 ::ffff:127.0.0.1）再复检。
    allow_private=True（security.allow_private_endpoints）时放行私网/
    环回/链路本地/保留段以支持 Ollama 等本地端点；组播与未指定地址
    （0.0.0.0/[::]）无论如何都拒绝——它们不是合法的端点目标。
    """
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    if ip.is_unspecified or ip.is_multicast:
        return f"禁止访问组播/未指定地址（解析到 {ip}）"
    if allow_private:
        return None
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        return f"禁止访问内网/环回/保留/组播地址（解析到 {ip}）"
    return None


def _validate_endpoint_static(endpoint: str) -> None:
    """注册/更新实例时的轻量端点校验（不做 DNS）。

    拦截 scheme 异常、URL 内嵌凭据与字面量内网地址；完整 DNS 解析级
    SSRF 校验在 /test、/scan-models 实际出网前执行（_reject_ssrf_target）。
    """
    parsed = urlparse(endpoint or "")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(400, "endpoint 仅支持 http/https URL")
    if parsed.username or parsed.password:
        raise HTTPException(400, "endpoint URL 不应内嵌凭据")
    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return
    reason = _forbidden_ip_reason(literal, _private_endpoints_allowed())
    if reason:
        raise HTTPException(400, reason)


async def _reject_ssrf_target(url: str) -> None:
    """SSRF 防护：仅允许 http/https，且解析出的所有 IP 都不得是
    私网/环回/链路本地/保留/组播/未指定地址。

    security.allow_private_endpoints=true 时放行私网/环回等本地目标
    （组播/未指定仍拒绝），供 Ollama/LM Studio 等本机推理端点使用；
    /test 与 /scan-models 共用本函数，门禁判定保持一致。

    已知限制（纵深防御备忘）：DNS 校验与实际连接是两次独立解析，
    理论上存在 DNS-rebinding 窗口；当前以「校验紧贴出网前执行 +
    follow_redirects=False」缓解。若未来威胁模型升级，应改为自定义
    transport 把连接目标固定为本次校验过的解析结果。
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(400, "仅支持 http/https 端点")
    if parsed.username or parsed.password:
        raise HTTPException(400, "端点 URL 不应内嵌凭据")
    allow_private = _private_endpoints_allowed()
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        raise HTTPException(400, "端点端口非法")
    # 字面量 IP 主机名快速判定：不经 DNS 直接复核（0.0.0.0/[::]/组播等形态）
    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal = None
    if literal is not None:
        reason = _forbidden_ip_reason(literal, allow_private)
        if reason:
            raise HTTPException(400, reason)
        return
    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo, parsed.hostname, port, proto=socket.IPPROTO_TCP
        )
    except Exception:
        raise HTTPException(400, "无法解析端点主机名")
    seen = set()
    for info in infos:
        addr = info[4][0]
        if addr in seen:
            continue
        seen.add(addr)
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        reason = _forbidden_ip_reason(ip, allow_private)
        if reason:
            raise HTTPException(400, reason)


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
            resp = await client.get(url, headers=headers)
            latency_ms = int((time.monotonic() - start) * 1000)
            # 不回显远端响应内容，避免信息泄露
            return {
                "status": "reachable",
                "http_status": resp.status_code,
                "latency_ms": latency_ms,
            }
    except Exception as e:
        # 不回显具体异常（避免泄露端点内部信息），只给通用分类
        logger.info(f"AI 实例 {instance_id} 连通性测试失败: {e}")
        return {"status": "unreachable", "error": "连接失败"}


def _extract_model_ids(payload: Any) -> List[str]:
    """从 /models 响应提取模型 ID 列表（去重保序，封顶 256）。

    兼容三种常见形态：OpenAI {"data":[{"id":..}]}、Ollama 原生
    {"models":[{"name":..}]}、裸数组 [{"id"|"name":..}]。
    """
    if isinstance(payload, dict):
        items = payload.get("data")
        if not isinstance(items, list):
            items = payload.get("models")
    elif isinstance(payload, list):
        items = payload
    else:
        items = None
    ids: List[str] = []
    if not isinstance(items, list):
        return ids
    for item in items:
        if isinstance(item, dict):
            raw = item.get("id") or item.get("name")
        else:
            raw = item
        if isinstance(raw, str) and raw.strip():
            mid = raw.strip()
            if mid not in ids:
                ids.append(mid)
        if len(ids) >= 256:
            break
    return ids


@router.post("/ai-instances/scan-models")
async def scan_models(req: ScanModelsRequest):
    """探测端点的可用模型列表，供前端勾选。

    与 /test 共用同一 SSRF 门禁（_reject_ssrf_target，含
    allow_private_endpoints 开关联动）；不回显远端响应原文与密钥。
    """
    endpoint = (req.endpoint or "").strip()
    api_key = req.api_key or ""
    if not endpoint and req.instance_id:
        inst = await capability_pool.get_by_id(req.instance_id)
        if not inst:
            raise HTTPException(404, "Instance not found")
        endpoint = inst.endpoint
        if not api_key:
            api_key = inst.api_key or ""
    if not endpoint:
        raise HTTPException(422, "endpoint 为必填项")
    _validate_endpoint_static(endpoint)
    url = f"{endpoint.rstrip('/')}/models"
    await _reject_ssrf_target(url)
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        # 与 /test 一致：禁止重定向，短超时；日志不落 URL 与密钥
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
            resp = await client.get(url, headers=headers)
    except Exception as e:
        logger.info(f"模型扫描连接失败: {type(e).__name__}")
        return {"status": "unreachable", "error": "连接失败", "models": []}
    if resp.status_code != 200:
        return {
            "status": "error",
            "error": f"HTTP {resp.status_code}",
            "models": [],
        }
    try:
        models = _extract_model_ids(resp.json())
    except Exception:
        return {
            "status": "error",
            "error": "响应不是有效的模型列表",
            "models": [],
        }
    if not models:
        return {"status": "error", "error": "端点未返回任何模型", "models": []}
    return {"status": "ok", "models": models, "count": len(models)}


@router.get("/capabilities")
async def list_capabilities():
    caps = await capability_pool.get_all(refresh=True)
    # 与列表接口一致：不返回明文 api_key，只暴露是否已配置
    return [_mask_instance(c.to_dict()) for c in caps]
