"""系统级 API：健康检查、统计、用量、日志、更新、自我进化。"""

import secrets
import time
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel
from loguru import logger


from app.core.config import get
from app.core.database import db
from app.core.updater import updater
from app.engine.cost import get_summary
from app.engine.self_improve import self_improver
from app.engine.tasks import task_manager
from app.llm.pool import capability_pool
from app.web.auth import configured_token, has_strict_token, require_strict_token
from app.web.push import manager as ws_manager

router = APIRouter(prefix="/api", tags=["system"])

_boot_time = time.monotonic()
_update_cache: dict = {"latest": None, "checked_at": 0.0}


async def _check_update_cached():
    """带缓存的更新检查，避免健康检查频繁请求 GitHub API。"""
    now = time.monotonic()
    if now - _update_cache["checked_at"] < 600 and _update_cache["checked_at"]:
        return _update_cache["latest"]
    try:
        latest = await updater.check()
    except Exception:
        latest = None
    _update_cache.update({"latest": latest, "checked_at": now})
    return latest


@router.get("/auth/check")
async def auth_check(x_api_token: Optional[str] = Header(None)):
    """登录页令牌校验（免鉴权路径）：只回答 是/否，不泄露任何其他信息。"""
    import secrets as _secrets

    token = configured_token()
    required = bool(token)
    authenticated = bool(
        required and x_api_token and _secrets.compare_digest(x_api_token, token)
    )
    return {"authenticated": authenticated, "required": required}


@router.get("/health")
async def health(x_api_token: Optional[str] = Header(None)):
    # 免鉴权路径：未携带有效 token 时仅返回存活状态，不泄露内部运行信息
    token = configured_token()
    authenticated = bool(
        token and x_api_token and secrets.compare_digest(x_api_token, token)
    )
    if not authenticated:
        return {"status": "ok"}
    caps = await capability_pool.get_all(refresh=False)
    latest = await _check_update_cached()
    return {
        "status": "ok",
        "version": get("system.version"),
        "latest_version": latest,
        "update_available": latest is not None,
        "active_tasks": len(task_manager._running),
        "ai_instances": len(caps),
        "ws_connections": len(ws_manager.global_connections)
        + sum(len(v) for v in ws_manager.task_connections.values()),
        "uptime_seconds": int(time.monotonic() - _boot_time),
    }


@router.get("/stats")
async def stats():
    rows = await db.fetch_all("SELECT status, COUNT(*) FROM tasks GROUP BY status")
    by_status = {r[0]: r[1] for r in rows}
    total = sum(by_status.values())
    caps = await capability_pool.get_all(refresh=False)
    usage = await get_summary()
    return {
        "total_tasks": total,
        "by_status": by_status,
        "active_tasks": by_status.get("executing", 0)
        + by_status.get("planning", 0)
        + by_status.get("reviewing", 0)
        + by_status.get("revising", 0),
        "completed_tasks": by_status.get("completed", 0),
        "failed_tasks": by_status.get("failed", 0),
        "paused_tasks": by_status.get("paused", 0),
        "ai_instances": len(caps),
        "ai_enabled": sum(1 for c in caps if c.enabled),
        "version": get("system.version"),
        "uptime_seconds": int(time.monotonic() - _boot_time),
        "usage": usage,
    }


@router.get("/usage")
async def usage():
    return await get_summary()


@router.get("/logs")
async def logs(
    limit: int = Query(200, ge=1, le=2000),
    level: Optional[str] = None,
    x_api_token: Optional[str] = Header(None),
):
    # 只读当日日志文件，与 WebSocket 日志消费者（_log_queue）无竞争
    from datetime import datetime

    # DEBUG 日志含 SQL 语句、内部路径等敏感细节，仅 strict token 持有者可见
    allow_debug = has_strict_token(x_api_token)
    data_dir = Path(get("system.data_dir", "./data"))
    log_file = data_dir / "logs" / f"app_{datetime.now().strftime('%Y-%m-%d')}.log"
    lines: List[str] = []
    try:
        if log_file.exists():
            raw = log_file.read_text(encoding="utf-8", errors="replace")
            lines = raw.splitlines()[-limit:]
    except Exception as e:
        logger.debug(f"读取日志文件失败: {e}")
    lines = lines[-limit:]
    result = []
    _VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        lv = "INFO"
        ts = ""
        # 文件格式: "YYYY-MM-DD HH:mm:ss | LEVEL | message"（时间取 HH:mm:ss 展示）
        parts = raw.split(" | ", 2)
        if len(parts) == 3:
            ts = parts[0].split(" ")[-1]
            candidate = parts[1].strip().upper()
            if candidate in _VALID_LEVELS:
                lv = candidate
                raw = parts[2]
        if lv == "DEBUG" and not allow_debug:
            continue
        if level and lv != level.upper():
            continue
        result.append({"time": ts, "level": lv, "message": raw})
    return result


@router.post("/self-improve", dependencies=[Depends(require_strict_token)])
async def trigger_self_improve():
    import uuid

    task_id = f"self-{uuid.uuid4().hex[:8]}"
    analysis = await self_improver.analyze(task_id)
    if not analysis.get("success"):
        return {"status": "error", "error": analysis.get("error", "分析失败")}
    result = await self_improver.apply_improvements(task_id, analysis)
    return {
        "status": "ok",
        "task_id": task_id,
        "analysis": analysis.get("analysis", "")[:500],
        "result": result,
    }


@router.post("/self-improve/push", dependencies=[Depends(require_strict_token)])
async def push_self_improve():
    ok = await self_improver.push_to_remote()
    return {"status": "ok" if ok else "error"}


@router.get("/update/check")
async def check_update():
    version = await updater.check()
    current = get("system.version")
    return {
        "current_version": current,
        "latest_version": version,
        "update_available": version is not None,
        # 当前安装形态对应的更新渠道，供前端展示与默认选择
        "channel": updater._resolve_channel(),
    }


class UpdateApplyRequest(BaseModel):
    """更新应用请求：channel 缺省时自动探测；silent 仅对 installer 渠道生效。"""

    channel: Optional[str] = None
    silent: bool = False


@router.post("/update/apply", dependencies=[Depends(require_strict_token)])
async def apply_update(req: Optional[UpdateApplyRequest] = None):
    body = req or UpdateApplyRequest()
    try:
        channel = updater._resolve_channel(body.channel)
    except Exception:
        channel = "portable"
    if body.channel and body.channel.lower() not in ("installer", "portable", "auto"):
        return {"status": "error", "error": f"未知渠道: {body.channel}"}
    version = await updater.check()
    if not version:
        return {"status": "error", "error": "没有新版本"}
    ok = await updater.download_and_update(
        version, channel=body.channel, silent=body.silent
    )
    message = {
        ("installer", True): "安装器已启动，请完成安装向导（应用将关闭）",
        ("installer", False): "更新失败，详见服务日志",
        ("portable", True): f"已更新到 v{version}",
        ("portable", False): "更新失败，已还原备份，详见服务日志",
    }.get((channel, ok), "更新失败")
    return {
        "status": "ok" if ok else "error",
        "version": version,
        "channel": channel,
        "message": message,
    }
