"""
udocker 沙箱管理
"""

import asyncio
from typing import Dict, Any
from loguru import logger
from core.config_manager import config_manager


class Sandbox:
    def __init__(self):
        self.engine = config_manager.get("security.sandbox.engine", "udocker")
        self.image = config_manager.get("security.sandbox.image", "python:3.11-slim")
        self.memory_limit = config_manager.get("security.sandbox.memory_limit", "512m")
        self.cpu_limit = config_manager.get("security.sandbox.cpu_limit", 1.0)
        self._available = self._check_engine()

    def _check_engine(self) -> bool:
        import subprocess
        try:
            subprocess.run(["udocker", "--version"], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("udocker 不可用，沙箱功能将降级")
            return False

    async def run(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """在沙箱中执行命令"""
        if not self._available:
            logger.warning("沙箱不可用，无法执行")
            return {"stdout": "", "stderr": "sandbox unavailable", "returncode": -1}

        cmd = [
            "udocker", "run",
            f"--memory={self.memory_limit}",
            f"--cpus={self.cpu_limit}",
            "--rm",
            self.image,
            "bash", "-c", command
        ]
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "stdout": stdout.decode(errors='replace'),
                "stderr": stderr.decode(errors='replace'),
                "returncode": proc.returncode
            }
        except asyncio.TimeoutError:
            if proc:
                proc.kill()
                await proc.wait()
            return {"stdout": "", "stderr": "timeout", "returncode": -1}
        except Exception as e:
            logger.error(f"沙箱执行失败: {e}")
            return {"stdout": "", "stderr": str(e), "returncode": -1}


sandbox = Sandbox()