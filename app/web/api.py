"""FastAPI 应用工厂：挂载路由、中间件、WebSocket 与前端静态资源。"""

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from .push import websocket_endpoint
from .routers import tasks, instances, config as config_router, system, uploads

app = FastAPI(title="IReckon AI Factory", version="2.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks.router)
app.include_router(instances.router)
app.include_router(config_router.router)
app.include_router(system.router)
app.include_router(uploads.router)

# Serve Vue frontend dist. If dist is missing, redirect to Vite dev server.
_frontend_candidates = []
_meipass = getattr(sys, "_MEIPASS", None)
if _meipass:
    _frontend_candidates.append(Path(_meipass) / "frontend" / "dist")
_frontend_candidates.append(Path(__file__).parent.parent.parent / "frontend" / "dist")

_frontend_available = False
for fp in _frontend_candidates:
    if fp.is_dir():
        _frontend_available = True
        break

if not _frontend_available:

    @app.get("/", include_in_schema=False)
    async def redirect_to_frontend():
        dev_url = _dev_url()
        return RedirectResponse(dev_url)


def _dev_url() -> str:
    from app.core.config import config_manager

    return config_manager.get("server.frontend_dev_url", "http://127.0.0.1:3000")


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


@app.websocket("/ws/{task_id}")
async def ws_task(websocket: WebSocket, task_id: str):
    await websocket_endpoint(websocket, task_id)


@app.websocket("/ws")
async def ws_global(websocket: WebSocket):
    await websocket_endpoint(websocket, task_id=None)


if _frontend_available:
    frontend_dir = next(fp for fp in _frontend_candidates if fp.is_dir())
    app.mount(
        "/assets",
        StaticFiles(directory=str(frontend_dir / "assets")),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """Vue Router history 模式回退：非 API 路径统一返回 index.html。"""
        if full_path.startswith(("api/", "ws/")):
            raise HTTPException(404)
        candidate = frontend_dir / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend_dir / "index.html")
else:

    @app.get("/{path:path}", include_in_schema=False)
    async def redirect_to_frontend(path: str):
        return RedirectResponse(_dev_url())
