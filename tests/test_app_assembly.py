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


def test_security_headers_present():
    with TestClient(app) as c:
        r = c.get("/api/health")
        csp = r.headers.get("content-security-policy", "")
        # CSP 关键指令：脚本仅限自身、对象/框架全禁
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "object-src 'none'" in csp
        assert "frame-ancestors 'none'" in csp
        # WebSocket 来源收敛为页面自身 authority（不再放行任意 ws:/wss: 外域）
        assert "connect-src 'self' ws://testserver wss://testserver" in csp
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.headers.get("x-frame-options") == "DENY"
        # API 敏感响应禁缓存
        assert r.headers.get("cache-control") == "no-store"


def test_csp_host_fallback_and_validation_error_sanitized():
    from fastapi.testclient import TestClient as _TC  # noqa: F401  # 确保同环境

    with TestClient(app) as c:
        # Host 异常（含非法字符）时回退纯 'self'，不注入畸形来源
        r = c.get("/api/health", headers={"Host": "evil.example_bad*host"})
        csp = r.headers.get("content-security-policy", "")
        assert "connect-src 'self'" in csp
        assert "evil.example" not in csp
        # 校验错误只回显 loc/msg：不泄露提交值(input)与内部断言(ctx)
        bad = c.post("/api/tasks", json={"user_request": {"nested": "secret"}})
        if bad.status_code == 422:
            detail = bad.json()["detail"]
            assert isinstance(detail, list)
            assert all(set(e) <= {"loc", "msg"} for e in detail)


def test_csp_self_hosts_fonts_and_blocks_foreign_scripts():
    with TestClient(app) as c:
        csp = c.get("/api/health").headers.get("content-security-policy", "")
        # 字体已自托管（frontend/public/fonts/），CSP 不放行任何字体外域
        assert "fonts.googleapis.com" not in csp
        assert "fonts.gstatic.com" not in csp
        assert "style-src 'self' 'unsafe-inline'" in csp
        assert "font-src 'self'" in csp
        # 脚本来源绝不包含外域
        script_part = [p for p in csp.split("; ") if p.startswith("script-src")][0]
        assert "http" not in script_part.replace("script-src 'self'", "").strip()
