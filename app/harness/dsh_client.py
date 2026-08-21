"""
DeepSeek Harness (dsh) 客户端
负责调用 DeepSeek 官方开源 agent harness 执行软件开发任务。
双通道设计：优先 Python SDK，SDK 不可用时降级到 headless CLI。
"""

import asyncio
import importlib.util
import os
import shlex
import shutil
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from app.core.config import config_manager
from app.security.filter import CommandLevel, command_filter

# 内置的 minimal cordis 组合配置模板（对应官方 jsonrpc-agent 示例）
DEFAULT_CORDIS_TEMPLATE = """\
# Complete unattended minimal-agent composition for the Python SDK. The model
# sees one deployment-selected system prompt and only the owner-scoped
# persistent Bash and string-replace editor tools.

- id: sdk-jsonrpc-server
  name: '@deepseek-ai/dsh-sdk-jsonrpc-server'
  config:
    maxTokensAsSuccess: false

- id: llm-deepseek
  name: '@deepseek-ai/dsh-llm-deepseek'
  config:
    apiKeyEnv: DEEPSEEK_API_KEY
    streamIdleTimeoutMs: 172800000
    models:
      - id: !!js process.env.DSH_MODEL ?? 'deepseek-v4-flash'
        contextWindow: !!js Number(process.env.DSH_CONTEXT_WINDOW ?? 1000000)

- id: sandbox
  name: '@deepseek-ai/dsh-sandbox-local'

- id: sandbox-policy
  name: '@deepseek-ai/dsh-sandbox-policy'
  config:
    mode: danger-full-access
    workspaceRoot: !!js process.env.DSH_CWD ?? process.cwd()

- id: subprocess
  name: '@deepseek-ai/dsh-subprocess-local'

- id: pty
  name: '@deepseek-ai/dsh-terminal'

- id: terminal-bash
  name: '@deepseek-ai/dsh-terminal-bash'
  config:
    timeoutMs: 300000

- id: fs-local
  name: '@deepseek-ai/dsh-fs-local'
  config:
    cwd: !!js process.env.DSH_CWD ?? process.cwd()

- id: agent-spine
  name: '@deepseek-ai/dsh-agent-spine-demo'
  config:
    includeHarnessIdentity: false
    includeRuntimeContext: false
    persona: !!js process.env.DSH_SYSTEM_PROMPT ?? 'You are a helpful software engineer assistant.'
    workspaceContext: false
    skills:
      enabled: false
    toolBash: false
    toolJobs: false

- id: persistent-bash
  name: '@deepseek-ai/dsh-tool-bash-persistent'
  config:
    timeoutMs: 300000
    description: |-
      Run commands in a bash shell
      * When invoking this tool, the contents of the "command" parameter does NOT need to be XML-escaped.
      * You don't have access to the internet via this tool.
      * You do have access to a mirror of common linux and python packages via apt and pip.
      * State is persistent across command calls and discussions with the user.
      * To inspect a particular line range of a file, e.g. lines 10-25, try 'sed -n 10,25p /path/to/the/file'.
      * Please avoid commands that may produce a very large amount of output.
      * Please run long lived commands in the background, e.g. 'sleep 10 &' or start a server in the background.

- id: str-replace-editor
  name: '@deepseek-ai/dsh-tool-str-replace-editor'
  config:
    maxOutputChars: 16000

- id: sessions
  name: '@deepseek-ai/dsh-session-persistence-jsonl'
  config:
    root: !!js process.env.DSH_SESSION_ROOT ?? './.sessions'
    compression: none
"""


@dataclass
class DSHResult:
    """dsh 执行结果～"""

    final_response: str = ""  # 最终回答
    session_id: str = ""  # 会话 ID
    workspace: str = ""  # 工作区路径
    mode: str = ""  # 使用的通道: sdk | cli
    ok: bool = False  # 是否成功
    error: str = ""  # 错误信息
    metadata: Dict[str, Any] = field(default_factory=dict)


