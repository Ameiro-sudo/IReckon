import asyncio
import tempfile
import os
import subprocess
from loguru import logger
from app.core.config import config_manager


class CodeScanner:
    def __init__(self, tool=None):
        self.tool = tool or config_manager.get("security.code_scanner", "bandit")
        self._available = self._check_tool()

    def _check_tool(self):
        try:
            subprocess.run([self.tool, "--version"], capture_output=True, check=True)
            return True
        except Exception:
            return False

    async def scan(self, code, language="python"):
        if not self._available:
            logger.warning(f"扫描工具 {self.tool} 不可用，跳过静态扫描")
            return []
        filepath = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=f".{language}", delete=False, mode="w"
            ) as f:
                f.write(code)
                f.flush()
                filepath = f.name
            return await self._run_scanner(filepath)
        except Exception as e:
            logger.error(f"扫描失败: {e}")
            return []
        finally:
            if filepath and os.path.exists(filepath):
                try:
                    os.unlink(filepath)
                except Exception as e:
                    logger.warning(f"临时文件清理失败: {e}")

    async def _run_scanner(self, filepath):
        proc = None
        try:
            if self.tool == "bandit":
                proc = await asyncio.create_subprocess_exec(
                    "bandit",
                    "-f",
                    "json",
                    filepath,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
                # bandit 发现漏洞时退出码为 1，但 JSON 输出仍然有效——必须无条件解析
                import json

                try:
                    return json.loads(stdout.decode()).get("results", [])
                except Exception as e:
                    logger.warning(f"bandit 输出解析失败 (exit={proc.returncode}): {e}")
                    return []
            elif self.tool == "semgrep":
                proc = await asyncio.create_subprocess_exec(
                    "semgrep",
                    "--config",
                    "auto",
                    "--json",
                    filepath,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
                import json

                try:
                    return json.loads(stdout.decode()).get("results", [])
                except Exception as e:
                    logger.warning(
                        f"semgrep 输出解析失败 (exit={proc.returncode}): {e}"
                    )
                    return []
            else:
                logger.warning(f"未知扫描工具: {self.tool}")
                return []
        except asyncio.TimeoutError:
            if proc:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
            logger.warning(f"扫描超时: {filepath}")
        except Exception as e:
            logger.error(f"扫描执行失败: {e}")
        return []


code_scanner = CodeScanner()
