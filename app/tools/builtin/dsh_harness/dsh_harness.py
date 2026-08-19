"""
dsh_task 工具：将任务委托给 DeepSeek Harness (dsh) 执行。

注意：该工具会在宿主机工作区执行 LLM 生成的命令，请谨慎使用。
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.config import config_manager
from app.harness import dsh_client


def _validate_workspace(workspace: Optional[str]) -> Optional[str]:
    """校验 workspace 必须位于 harness.workspace_root 之下。"""
    if not workspace:
        return None
    root = Path(
        config_manager.get("harness.workspace_root", "./data/harness/workspaces")
    ).resolve()
    ws = Path(workspace).resolve()
    try:
        ws.relative_to(root)
    except ValueError:
        raise ValueError(f"workspace 必须位于 {root} 之下")
    return str(ws)


def dsh_task(
    task: str,
    workspace: Optional[str] = None,
    session_id: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    """在 DeepSeek Harness 独立工作区运行任务，返回最终回答。

    参数：
    - task: 自然语言任务描述（必填）
    - workspace: 工作区路径，默认 data/harness/workspaces/<session_id>
    - session_id: 会话 ID，复用可延续对话与持久 Bash 状态
    - model: 模型名，默认取配置 harness.model
    - max_tokens: 最大输出 token，默认取配置 harness.max_tokens
    """
    if not task or not task.strip():
        return {"ok": False, "error": "task 不能为空"}
    try:
        workspace = _validate_workspace(workspace)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    async def _run():
        return await dsh_client.run(
            task=task,
            workspace=workspace,
            session_id=session_id,
            model=model,
            max_tokens=max_tokens,
        )

    try:
        result = asyncio.run(_run())
    except RuntimeError:
        # 当前线程已有运行中的事件循环（例如被异步链路同步调用）：
        # 在独立线程中执行，避免 "loop already running" 冲突
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(asyncio.run, _run()).result()

    return {
        "ok": result.ok,
        "final_response": result.final_response,
        "session_id": result.session_id,
        "workspace": result.workspace,
        "mode": result.mode,
        "error": result.error,
    }


def check_available() -> Dict[str, Any]:
    """探测 dsh 可用状态：sdk / cli / 不可用。"""
    mode = dsh_client.available_mode()
    return {
        "available": bool(mode),
        "mode": mode or "none",
        "sdk_installed": dsh_client.sdk_available(),
        "cli_available": dsh_client.cli_available(),
        "enabled": dsh_client._enabled(),
    }