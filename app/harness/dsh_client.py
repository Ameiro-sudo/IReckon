"""
DeepSeek Harness (dsh) 客户端
负责调用 DeepSeek 官方开源 agent harness 执行软件开发任务。
双通道设计：优先 Python SDK，SDK 不可用时降级到 headless CLI。
"""

import asyncio
import importlib.util
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from app.core.config import config_manager

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


class DSHClient:
    """
    DeepSeek Harness 客户端核心类～
    支持 SDK / headless CLI 双通道自动选择，会话持久化，超时控制。
    """

    def __init__(self, cfg: Any = None):
        self.cfg = cfg or config_manager
        self._sdk_checked: Optional[bool] = None
        self._cli_checked: Optional[bool] = None

    # ---- 可用性探测 ----

    def sdk_available(self) -> bool:
        """Python SDK (deepseek-harness-sdk) 是否可用～"""
        if self._sdk_checked is None:
            self._sdk_checked = importlib.util.find_spec("deepseek_harness") is not None
        return self._sdk_checked

    def cli_available(self) -> bool:
        """headless CLI (npx @deepseek-ai/dsh) 是否可用～"""
        if self._cli_checked is None:
            self._cli_checked = shutil.which("npx") is not None or shutil.which("node") is not None
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

    def _cordis_config(self) -> Optional[Path]:
        """解析 cordis 组合配置，缺失时用内置模板生成～"""
        raw = self._get("cordis_config", "config/harness/minimal.cordis.yml")
        if not raw:
            return None
        p = Path(raw)
        if not p.is_absolute():
            base = Path(getattr(self.cfg, "base_dir", Path.cwd())).resolve()
            p = base / p
        if not p.exists():
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(DEFAULT_CORDIS_TEMPLATE, encoding="utf-8")
                logger.info(f"已生成 dsh cordis 配置模板: {p}")
            except OSError as e:
                logger.warning(f"无法生成 cordis 配置: {e}")
                return None
        return p

    def _resolve_workspace(self, workspace: Optional[str], session_id: str) -> Path:
        """工作区：显式传入优先，否则按 session_id 隔离～"""
        if workspace:
            p = Path(workspace)
            if not p.is_absolute():
                p = Path.cwd() / p
        else:
            root = self._get("workspace_root", "./data/harness/workspaces")
            base = Path(root)
            if not base.is_absolute():
                base = Path(getattr(self.cfg, "base_dir", Path.cwd())).resolve() / base
            p = base / session_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _resolve_session_root(self) -> str:
        raw = self._get("session_root", "./data/harness/sessions")
        base = Path(raw)
        if not base.is_absolute():
            base = Path(getattr(self.cfg, "base_dir", Path.cwd())).resolve() / base
        base.mkdir(parents=True, exist_ok=True)
        return str(base)

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
        """
        if not self._enabled():
            return DSHResult(ok=False, error="harness 未启用 (config harness.enabled = false)")
        if not task.strip():
            return DSHResult(ok=False, error="任务描述为空")

        sid = session_id or f"session-{uuid.uuid4().hex[:12]}"
        ws = self._resolve_workspace(workspace, sid)
        model = model or self._get("model", "deepseek-v4-flash")
        max_tokens = max_tokens or self._get("max_tokens", 49152)
        timeout = timeout or self._get("timeout_seconds", 600)
        mode = self._get("mode", "auto")
        session_root = self._resolve_session_root()

        if mode in ("sdk", "auto") and self.sdk_available():
            try:
                return await asyncio.wait_for(
                    self._run_sdk(task, ws, sid, session_root, model, max_tokens),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(f"dsh SDK 超时({timeout}s)，尝试 CLI 降级...")
            except Exception as e:
                logger.warning(f"dsh SDK 失败: {e}，尝试 CLI 降级...")

        if mode in ("cli", "auto") and self.cli_available():
            try:
                return await asyncio.wait_for(
                    self._run_cli(task, ws, sid, session_root, model, max_tokens),
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
    ) -> DSHResult:
        """CLI 通道：npx @deepseek-ai/dsh --profile headless "task"～"""
        cmd_str = self._get("cli_command", "npx @deepseek-ai/dsh")
        cmd = cmd_str.split()
        cmd.append("--profile")
        cmd.append("headless")
        cmd.append(task)

        env = dict(os.environ)
        env.setdefault("DSH_MODEL", model)
        env.setdefault("DSH_SESSION_ROOT", session_root)
        env.setdefault("DSH_MAX_TOKENS", str(max_tokens))
        base_url = self._get("base_url", "")
        if base_url:
            env["DEEPSEEK_BASE_URL"] = base_url
        if "DEEPSEEK_API_KEY" not in env:
            env["DEEPSEEK_API_KEY"] = self._get("api_key", "")

        logger.info(f"dsh CLI 运行任务 {session_id} 于 {workspace}")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(workspace),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        out = stdout.decode(errors="replace")
        err = stderr.decode(errors="replace")
        if proc.returncode != 0:
            return DSHResult(
                session_id=session_id,
                workspace=str(workspace),
                mode="cli",
                ok=False,
                error=f"dsh CLI 退出码 {proc.returncode}: {err[:2000]}",
            )
        return DSHResult(
            final_response=out.strip(),
            session_id=session_id,
            workspace=str(workspace),
            mode="cli",
            ok=True,
            metadata={"model": model},
        )


# 全局 dsh 客户端实例～
dsh_client = DSHClient()
