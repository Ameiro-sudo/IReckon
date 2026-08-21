import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx
from loguru import logger
from app.core.config import config_manager  # noqa: F401  # 测试通过模块属性访问
from app.core.config import get

_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
_GITHUB_API_PREFIX = "https://api.github.com/repos/"
_MAX_ZIP_BYTES = 100 * 1024 * 1024
_READ_CHUNK = 64 * 1024
# 备份时排除的运行时/体积巨大目录（copytree 整目录拷贝会拖垮更新速度）
_BACKUP_EXCLUDE_DIRS = (
    "data",
    ".venv",
    "venv",
    "node_modules",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
)


def _parse_version(v: str) -> Optional[Tuple[int, ...]]:
    """版本字符串转数字元组用于正确比较（"0.10.0" > "0.9.0"）；非法版本返回 None。"""
    try:
        return tuple(int(x) for x in str(v).strip().lstrip("v").split("."))
    except (ValueError, AttributeError):
        return None


def _validate_release_url(url: str) -> bool:
    """校验 URL 必须指向 https://api.github.com/repos/ 且 repo 匹配白名单格式。"""
    if not url.startswith(_GITHUB_API_PREFIX):
        return False
    rest = url[len(_GITHUB_API_PREFIX) :]
    repo_part = "/".join(rest.split("/", 2)[:2])
    return bool(_REPO_RE.match(repo_part))


