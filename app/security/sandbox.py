import asyncio
from typing import Dict, Any
from loguru import logger
from app.core.config import config_manager


class Sandbox:
    """udocker 容器沙箱：提供资源受限的隔离执行。"""

    def __init__(self):
        self.engine = config_manager.get("security.sandbox.engine", "udocker")
        self.image = config_manager.get("security.sandbox.image", "python:3.11-slim")
        self.memory_limit = config_manager.get("security.sandbox.memory_limit", "512m")
        self.cpu_limit = config_manager.get("security.sandbox.cpu_limit", 1.0)
        self._available = self._check_engine()
        self._image_ready = not self._available  # 引擎不可用时无需拉镜像

    def _check_engine(self) -> bool:
        import subprocess

        try:
            subprocess.run(["udocker", "--version"], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("udocker 不可用，沙箱功能将降级")
            return False

    def _ensure_image(self) -> bool:
        """确保镜像已存在；缺失时尝试拉取（带超时）。"""
        import subprocess

        try:
            check = subprocess.run(
                ["udocker", "inspect", self.image],
                capture_output=True,
                timeout=10,
            )
            if check.returncode == 0:
                return True
        except Exception:
            pass
        logger.info(f"沙箱镜像 {self.image} 不存在，尝试拉取...")
        try:
            pull = subprocess.run(
                ["udocker", "pull", self.image],
                capture_output=True,
                timeout=300,
            )
            if pull.returncode != 0:
                logger.warning(f"拉取沙箱镜像失败: {pull.stderr.decode(errors='replace')[:300]}")
                return False
            return True
        except subprocess.TimeoutExpired:
            logger.warning("拉取沙箱镜像超时")
            return False
        except FileNotFoundError:
            return False

    async def run(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        if not self._available:
            logger.warning("沙箱不可用，无法执行")
            return {"stdout": "", "stderr": "sandbox unavailable", "returncode": -1}

        if not self._image_ready:
            self._image_ready = self._ensure_image()
            if not self._image_ready:
                return {"stdout": "", "stderr": "sandbox image unavailable", "returncode": -1}

        cmd = [
            "udocker",
            "run",
            "--user=65534",  # nobody 用户，避免容器内 root 权限
            f"--memory={self.memory_limit}",
            f"--cpus={str(self.cpu_limit)}",
            "--rm",
            self.image,
            "bash",
            "-c",
            command,
        ]
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"),
                "returncode": proc.returncode,
            }
        except asyncio.TimeoutError:
            if proc:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
            return {"stdout": "", "stderr": "timeout", "returncode": -1}
        except Exception as e:
            logger.error(f"沙箱执行失败: {e}")
            return {"stdout": "", "stderr": str(e), "returncode": -1}


sandbox = Sandbox()