"""
DeepSeek Harness (dsh) 集成包～

封装 DeepSeek 官方开源 agent harness，提供双通道执行：
- SDK 通道：deepseek-harness-sdk（Python SDK，推荐）
- CLI 通道：npx @deepseek-ai/dsh --profile headless（无 SDK 时的降级方案）
"""

from .dsh_client import DSHClient, DSHResult, dsh_client

__all__ = ["DSHClient", "DSHResult", "dsh_client"]
