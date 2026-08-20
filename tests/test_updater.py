"""更新器测试:zip 安全解压、版本替换、应用与回滚。"""

import asyncio
import io
import zipfile

import pytest

import app.core.updater as updater_mod
from app.core.updater import Updater


def _make_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def make_updater(monkeypatch):
    cfg = {
        "self_update.repo": "Ameiro-sudo/IReckon",
        "system.version": "0.1.0",
        "self_update.check_interval_hours": 24,
        "system.data_dir": "./data",
    }
    monkeypatch.setattr(
        updater_mod.config_manager, "get", lambda k, d=None: cfg.get(k, d)
    )
    return Updater()


@pytest.fixture
def base_tree(tmp_path):
    base = tmp_path / "base"
    (base / "app" / "engine").mkdir(parents=True)
    (base / "config").mkdir()
    (base / "data").mkdir()
    (base / "app" / "engine" / "cost.py").write_text("old", encoding="utf-8")
    (base / "config" / "config.yaml").write_text(
        "system:\n  version: 0.1.0\n", encoding="utf-8"
    )
    (base / "data" / "user.db").write_text("keep", encoding="utf-8")
    return base


# ---------- 安全解压 ----------


def test_safe_extract_rejects_traversal(monkeypatch, tmp_path):
    imp = make_updater(monkeypatch)
    dest = tmp_path / "dest"
    dest.mkdir()
    bad_names = [
        "../evil.py",
        "/abs.py",
        "a/../../evil.py",
        "C:/evil.py",
        "C:evil.py",
        "..\\evil.py",
    ]
    for name in bad_names:
        with zipfile.ZipFile(io.BytesIO(_make_zip({name: "x"}))) as zf:
            with pytest.raises(ValueError):
                imp._safe_extract(zf, dest)


def test_safe_extract_ok(monkeypatch, tmp_path):
    imp = make_updater(monkeypatch)
    dest = tmp_path / "dest"
    data = _make_zip({"app/x.py": "print(1)", "dir/": "", "dir/sub/": ""})
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        imp._safe_extract(zf, dest)
    assert (dest / "app" / "x.py").read_text() == "print(1)"
    assert (dest / "dir").is_dir()


# ---------- 应用与回滚 ----------


def test_apply_update_success(monkeypatch, tmp_path, base_tree):
    imp = make_updater(monkeypatch)
    zip_path = tmp_path / "pkg.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("IReckon/app/engine/cost.py", "new")
        zf.writestr("IReckon/README.md", "readme")

    ok = asyncio.run(imp._apply_update(str(zip_path), "0.2.0", base_dir=base_tree))
    assert ok
    assert (base_tree / "app" / "engine" / "cost.py").read_text(
        encoding="utf-8"
    ) == "new"
    assert (base_tree / "README.md").read_text(encoding="utf-8") == "readme"
    assert "version: 0.2.0" in (base_tree / "config" / "config.yaml").read_text(
        encoding="utf-8"
    )
    assert (base_tree / "data" / "user.db").exists()
    assert (tmp_path / "backup_v0.1.0").is_dir()


def test_apply_update_multiple_top_level(monkeypatch, tmp_path, base_tree):
    imp = make_updater(monkeypatch)
    zip_path = tmp_path / "pkg.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("app/engine/cost.py", "new")
        zf.writestr("config/settings.json", "{}")

    ok = asyncio.run(imp._apply_update(str(zip_path), "0.2.0", base_dir=base_tree))
    assert ok
    assert (base_tree / "app" / "engine" / "cost.py").read_text(
        encoding="utf-8"
    ) == "new"
    assert (base_tree / "config" / "settings.json").exists()


def test_apply_update_zip_slip_rejected(monkeypatch, tmp_path, base_tree):
    imp = make_updater(monkeypatch)
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../evil.py", "x")

    ok = asyncio.run(imp._apply_update(str(zip_path), "0.2.0", base_dir=base_tree))
    assert ok is False
    assert (base_tree / "app" / "engine" / "cost.py").read_text(
        encoding="utf-8"
    ) == "old"


def test_apply_update_failure_restores(monkeypatch, tmp_path, base_tree):
    imp = make_updater(monkeypatch)
    zip_path = tmp_path / "bad.zip"
    # 同一路径先作为文件、后作为目录出现 -> 解压必然冲突
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("app", "conflict")
        zf.writestr("app/engine/cost.py", "new")

    ok = asyncio.run(imp._apply_update(str(zip_path), "0.2.0", base_dir=base_tree))
    assert ok is False
    assert (base_tree / "app" / "engine" / "cost.py").read_text(
        encoding="utf-8"
    ) == "old"
    assert "version: 0.1.0" in (base_tree / "config" / "config.yaml").read_text(
        encoding="utf-8"
    )


def test_apply_update_version_not_found_keeps_files(monkeypatch, tmp_path, base_tree):
    imp = make_updater(monkeypatch)
    (base_tree / "config" / "config.yaml").write_text(
        "system:\n  version: 9.9.9\n", encoding="utf-8"
    )
    zip_path = tmp_path / "pkg.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("IReckon/app/engine/cost.py", "new")

    ok = asyncio.run(imp._apply_update(str(zip_path), "0.2.0", base_dir=base_tree))
    assert ok
    assert "version: 9.9.9" in (base_tree / "config" / "config.yaml").read_text(
        encoding="utf-8"
    )
    assert (base_tree / "app" / "engine" / "cost.py").read_text(
        encoding="utf-8"
    ) == "new"


# ---------- 版本检查（回归: resp.get 曾导致 check 恒返回 None） ----------


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, resp):
        self._resp = resp

    async def get(self, url):
        return self._resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def test_check_detects_new_version(monkeypatch):
    imp = make_updater(monkeypatch)
    monkeypatch.setattr(
        updater_mod.httpx,
        "AsyncClient",
        lambda **kw: FakeClient(FakeResponse({"tag_name": "v0.2.0"})),
    )
    latest = asyncio.run(imp.check())
    assert latest == "0.2.0"


def test_check_no_new_version(monkeypatch):
    imp = make_updater(monkeypatch)
    monkeypatch.setattr(
        updater_mod.httpx,
        "AsyncClient",
        lambda **kw: FakeClient(FakeResponse({"tag_name": "v0.0.9"})),
    )
    assert asyncio.run(imp.check()) is None


def test_check_http_error_returns_none(monkeypatch):
    imp = make_updater(monkeypatch)
    monkeypatch.setattr(
        updater_mod.httpx,
        "AsyncClient",
        lambda **kw: FakeClient(FakeResponse({}, status_code=404)),
    )
    assert asyncio.run(imp.check()) is None
