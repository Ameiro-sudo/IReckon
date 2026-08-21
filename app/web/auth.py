"""API 鉴权：token 校验与信任边界判定。

设计原则（fail-closed）：
- token 来源优先级：IRECKON_API_TOKEN 环境变量 > config.yaml 的 security.api_token
  > 启动时自动生成的随机 token（持久化回 config.yaml，仅持久化失败时本次运行内有效）；
- 首次启动无 token 时自动生成随机 token 并打印到控制台，用户在前端登录页粘贴后
  存入浏览器 localStorage（Jupyter/VS Code 模式）；
- 高危端点（自我进化、自更新等可改写程序自身的操作）：必须显式携带有效 token。
"""

import os
import secrets
from typing import Optional

from fastapi import Header, HTTPException, Request
from loguru import logger

from app.core.config import get, config_manager

# 鉴权豁免路径：登录校验、健康检查与主题加载无需 token
AUTH_EXEMPT_PATHS = {"/api/health", "/api/themes", "/api/auth/check"}

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

# 自动生成且未能持久化时的运行时兜底 token
_runtime_token: str = ""


def generate_api_token() -> str:
    """生成 256-bit 随机 API token。"""
    return "irk_" + secrets.token_urlsafe(32)


def ensure_token() -> str:
    """启动时调用：确保存在可用 token，必要时自动生成并持久化到 config.yaml。

    返回当前生效的 token（供启动横幅打印）。
    """
    global _runtime_token
    env_token = os.environ.get("IRECKON_API_TOKEN", "").strip()
    if env_token:
        return env_token
    cfg_token = str(get("security.api_token", "") or "").strip()
    if cfg_token:
        return cfg_token

    token = generate_api_token()
    _runtime_token = token
    persisted = False
    try:
        persisted = config_manager.save_value("security.api_token", token)
    except Exception as exc:
        logger.warning(f"API token 持久化异常（仅本次运行有效）: {exc}")
    if persisted:
        logger.info("已自动生成随机 API token 并写入 config/config.yaml")
    else:
        logger.warning("API token 未能持久化，重启后将重新生成（仅本次运行有效）")
    return token


def configured_token() -> str:
    """读取鉴权 token：环境变量优先，其次 config.yaml，最后运行时兜底 token。"""
    return (
        os.environ.get("IRECKON_API_TOKEN", "")
        or str(get("security.api_token", "") or "")
        or _runtime_token
    )


def server_bound_loopback() -> bool:
    """服务绑定地址是否为回环地址（决定未配置 token 时的信任边界）。"""
    return str(get("server.host", "127.0.0.1") or "").strip().lower() in _LOOPBACK_HOSTS


def warn_if_insecure() -> None:
    """启动时提示当前鉴权态势（供 main.initialize 调用；正常情况下 ensure_token
    已保证 token 存在，此函数仅在异常兜底场景给出提示）。"""
    if not configured_token() and not server_bound_loopback():
        logger.warning(
            "未配置 API token 且服务绑定非回环地址：所有 API/WS 将拒绝远程访问，"
            "请设置 IRECKON_API_TOKEN 后重启"
        )


def _verify(x_api_token: Optional[str], token: str) -> None:
    if not x_api_token or not secrets.compare_digest(x_api_token, token):
        raise HTTPException(status_code=401, detail="Unauthorized")


async def require_api_token(
    request: Request, x_api_token: Optional[str] = Header(None)
) -> None:
    """全局 /api/* 鉴权依赖。"""
    if request.url.path in AUTH_EXEMPT_PATHS:
        return
    token = configured_token()
    if not token:
        if not server_bound_loopback():
            raise HTTPException(
                status_code=401,
                detail="API token 未配置且服务绑定非回环地址，已拒绝访问；"
                "请设置 IRECKON_API_TOKEN 或将 server.host 改为 127.0.0.1",
            )
        return
    _verify(x_api_token, token)


async def require_strict_token(x_api_token: Optional[str] = Header(None)) -> None:
    """高危端点鉴权：必须显式配置并携带 token，本机回环也不例外。"""
    token = configured_token()
    if not token:
        raise HTTPException(
            status_code=403,
            detail="该端点为高危操作，需先配置 IRECKON_API_TOKEN"
            "（或 security.api_token）后携带 X-API-Token 调用",
        )
    _verify(x_api_token, token)


def has_strict_token(x_api_token: Optional[str]) -> bool:
    """供需要"降级响应"的端点判断调用方是否持有有效 strict token。"""
    token = configured_token()
    if not token or not x_api_token:
        return False
    try:
        return bool(secrets.compare_digest(x_api_token, token))
    except Exception:
        return False


# --- WebSocket 握手鉴权（子协议优先） ---
#
# token 走 Sec-WebSocket-Protocol 头：客户端以 ["ireckon.v1", <token>] 请求子协议，
# 服务端校验后只回显常量服务名。token 不再进入 URL——反代 access_log、浏览器
# 历史、Referer 泄漏面归零（上反向代理前的强制项，见安全审计留档）。
# 查询参数 ?token= 仅作旧外部脚本兼容保留，使用时会打一次弃用告警。
WS_SUBPROTOCOL = "ireckon.v1"

_query_token_warned = False


def _ws_requested_protocols(websocket) -> list:
    """解析 Sec-WebSocket-Protocol 头为去空白协议名列表。"""
    header = websocket.headers.get("sec-websocket-protocol", "")
    return [p.strip() for p in header.split(",") if p.strip()]


def ws_handshake(websocket):
    """校验 WebSocket 握手，返回 (authorized, subprotocol)。

    - authorized：是否放行（无 token 配置时沿用回环信任边界语义）；
    - subprotocol：客户端请求了本服务子协议时 accept 应回显的名称
      （只回显常量服务名，不把 token 原样写回响应头），否则 None。
    """
    global _query_token_warned
    token = configured_token()
    requested = _ws_requested_protocols(websocket)
    subprotocol = WS_SUBPROTOCOL if WS_SUBPROTOCOL in requested else None

    if not token:
        return server_bound_loopback(), subprotocol

    supplied = ""
    if len(requested) >= 2 and requested[0] == WS_SUBPROTOCOL:
        # 子协议二元组：<公开服务名>, <凭据>
        supplied = requested[1]
    elif websocket.query_params.get("token"):
        supplied = str(websocket.query_params.get("token", ""))
        if not _query_token_warned:
            _query_token_warned = True
            logger.warning(
                "WebSocket 鉴权使用了 ?token= 查询参数（已弃用）："
                f"请改用 Sec-WebSocket-Protocol ['{WS_SUBPROTOCOL}', <token>]，"
                "避免 token 进入 URL 与访问日志"
            )
    authorized = bool(supplied) and secrets.compare_digest(supplied, token)
    return authorized, subprotocol
