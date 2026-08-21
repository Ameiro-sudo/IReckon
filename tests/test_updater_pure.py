"""updater 纯函数补测：版本解析、发布/下载 URL 白名单、检查节流。"""

import sys
import time

import pytest
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from app.core.updater import (
    _parse_version,
    _validate_release_url,
    _validate_zip_download_url,
)


# ---------- _parse_version ----------


def test_parse_version_tuple_compare():
    assert _parse_version("0.10.0") > _parse_version("0.9.0")  # 数字比较非字符串
    assert _parse_version("v1.2.3") == (1, 2, 3)  # 前缀 v 容忍
    assert _parse_version("1.2") == (1, 2)


def test_parse_version_invalid_returns_none():
    for bad in ("", "abc", "v.x.y", None, "1.2.x"):
        assert _parse_version(bad) is None


# ---------- _validate_release_url ----------


def test_release_url_valid():
    assert _validate_release_url(
        "https://api.github.com/repos/Ameiro-sudo/IReckon/releases/latest"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://api.github.com/repos/Ameiro-sudo/IReckon/releases/latest",  # 非 https
        "https://evil.com/repos/Ameiro-sudo/IReckon/releases/latest",  # 非官方域
        "https://api.github.com/repos/",  # 缺 repo
        "https://api.github.com/repos/has space/repo/x",  # repo 含非法字符
    ],
)
def test_release_url_invalid(url):
    assert not _validate_release_url(url)


# ---------- _validate_zip_download_url ----------


REPO = "Ameiro-sudo/IReckon"


def test_zip_url_github_release_asset_ok():
    url = f"https://github.com/{REPO}/releases/download/v0.2.0/dist.zip"
    assert _validate_zip_download_url(url, REPO)


def test_zip_url_cdn_host_ok_without_repo_prefix():
    url = "https://objects.githubusercontent.com/some/redirect/path/dist.zip"
    assert _validate_zip_download_url(url, REPO)


def test_zip_url_github_wrong_prefix_rejected():
    url = "https://github.com/Evil-org/other/releases/download/v1/dist.zip"
    assert not _validate_zip_download_url(url, REPO)


def test_zip_url_query_string_bypass_blocked():
    # 子串匹配绕过尝试：evil.com/?x=Ameiro-sudo/IReckon/
    url = f"https://evil.com/?x={REPO}/releases/download/v1/f.zip"
    assert not _validate_zip_download_url(url, REPO)


def test_zip_url_non_https_and_no_host_rejected():
    assert not _validate_zip_download_url(
        f"http://github.com/{REPO}/releases/download/v1/f.zip", REPO
    )
    assert not _validate_zip_download_url("not a url", REPO)


# ---------- should_check / mark_checked 节流 ----------


def test_should_check_throttled_by_interval(tmp_path):
    import os
    from app.core.updater import Updater

    up = Updater.__new__(Updater)  # 绕过 __init__ 的配置读取，手动装配
    up._last_check_file = tmp_path / ".last_update_check"
    up._check_interval = 24.0

    # 从未检查过(文件不存在) → 应该查
    assert up.should_check() is True

    up.mark_checked()
    assert up.should_check() is False  # mtime 新鲜，节流生效

    # 把 mtime 改旧超过 interval → 应该再查
    old = time.time() - 25 * 3600
    os.utime(up._last_check_file, (old, old))
    assert up.should_check() is True


def test_mark_checked_creates_marker_with_fresh_mtime(tmp_path):
    import os
    from app.core.updater import Updater

    up = Updater.__new__(Updater)
    up._last_check_file = tmp_path / ".last_update_check"
    up.mark_checked()
    assert up._last_check_file.exists()
    age = time.time() - os.path.getmtime(up._last_check_file)
    assert 0 <= age < 60


def test_should_check_survives_stat_errors(tmp_path):
    # 目录不存在时 stat 招异常，应容错为"需要检查"
    from app.core.updater import Updater

    up = Updater.__new__(Updater)
    up._last_check_file = tmp_path / "no-such-dir" / ".x"
    # 文件不存在分支先命中：返回 True
    assert up.should_check() is True
