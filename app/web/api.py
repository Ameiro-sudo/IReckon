from fastapi import FastAPI, HTTPException, WebSocket, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
import uuid
import yaml
import httpx
from loguru import logger

from app.core.database import db
from app.core.config import config_manager
from app.core.updater import updater
from app.llm.pool import capability_pool, AICapability
from app.engine.tasks import task_manager
from app.engine.room import meeting_room_manager, MessageLayer
from app.engine.self_improve import self_improver
from .ws import websocket_endpoint

app = FastAPI(title="IReckon AI Factory", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.exception_handler(RequestValidationError)
async def validation_handler(request, exc):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

@app.exception_handler(HTTPException)
async def http_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.exception_handler(Exception)
async def global_handler(request, exc):
    logger.exception(f"未处理异常: {exc}")
    return JSONResponse(status_code=500, content={"detail": str(exc)})

class CreateTaskRequest(BaseModel):
    user_request: str
    scheduler_cap_id: Optional[str] = None

class SendMessageRequest(BaseModel):
    content: str
    layer: str = "L1"

class AIInstanceRequest(BaseModel):
    id: str
    name: str
    endpoint: str
    model: str
    api_key: str = ""
    parameters: Dict[str, Any] = {}
    tags: List[str] = []
    cost_per_1k_tokens: float = 0.0
    max_context: int = 4096
    enabled: bool = True

class ConfigUpdateRequest(BaseModel):
    updates: Dict[str, Any]

@app.post("/api/tasks")
async def create_task(req: CreateTaskRequest):
    task_id = await task_manager.create_task(req.user_request)
    asyncio.create_task(task_manager.start_task(task_id, req.scheduler_cap_id))
    row = await db.fetch_one("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
    return {"task_id": row[0], "user_request": row[1], "status": row[2], "created_at": row[3], "updated_at": row[4]}

@app.get("/api/tasks")
async def list_tasks():
    rows = await db.fetch_all("SELECT task_id, user_request, status, created_at, updated_at FROM tasks ORDER BY created_at DESC")
    return [{"task_id": r[0], "user_request": r[1], "status": r[2], "created_at": r[3], "updated_at": r[4]} for r in rows]

@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    row = await db.fetch_one("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
    if not row: raise HTTPException(404, "Task not found")
    return {"task_id": row[0], "user_request": row[1], "status": row[2], "created_at": row[3], "updated_at": row[4]}

@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    ok = await task_manager.cancel_task(task_id)
    if not ok: raise HTTPException(400, "无法取消")
    return {"status": "cancelled"}

@app.post("/api/tasks/{task_id}/resume")
async def resume_task(task_id: str):
    ok = await task_manager.resume_task(task_id)
    if not ok: raise HTTPException(400, "无法恢复")
    return {"status": "resumed"}

@app.get("/api/tasks/{task_id}/messages")
async def get_messages(task_id: str, layer: str = "L1", since: Optional[str] = None, limit: int = 100):
    q = "SELECT msg_id, task_id, layer, sender_role, sender_id, content, metadata, timestamp FROM conversation_messages WHERE task_id = ? AND layer = ?"
    params = [task_id, layer]
    if since:
        q += " AND timestamp > ?"; params.append(since)
    q += " ORDER BY timestamp ASC LIMIT ?"; params.append(limit)
    rows = await db.fetch_all(q, tuple(params))
    return [{"msg_id": r[0], "layer": r[2], "sender_role": r[3], "sender_id": r[4], "content": r[5], "metadata": r[6], "timestamp": r[7]} for r in rows]

@app.post("/api/tasks/{task_id}/messages")
async def send_message(task_id: str, req: SendMessageRequest):
    room = await meeting_room_manager.get_room(task_id)
    if not room: raise HTTPException(404, "Task room not found")
    layer = MessageLayer.L1_PUBLIC if req.layer == "L1" else MessageLayer.L2_MEETING
    msg = await room.broadcast(layer=layer, sender_role="user", sender_id="user", content=req.content)
    return {"msg_id": msg.msg_id, "timestamp": msg.timestamp.isoformat()}

@app.get("/api/ai-instances")
async def list_ai_instances():
    return await db.get_all_ai_instances(enabled_only=False)

@app.post("/api/ai-instances")
async def create_ai_instance(inst: AIInstanceRequest):
    cap = AICapability(**inst.model_dump())
    await capability_pool.add_instance(cap)
    return {"status": "ok"}

@app.put("/api/ai-instances/{instance_id}")
async def update_ai_instance(instance_id: str, inst: AIInstanceRequest):
    cap = AICapability(**inst.model_dump())
    cap.id = instance_id
    await capability_pool.update_instance(cap)
    return {"status": "ok"}

@app.delete("/api/ai-instances/{instance_id}")
async def delete_ai_instance(instance_id: str):
    await capability_pool.remove_instance(instance_id)
    return {"status": "ok"}

@app.post("/api/ai-instances/{instance_id}/test")
async def test_ai_instance(instance_id: str):
    inst = await capability_pool.get_by_id(instance_id)
    if not inst: raise HTTPException(404, "Instance not found")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(inst.endpoint)
            return {"status": "reachable", "http_status": resp.status_code, "endpoint": inst.endpoint}
    except Exception as e:
        return {"status": "unreachable", "error": str(e), "endpoint": inst.endpoint}

@app.get("/api/capabilities")
async def list_capabilities():
    caps = await capability_pool.get_all(refresh=True)
    return [c.to_dict() for c in caps]

@app.get("/api/config")
async def get_config():
    return config_manager.get_all()

@app.post("/api/config/update")
async def update_config(req: ConfigUpdateRequest):
    config_path = config_manager.config_path
    with open(config_path, "r", encoding="utf-8") as f:
        current = yaml.safe_load(f)
    for key, value in req.updates.items():
        keys = key.split(".")
        d = current
        for k in keys[:-1]: d = d.setdefault(k, {})
        d[keys[-1]] = value
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(current, f, allow_unicode=True, default_flow_style=False)
    config_manager.reload()
    return {"status": "ok"}

@app.get("/api/themes")
async def list_themes():
    from app.engine.style import style_engine
    return {name: {"name": t.get("name", name)} for name, t in style_engine._themes.items()}

@app.post("/api/self-improve")
async def trigger_self_improve():
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

@app.post("/api/self-improve/push")
async def push_self_improve():
    ok = await self_improver.push_to_remote()
    return {"status": "ok" if ok else "error"}

@app.get("/api/update/check")
async def check_update():
    version = await updater.check()
    current = config_manager.get("system.version")
    return {
        "current_version": current,
        "latest_version": version,
        "update_available": version is not None,
    }

@app.post("/api/update/apply")
async def apply_update():
    version = await updater.check()
    if not version:
        return {"status": "error", "error": "没有新版本"}
    ok = await updater.download_and_update(version)
    return {"status": "ok" if ok else "error", "version": version}

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": config_manager.get("system.version"), "active_tasks": len(task_manager._running)}

@app.websocket("/ws/{task_id}")
async def ws_task(websocket: WebSocket, task_id: str):
    await websocket_endpoint(websocket, task_id)

@app.websocket("/ws")
async def ws_global(websocket: WebSocket):
    await websocket_endpoint(websocket, task_id=None)
