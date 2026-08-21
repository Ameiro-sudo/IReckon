"""IReckon MCP Server 启动器（stdio 传输）。

必须在导入任何 app.* 之前设置 IRECKON_LOG_STREAM=stderr：
MCP stdio 模式下 stdout 是 JSON-RPC 协议通道，所有日志（含导入期）
必须让路到 stderr，否则会污染协议流导致客户端解析失败。

用法：
    python mcp_server.py
"""

import os

os.environ.setdefault("IRECKON_LOG_STREAM", "stderr")

from app.mcp_server import main  # noqa: E402

if __name__ == "__main__":
    main()
