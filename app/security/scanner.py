import asyncio
import json
import shlex
import tempfile
import os
import subprocess
from pathlib import Path
from typing import Optional

from loguru import logger

from app.core.config import get

from .sandbox import sandbox

# 各扫描工具的容器内 argv（不含目标文件路径）
_SCAN_TOOL_ARGV = {
    "bandit": ("bandit", "-f", "json"),
    "semgrep": ("semgrep", "--config", "auto", "--json"),
}

# 扫描目标在容器内的挂载点（临时文件所在目录以只读方式挂入）
_SANDBOX_SCAN_DIR = "/scan"


class CodeScanner:
    def __init__(self, tool=None):
        self.tool = tool or get("security.code_scanner", "bandit")
        # 懒探测：首次 scan 时才检查工具，避免导入期执行 subprocess
        self._available = None

    def _check_tool(self):
        try:
            subprocess.run([self.tool, "--version"], capture_output=True, check=True)
            return True
        except Exception:
            return False

    async def ensure_available(self) -> bool:
        """探测扫描工具可用性（结果缓存）。入库门禁用：不可用时调用方应 fail-closed。"""
        if self._available is None:
            self._available = await asyncio.to_thread(self._check_tool)
        return bool(self._available)

    async def scan(self, code, language="python"):
        if not await self.ensure_available():
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

    async def _scan_in_sandbox(self, filepath) -> Optional[list]:
        """容器内执行扫描（可选增强：security.sandbox.enabled）。

        返回 findings 列表；返回 None 表示沙箱路径不可用或失败，
        调用方应回退宿主机扫描——绝不因沙箱缺失改变门禁既有语义。
        目标目录以只读挂载进容器固定路径，扫描器只读代码、不落盘宿主机。
        """
        argv = _SCAN_TOOL_ARGV.get(self.tool)
        if argv is None:
            return None
        target = Path(filepath)
        inner_cmd = shlex.join([*argv, f"{_SANDBOX_SCAN_DIR}/{target.name}"])
        result = await sandbox.run(
            inner_cmd,
            timeout=30,
            mounts={_SANDBOX_SCAN_DIR: (str(target.parent), "ro")},
        )
        # bandit 发现问题时退出码为 1，输出仍是合法 JSON——与宿主机路径同语义
        if result.get("returncode") not in (0, 1):
            logger.warning(
                f"沙箱扫描失败(rc={result.get('returncode')})，回退宿主机: "
                f"{str(result.get('stderr', ''))[:200]}"
            )
            return None
        try:
            # 显式标注：json.loads 返回 Any，收口为 list 再返回
            findings: list = json.loads(result.get("stdout") or "{}").get("results", [])
            return findings
        except Exception as e:
            logger.warning(f"沙箱扫描输出解析失败: {e}")
            return None

    async def _run_scanner(self, filepath):
        # 沙箱总闸开启时优先容器内隔离执行；失败/不可用自动回退宿主机路径
        if bool(get("security.sandbox.enabled", False)):
            sandboxed = await self._scan_in_sandbox(filepath)
            if sandboxed is not None:
                return sandboxed
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
                try:
                    return json.loads(stdout).get("results", [])
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
                try:
                    return json.loads(stdout).get("results", [])
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
