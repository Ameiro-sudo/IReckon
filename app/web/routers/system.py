"""系统级 API：健康检查、统计、用量、日志、更新、自我进化。"""

import time
from collections import deque
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Query
from loguru import logger

from app.core.config import config_manager
from app.core.database import db
from app.core.logger import _log_queue
from app.core.updater import updater
from app.engine.cost import cost_tracker
from app.engine.self_improve import self_improver
from app.engine.tasks import task_manager
from app.llm.pool import capability_pool
from app.web.push import manager as ws_manager

router = APIRouter(prefix="/api", tags=["system"])

_log_buffer: deque = deque(maxlen=500)
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


def _drain_log_queue() -> List[str]:
    items = []
    while not _log_queue.empty():
        try:
            items.append(_log_queue.get_nowait())
        except Exception:
            break
    for item in items:
        _log_buffer.append(item)
    return items


@router.get("/health")
async def health():
    _drain_log_queue()
    caps = await capability_pool.get_all(refresh=False)
    latest = await _check_update_cached()
    return {
        "status": "ok",
        "version": config_manager.get("system.version"),
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
    usage = await cost_tracker.get_summary()
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
        "version": config_manager.get("system.version"),
        "uptime_seconds": int(time.monotonic() - _boot_time),
        "usage": usage,
    }


@router.get("/usage")
async def usage():
    return await cost_tracker.get_summary()


@router.get("/logs")
async def logs(limit: int = Query(200, ge=1, le=2000), level: Optional[str] = None):
    _drain_log_queue()
    # 优先从当日日志文件读取（与 WebSocket 消费者无竞争）
    from datetime import datetime

    data_dir = Path(config_manager.get("system.data_dir", "./data"))
    log_file = data_dir / "logs" / f"app_{datetime.now().strftime('%Y-%m-%d')}.log"
    lines: List[str] = []
    try:
        if log_file.exists():
            raw = log_file.read_text(encoding="utf-8", errors="replace")
            lines = raw.splitlines()[-limit:]
    except Exception as e:
        logger.debug(f"读取日志文件失败: {e}")
    lines = lines + list(_log_buffer)[-limit:]
    lines = lines[-limit:]
    result = []
    _VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        lv = "INFO"
        # 文件格式: "YYYY-MM-DD HH:MM:SS | LEVEL | message"
        parts = raw.split(" | ", 2)
        if len(parts) == 3:
            candidate = parts[1].strip().upper()
            if candidate in _VALID_LEVELS:
                lv = candidate
                raw = parts[2]
        # 队列格式: "LEVEL|message"
        elif "|" in raw:
            head, _, rest = raw.partition("|")
            candidate = head.strip().upper()
            if candidate in _VALID_LEVELS:
                lv = candidate
                raw = rest.strip()
        if level and lv != level.upper():
            continue
        result.append({"level": lv, "message": raw})
    return result


@router.post("/self-improve")
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


@router.post("/self-improve/push")
async def push_self_improve():
    ok = await self_improver.push_to_remote()
    return {"status": "ok" if ok else "error"}


@router.get("/update/check")
async def check_update():
    version = await updater.check()
    current = config_manager.get("system.version")
    return {
        "current_version": current,
        "latest_version": version,
        "update_available": version is not None,
    }


@router.post("/update/apply")
async def apply_update():
    version = await updater.check()
    if not version:
        return {"status": "error", "error": "没有新版本"}
    ok = await updater.download_and_update(version)
    return {"status": "ok" if ok else "error", "version": version}
