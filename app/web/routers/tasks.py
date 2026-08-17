"""任务相关 API：创建/列表/详情/取消/恢复/消息/看板/产物/删除。"""

import asyncio
import zipfile
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from loguru import logger

from app.core.config import config_manager
from app.core.database import db
from app.core.state import StateManager
from app.engine.board import TaskBoard
from app.engine.tasks import task_manager
from app.engine.room import meeting_room_manager, MessageLayer

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

_STATUS_MAP = {
    "pending": "pending",
    "planning": "planning",
    "executing": "executing",
    "reviewing": "reviewing",
    "revising": "revising",
    "delivering": "delivering",
    "completed": "completed",
    "failed": "failed",
    "paused": "paused",
}


class CreateTaskRequest(BaseModel):
    user_request: str
    scheduler_cap_id: Optional[str] = None
    upload_id: Optional[str] = None


class SendMessageRequest(BaseModel):
    content: str
    layer: str = "L1"


def _row_to_task(r) -> dict:
    """任务行转 dict：列布局 task_id, user_request, title, status, created_at, updated_at, ..."""
    return {
        "task_id": r[0],
        "user_request": r[1],
        "title": r[2] or None,
        "status": r[3],
        "created_at": r[4],
        "updated_at": r[5],
    }


@router.post("")
async def create_task(req: CreateTaskRequest):
    if not req.user_request or not req.user_request.strip():
        raise HTTPException(422, "任务描述不能为空")
    task_id = await task_manager.create_task(req.user_request.strip(), req.upload_id)
    asyncio.create_task(task_manager.start_task(task_id, req.scheduler_cap_id))
    row = await db.fetch_one("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
    return _row_to_task(row)


@router.get("")
async def list_tasks(
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: Optional[str] = None,
):
    params: List[Any] = []
    where = ""
    if status:
        where = " WHERE status = ?"
        params.append(status)
    rows = await db.fetch_all(
        "SELECT t.task_id, t.user_request, t.title, t.status, t.created_at, t.updated_at, "
        "COALESCE((SELECT SUM(u.tokens) FROM usage_log u WHERE u.task_id = t.task_id), 0) AS tokens "
        f"FROM tasks t{where} ORDER BY t.created_at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    )
    return [
        {**_row_to_task(r), "tokens": r[6] or 0}
        for r in rows
    ]


@router.get("/{task_id}")
async def get_task(task_id: str):
    row = await db.fetch_one("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
    if not row:
        raise HTTPException(404, "Task not found")
    detail = _row_to_task(row)
    detail["output_dir"] = row[7] or None
    if len(row) > 8 and row[8]:
        import json as _json

        try:
            detail["file_refs"] = _json.loads(row[8])
        except (_json.JSONDecodeError, TypeError):
            detail["file_refs"] = None
    if row[6]:
        import json

        try:
            detail["plan"] = json.loads(row[6])
        except (json.JSONDecodeError, TypeError):
            detail["plan"] = None
    board = await TaskBoard(task_id).load()
    if board:
        detail["board"] = board.to_dict()
    usage = await db.fetch_one(
        "SELECT COALESCE(SUM(tokens),0), COALESCE(SUM(cost),0) FROM usage_log WHERE task_id=?",
        (task_id,),
    )
    detail["tokens"] = usage[0] if usage else 0
    detail["cost"] = round(usage[1], 4) if usage else 0.0
    return detail


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str):
    ok = await task_manager.cancel_task(task_id)
    if not ok:
        raise HTTPException(400, "无法取消")
    return {"status": "cancelled"}


@router.post("/{task_id}/resume")
async def resume_task(task_id: str):
    ok = await task_manager.resume_task(task_id)
    if not ok:
        raise HTTPException(400, "无法恢复")
    return {"status": "resumed"}


@router.delete("/{task_id}")
async def delete_task(task_id: str):
    if task_id in task_manager._running:
        raise HTTPException(400, "运行中的任务不能删除，请先取消")
    await task_manager.cancel_task(task_id)
    await db.delete_task(task_id)
    try:
        sm = StateManager(task_id)
        await sm.cleanup()
        for f in sm.states_dir.glob("snapshot_*.json"):
            f.unlink(missing_ok=True)
    except Exception as e:
        logger.warning(f"清理任务{task_id}快照失败: {e}")
    try:
        await meeting_room_manager.close_room(task_id)
    except Exception:
        pass
    return {"status": "deleted"}


@router.get("/{task_id}/board")
async def get_task_board(task_id: str):
    board = await TaskBoard(task_id).load()
    if not board:
        raise HTTPException(404, "任务看板不存在")
    return board.to_dict()


@router.get("/{task_id}/messages")
async def get_messages(
    task_id: str,
    layer: str = "L1",
    since: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
):
    q = "SELECT msg_id, task_id, layer, sender_role, sender_id, content, metadata, timestamp FROM conversation_messages WHERE task_id = ? AND layer = ?"
    params: List[Any] = [task_id, layer]
    if since:
        q += " AND timestamp > ?"
        params.append(since)
    q += " ORDER BY timestamp ASC LIMIT ?"
    params.append(limit)
    rows = await db.fetch_all(q, tuple(params))
    return [
        {
            "msg_id": r[0],
            "layer": r[2],
            "sender_role": r[3],
            "sender_id": r[4],
            "content": r[5],
            "metadata": r[6],
            "timestamp": r[7],
        }
        for r in rows
    ]


@router.post("/{task_id}/messages")
async def send_message(task_id: str, req: SendMessageRequest):
    room = await meeting_room_manager.get_room(task_id)
    if not room:
        raise HTTPException(404, "Task room not found")
    layer = MessageLayer.L1_PUBLIC if req.layer == "L1" else MessageLayer.L2_MEETING
    msg = await room.broadcast(
        layer=layer, sender_role="user", sender_id="user", content=req.content
    )
    return {"msg_id": msg.msg_id, "timestamp": msg.timestamp.isoformat()}


def _output_dir(task_id: str) -> Optional[Path]:
    data_dir = Path(config_manager.get("system.data_dir", "./data"))
    out_dir = Path(config_manager.get("system.output_dir", str(data_dir / "outputs")))
    if not out_dir.is_absolute():
        out_dir = config_manager.base_dir / out_dir
    candidates = [
        out_dir / task_id,
        data_dir / "harness" / "workspaces" / task_id,
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return None


@router.get("/{task_id}/artifacts")
async def list_artifacts(task_id: str):
    out = _output_dir(task_id)
    if not out:
        return {"task_id": task_id, "files": []}
    files = []
    for p in sorted(out.rglob("*")):
        if p.is_file():
            files.append(
                {
                    "path": str(p.relative_to(out)),
                    "size": p.stat().st_size,
                    "mtime": p.stat().st_mtime,
                }
            )
    return {"task_id": task_id, "root": str(out), "files": files}


@router.get("/{task_id}/artifact")
async def get_artifact(task_id: str, path: str = Query(..., max_length=500)):
    """读取单个产物文件内容（路径穿越防护 + 大小限制）。"""
    out = _output_dir(task_id)
    if not out:
        raise HTTPException(404, "无交付产物")
    try:
        fp = (out / path).resolve()
        root = out.resolve()
    except (OSError, ValueError):
        raise HTTPException(400, "非法路径")
    if not str(fp).startswith(str(root)) or not fp.is_file():
        raise HTTPException(404, "文件不存在")
    if fp.stat().st_size > 1024 * 1024:
        return {"path": path, "size": fp.stat().st_size, "truncated": True, "content": ""}
    content = fp.read_text(encoding="utf-8", errors="replace")
    return {
        "path": path,
        "size": fp.stat().st_size,
        "truncated": False,
        "content": content,
    }


@router.get("/{task_id}/download")
async def download_artifacts(task_id: str):
    out = _output_dir(task_id)
    if not out:
        raise HTTPException(404, "无交付产物")
    zip_path = out.parent / f"{task_id}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in out.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(out))
    return FileResponse(
        zip_path,
        filename=f"{task_id}.zip",
        media_type="application/zip",
    )
