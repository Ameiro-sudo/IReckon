"""更新渠道测试(补双渠道发行)：渠道解析、资产选择、installer/portable 双流程。"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


import app.core.updater as updater_mod
from app.core.updater import Updater


def _up(tmp_path):
    up = Updater.__new__(Updater)
    up._repo = "Ameiro-sudo/IReckon"
    up._github_api = "https://api.github.com/repos/Ameiro-sudo/IReckon"
    up._current_version = "0.1.0"
    up._max_zip_bytes = 10 * 1024 * 1024
    up._last_check_file = tmp_path / ".lc"
    return up


class FakeResp:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload or {}
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeStreamResp(FakeResp):
    def __init__(self, content=b"DATA"):
        super().__init__()
        self.status_code = 200
        self._c = content

    async def aiter_bytes(self, n):
        yield self._c


class FakeClient:
    def __init__(self, release_resp, dl_content=b"DATA"):
        self._r = release_resp
        self._dl = dl_content

    async def get(self, url):
        return self._r

    def stream(self, method, url):
        outer = self

        class Ctx:
            async def __aenter__(self):
                return FakeStreamResp(outer._dl)

            async def __aexit__(self, *a):
                return False

        return Ctx()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


ASSETS = [
    {
        "name": "IReckon-Setup-0.2.0-win64.exe",
        "browser_download_url": "https://github.com/Ameiro-sudo/IReckon/releases/download/v0.2.0/IReckon-Setup-0.2.0-win64.exe",
    },
    {
        "name": "IReckon-Portable-0.2.0-win64.zip",
        "browser_download_url": "https://github.com/Ameiro-sudo/IReckon/releases/download/v0.2.0/IReckon-Portable-0.2.0-win64.zip",
    },
    {
        "name": "source.tar.gz",
        "browser_download_url": "https://github.com/x/y/archive/v1.tar.gz",
    },
]


# ---------- _resolve_channel ----------


def _patch_frozen(monkeypatch, frozen, exe_dir=None):
    monkeypatch.setattr(updater_mod.sys, "frozen", frozen, raising=False)
    if exe_dir:
        monkeypatch.setattr(
            updater_mod.sys, "executable", str(exe_dir / "IReckon.exe"), raising=False
        )


def test_resolve_explicit_overrides_all(monkeypatch, tmp_path):
    up = _up(tmp_path)
    assert up._resolve_channel("installer") == "installer"


def test_resolve_auto_source_tree_is_portable(monkeypatch, tmp_path):
    _patch_frozen(monkeypatch, False)
    assert _up(tmp_path)._resolve_channel() == "portable"


def test_resolve_auto_portable_when_no_uninstaller(monkeypatch, tmp_path):
    _patch_frozen(monkeypatch, True, tmp_path)
    assert _up(tmp_path)._resolve_channel() == "portable"


def test_resolve_auto_installer_when_uninstaller_present(monkeypatch, tmp_path):
    (tmp_path / "unins000.exe").write_bytes(b"")
    _patch_frozen(monkeypatch, True, tmp_path)
    assert _up(tmp_path)._resolve_channel() == "installer"


# ---------- _select_asset ----------


def test_select_installer_asset():
    url, name = Updater._select_asset(ASSETS, "installer")
    assert name.startswith("ireckon-setup-") and url.endswith(".exe")


def test_select_portable_asset():
    url, name = Updater._select_asset(ASSETS, "portable")
    assert name.startswith("ireckon-portable-") and url.endswith(".zip")


def test_select_skips_source_archives():
    only_src = [
        {
            "name": "source.zip",
            "browser_download_url": "https://github.com/a/b/releases/download/v1/source.zip",
        }
    ]
    # source.zip 不带 ireckon-portable- 前缀，不得被误选
    assert Updater._select_asset(only_src, "portable") == ("", "")


# ---------- download_and_update 双流程 ----------


def _run_download(monkeypatch, tmp_path, channel, assets=ASSETS, silent=False):
    up = _up(tmp_path)
    launched = {}

    class FakeProc:
        pass

    def fake_popen(args, **kw):
        launched["args"] = args
        return FakeProc()

    monkeypatch.setattr(updater_mod.subprocess, "Popen", fake_popen)

    applied = {}

    async def fake_apply(zip_path, version, base_dir=None):
        applied["zip"] = zip_path
        return True

    if channel == "portable":
        # 实例级打桩：打在类上会把 self 串进第一参数
        up._apply_update = fake_apply

    release = FakeResp({"assets": assets})
    monkeypatch.setattr(
        updater_mod.httpx,
        "AsyncClient",
        lambda **kw: FakeClient(release, dl_content=b"PAYLOAD"),
    )
    ok = asyncio.run(up.download_and_update("0.2.0", channel=channel, silent=silent))
    return ok, launched, applied


def test_installer_flow_launches_setup(monkeypatch, tmp_path):
    ok, launched, applied = _run_download(monkeypatch, tmp_path, "installer")
    assert ok is True and not applied
    args = launched["args"]
    assert args[0].endswith(".exe") and Path(args[0]).exists()
    # 非 silent：不带静默参数；文件保留给安装进程
    assert len(args) == 1


def test_installer_silent_flags(monkeypatch, tmp_path):
    ok, launched, _ = _run_download(monkeypatch, tmp_path, "installer", silent=True)
    assert ok is True
    assert "/SILENT" in launched["args"]


def test_portable_flow_applies_zip_and_cleans(monkeypatch, tmp_path):
    ok, launched, applied = _run_download(monkeypatch, tmp_path, "portable")
    assert ok is True and "zip" in applied
    z = Path(applied["zip"])
    # 应用完成后临时包应清理
    assert not z.exists()


def test_missing_channel_asset_fails_gracefully(monkeypatch, tmp_path):
    setup_only = [ASSETS[0]]
    ok, _, applied = _run_download(monkeypatch, tmp_path, "portable", assets=setup_only)
    assert ok is False and not applied


def test_invalid_version_rejected(monkeypatch, tmp_path):
    up = _up(tmp_path)
    assert asyncio.run(up.download_and_update("not-a-version")) is False
