"""IReckon MCP Server — 把能力池/执行通道暴露为标准 MCP 工具。

让外部 host（opencode / Claude Code / Claude Desktop 等）把 IReckon 当作
"专门被工具调用的模型池"：主模型遇到自包含子任务时一次 tool call 委托
过来，由执行通道（按 token/自托管）内部消化，主计费通道只留判断点。

启动（stdio 传输，推荐用根目录启动器——它会在导入 app 前把日志让路到 stderr）：
    python mcp_server.py

客户端注册示例（opencode.json / claude_desktop_config.json）：
    {
      "mcpServers": {
        "ireckon": {
          "command": "python",
          "args": ["mcp_server.py"],
          "cwd": "/path/to/IReckon"
        }
      }
    }

安全提示：stdio 仅本机可用；若改为 SSE/HTTP 传输暴露，必须自行加鉴权，
否则等于把 LLM 花费接口公开。
"""

import os

# 尽早生效：stdio 下 stdout 是协议通道，日志（含导入期）必须走 stderr。
# 根启动器 mcp_server.py 会在导入 app 包之前设置同一变量，双保险。
os.environ.setdefault("IRECKON_LOG_STREAM", "stderr")

from typing import Any, Dict, Optional  # noqa: E402

# 工具逻辑与 MCP 传输解耦：以下纯函数可直接单测（无需安装 mcp 包）

_db_ready = False


async def _ensure_db() -> None:
    """独立进程运行时懒初始化数据库（幂等）。"""
    global _db_ready
    if _db_ready:
        return
    from app.core.database import db

    await db.connect()
    _db_ready = True


async def tool_ask(
    prompt: str,
    system_prompt: str = "",
    tier: str = "light",
    max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    """一次性问答：默认走执行通道（轻模型），自包含子任务的最佳入口。"""
    await _ensure_db()
    from app.llm.router import ask

    return await ask(
        prompt,
        system_prompt=system_prompt or None,
        tier=tier,
        temperature=0.0,
        max_tokens=max_tokens,
        use_cache=True,
    )


async def tool_delegate(
    task: str,
    session_id: Optional[str] = None,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """粗粒度委托：整个子任务交给 dsh harness 自主循环完成，1 次调用换全部中间过程。"""
    await _ensure_db()
    from app.harness import dsh_client

    result = await dsh_client.run(task, workspace=workspace, session_id=session_id)
    return {
        "ok": result.ok,
        "session_id": result.session_id,
        "workspace": result.workspace,
        "mode": result.mode,
        "final_response": result.final_response,
        "error": result.error,
    }


REVIEW_SYSTEM_PROMPT = (
    "你是资深代码审查员。对给定代码做正确性与效率审查，输出：\n"
    "1. verdict: pass 或 fail\n"
    "2. issues: 问题列表（每条含 severity/file_or_scope/description/suggestion）\n"
    "3. summary: 一句话总评\n"
    "只做判断，不要重写整份代码。用 JSON 输出。"
)


async def tool_review(
    code: str,
    language: str = "",
    focus: str = "",
) -> Dict[str, Any]:
    """审查判定：走主通道（重模型），只给判定与修改建议，返工交给执行通道。"""
    await _ensure_db()
    from app.llm.router import ask

    prompt = f"语言: {language or '未知'}\n审查重点: {focus or '正确性+效率'}\n\n代码:\n```\n{code}\n```"
    return await ask(
        prompt,
        system_prompt=REVIEW_SYSTEM_PROMPT,
        tier="heavy",
        temperature=0.0,
        use_cache=True,
    )


async def tool_pool_status() -> Dict[str, Any]:
    """池状态：实例清单+计费通道+缓存命中统计（交叉测试观测用）。

    endpoint 只回传 host:port 的存在性形态（scheme+host 掩去路径与端口细节）：
    该工具暴露给任意注册的 MCP 客户端，完整 endpoint 属内部网络拓扑信息。
    """
    await _ensure_db()
    from app.llm.cache import response_cache
    from app.llm.pool import capability_pool
    from app.llm.router import channel_of
    from urllib.parse import urlparse

    def _masked_endpoint(endpoint: str) -> str:
        try:
            p = urlparse(endpoint or "")
            if not p.scheme or not p.hostname:
                return "(未配置)"
            return f"{p.scheme}://{p.hostname}{'/*' if p.port else ''}"
        except ValueError:
            return "(非法)"

    caps = list(await capability_pool.get_all())
    return {
        "instances": [
            {
                "id": c.id,
                "name": c.name,
                "model": c.model,
                "endpoint": _masked_endpoint(c.endpoint),
                "channel": channel_of(c),
                "enabled": c.enabled,
                "cost_per_1k_tokens": c.cost_per_1k_tokens,
            }
            for c in caps
        ],
        "cache": response_cache.stats(),
    }


# ---- MCP 传输层（需要 mcp 包，缺失时给出可执行的安装提示）----


def build_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        raise SystemExit("缺少 MCP SDK，请先安装: pip install 'mcp>=1.2,<2'") from e

    mcp = FastMCP("ireckon")

    @mcp.tool()
    async def ireckon_ask(
        prompt: str, system_prompt: str = "", tier: str = "light", max_tokens: int = 0
    ) -> dict:
        """一次性问答（默认轻量执行通道）。适合摘要/分类/抽取/生成等自包含子任务。"""
        return await tool_ask(prompt, system_prompt, tier, max_tokens or None)

    @mcp.tool()
    async def ireckon_delegate(
        task: str, session_id: str = "", workspace: str = ""
    ) -> dict:
        """粗粒度委托编码任务给 dsh 执行引擎，自主循环直到完成并汇回产物。"""
        return await tool_delegate(task, session_id or None, workspace or None)

    @mcp.tool()
    async def ireckon_review(code: str, language: str = "", focus: str = "") -> dict:
        """代码审查判定（重量级通道）：verdict + issues + summary，JSON 输出。"""
        return await tool_review(code, language, focus)

    @mcp.tool()
    async def ireckon_pool_status() -> dict:
        """查看能力池实例、计费通道划分与响应缓存命中统计。"""
        return await tool_pool_status()

    return mcp


def main() -> None:
    # 日志走向由 IRECKON_LOG_STREAM=stderr 控制（模块顶部已设置；
    # 根启动器在导入 app 前也会设置），stdout 保持纯 JSON-RPC。
    server = build_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