class _StdoutSink:
    """stdout 收集器：累计超过 max_bytes 后截断，后续输出丢弃。"""

    def __init__(self, max_bytes: int = 200 * 1024):
        self._max = max_bytes
        self._parts: List[bytes] = []
        self._size = 0
        self._truncated = False

    def feed(self, line: bytes) -> None:
        if self._truncated:
            return
        room = self._max - self._size
        if room <= 0:
            self._truncated = True
            return
        if len(line) > room:
            self._parts.append(line[:room])
            self._size = self._max
            self._truncated = True
            logger.warning(f"[dsh CLI] stdout 超过 {self._max} 字节，后续输出已截断")
        else:
            self._parts.append(line)
            self._size += len(line)

    def text(self) -> str:
        return b"".join(self._parts).decode(errors="replace")


class _StderrTail:
    """stderr 收集器：每行增量转发到 logger(warning)，并保留尾部用于报错。"""

    def __init__(self, max_bytes: int = 2000):
        self._max = max_bytes
        self._parts: List[bytes] = []
        self._size = 0

    def feed(self, line: bytes) -> None:
        text = line.decode(errors="replace").rstrip()
        if text:
            logger.warning(f"[dsh CLI stderr] {text}")
        self._parts.append(line)
        self._size += len(line)
        while self._size > self._max and len(self._parts) > 1:
            dropped = self._parts.pop(0)
            self._size -= len(dropped)

    def text(self) -> str:
        return b"".join(self._parts).decode(errors="replace")


async def _drain_cli(proc, stdout_sink, stderr_tail):
    """增量读取 stdout/stderr：communicate() 会一次攒满内存，这里改为增量。

    - stdout：累计超过 200KB 截断（丢弃后续）；
    - stderr：每行实时转发到 logger（warning 级）+ 保留尾部用于报错。
    """

    async def drain(stream, sink):
        while True:
            line = await stream.readline()
            if not line:
                break
            sink.feed(line)

    await asyncio.gather(
        drain(proc.stdout, stdout_sink), drain(proc.stderr, stderr_tail)
    )


def _kill_tree(proc) -> None:
    """终止整个进程树，防止超时后 node/npx 孙进程残留。

    - Windows：taskkill /F /T 按 PID 杀树；
    - POSIX：对进程组发 SIGKILL（子进程以 start_new_session 启动）；
    - 任一步失败退回 proc.kill() 兜底。
    """
    pid = getattr(proc, "pid", None)
    if pid:
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    timeout=10,
                )
                return
            except Exception:
                pass
        else:
            # getattr 防御：非 POSIX 平台无 killpg/getpgid/SIGKILL
            killpg = getattr(os, "killpg", None)
            getpgid = getattr(os, "getpgid", None)
            sigkill = getattr(signal, "SIGKILL", None)
            if killpg is not None and getpgid is not None and sigkill is not None:
                try:
                    killpg(getpgid(pid), sigkill)
                    return
                except (ProcessLookupError, PermissionError, OSError):
                    pass
    try:
        proc.kill()
    except Exception:
        pass


