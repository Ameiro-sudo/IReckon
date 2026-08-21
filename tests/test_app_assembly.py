"""app 装配层测试：lifespan 存活、交互文档默认关闭、CORS 来源白名单语义。"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app.web.api import app


def test_lifespan_runs_and_health_ok():
    # TestClient 会真正执行 lifespan(拉起日志消费者/心跳扫描并在退出时取消)
    with TestClient(app) as c:
        r = c.get("/api/health")
        assert r.status_code == 200


def test_interactive_docs_disabled_by_default():
    with TestClient(app) as c:
        # openapi.json 会暴露完整攻击面，默认必须关闭
        assert c.get("/docs").status_code == 404
        assert c.get("/redoc").status_code == 404
        assert c.get("/openapi.json").status_code == 404


def test_cors_allowlist_semantics():
    with TestClient(app) as c:
        allowed = c.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:8000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert allowed.headers.get("access-control-allow-origin") == (
            "http://localhost:8000"
        )

        # 白名单外来源：drive-by localhost 防护，不给跨域许可
        stranger = c.options(
            "/api/health",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert stranger.headers.get("access-control-allow-origin") is None


def test_cors_credentials_never_offered():
    with TestClient(app) as c:
        r = c.get("/api/health", headers={"Origin": "http://127.0.0.1:3000"})
        # allow_credentials=False：绝不出现允许携带凭据的响应头
        assert r.headers.get("access-control-allow-credentials") in (None, "false")
