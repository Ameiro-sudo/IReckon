"""WebSocket 握手鉴权测试：Sec-WebSocket-Protocol 子协议优先、查询参数兼容、信任边界。

背景（安全审计遗留项）：token 原先只能走 URL 查询参数，会落入反代 access_log /
浏览器历史 / Referer。现改为客户端以子协议二元组 [WS_SUBPROTOCOL, <token>] 传递，
查询参数仅作旧脚本兼容保留。
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from loguru import logger
from starlette.websockets import WebSocketDisconnect

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import app.web.auth as auth
from app.web.api import app
from app.web.push import ConnectionManager

TOKEN = "irk_test_token_abc123"
WS_DEPRECATION_MARK = "已弃用"


class _StubWS:
    """ws_handshake 单测桩：只暴露 headers 与 query_params 两个读取面。"""

    def __init__(self, protocols=None, query=None):
        self.headers = (
            {"sec-websocket-protocol": ", ".join(protocols)} if protocols else {}
        )
        self.query_params = query or {}


@pytest.fixture(autouse=True)
def _fixed_token(monkeypatch):
    # 隔离本机 config.yaml 的真实 token，保证断言确定性
    monkeypatch.setattr(auth, "configured_token", lambda: TOKEN)


def _ping_pong(ws):
    ws.send_text("ping")
    assert ws.receive_json()["type"] == "pong"


# --- 端到端握手矩阵 ---


def test_subprotocol_pair_authorized():
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws", subprotocols=[auth.WS_SUBPROTOCOL, TOKEN]
        ) as ws:
            _ping_pong(ws)


def test_wrong_token_in_subprotocol_denied():
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                "/ws", subprotocols=[auth.WS_SUBPROTOCOL, "irk_wrong"]
            ):
                pass
    assert exc_info.value.code == 4401


def test_no_credentials_denied():
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws"):
                pass
    assert exc_info.value.code == 4401


def test_query_param_fallback_still_authorized():
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws?token={TOKEN}"):
            pass


def test_query_param_wrong_token_denied():
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws?token=irk_wrong"):
                pass
    assert exc_info.value.code == 4401


def test_service_name_without_token_slot_falls_back_to_query():
    # 只带服务名不带凭据位：不满足子协议二元组形态，回落查询参数判定
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect("/ws", subprotocols=[auth.WS_SUBPROTOCOL]):
                pass
        assert denied.value.code == 4401
        with client.websocket_connect(
            f"/ws?token={TOKEN}", subprotocols=[auth.WS_SUBPROTOCOL]
        ):
            pass


def test_task_scoped_endpoint_same_semantics():
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/task-1", subprotocols=[auth.WS_SUBPROTOCOL, TOKEN]
        ):
            pass
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws/task-1"):
                pass
    assert exc_info.value.code == 4401


def test_unconfigured_token_loopback_trust_boundary(monkeypatch):
    monkeypatch.setattr(auth, "configured_token", lambda: "")
    monkeypatch.setattr(auth, "server_bound_loopback", lambda: True)
    with TestClient(app) as client:
        # 无凭据也可连（与原 ws_authorized 回环信任语义一致）
        with client.websocket_connect("/ws"):
            pass


def test_unconfigured_token_remote_denied(monkeypatch):
    monkeypatch.setattr(auth, "configured_token", lambda: "")
    monkeypatch.setattr(auth, "server_bound_loopback", lambda: False)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws"):
                pass
    assert exc_info.value.code == 4401


def test_query_param_deprecation_warned_once(monkeypatch):
    monkeypatch.setattr(auth, "_query_token_warned", False)
    records = []
    sink_id = logger.add(records.append)
    try:
        with TestClient(app) as client:
            with client.websocket_connect(f"/ws?token={TOKEN}"):
                pass
            with client.websocket_connect(f"/ws/task-2?token={TOKEN}"):
                pass
    finally:
        logger.remove(sink_id)
    warnings = [r for r in records if WS_DEPRECATION_MARK in str(r)]
    assert len(warnings) == 1


# --- ws_handshake 解析细节（桩测） ---


def test_handshake_echoes_constant_not_token():
    authorized, subprotocol = auth.ws_handshake(_StubWS([auth.WS_SUBPROTOCOL, TOKEN]))
    assert authorized is True
    # 只回显常量服务名，绝不把 token 原样写回响应头
    assert subprotocol == auth.WS_SUBPROTOCOL


def test_handshake_credential_slot_is_positional_strict():
    # 凭据只认紧随服务名的第二位，不扫描全列表——防止形似列表混入合法 token 放行
    authorized, _ = auth.ws_handshake(_StubWS([auth.WS_SUBPROTOCOL, "bad", TOKEN]))
    assert authorized is False


def test_handshake_foreign_protocol_not_echoed():
    authorized, subprotocol = auth.ws_handshake(_StubWS(["other.v9", TOKEN]))
    assert authorized is False
    assert subprotocol is None


def test_handshake_header_whitespace_tolerant():
    stub = _StubWS()
    stub.headers["sec-websocket-protocol"] = "  ireckon.v1 ,  ,  " + TOKEN + " "
    authorized, subprotocol = auth.ws_handshake(stub)
    assert authorized is True
    assert subprotocol == auth.WS_SUBPROTOCOL


def test_handshake_subprotocol_with_invalid_token_denies_despite_valid_query():
    # 子协议形态优先于查询参数：带了错误凭据位时，即使 query 合法也不放行
    stub = _StubWS([auth.WS_SUBPROTOCOL, "bad"], query={"token": TOKEN})
    authorized, _ = auth.ws_handshake(stub)
    assert authorized is False


# --- manager.connect 子协议回显 ---


class _FakeSocket:
    def __init__(self):
        self.accepted_with = None

    async def accept(self, subprotocol=None):
        self.accepted_with = subprotocol


async def test_manager_connect_passes_negotiated_subprotocol():
    manager = ConnectionManager()
    sock = _FakeSocket()
    await manager.connect(sock, None, subprotocol=auth.WS_SUBPROTOCOL)
    assert sock.accepted_with == auth.WS_SUBPROTOCOL
    await manager.disconnect(sock)

    plain = _FakeSocket()
    await manager.connect(plain, None)
    assert plain.accepted_with is None
    await manager.disconnect(plain)
