"""
GitHub speedup tool helper.
Provides proxy mirror selection, clone/download support, and release access helpers.
"""

import subprocess
import time
import urllib.request
import urllib.error
import urllib.parse
import json
import os
import concurrent.futures
from typing import Optional, Tuple

MIRROR_POOL = [
    "https://edgeone.gh-proxy.com",
    "https://hk.gh-proxy.com/",
    "https://gh-proxy.com/",
    "https://gh.llkk.cc/",
    "https://ghproxy.net/",
    "https://mirror.ghproxy.com/",
    "https://gh.api.99988866.xyz/",
    "https://ghproxy.com/",
]

SPEED_TEST_TIMEOUT = 5
_cached_best_mirror: Optional[str] = None
_cached_best_time: float = float("inf")
_cache_timestamp: float = 0.0
_CACHE_TTL = 60


def _require_http_url(url: str) -> str:
    """仅允许 http/https 协议，防止 file:// 等非预期 scheme。"""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"仅支持 http/https URL: {url}")
    return url


def _test_one_mirror(mirror: str) -> Tuple[str, float]:
    """Test a single mirror and return (mirror, elapsed)."""
    test_raw = "https://raw.githubusercontent.com/octocat/Hello-World/master/README"
    url = _require_http_url(mirror.rstrip("/") + "/" + test_raw)
    start = time.time()
    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("Range", "bytes=0-0")
        resp = urllib.request.urlopen(req, timeout=SPEED_TEST_TIMEOUT)  # nosec B310: url 已通过 _require_http_url 校验
        resp.read(1)
        elapsed = time.time() - start
        return mirror, elapsed
    except Exception:
        return mirror, float("inf")


def _select_fastest_mirror(force: bool = False) -> Optional[str]:
    """Choose the fastest mirror, using cached results."""
    global _cached_best_mirror, _cached_best_time, _cache_timestamp
    now = time.time()
    if (
        not force
        and (_cached_best_mirror is not None)
        and (now - _cache_timestamp < _CACHE_TTL)
    ):
        return _cached_best_mirror if _cached_best_time != float("inf") else None

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=len(MIRROR_POOL)
    ) as executor:
        futures = {executor.submit(_test_one_mirror, m): m for m in MIRROR_POOL}
        best_mirror = None
        best_time = float("inf")
        for future in concurrent.futures.as_completed(futures):
            mirror, elapsed = future.result()
            if elapsed < best_time:
                best_time = elapsed
                best_mirror = mirror

    _cached_best_mirror = best_mirror
    _cached_best_time = best_time
    _cache_timestamp = now
    return best_mirror


def _proxy_url(mirror: str, original_url: str) -> str:
    return mirror.rstrip("/") + "/" + original_url


def _run_command(
    cmd: list, cwd: Optional[str] = None, timeout: int = 60
) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError:
        return -1, "", "command not found"


def _build_api_request(url: str):
    req = urllib.request.Request(_require_http_url(url))
    req.add_header("User-Agent", "IReckon-AI-Factory/2.0")
    req.add_header("Accept", "application/vnd.github.v3+json")
    return req


def github_access_helper(operation: str, *args, **kwargs):
    """Handle GitHub access operations."""
    if operation == "speed_test":
        results = {}
        _select_fastest_mirror(force=True)
        for m in MIRROR_POOL:
            _, t = _test_one_mirror(m)
            results[m] = f"{t:.3f}s" if t != float("inf") else "timeout"
        return results

    if operation in ("clone", "raw_download", "release_info", "release_download"):
        best_mirror = _select_fastest_mirror()
    else:
        best_mirror = None

    if operation == "clone":
        repo_url = args[0] if args else None
        if not repo_url:
            return "Repository URL is required"
        target = (
            args[1]
            if len(args) > 1
            else repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        )
        if not best_mirror:
            returncode, stdout, stderr = _run_command(
                ["git", "clone", repo_url, target]
            )
            if returncode == 0:
                return f"Clone succeeded -> {target}"
            return f"Clone failed: {stderr}"
        proxy_url = _proxy_url(best_mirror, repo_url)
        returncode, stdout, stderr = _run_command(["git", "clone", proxy_url, target])
        if returncode == 0:
            return f"Clone succeeded via {best_mirror} -> {target}"
        return f"Clone failed: {stderr}"

    elif operation == "raw_download":
        raw_url = args[0] if args else None
        if not raw_url:
            return "Raw URL is required"
        urls_to_try = []
        if best_mirror:
            urls_to_try.append(_proxy_url(best_mirror, raw_url))
        urls_to_try.append(raw_url)
        for url in urls_to_try:
            try:
                req = _build_api_request(url)
                with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310: url 已通过 _require_http_url 校验
                    return resp.read().decode("utf-8", errors="replace")
            except Exception:
                continue
        return "Download failed"

    elif operation == "release_info":
        repo = args[0] if args else None
        if not repo:
            return "Repository name is required"
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        urls = []
        if best_mirror:
            urls.append(_proxy_url(best_mirror, api_url))
        urls.append(api_url)
        for url in urls:
            try:
                req = _build_api_request(url)
                with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310: url 已通过 _require_http_url 校验
                    data = json.loads(resp.read().decode("utf-8", errors="replace"))
                    return {
                        "tag_name": data.get("tag_name"),
                        "name": data.get("name"),
                        "assets": [
                            {
                                "name": a["name"],
                                "browser_download_url": a["browser_download_url"],
                            }
                            for a in data.get("assets", [])
                        ],
                    }
            except Exception:
                continue
        return "Release info fetch failed"

    elif operation == "release_download":
        repo = args[0] if args else None
        save_dir = args[1] if len(args) > 1 else "."
        if not repo:
            return "Repository name is required"
        info = github_access_helper("release_info", repo)
        if isinstance(info, str):
            return info
        assets = info.get("assets", [])
        if not assets:
            return "Release has no assets"
        asset = assets[0]
        download_url = asset["browser_download_url"]
        file_name = asset["name"]
        urls = []
        if best_mirror:
            urls.append(_proxy_url(best_mirror, download_url))
        urls.append(download_url)
        for url in urls:
            try:
                req = _build_api_request(url)
                with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310: url 已通过 _require_http_url 校验
                    content = resp.read()
                    save_path = os.path.join(save_dir, file_name)
                    with open(save_path, "wb") as f:
                        f.write(content)
                    return f"Download succeeded: {save_path}"
            except Exception:
                continue
        return "Download failed"

    elif operation == "direct_clone":
        repo_url = args[0] if args else None
        if not repo_url:
            return "Repository URL is required"
        target = (
            args[1]
            if len(args) > 1
            else repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        )
        returncode, stdout, stderr = _run_command(["git", "clone", repo_url, target])
        if returncode == 0:
            return f"Clone succeeded -> {target}"
        return f"Clone failed: {stderr}"

    else:
        return f"Unsupported operation: {operation}"
