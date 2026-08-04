import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

from .config import config_manager


class Updater:
    def __init__(self):
        self._repo = config_manager.get("self_update.repo", "ninasukiwww-png/IReckon")
        self._current_version = config_manager.get("system.version", "2.0.0")
        self._check_interval = config_manager.get("self_update.check_interval_hours", 24)
        self._github_api = f"https://api.github.com/repos/{self._repo}"
        self._last_check_file = Path(config_manager.get("system.data_dir", "./data")) / ".last_update_check"

    async def check(self) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self._github_api}/releases/latest")
                if resp.status_code != 200:
                    logger.debug(f"检查更新失败: HTTP {resp.status_code}")
                    return None
                data = resp.json()
                latest = data.get("tag_name", "").lstrip("v")
                if latest and latest > self._current_version:
                    logger.info(f"发现新版本: {latest} (当前: {self._current_version})")
                    return latest
                return None
        except Exception as e:
            logger.debug(f"检查更新异常: {e}")
            return None

    async def download_and_update(self, version: str) -> bool:
        download_url = f"{self._github_api}/releases/tags/v{version}"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(download_url)
                if resp.status_code != 200:
                    logger.error(f"获取 Release 信息失败: {resp.status_code}")
                    return False
                data = resp.json()
                assets = data.get("assets", [])
                if not assets:
                    logger.error("Release 没有附件")
                    return False

                zip_url = assets[0]["browser_download_url"]
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
        base_dir = Path(sys.argv[0]).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).parent.parent.parent
        backup_dir = base_dir.parent / f"backup_v{self._current_version}"

        try:
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            shutil.copytree(base_dir, backup_dir)
            logger.info(f"已备份当前版本到: {backup_dir}")

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(temp_dir := tempfile.mkdtemp())

            extracted = list(Path(temp_dir).iterdir())[0] if Path(temp_dir).is_dir() else Path(temp_dir)

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
                content = content.replace(f"version: '{self._current_version}'", f"version: '{version}'")
                config_path.write_text(content, encoding="utf-8")

            logger.info(f"已更新到 v{version}")
            return True
        except Exception as e:
            logger.error(f"应用更新失败: {e}")
            if backup_dir.exists():
                logger.info("正在还原备份...")
                for item in backup_dir.iterdir():
                    target = base_dir.parent / item.name
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