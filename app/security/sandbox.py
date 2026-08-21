"""容器沙箱：隔离执行不可信命令（可选增强，总闸默认关闭）。

安全审计遗留项的落地修复：
- **enabled 总闸**：`security.sandbox.enabled` 默认 false——未显式启用时 run()
  直接拒绝，绝不触碰容器运行时（无 docker/udocker 的环境零行为变化）；
- **env 白名单**：宿主机环境变量永不整包进入容器，仅放行
  `security.sandbox.env_whitelist` 命中的键（默认空 = 不传任何变量）；
- **网络隔离**：docker 引擎默认 `--network=none`（`security.sandbox.network`
  可配置/置空关闭）；**udocker 无网络命名空间，明确不支持而非伪造隔离**
  （proot 用户态方案没有 cgroup/netns 能力）；
- **超时杀树**：超时后经 psutil 先杀子进程树再杀主进程，不留孤儿进程。

引擎能力差异（如实声明，参考 udocker reference card）：
- docker（默认）：network/memory/cpus 全部生效；
- udocker：仅 --user/--volume/--env/--rm；资源与网络参数不传
  （原实现给 udocker 传 --memory/--cpus 属潜伏必失败缺陷，已修正）。
"""

import asyncio
import subprocess
from typing import Any, Dict, Optional

import psutil
from loguru import logger

from app.core.config import get


def _check_engine(engine: str) -> bool:
    try:
        subprocess.run(
            [engine, "--version"], capture_output=True, check=True, timeout=15
        )
        return True
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        logger.warning(f"容器引擎 {engine} 不可用，沙箱功能将降级")
        return False


def filter_env(desired: Dict[str, str], whitelist) -> Dict[str, str]:
    """按白名单过滤环境变量：交集之外一律丢弃；白名单为空 = 全部丢弃。"""
    allow = {str(k) for k in (whitelist or [])}
    return {k: v for k, v in (desired or {}).items() if k in allow}


class Sandbox:
    """容器沙箱：提供资源受限、可网络隔离的命令执行。

    run() 返回结构恒为 {"stdout", "stderr", "returncode"}；
    沙箱未启用/引擎缺失/镜像缺失均以 returncode=-1 + 说明性 stderr 拒绝，
    调用方据此自行降级（如 scanner 回退宿主机扫描）。
    """

    def __init__(self):
        self.enabled = bool(get("security.sandbox.enabled", False))
        self.engine = str(get("security.sandbox.engine", "docker"))
        self.image = get("security.sandbox.image", "python:3.11-slim")
        self.memory_limit = get("security.sandbox.memory_limit", "512m")
        self.cpu_limit = get("security.sandbox.cpu_limit", 1.0)
        # 网络隔离目标（docker 引擎生效）；空字符串 = 不传 network 参数
        self.network = str(get("security.sandbox.network", "none"))
        # 允许进入容器的宿主机环境变量键名白名单
        self.env_whitelist = list(get("security.sandbox.env_whitelist", []) or [])
        # 懒探测：首次 run 时才检查引擎，避免导入期阻塞（无引擎环境也正常启动）
        self._available: Optional[bool] = None
        self._image_ready: Optional[bool] = None

    def _container_args(
        self,
        mounts: Optional[Dict[str, Any]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> list:
        """组装容器运行参数（纯函数，便于单测）。

        mounts: {容器路径: (宿主机路径, "ro"|"rw"|None)}
        env: 期望传入容器的环境变量（经白名单过滤后才放行）
        """
        args = []
        if self.engine == "docker":
            # 网络与资源限制仅 docker 引擎具备真实强制力
            if self.network:
                args.append(f"--network={self.network}")
            args.append(f"--memory={self.memory_limit}")
            args.append(f"--cpus={str(self.cpu_limit)}")
        args.append("--user=65534")  # nobody，避免容器内 root 权限
        for container_path, spec in (mounts or {}).items():
            host_path, mode = spec
            suffix = f":{mode}" if mode else ""
            args.append(f"--volume={host_path}:{container_path}{suffix}")
        for key, value in filter_env(env or {}, self.env_whitelist).items():
            args.append(f"--env={key}={value}")
        args.append("--rm")
        return args

    def _ensure_image(self) -> bool:
        """确保镜像已存在；缺失时尝试拉取（带超时）。"""
        try:
            check = subprocess.run(
                [self.engine, "inspect", self.image],
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
                [self.engine, "pull", self.image],
                capture_output=True,
                timeout=300,
            )
            if pull.returncode != 0:
                logger.warning(
                    f"拉取沙箱镜像失败: {pull.stderr.decode(errors='replace')[:300]}"
                )
                return False
            return True
        except subprocess.TimeoutExpired:
            logger.warning("拉取沙箱镜像超时")
            return False
        except FileNotFoundError:
            return False

    async def _kill_tree(self, proc) -> None:
        """超时兜底：先杀子进程树再杀主进程（bash -c 会派生孙进程）。"""
        try:
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                try:
                    child.kill()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        try:
            await proc.wait()
        except Exception:
            pass

    async def run(
        self,
        command: str,
        timeout: int = 30,
        mounts: Optional[Dict[str, Any]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        # 总闸：未显式启用直接拒绝，不探测运行时、不启动任何子进程
        if not self.enabled:
            logger.warning("沙箱未启用(security.sandbox.enabled=false)，拒绝执行")
            return {"stdout": "", "stderr": "sandbox disabled", "returncode": -1}

        if self._available is None:
            self._available = await asyncio.to_thread(_check_engine, self.engine)
        if not self._available:
            logger.warning("沙箱不可用，无法执行")
            return {"stdout": "", "stderr": "sandbox unavailable", "returncode": -1}

        if self._image_ready is None:
            self._image_ready = await asyncio.to_thread(self._ensure_image)
        if not self._image_ready:
            return {
                "stdout": "",
                "stderr": "sandbox image unavailable",
                "returncode": -1,
            }

        cmd = [
            self.engine,
            "run",
            *self._container_args(mounts, env),
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
                await self._kill_tree(proc)
            return {"stdout": "", "stderr": "timeout", "returncode": -1}
        except Exception as e:
            logger.error(f"沙箱执行失败: {e}")
            return {"stdout": "", "stderr": str(e), "returncode": -1}


sandbox = Sandbox()
