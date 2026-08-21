"""FastAPI 应用工厂：挂载路由、中间件、WebSocket 与前端静态资源。"""

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from .auth import require_api_token, ws_authorized
from .push import heartbeat_loop, log_consumer, websocket_endpoint
from .routers import tasks, instances, config as config_router, system, uploads

from app.core.config import get


@asynccontextmanager
async def lifespan(app: FastAPI):
    """后台任务：日志队列消费者 + WebSocket 僵尸连接扫描。"""
    background = [
        asyncio.create_task(log_consumer()),
        asyncio.create_task(heartbeat_loop()),
    ]
    try:
        yield
    finally:
        for task in background:
            task.cancel()
        for task in background:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


# 交互文档默认关闭（openapi.json 会完整暴露 API 攻击面），仅开发时显式开启
_docs_enabled = str(get("server.docs_enabled", False)).lower() in ("1", "true", "yes")

app = FastAPI(
    title="IReckon AI Factory",
    version=get("system.version", "0.1.0"),
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

# 同源部署无需跨域；仅放行本机前后端的固定来源，
# 防止浏览器中的恶意网页借 CORS 扫描/调用本机 API（drive-by localhost）
_allowed_origins = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["X-API-Token", "Content-Type"],
)

app.include_router(tasks.router, dependencies=[Depends(require_api_token)])
app.include_router(instances.router, dependencies=[Depends(require_api_token)])
app.include_router(config_router.router, dependencies=[Depends(require_api_token)])
app.include_router(system.router, dependencies=[Depends(require_api_token)])
app.include_router(uploads.router, dependencies=[Depends(require_api_token)])

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
    from typing import cast

    return cast(str, get("server.frontend_dev_url", "http://127.0.0.1:3000"))


@app.exception_handler(RequestValidationError)
async def validation_handler(request, exc):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(HTTPException)
async def http_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def global_handler(request, exc):
    # 异常详情只进日志，不回显给客户端
    logger.exception(f"未处理异常: {type(exc).__name__}: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


def _ws_authorized(websocket: WebSocket) -> bool:
    """WebSocket 握手鉴权（fail-closed 语义见 app.web.auth）。"""
    return ws_authorized(websocket)


@app.websocket("/ws/{task_id}")
async def ws_task(websocket: WebSocket, task_id: str):
    if not _ws_authorized(websocket):
        await websocket.close(code=4401)
        return
    await websocket_endpoint(websocket, task_id)


@app.websocket("/ws")
async def ws_global(websocket: WebSocket):
    if not _ws_authorized(websocket):
        await websocket.close(code=4401)
        return
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
        if not _docs_enabled and full_path in ("docs", "redoc", "openapi.json"):
            # 文档已关闭：不让 SPA 回退伪装成 200，直接 404
            raise HTTPException(404)
        candidate = (frontend_dir / full_path).resolve()
        try:
            # 路径穿越防护：解析后的路径必须仍在 frontend_dir 内
            candidate.relative_to(frontend_dir.resolve())
        except ValueError:
            raise HTTPException(404)
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend_dir / "index.html")
else:

    @app.get("/{path:path}", include_in_schema=False)
    async def redirect_to_dev(path: str):
        return RedirectResponse(_dev_url())
