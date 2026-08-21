"""2026-08 安全审计修复的回归测试。

覆盖：
- tasks._output_dir 的 task_id 白名单（".." 曾使产物端点退化为整个 data 目录）
- instances SSRF 过滤加固（0.0.0.0/组播/未指定/IPv6-mapped/URL 内嵌凭据）
- config 更新白名单值校验（frontend_dev_url 开放重定向收口）
- app.utils.filename.safe_segment 的 Windows 保留名/尾部点空格/NFKC 处理
- supply 防火墙的无空格列表形式绕过封堵
- tool_manager LIKE 通配符转义
"""

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from app.security.supply import SupplyChainFirewall  # noqa: E402
from app.utils.filename import safe_segment  # noqa: E402


@pytest.fixture
def fw():
    return SupplyChainFirewall()


# ---------- P1: tasks 产物端点 task_id 白名单 ----------


def test_output_dir_rejects_dotdot():
    """task_id=".." 在旧实现下会返回 data 根目录本身（列目录/下载全库）。"""
    from app.web.routers.tasks import _output_dir

    out_root = Path("data") / "outputs"
    (out_root / "task-real123").mkdir(parents=True, exist_ok=True)
    try:
        assert _output_dir("..") is None
        assert _output_dir(".") is None
        assert _output_dir("a/b") is None
        assert _output_dir("..\\..\\etc") is None
        assert _output_dir("task id with space") is None
        real = _output_dir("task-real123")
        assert real is not None
        assert Path(real).name == "task-real123"
    finally:
        import shutil

        shutil.rmtree(out_root, ignore_errors=True)


# ---------- P1: instances SSRF 过滤 ----------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://0.0.0.0:8000/v1",
        "http://[::]/v1",
        "http://224.0.0.1/v1",
        "http://[::ffff:127.0.0.1]/v1",
        "http://169.254.169.254/latest/meta-data",
    ],
)
async def test_ssrf_rejects_dangerous_literal_targets(url):
    from app.web.routers.instances import _reject_ssrf_target

    with pytest.raises(HTTPException):
        await _reject_ssrf_target(url)


@pytest.mark.asyncio
async def test_ssrf_allows_public_literal_without_dns():
    """公网字面量 IP 直接放行，不需要 DNS（离线 CI 可跑）。"""
    from app.web.routers.instances import _reject_ssrf_target

    await _reject_ssrf_target("https://93.184.216.34/v1")


@pytest.mark.asyncio
async def test_ssrf_rejects_embedded_credentials():
    from app.web.routers.instances import _reject_ssrf_target

    with pytest.raises(HTTPException):
        await _reject_ssrf_target("http://user:pass@93.184.216.34/v1")


def test_endpoint_static_validation():
    from app.web.routers.instances import _validate_endpoint_static

    with pytest.raises(HTTPException):
        _validate_endpoint_static("http://0.0.0.0:8000")
    with pytest.raises(HTTPException):
        _validate_endpoint_static("ftp://93.184.216.34")
    with pytest.raises(HTTPException):
        _validate_endpoint_static("http://admin:pw@example.com/v1")
    _validate_endpoint_static("https://api.example.com/v1")


# ---------- P2: frontend_dev_url 值校验（开放重定向收口）----------


def test_dev_url_value_whitelist():
    from app.web.routers.config import _validate_update_value

    with pytest.raises(HTTPException):
        _validate_update_value("server.frontend_dev_url", "https://evil.example")
    with pytest.raises(HTTPException):
        _validate_update_value("server.frontend_dev_url", "http://192.168.1.5:3000")
    assert (
        _validate_update_value("server.frontend_dev_url", " http://127.0.0.1:3000/ ")
        == "http://127.0.0.1:3000/"
    )
    assert _validate_update_value("system.log_level", "DEBUG") == "DEBUG"


# ---------- P2: Windows 文件名消毒 ----------


@pytest.mark.parametrize(
    "raw,expect",
    [
        ("CON", "_CON"),
        ("con.txt", "_con.txt"),
        ("NUL", "_NUL"),
        ("com1", "_com1"),
        ("LPT9.log", "_LPT9.log"),
        ("evil.py.", "evil.py"),
        ("script .py", "script .py"),
        ("a:b$c.txt", "a_b$c.txt"),
        ("model_v2.py", "model_v2.py"),
        ("\uff23\uff4f\uff4e", "_Con"),  # 全角小写混排：IGNORECASE 命中保留名
    ],
)
def test_safe_segment(raw, expect):
    assert safe_segment(raw) == expect


def test_safe_segment_degenerate_to_empty():
    assert safe_segment("..") == ""
    assert safe_segment("...") == ""
    assert safe_segment("   ") == ""


# ---------- P2: supply 列表形式绕过封堵 ----------


def test_supply_blocks_list_form_pip(fw):
    cmd = 'subprocess.run(["pip", "install", "requests-fake"])'
    assert fw.check_install_command(cmd) is False
    cmd_nospace = 'subprocess.run(["pip","install","requests_fake"])'
    assert fw.check_install_command(cmd_nospace) is False


def test_supply_blocks_list_form_python_m_pip(fw):
    cmd = 'subprocess.run(["python", "-m", "pip", "install", "secrethash"])'
    assert fw.check_install_command(cmd) is False


def test_supply_blocks_list_form_npm(fw):
    cmd = "run(['npm', 'add', 'evil-package'])"
    assert fw.check_install_command(cmd) is False


def test_supply_list_form_clean_packages_pass(fw):
    cmd = 'subprocess.run(["pip", "install", "numpy", "pandas"])'
    assert fw.check_install_command(cmd) is True
    cmd_js = "exec(['npm','install','left-pad'])"
    assert fw.check_install_command(cmd_js) is True


# ---------- P2: LIKE 通配符转义 ----------


def test_like_literal_escapes_wildcards():
    from app.agents.tool_manager import _like_literal

    assert _like_literal("100%") == "100\\%"
    assert _like_literal("a_b") == "a\\_b"
    assert _like_literal("back\\slash") == "back\\\\slash"
    assert _like_literal("plain") == "plain"


# ---------- updater：更新包 URL 白名单回归 ----------


def test_zip_download_url_host_whitelist_still_holds():
    from app.core.updater import Updater, _validate_zip_download_url

    repo = "Ameiro-sudo/IReckon"
    assert _validate_zip_download_url(
        "https://github.com/Ameiro-sudo/IReckon/releases/download/v1/a.zip", repo
    )
    assert not _validate_zip_download_url(
        "https://evil.com/?x=Ameiro-sudo/IReckon/a.zip", repo
    )
    assert not _validate_zip_download_url(
        "http://github.com/Ameiro-sudo/IReckon/releases/download/v1/a.zip", repo
    )
    Updater()
