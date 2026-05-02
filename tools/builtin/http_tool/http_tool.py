"""
工具零件：HTTP 请求助手
提供 GET、POST、PUT、DELETE 等常见 HTTP 操作，支持自定义头、超时、自动解析 JSON。
"""

import httpx
from typing import Optional, Dict, Any, Union

# 默认超时（秒）
DEFAULT_TIMEOUT = 15.0

def _make_client(timeout: float = DEFAULT_TIMEOUT) -> httpx.Client:
    """创建一个带超时的同步 httpx 客户端（连接池复用由上下文管理）。"""
    return httpx.Client(timeout=httpx.Timeout(timeout))

def http_request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json_data: Optional[Any] = None,
    data: Optional[Union[str, bytes]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """
    执行 HTTP 请求。

    Args:
        method: GET, POST, PUT, DELETE 等
        url: 请求地址
        headers: 请求头字典
        json_data: JSON 请求体（自动设置 Content-Type: application/json）
        data: 原始请求体（字符串或字节）
        timeout: 超时秒数

    Returns:
        字典包含 {
            "status_code": int,
            "headers": dict,          # 响应头
            "text": str,              # 响应体文本
            "json": Any,              # 自动解析的 JSON 对象（如果响应是 JSON）
            "elapsed": float          # 请求耗时(秒)
        }
        出错时返回 {"error": str}
    """
    method = method.upper()
    try:
        with _make_client(timeout) as client:
            request_kwargs = {"headers": headers or {}}
            if json_data is not None:
                request_kwargs["json"] = json_data
            if data is not None:
                request_kwargs["content"] = data if isinstance(data, bytes) else data.encode()

            response = client.request(method, url, **request_kwargs)

            result = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "text": response.text,
                "elapsed": response.elapsed.total_seconds(),
            }
            # 尝试解析 JSON
            try:
                result["json"] = response.json()
            except Exception:
                result["json"] = None
            return result
    except Exception as e:
        return {"error": str(e)}