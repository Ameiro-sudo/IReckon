"""更新渠道测试(补双渠道发行)：渠道解析、资产选择、installer/portable 双流程、SHA-256 校验门。"""

import asyncio
import hashlib
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


import app.core.updater as updater_mod
from app.core.updater import Updater

# 伪造下载体的真实摘要：校验门 happy path 与 mismatch 用例共用
PAYLOAD = b"PAYLOAD"
PAYLOAD_SHA256 = hashlib.sha256(PAYLOAD).hexdigest()
CHECKSUMS_TXT = (
    f"{PAYLOAD_SHA256}  IReckon-Setup-0.2.0-win64.exe\n"
    f"# 注释行与空行应被忽略\n\n"
    f"{PAYLOAD_SHA256.upper()}  IReckon-Portable-0.2.0-win64.zip\n"
)


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
    def __init__(self, content=b"DATA", status_code=200):
        super().__init__()
        self.status_code = status_code
        self._c = content

    async def aiter_bytes(self, n):
        yield self._c


class FakeClient:
    """按 URL 路由的假客户端：release API 走 get，资产/清单下载走 stream。"""

    def __init__(
        self,
        release_resp,
        dl_content=b"DATA",
        checksum_text=CHECKSUMS_TXT,
        checksum_status=200,
    ):
        self._r = release_resp
        self._dl = dl_content
        self._cs_text = checksum_text
        self._cs_status = checksum_status
        self.streamed_urls = []

    async def get(self, url):
        return self._r

    def stream(self, method, url):
        outer = self
        outer.streamed_urls.append(url)
        if "checksums.txt" in url:
            body = outer._cs_text.encode("utf-8")
            status = outer._cs_status
        else:
            body, status = outer._dl, 200

        class Ctx:
            async def __aenter__(self):
                return FakeStreamResp(body, status)

            async def __aexit__(self, *a):
                return False

        return Ctx()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


CHECKSUM_ASSET = {
    "name": "checksums.txt",
    "browser_download_url": "https://github.com/Ameiro-sudo/IReckon/releases/download/v0.2.0/checksums.txt",
}
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
    CHECKSUM_ASSET,
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


def _run_download(
    monkeypatch,
    tmp_path,
    channel,
    assets=ASSETS,
    silent=False,
    checksum_text=CHECKSUMS_TXT,
    checksum_status=200,
):
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
    client = FakeClient(
        release,
        dl_content=PAYLOAD,
        checksum_text=checksum_text,
        checksum_status=checksum_status,
    )
    monkeypatch.setattr(updater_mod.httpx, "AsyncClient", lambda **kw: client)
    ok = asyncio.run(up.download_and_update("0.2.0", channel=channel, silent=silent))
    return ok, launched, applied, client


def test_installer_flow_launches_setup(monkeypatch, tmp_path):
    ok, launched, applied, _ = _run_download(monkeypatch, tmp_path, "installer")
    assert ok is True and not applied
    args = launched["args"]
    assert args[0].endswith(".exe") and Path(args[0]).exists()
    # 非 silent：不带静默参数；文件保留给安装进程
    assert len(args) == 1


def test_installer_silent_flags(monkeypatch, tmp_path):
    ok, launched, _, _ = _run_download(monkeypatch, tmp_path, "installer", silent=True)
    assert ok is True
    assert "/SILENT" in launched["args"]


def test_portable_flow_applies_zip_and_cleans(monkeypatch, tmp_path):
    ok, launched, applied, client = _run_download(monkeypatch, tmp_path, "portable")
    assert ok is True and "zip" in applied
    # 校验清单先于资产下载（先取摘要再落地文件）
    assert client.streamed_urls[0].endswith("checksums.txt")
    z = Path(applied["zip"])
    # 应用完成后临时包应清理
    assert not z.exists()


def test_missing_channel_asset_fails_gracefully(monkeypatch, tmp_path):
    setup_only = [ASSETS[0], CHECKSUM_ASSET]
    ok, _, applied, _ = _run_download(
        monkeypatch, tmp_path, "portable", assets=setup_only
    )
    assert ok is False and not applied


def test_invalid_version_rejected(monkeypatch, tmp_path):
    up = _up(tmp_path)
    assert asyncio.run(up.download_and_update("not-a-version")) is False


# ---------- SHA-256 校验门（用户决策：哈希完整性校验，fail-closed） ----------


def test_missing_checksum_manifest_fails_closed(monkeypatch, tmp_path):
    assets = [a for a in ASSETS if a["name"] != "checksums.txt"]
    ok, _, applied, client = _run_download(
        monkeypatch, tmp_path, "portable", assets=assets
    )
    assert ok is False and not applied
    # 清单缺失时连资产下载都不应发起
    assert all(not u.endswith(".zip") for u in client.streamed_urls)


def test_checksum_mismatch_rejects_and_cleans(monkeypatch, tmp_path):
    # 两行条目全部换成错误摘要（'f'*64 是合法 hex 但必不等于真实摘要）
    bad_manifest = "\n".join(
        f"{'f' * 64}  {name}"
        for name in (
            "IReckon-Setup-0.2.0-win64.exe",
            "IReckon-Portable-0.2.0-win64.zip",
        )
    )
    ok, _, applied, _ = _run_download(
        monkeypatch, tmp_path, "portable", checksum_text=bad_manifest
    )
    assert ok is False and not applied
    # 被拒的残留更新包任何渠道都不应留在临时目录
    leftover = Path(tempfile.gettempdir()) / "IReckon-update-portable-0.2.0.zip"
    assert not leftover.exists()


def test_checksum_entry_missing_for_asset_fails(monkeypatch, tmp_path):
    partial = f"{PAYLOAD_SHA256}  IReckon-Setup-0.2.0-win64.exe\n"
    ok, _, applied, _ = _run_download(
        monkeypatch, tmp_path, "portable", checksum_text=partial
    )
    assert ok is False and not applied


def test_checksum_http_error_fails_closed(monkeypatch, tmp_path):
    ok, _, applied, _ = _run_download(
        monkeypatch, tmp_path, "portable", checksum_status=404
    )
    assert ok is False and not applied


def test_malformed_manifest_fails_closed(monkeypatch, tmp_path):
    ok, _, applied, _ = _run_download(
        monkeypatch, tmp_path, "portable", checksum_text="not a checksum list\n"
    )
    assert ok is False and not applied


# ---------- 清单解析纯函数 ----------


def test_parse_checksums_standard_binary_marker_comments():
    text = (
        "# comment\n"
        f"{PAYLOAD_SHA256}  app.zip\n"
        f"{PAYLOAD_SHA256.upper()} *app-bin.zip\n"
        "garbage-line\n"
        "\n"
        "zzzz  short-hash.bin\n"
    )
    digests = Updater._parse_checksums(text)
    assert digests == {
        "app.zip": PAYLOAD_SHA256,
        "app-bin.zip": PAYLOAD_SHA256,
    }


def test_parse_checksums_filename_with_spaces():
    text = f"{PAYLOAD_SHA256}  my release file name.zip\n"
    assert Updater._parse_checksums(text) == {
        "my release file name.zip": PAYLOAD_SHA256
    }


def test_find_checksum_url_case_insensitive_exact_name():
    assets = [
        {
            "name": "Checksums.TXT",
            "browser_download_url": "https://github.com/a/b/releases/download/v1/checksums.txt",
        },
        {
            "name": "checksums.txt.bak",
            "browser_download_url": "https://github.com/a/b/x",
        },
    ]
    assert Updater._find_checksum_url(assets).endswith("/v1/checksums.txt")
    assert Updater._find_checksum_url([ASSETS[0]]) == ""