class DSHClient:
    """
    DeepSeek Harness 客户端核心类～
    支持 SDK / headless CLI 双通道自动选择，会话持久化，超时控制。
    """

    def __init__(self, cfg: Any = None):
        self.cfg = cfg or config_manager
        self._sdk_checked: Optional[bool] = None
        self._cli_checked: Optional[bool] = None
        # 探测时间戳：构造即视为已探测（兼容测试直接赋值 _sdk_checked/_cli_checked）
        self._sdk_checked_at: float = time.monotonic()
        self._cli_checked_at: float = time.monotonic()
        # per-session 互斥锁：同一 session_root+session_id 的 SDK/CLI 通道串行执行，
        # 防止 SDK 超时后线程仍在跑时 CLI 通道并发启动
        self._session_locks: Dict[str, asyncio.Lock] = {}

    # ---- 可用性探测 ----

    def sdk_available(self) -> bool | None:
        """Python SDK (deepseek-harness-sdk) 是否可用～（探测结果 TTL 缓存，默认 300s）"""
        ttl = float(self._get("availability_ttl_seconds", 300))
        if self._sdk_checked is None or time.monotonic() - self._sdk_checked_at > ttl:
            self._sdk_checked = importlib.util.find_spec("deepseek_harness") is not None
            self._sdk_checked_at = time.monotonic()
        return self._sdk_checked

    def cli_available(self) -> bool | None:
        """headless CLI (npx @deepseek-ai/dsh) 是否可用～（探测结果 TTL 缓存，默认 300s）"""
        ttl = float(self._get("availability_ttl_seconds", 300))
        if self._cli_checked is None or time.monotonic() - self._cli_checked_at > ttl:
            self._cli_checked = (
                shutil.which("npx") is not None or shutil.which("node") is not None
            )
            self._cli_checked_at = time.monotonic()
        return self._cli_checked

    def available_mode(self) -> str:
        """返回可用通道：sdk > cli > 空串～"""
        if self.sdk_available():
            return "sdk"
        if self.cli_available():
            return "cli"
        return ""

    # ---- 配置辅助 ----

    def _get(self, key: str, default: Any = None) -> Any:
        return self.cfg.get(f"harness.{key}", default)

    def _enabled(self) -> bool:
        return bool(self._get("enabled", True))

    def _session_lock(self, session_root: str, session_id: str) -> asyncio.Lock:
        """per-session 互斥锁：key = session_root + session_id。"""
        key = f"{session_root}|{session_id}"
        lock = self._session_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[key] = lock
        # 长驻进程下修剪不再使用的锁，防止无界增长
        if len(self._session_locks) > 100:
            stale = [k for k, v in self._session_locks.items() if not v.locked()]
            for k in stale[:50]:
                self._session_locks.pop(k, None)
        return lock

    def _cordis_config(self) -> Optional[Path]:
        """解析 cordis 组合配置，缺失时用内置模板生成～

        生成时策略模式取 harness.policy_mode（默认 danger-full-access，
        需配合 harness.allow_full_access: true 才能实际运行，见 _policy_check）。
        """
        raw = self._get("cordis_config", "config/harness/minimal.cordis.yml")
        if not raw:
            return None
        p = Path(raw)
        if not p.is_absolute():
            base = Path(getattr(self.cfg, "base_dir", Path.cwd())).resolve()
            p = base / p
        if not p.exists():
            try:
                policy_mode = str(
                    self._get("policy_mode", "danger-full-access")
                ).strip()
                template = DEFAULT_CORDIS_TEMPLATE.replace(
                    "mode: danger-full-access", f"mode: {policy_mode}", 1
                )
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(template, encoding="utf-8")
                logger.info(f"已生成 dsh cordis 配置模板: {p}")
            except OSError as e:
                logger.warning(f"无法生成 cordis 配置: {e}")
                return None
        return p

    def _policy_check(self) -> Optional[str]:
        """安全门（fail-closed）：cordis 策略为 danger-full-access 时必须显式允许。

        dsh 在宿主机以完全访问模式执行 LLM 生成的命令，属于高危操作；
        未配置 harness.allow_full_access: true 时拒绝运行，防止默认部署裸奔。
        """
        if bool(self._get("allow_full_access", False)):
            return None
        cordis = self._cordis_config()
        if cordis is None:
            return None
        try:
            text = cordis.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        if "danger-full-access" in text:
            return (
                "dsh sandbox-policy 为 danger-full-access（宿主机完全访问），"
                "已被安全门拦截；如确认信任当前环境，请在配置中设置 "
                "harness.allow_full_access: true，或改用受限策略的 cordis 配置"
                "（harness.policy_mode / cordis_config）"
            )
        return None

    def _task_filter_check(self, task: str) -> Optional[str]:
        """命令过滤接入点：任务文本内嵌危险 shell 构造时拒绝执行。

        过滤器此前从未接入任何执行链路（死代码）；dsh 是唯一在宿主机
        执行 LLM 生成命令的通道，此处对任务文本做 L3 拦截作为纵深防御。
        可通过 harness.command_filter_enabled: false 关闭。
        """
        if not bool(self._get("command_filter_enabled", True)):
            return None
        try:
            level = command_filter.classify(task)
        except Exception:
            return None
        if level == CommandLevel.L3:
            _lvl, reason = command_filter._classify_detail(task)
            return f"任务文本命中命令过滤高危规则，已拒绝执行：{reason}"
        return None

    def _resolve_workspace(self, workspace: Optional[str], session_id: str) -> Path:
        """工作区：显式传入优先，否则按 session_id 隔离。

        resolve 后必须位于 workspace_root 之下（防越权/符号链接逃逸），否则拒绝。
        """
        root = self._get("workspace_root", "./data/harness/workspaces")
        base = Path(root)
        if not base.is_absolute():
            base = Path(getattr(self.cfg, "base_dir", Path.cwd())).resolve() / base
        base = base.resolve()
        if workspace:
            p = Path(workspace)
            if not p.is_absolute():
                p = Path.cwd() / p
            p = p.resolve()  # resolve 同时处理符号链接
        else:
            p = base / session_id
        try:
            p.relative_to(base)
        except ValueError:
            raise ValueError(
                f"工作区路径 {p} 必须在 workspace_root({base}) 之下"
            ) from None
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _resolve_session_root(self) -> str:
        raw = self._get("session_root", "./data/harness/sessions")
        base = Path(raw)
        if not base.is_absolute():
            base = Path(getattr(self.cfg, "base_dir", Path.cwd())).resolve() / base
        base.mkdir(parents=True, exist_ok=True)
        return str(base)

    # ---- CLI 命令解析 / 子进程环境 ----

    def _resolve_cli_cmd(self, task: str) -> List[str]:
        """解析 CLI 命令为可执行列表。

        - harness.cli_command 是字符串（如 "npx @deepseek-ai/dsh"），shlex.split 成列表；
        - 首个可执行文件用 shutil.which 解析真实路径（Windows 上 npx → npx.cmd），
          否则 create_subprocess_exec 在 Windows 无法直接执行裸 "npx"；
        - dsh 若支持 -- 分隔符（cli_double_dash 默认 true），先追加 "--" 再跟 task，
          防止 task 被解析成命令参数注入；不支持时跳过直接追加 task。
        """
        raw = self._get("cli_command", "npx @deepseek-ai/dsh")
        if isinstance(raw, str):
            parts = shlex.split(raw)
        elif isinstance(raw, (list, tuple)):
            parts = [str(p) for p in raw]
        else:
            raise ValueError(f"harness.cli_command 类型不合法: {type(raw).__name__}")
        if not parts:
            raise ValueError("harness.cli_command 为空")
        resolved = [shutil.which(parts[0]) or parts[0]] + list(parts[1:])
        resolved += ["--profile", "headless"]
        if self._get("cli_double_dash", True):
            resolved.append("--")
        resolved.append(task)
        return resolved

    def _build_cli_env(
        self, session_root: str, model: str, max_tokens: int
    ) -> Dict[str, str]:
        """构造子进程环境：仅透传白名单变量（PATH/HOME/DEEPSEEK_API_KEY/DSH_* 等）。"""
        env: Dict[str, str] = {}
        # 系统必要变量白名单
        for k in (
            "PATH",
            "HOME",
            "USERPROFILE",
            "SYSTEMROOT",
            "COMSPEC",
            "PATHEXT",
            "TEMP",
            "TMP",
            "LANG",
            "LC_ALL",
        ):
            if k in os.environ:
                env[k] = os.environ[k]
        # DSH_* 运行时变量白名单（dsh 自身约定的配置前缀）
        for k, v in os.environ.items():
            if k.startswith("DSH_"):
                env[k] = v
        env.setdefault("DSH_MODEL", model)
        env.setdefault("DSH_SESSION_ROOT", session_root)
        env.setdefault("DSH_MAX_TOKENS", str(max_tokens))
        # API key 经 env 完整透传（子进程需要访问）
        env["DEEPSEEK_API_KEY"] = os.environ.get(
            "DEEPSEEK_API_KEY", self._get("api_key", "")
        )
        base_url = self._get("base_url", "")
        if base_url:
            env["DEEPSEEK_BASE_URL"] = base_url
        return env

    # ---- 执行入口 ----

    async def run(
        self,
        task: str,
        workspace: Optional[str] = None,
        session_id: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[int] = None,
    ) -> DSHResult:
        """
        在独立工作区运行一个 dsh 任务～
        - workspace: 工作区路径，默认 data/harness/workspaces/<session_id>
        - session_id: 会话 ID，复用同一 ID 可延续对话与持久 Bash 状态
        - 同一 session 串行：SDK/CLI 通道执行前都先获取 per-session 互斥锁
        """
        if not self._enabled():
            return DSHResult(
                ok=False, error="harness 未启用 (config harness.enabled = false)"
            )
        if not task.strip():
            return DSHResult(ok=False, error="任务描述为空")

        sid = session_id or f"session-{uuid.uuid4().hex[:12]}"

        # 安全门 1：danger-full-access 策略必须显式开启
        policy_error = self._policy_check()
        if policy_error:
            return DSHResult(ok=False, session_id=sid, error=policy_error)
        # 安全门 2：任务文本内嵌危险 shell 构造时拒绝（命令过滤接入点）
        filter_error = self._task_filter_check(task)
        if filter_error:
            logger.warning(f"dsh 任务被命令过滤拦截: {task[:200]}")
            return DSHResult(ok=False, session_id=sid, error=filter_error)
        try:
            ws = self._resolve_workspace(workspace, sid)
        except ValueError as e:
            return DSHResult(ok=False, session_id=sid, error=str(e))
        model = model or self._get("model", "deepseek-v4-flash")
        max_tokens = max_tokens or self._get("max_tokens", 49152)
        timeout = timeout or self._get("timeout_seconds", 600)
        mode = self._get("mode", "auto")
        session_root = self._resolve_session_root()

        # 同一 session 串行执行（防 SDK 线程未收尾时 CLI 并发启动）
        async with self._session_lock(session_root, sid):
            if mode in ("sdk", "auto") and self.sdk_available():
                sdk_task = asyncio.create_task(
                    self._run_sdk(task, ws, sid, session_root, model, max_tokens)
                )
                try:
                    # shield：超时不打断 asyncio.to_thread 的等待，线程继续收尾
                    return await asyncio.wait_for(
                        asyncio.shield(sdk_task), timeout=timeout
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"dsh SDK 超过 {timeout}s 未完成，等待线程收尾...")
                    try:
                        # 等 SDK 线程结束并取其结果（线程不可取消，必须等待）
                        result = await asyncio.wait_for(
                            asyncio.shield(sdk_task), timeout=30
                        )
                        logger.warning(
                            f"dsh SDK 线程已收尾（实际耗时超过 {timeout}s），采用其结果"
                        )
                        return result
                    except asyncio.TimeoutError:
                        # 额外 30s 仍未完成：记录 error 并返回超时错误，不启动 CLI 通道
                        logger.error(
                            "dsh SDK 线程 30s 内未收尾，放弃 CLI 降级，返回超时错误"
                        )
                        return DSHResult(
                            session_id=sid,
                            workspace=str(ws),
                            mode="sdk",
                            ok=False,
                            error=f"dsh SDK 执行超时({timeout}s)",
                        )
                    except Exception as e:
                        # SDK 线程以异常收尾（线程已结束，可安全降级 CLI）
                        logger.warning(f"dsh SDK 失败: {e}，尝试 CLI 降级...")
                except Exception as e:
                    # 非超时的 SDK 失败（线程已结束，可安全降级 CLI）
                    logger.warning(f"dsh SDK 失败: {e}，尝试 CLI 降级...")

            if mode in ("cli", "auto") and self.cli_available():
                try:
                    return await asyncio.wait_for(
                        self._run_cli(
                            task, ws, sid, session_root, model, max_tokens, timeout
                        ),
                        timeout=timeout,
                    )
                except asyncio.TimeoutError:
                    return DSHResult(
                        final_response="",
                        session_id=sid,
                        workspace=str(ws),
                        mode="cli",
                        ok=False,
                        error=f"dsh CLI 执行超时({timeout}s)",
                    )
                except Exception as e:
                    logger.error(f"dsh CLI 失败: {e}")
                    return DSHResult(
                        session_id=sid,
                        workspace=str(ws),
                        mode="cli",
                        ok=False,
                        error=f"dsh CLI 失败: {e}",
                    )

            return DSHResult(
                session_id=sid,
                workspace=str(ws),
                ok=False,
                error="无可用通道：请安装 deepseek-harness-sdk 或 Node.js(npx @deepseek-ai/dsh)",
            )

    async def _run_sdk(
        self,
        task: str,
        workspace: Path,
        session_id: str,
        session_root: str,
        model: str,
        max_tokens: int,
    ) -> DSHResult:
        """SDK 通道：deepseek_harness.DeepSeekHarness～"""
        cordis = self._cordis_config()
        if cordis is None:
            raise RuntimeError("cordis 配置不可用")
        provider = self._get("provider", "deepseek-official")

        def _inner() -> DSHResult:
            from deepseek_harness import DeepSeekHarness

            with DeepSeekHarness(
                provider=provider,
                model=model,
                max_tokens=max_tokens,
                cwd=str(workspace),
                session_root=session_root,
                cordis=str(cordis),
            ) as harness:
                result = harness.run(task, session_id=session_id)
            return DSHResult(
                final_response=getattr(result, "final_response", ""),
                session_id=session_id,
                workspace=str(workspace),
                mode="sdk",
                ok=True,
                metadata={"model": model},
            )

        return await asyncio.to_thread(_inner)

    async def _run_cli(
        self,
        task: str,
        workspace: Path,
        session_id: str,
        session_root: str,
        model: str,
        max_tokens: int,
        timeout: int,
    ) -> DSHResult:
        """CLI 通道：npx @deepseek-ai/dsh --profile headless [--] <task>～"""
        try:
            cmd = self._resolve_cli_cmd(task)
        except (ValueError, OSError) as e:
            return DSHResult(
                session_id=session_id,
                workspace=str(workspace),
                mode="cli",
                ok=False,
                error=f"CLI 命令解析失败: {e}",
            )

        env = self._build_cli_env(session_root, model, max_tokens)

        logger.info(f"dsh CLI 运行任务 {session_id} 于 {workspace}: {cmd}")
        spawn_kwargs: Dict[str, Any] = {}
        if os.name == "nt":
            # 独立进程组：超时后 taskkill /T 可整树清理
            spawn_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            # 独立会话：超时后 killpg 可整组清理
            spawn_kwargs["start_new_session"] = True
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(workspace),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **spawn_kwargs,
        )

        stdout_sink = _StdoutSink(max_bytes=200 * 1024)  # stdout 上限 200KB
        stderr_tail = _StderrTail(max_bytes=2000)
        try:
            await asyncio.wait_for(
                _drain_cli(proc, stdout_sink, stderr_tail), timeout=timeout
            )
        except asyncio.TimeoutError:
            # 超时路径必须整树终止 + wait 回收子进程，防止僵尸/孤儿进程
            _kill_tree(proc)
            await proc.wait()
            logger.warning(f"dsh CLI 执行超时({timeout}s)，已终止子进程树")
            return DSHResult(
                session_id=session_id,
                workspace=str(workspace),
                mode="cli",
                ok=False,
                error=f"dsh CLI 执行超时({timeout}s)",
            )
        except BaseException:
            # 外部取消等：同样回收子进程后继续抛出
            if proc.returncode is None:
                _kill_tree(proc)
                await proc.wait()
            raise

        if proc.returncode != 0:
            return DSHResult(
                session_id=session_id,
                workspace=str(workspace),
                mode="cli",
                ok=False,
                error=f"dsh CLI 退出码 {proc.returncode}: {stderr_tail.text()[:2000]}",
            )
        return DSHResult(
            final_response=stdout_sink.text().strip(),
            session_id=session_id,
            workspace=str(workspace),
            mode="cli",
            ok=True,
            metadata={"model": model},
        )


# 全局 dsh 客户端实例～
dsh_client = DSHClient()
