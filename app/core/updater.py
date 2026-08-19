import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Tuple

import httpx
from loguru import logger

from .config import config_manager

_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
_GITHUB_API_PREFIX = "https://api.github.com/repos/"


def _parse_version(v: str) -> Optional[Tuple[int, ...]]:
    """版本字符串转数字元组用于正确比较（"0.10.0" > "0.9.0"）；非法版本返回 None。"""
    try:
        return tuple(int(x) for x in str(v).strip().lstrip("v").split("."))
    except (ValueError, AttributeError):
        return None


class Updater:
    def __init__(self):
        # 构造时读取一次并固定 _repo，不允许通过配置热更新替换仓库地址
        repo = config_manager.get("self_update.repo", "Ameiro-sudo/IReckon")
        if not _REPO_RE.match(repo):
            logger.warning(f"非法 repo 配置: {repo}，回退到默认仓库")
            repo = "Ameiro-sudo/IReckon"
        self._repo = repo
        self._current_version = config_manager.get("system.version", "0.1.0")
        self._check_interval = config_manager.get(
            "self_update.check_interval_hours", 24
        )
        self._github_api = f"{_GITHUB_API_PREFIX}{self._repo}"
        self._last_check_file = (
            Path(config_manager.get("system.data_dir", "./data")) / ".last_update_check"
        )

    def _validate_release_url(self, url: str) -> bool:
        """校验 URL 必须指向 https://api.github.com/repos/ 且 repo 匹配白名单格式。"""
        if not url.startswith(_GITHUB_API_PREFIX):
            return False
        rest = url[len(_GITHUB_API_PREFIX):]
        repo_part = "/".join(rest.split("/", 2)[:2])
        return bool(_REPO_RE.match(repo_part))

    async def check(self) -> Optional[str]:
        try:
            if not self._validate_release_url(self._github_api):
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

    async def download_and_update(self, version: str) -> bool:
        if not _parse_version(version):
            logger.error(f"非法版本号: {version}")
            return False
        download_url = f"{self._github_api}/releases/tags/v{version}"
        if not self._validate_release_url(download_url):
            logger.error("Release URL 非法，拒绝下载")
            return False
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(download_url)
                if resp.status_code != 200:
                    logger.error(f"获取 Release 信息失败: {resp.status_code}")
                    return False
                assets = resp.json().get("assets", [])
                if not assets:
                    logger.error("Release 没有附件")
                    return False

                zip_url = assets[0].get("browser_download_url", "")
                # 下载 zip 前校验：仅允许 https 且 URL 必须属于固定仓库
                if not zip_url.startswith("https://") or f"/{self._repo}/" not in zip_url:
                    logger.error(f"更新包 URL 非法: {zip_url}")
                    return False
                logger.info(f"下载更新包: {zip_url}")
                zip_resp = await client.get(zip_url)
                if zip_resp.status_code != 200:
                    logger.error(f"下载失败: {zip_resp.status_code}")
                    return False

                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
                    f.write(zip_resp.content)
                    zip_path = f.name

                return await self._apply_update(zip_path, version)
        except Exception as e:
            logger.error(f"更新失败: {e}")
            return False

    async def _apply_update(self, zip_path: str, version: str) -> bool:
        base_dir = (
            Path(sys.argv[0]).resolve().parent
            if getattr(sys, "frozen", False)
            else Path(__file__).parent.parent.parent
        )
        backup_dir = base_dir.parent / f"backup_v{self._current_version}"
        temp_dir: Optional[str] = None

        try:
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            shutil.copytree(base_dir, backup_dir)
            logger.info(f"已备份当前版本到: {backup_dir}")

            with zipfile.ZipFile(zip_path, "r") as zf:
                for member in zf.infolist():
                    member_path = Path(member.filename)
                    if member_path.is_absolute() or ".." in member_path.parts:
                        raise ValueError(f"更新包包含非法路径: {member.filename}")
                temp_dir = tempfile.mkdtemp()
                zf.extractall(temp_dir)

            extracted = (
                list(Path(temp_dir).iterdir())[0]
                if Path(temp_dir).is_dir()
                else Path(temp_dir)
            )

            for item in extracted.rglob("*"):
                if item.is_file():
                    rel_path = item.relative_to(extracted)
                    target = base_dir / rel_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target)

            shutil.rmtree(temp_dir)
            os.unlink(zip_path)

            config_path = base_dir / "config" / "config.yaml"
            if config_path.exists():
                content = config_path.read_text(encoding="utf-8")
                content = content.replace(
                    f"version: '{self._current_version}'", f"version: '{version}'"
                )
                config_path.write_text(content, encoding="utf-8")

            logger.info(f"已更新到 v{version}")
            return True
        except Exception as e:
            logger.error(f"应用更新失败: {e}")
            # 清理本次解压的临时目录，避免残留文件
            if temp_dir and Path(temp_dir).exists():
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
            import time

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
