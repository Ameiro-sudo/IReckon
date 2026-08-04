"""
统一异常定义
"""
from typing import Optional


class IReckonError(Exception):
    """基础异常类"""
    def __init__(self, message: str, original: Optional[Exception] = None):
        super().__init__(message)
        self.original = original
        self.message = message


class TaskError(IReckonError):
    """任务相关错误"""
    pass


class AgentError(IReckonError):
    """代理相关错误"""
    pass


class LLMError(IReckonError):
    """LLM调用错误"""
    pass


class DatabaseError(IReckonError):
    """数据库错误"""
    pass


class ConfigError(IReckonError):
    """配置错误"""
    pass


class RoomError(IReckonError):
    """会议室错误"""
    pass


class ToolError(IReckonError):
    """工具执行错误"""
    pass


class SecurityError(IReckonError):
    """安全相关错误"""
    pass