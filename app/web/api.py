"""FastAPI 应用工厂：挂载路由、中间件、WebSocket 与前端静态资源。"""

import asyncio
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from .auth import require_api_token, ws_handshake
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

# 安全响应头（P2-12）：CSP 收紧脚本/对象/框架来源，其余为通用加固。
# 说明：
# - script-src 'self'：主题引导已外链为 /theme-init.js（public/），入口无内联脚本；
# - style-src 'self' 'unsafe-inline'：Vue 运行时与 Tailwind 会注入内联样式，无法收紧；
# - 字体已自托管于前端 public/fonts/（woff2 子集），CSP 不再放行任何第三方域；
# - connect-src 的 WebSocket 来源按请求 Host 动态收敛为页面自身 authority
#   （裸 ws:/wss: scheme-source 曾允许向任意外部 WS 主机外带数据）；
# - frame-ancestors 'none' 禁止被嵌入 iframe，配合 X-Frame-Options DENY。
_CSP_TEMPLATE = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "font-src 'self' data:",
        "img-src 'self' data:",
        "connect-src 'self' {ws_sources}",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

# Host 头合法性：hostname[:port]，容忍 IPv6 字面量方括号
_HOST_RE = re.compile(r"^[A-Za-z0-9.\-\[\]]+(:\d+)?$")


def _build_csp(host: str) -> str:
    if host and _HOST_RE.match(host):
        ws_sources = f"ws://{host} wss://{host}"
    else:
        # Host 异常时仅留 'self'：现代浏览器同源策略已覆盖同主机 WS
        ws_sources = ""
    return _CSP_TEMPLATE.format(ws_sources=ws_sources)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = _build_csp(
        request.headers.get("host", "")
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.path.startswith("/api/"):
        # 日志/产物/配置等敏感响应不落共享机磁盘缓存
        response.headers["Cache-Control"] = "no-store"
    return response


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
    # 只回显 loc/msg 白名单字段：pydantic v2 的 errors() 会携带 input
    # （用户提交值回显）与 ctx（内部断言/正则细节），不应对外暴露
    safe = [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": safe})


@app.exception_handler(HTTPException)
async def http_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def global_handler(request, exc):
    # 异常详情只进日志，不回显给客户端
    logger.exception(f"未处理异常: {type(exc).__name__}: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


@app.websocket("/ws/{task_id}")
async def ws_task(websocket: WebSocket, task_id: str):
    authorized, subprotocol = ws_handshake(websocket)
    if not authorized:
        await websocket.close(code=4401)
        return
    await websocket_endpoint(websocket, task_id, subprotocol=subprotocol)


@app.websocket("/ws")
async def ws_global(websocket: WebSocket):
    authorized, subprotocol = ws_handshake(websocket)
    if not authorized:
        await websocket.close(code=4401)
        return
    await websocket_endpoint(websocket, task_id=None, subprotocol=subprotocol)


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
        # 文档已关闭时无前端 dist 也必须直接 404：
        # 否则 302 到 dev server 后 TestClient 会把绝对URL再次喂回本应用形成重定向循环，
        # 且交互文档端点不应借 dev server 重定向"复活"
        if not _docs_enabled and path in ("docs", "redoc", "openapi.json"):
            raise HTTPException(404)
        return RedirectResponse(_dev_url())
