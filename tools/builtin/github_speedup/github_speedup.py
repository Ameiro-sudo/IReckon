"""
工具零件：GitHub 加速访问助手
自动检测最快镜像代理，提供克隆、下载、Release 获取等功能。
"""

import subprocess
import time
import urllib.request
import urllib.error
import json
import os
import concurrent.futures
from typing import Optional, List, Tuple, Dict

# ── 镜像站列表（按优先级）──
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
# 用于缓存最近一次检测的最快镜像，避免重复测速
_cached_best_mirror: Optional[str] = None
_cached_best_time: float = float('inf')
_cache_timestamp: float = 0.0
_CACHE_TTL = 60  # 缓存 60 秒


def _test_one_mirror(mirror: str) -> Tuple[str, float]:
    """测试单个镜像延迟，返回 (mirror, 耗时秒数)。失败则耗时 inf。"""
    test_raw = "https://raw.githubusercontent.com/octocat/Hello-World/master/README"
    # 使用 GET + Range 头来避免下载大量数据，同时兼容仅支持 GET 的镜像
    url = mirror.rstrip("/") + "/" + test_raw
    start = time.time()
    try:
        req = urllib.request.Request(url, method='GET')
        req.add_header("Range", "bytes=0-0")
        # 设置短超时
        resp = urllib.request.urlopen(req, timeout=SPEED_TEST_TIMEOUT)
        resp.read(1)   # 读取极小数据确认连通
        elapsed = time.time() - start
        return (mirror, elapsed)
    except Exception:
        return (mirror, float('inf'))


def _select_fastest_mirror(force: bool = False) -> Optional[str]:
    """选择当前最快镜像（使用缓存避免频繁测速）。"""
    global _cached_best_mirror, _cached_best_time, _cache_timestamp
    now = time.time()
    if not force and (_cached_best_mirror is not None) and (now - _cache_timestamp < _CACHE_TTL):
        return _cached_best_mirror if _cached_best_time != float('inf') else None

    # 并发测试所有镜像
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(MIRROR_POOL)) as executor:
        futures = {executor.submit(_test_one_mirror, m): m for m in MIRROR_POOL}
        best_mirror = None
        best_time = float('inf')
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


def _run_command(cmd: list, cwd: str = None, timeout: int = 60) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError:
        return -1, "", "command not found"


def _build_api_request(url: str):
    """构建带有 User‑Agent 的 Request，避免 GitHub API 403。"""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "IReckon-AI-Factory/2.0")
    req.add_header("Accept", "application/vnd.github.v3+json")
    return req


def github_access_helper(operation: str, *args, **kwargs):
    """
    执行 GitHub 访问操作。

    支持操作：
        - clone:             克隆仓库，自动使用最快镜像。
        - raw_download:      下载 raw 文件内容，返回文本。
        - release_info:      获取最新 Release 信息（JSON）。
        - release_download:  下载最新 Release 的第一个资产文件，保存到指定目录。
        - speed_test:        测试所有镜像延迟，返回结果。
        - direct_clone:      直接使用原始 URL 克隆（不加速）。
    """
    if operation == "speed_test":
        results = {}
        # 强制刷新缓存
        best = _select_fastest_mirror(force=True)
        for m in MIRROR_POOL:
            # 这里直接测试一遍即可，但我们已经有结果，从缓存再测一次会重复，复用 _test_one_mirror
            _, t = _test_one_mirror(m)
            results[m] = f"{t:.3f}s" if t != float('inf') else "timeout"
        return results

    # 对于需要镜像加速的操作，按需获取最快镜像（使用缓存）
    if operation in ("clone", "raw_download", "release_info", "release_download"):
        best_mirror = _select_fastest_mirror()
    else:
        best_mirror = None

    if operation == "clone":
        repo_url = args[0] if args else None
        if not repo_url:
            return "缺少仓库 URL"
        target = args[1] if len(args) > 1 else repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        if not best_mirror:
            returncode, stdout, stderr = _run_command(["git", "clone", repo_url, target])
            if returncode == 0:
                return f"直连克隆成功 -> {target}"
            return f"克隆失败（直连）: {stderr}"
        proxy_url = _proxy_url(best_mirror, repo_url)
        returncode, stdout, stderr = _run_command(["git", "clone", proxy_url, target])
        if returncode == 0:
            return f"克隆成功（使用 {best_mirror}) -> {target}"
        return f"克隆失败: {stderr}"

    elif operation == "raw_download":
        raw_url = args[0] if args else None
        if not raw_url:
            return "缺少 raw URL"
        urls_to_try = []
        if best_mirror:
            urls_to_try.append(_proxy_url(best_mirror, raw_url))
        urls_to_try.append(raw_url)
        for url in urls_to_try:
            try:
                req = _build_api_request(url)  # User-Agent 无妨
                with urllib.request.urlopen(req, timeout=10) as resp:
                    content = resp.read().decode('utf-8', errors='replace')
                    return content
            except Exception:
                continue
        return "下载失败"

    elif operation == "release_info":
        repo = args[0] if args else None
        if not repo:
            return "缺少仓库全名（owner/repo）"
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        urls = []
        if best_mirror:
            urls.append(_proxy_url(best_mirror, api_url))
        urls.append(api_url)
        for url in urls:
            try:
                req = _build_api_request(url)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                    return {
                        "tag_name": data.get("tag_name"),
                        "name": data.get("name"),
                        "assets": [{"name": a["name"], "browser_download_url": a["browser_download_url"]} for a in data.get("assets", [])]
                    }
            except Exception:
                continue
        return "获取 Release 信息失败"

    elif operation == "release_download":
        repo = args[0] if args else None
        save_dir = args[1] if len(args) > 1 else "."
        if not repo:
            return "缺少仓库全名"
        info = github_access_helper("release_info", repo)
        if isinstance(info, str):
            return info
        assets = info.get("assets", [])
        if not assets:
            return "该 Release 没有资产文件"
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
                with urllib.request.urlopen(req, timeout=30) as resp:
                    content = resp.read()
                    save_path = os.path.join(save_dir, file_name)
                    with open(save_path, 'wb') as f:
                        f.write(content)
                    return f"下载成功: {save_path}"
            except Exception:
                continue
        return "下载失败"

    elif operation == "direct_clone":
        repo_url = args[0] if args else None
        if not repo_url:
            return "缺少仓库 URL"
        target = args[1] if len(args) > 1 else repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        returncode, stdout, stderr = _run_command(["git", "clone", repo_url, target])
        if returncode == 0:
            return f"直连克隆成功 -> {target}"
        return f"直连克隆失败: {stderr}"

    else:
        return f"不支持的操作: {operation}"