def _validate_zip_download_url(url: str, repo: str) -> bool:
    """校验 zip 下载地址：必须为 https、host 属于 github.com 及其 CDN、路径归属固定仓库。

    用 URL 解析替代子串匹配，防止 `https://evil.com/?x=/{repo}/` 一类绕过。
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    allowed_hosts = ("github.com", "objects.githubusercontent.com")
    if not any(host == h or host.endswith("." + h) for h in allowed_hosts):
        return False
    path = parsed.path.lstrip("/")
    repo_prefix = f"{repo}/"
    # releases/download 资产路径形如 <repo>/releases/download/<tag>/<file>；
    # objects.githubusercontent.com 跳转链不含 repo 前缀，由 host 白名单兜底
    if host == "github.com" and not path.startswith(repo_prefix):
        return False
    return True


class Updater:
    def __init__(self) -> None:
        # 构造时读取一次并固定 _repo，不允许通过配置热更新替换仓库地址
        repo = get("self_update.repo", "Ameiro-sudo/IReckon")
        if not _REPO_RE.match(repo):
            logger.warning(f"非法 repo 配置: {repo}，回退到默认仓库")
            repo = "Ameiro-sudo/IReckon"
        self._repo = repo
        self._current_version = get("system.version", "0.1.0")
        self._check_interval = float(get("self_update.check_interval_hours", 24) or 24)
        self._max_zip_bytes = get("self_update.max_zip_bytes", _MAX_ZIP_BYTES)
        self._github_api = f"{_GITHUB_API_PREFIX}{self._repo}"
        self._last_check_file = (
            Path(get("system.data_dir", "./data")) / ".last_update_check"
        )

    async def check(self) -> Optional[str]:
        try:
            if not _validate_release_url(self._github_api):
                logger.error("GitHub API URL 非法，跳过更新检查")
                return None
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self._github_api}/releases/latest")
                if resp.status_code != 200:
                    logger.debug(f"检查更新失败: HTTP {resp.status_code}")
                    return None
                latest = str(resp.json().get("tag_name", "")).lstrip("v")
                latest_v = _parse_version(latest)
                current_v = _parse_version(self._current_version)
                # 元组比较避免字符串比较错误（"0.9.0" > "0.10.0" 为 False）
                if latest_v and current_v and latest_v > current_v:
                    logger.info(f"发现新版本: {latest} (当前: {self._current_version})")
                    return latest
                return None
        except Exception as e:
            logger.debug(f"检查更新异常: {e}")
            return None

    def _resolve_channel(self, explicit: Optional[str] = None) -> str:
        """更新渠道解析：显式参数 > 配置 self_update.channel > 自动探测。

        auto 规则：冻结环境下同目录存在 Inno Setup 卸载器(unins*.exe)
        → installer(下载 Setup 安装器由用户完成安装)；否则
        portable(便携 zip 自替换)。源码运行一律 portable。
        """
        cfg = str(explicit or get("self_update.channel", "auto") or "auto").lower()
        if cfg in ("installer", "portable"):
            return cfg
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            if any(exe_dir.glob("unins*.exe")):
                return "installer"
            return "portable"
        return "portable"

    @staticmethod
    def _select_asset(assets: list, channel: str) -> Tuple[str, str]:
        """按渠道挑选发行资产，返回 (下载URL, 资产名)；未命中返回 ("", "")。

        命名约定（build.yml 保证）：
          installer → IReckon-Setup-<ver>-win64.exe
          portable  → IReckon-Portable-<ver>-win64.zip
        """
        for a in assets:
            name = (a.get("name") or "").lower()
            if (
                channel == "installer"
                and name.startswith("ireckon-setup-")
                and name.endswith(".exe")
            ):
                return a.get("browser_download_url") or "", name
            if (
                channel == "portable"
                and name.startswith("ireckon-portable-")
                and name.endswith(".zip")
            ):
                return a.get("browser_download_url") or "", name
        return "", ""

    async def download_and_update(
        self,
        version: str,
        channel: Optional[str] = None,
        silent: bool = False,
    ) -> bool:
        if not _parse_version(version):
            logger.error(f"非法版本号: {version}")
            return False
        download_url = f"{self._github_api}/releases/tags/v{version}"
        if not _validate_release_url(download_url):
            logger.error("Release URL 非法，拒绝下载")
            return False
        ch = self._resolve_channel(channel)
        local_path: Optional[Path] = None
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, read=180.0)
            ) as client:
                resp = await client.get(download_url)
                if resp.status_code != 200:
                    logger.error(f"获取 Release 信息失败: {resp.status_code}")
                    return False
                assets = resp.json().get("assets", [])
                asset_url, asset_name = self._select_asset(assets, ch)
                if not asset_url:
                    names = ", ".join(a.get("name", "") for a in assets) or "(无附件)"
                    logger.error(f"Release 缺少 {ch} 渠道资产，现有: {names}")
                    return False
                suffix = ".exe" if ch == "installer" else ".zip"
                local_path = Path(tempfile.gettempdir()) / (
                    f"IReckon-update-{ch}-{version}{suffix}"
                )
                logger.info(f"下载更新包({ch}): {asset_url}")
                # 受控跟随重定向：httpx 默认不跟跳，而 GitHub 资产必经 302 到 CDN，
                # 此前 portable 更新恒报"下载失败"。改为手动逐跳校验——每一跳都必须
                # 重新通过 host/路径白名单（_validate_zip_download_url），防跳向任意外域。
                download_url_hop = asset_url
                saved = False
                for _hop in range(5):
                    if not _validate_zip_download_url(download_url_hop, self._repo):
                        logger.error(
                            f"更新包 URL 非法(第{_hop + 1}跳): {download_url_hop}"
                        )
                        return False
                    async with client.stream("GET", download_url_hop) as dl_resp:
                        if dl_resp.status_code in (301, 302, 303, 307, 308):
                            location = dl_resp.headers.get("location", "")
                            if not location:
                                logger.error("重定向缺少 Location 头")
                                return False
                            download_url_hop = str(
                                httpx.URL(download_url_hop).join(location)
                            )
                            continue  # 关闭本跳响应，进入下一跳白名单校验
                        if dl_resp.status_code != 200:
                            logger.error(f"下载失败: {dl_resp.status_code}")
                            return False
                        downloaded = 0
                        with open(local_path, "wb") as f:
                            async for chunk in dl_resp.aiter_bytes(_READ_CHUNK):
                                downloaded += len(chunk)
                                if downloaded > self._max_zip_bytes:
                                    logger.error(
                                        f"更新包超过大小限制 "
                                        f"({self._max_zip_bytes} bytes)，拒绝应用"
                                    )
                                    return False
                                f.write(chunk)
                        saved = True
                if not saved:
                    logger.error("更新包下载重定向跳数超限")
                    return False

                if ch == "installer":
                    # 安装器渠道：启动向导后即返回成功；不清理临时文件，
                    # 安装器进程稍后需要读取。silent 时走 Inno 静默参数。
                    flags = (
                        [
                            "/SILENT",
                            "/SUPPRESSMSGBOXES",
                            "/CLOSEAPPLICATIONS",
                            "/RESTARTAPPLICATIONS",
                        ]
                        if silent
                        else []
                    )
                    subprocess.Popen([str(local_path), *flags], close_fds=True)
                    logger.info(f"安装器已启动: {local_path} (flags={flags})")
                    return True

                ok = await self._apply_update(str(local_path), version)
                try:
                    os.unlink(local_path)
                except OSError:
                    pass
                local_path = None
                return ok
        except Exception as e:
            logger.error(f"更新失败: {e}")
            return False
        finally:
            # 仅 portable 失败路径需要清理；安装器文件留给安装进程使用
            if local_path is not None and ch == "portable":
                try:
                    os.unlink(local_path)
                except OSError:
                    pass

    @staticmethod
    def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
        """逐个成员安全解压到 dest；拒绝绝对路径、..、盘符与反斜杠穿越。"""
        dest_resolved = dest.resolve()
        for member in zf.infolist():
            # 拒绝符号链接成员：解压后跟随链接可写入任意路径
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f"更新包包含符号链接: {member.filename}")
            name = member.filename.replace("\\", "/")
            parts = name.split("/")
            if (
                not parts
                or parts[0] == ""
                or name.startswith("/")
                or ".." in parts
                or ":" in parts[0]
            ):
                raise ValueError(f"更新包包含非法路径: {member.filename}")
            target = (dest / name).resolve()
            if dest_resolved not in target.parents:
                raise ValueError(f"更新包路径越界: {member.filename}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)

    async def _apply_update(
        self, zip_path: str, version: str, base_dir: Optional[Path] = None
    ) -> bool:
        # 解压/备份/逐文件拷贝均为重同步 IO，放线程池执行避免阻塞事件循环
        return await asyncio.to_thread(
            self._apply_update_sync, zip_path, version, base_dir
        )

    def _apply_update_sync(
        self, zip_path: str, version: str, base_dir: Optional[Path] = None
    ) -> bool:
        if base_dir is None:
            base_dir = (
                Path(sys.argv[0]).resolve().parent
                if getattr(sys, "frozen", False)
                else Path(__file__).parent.parent.parent
            )
        backup_dir = base_dir.parent / f"backup_v{self._current_version}"
        temp_dir: Optional[Path] = None

        try:
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            # 排除 data/venv/node_modules 等运行时目录，避免 GB 级无效拷贝
            shutil.copytree(
                base_dir,
                backup_dir,
                ignore=shutil.ignore_patterns(*_BACKUP_EXCLUDE_DIRS),
            )
            logger.info(f"已备份当前版本到: {backup_dir}")

            temp_dir = Path(tempfile.mkdtemp())
            with zipfile.ZipFile(zip_path, "r") as zf:
                self._safe_extract(zf, temp_dir)

            # 兼容 zip 内单个顶层目录（打包外壳，视为项目根）与散装文件两种结构
            top_items = list(temp_dir.iterdir())
            wrapped = len(top_items) == 1 and top_items[0].is_dir()
            for root in top_items:
                if root.is_dir():
                    files = [f for f in root.rglob("*") if f.is_file()]
                    rel_base = root if wrapped else root.parent
                else:
                    files = [root]
                    rel_base = root.parent
                for f in files:
                    rel = f.relative_to(rel_base)
                    target = base_dir / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, target)

            shutil.rmtree(temp_dir, ignore_errors=True)

            config_path = base_dir / "config" / "config.yaml"
            if config_path.exists():
                content = config_path.read_text(encoding="utf-8")
                # 兼容带引号与不带引号的写法（version: 0.1.0 / version: '0.1.0'）
                pattern = re.compile(
                    r"^(\s*version:\s*['\"]?)"
                    + re.escape(str(self._current_version))
                    + r"(['\"]?\s*)$",
                    re.MULTILINE,
                )
                new_content, replaced = pattern.subn(
                    lambda m: m.group(1) + version + m.group(2), content, count=1
                )
                if replaced:
                    config_path.write_text(new_content, encoding="utf-8")
                else:
                    logger.warning(
                        f"config.yaml 未找到版本 {self._current_version}，跳过版本号更新"
                    )

            logger.info(f"已更新到 v{version}")
            return True
        except Exception as e:
            logger.error(f"应用更新失败: {e}")
            # 清理本次解压的临时目录，避免残留文件
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            # 还原策略：不删除备份中不存在的顶层项（避免误删用户新增数据），
            # 只把备份里的顶层项覆盖放回，保证还原后与备份一致
            if backup_dir.exists():
                logger.info("正在还原备份...")
                for item in backup_dir.iterdir():
                    target = base_dir / item.name
                    if target.exists():
                        if target.is_dir():
                            shutil.rmtree(target)
                        else:
                            target.unlink()
                    shutil.move(str(item), str(target))
            return False

    def should_check(self) -> bool:
        if not self._last_check_file.exists():
            return True
        try:
            mtime = self._last_check_file.stat().st_mtime
            return (time.time() - mtime) > self._check_interval * 3600
        except Exception:
            return True

    def mark_checked(self):
        try:
            self._last_check_file.parent.mkdir(parents=True, exist_ok=True)
            self._last_check_file.touch()
        except Exception:
            pass


updater = Updater()
