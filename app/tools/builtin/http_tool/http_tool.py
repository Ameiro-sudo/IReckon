"""
HTTP request helper.
Provides GET, POST, PUT, DELETE wrappers using httpx.

SSRF 防护：仅允许公网 http/https 目标，拒绝内网/环回/链路本地地址，
禁止重定向，限制响应体大小。
"""

import ipaddress
import socket
from typing import Optional, Dict, Any, Union
from urllib.parse import urlsplit

import httpx

DEFAULT_TIMEOUT = 10.0
MAX_RESPONSE_BYTES = 1024 * 1024  # 1MB


def _is_safe_url(url: str) -> str:
    """校验 URL scheme 与目标 IP，返回规范化 URL；不安全时抛 ValueError。"""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"仅支持 http/https URL: {url}")
    host = parts.hostname
    if not host:
        raise ValueError(f"URL 缺少主机名: {url}")
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValueError(f"无法解析主机: {host}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError(f"禁止访问内网/保留地址: {host} ({ip})")
    return url


def _make_client(timeout: float = DEFAULT_TIMEOUT) -> httpx.Client:
    """Create a client with a timeout; redirects disabled (SSRF 防护)."""
    return httpx.Client(timeout=httpx.Timeout(timeout), follow_redirects=False)


def http_request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json_data: Optional[Any] = None,
    data: Optional[Union[str, bytes]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """Send an HTTP request and return a normalized result."""
    method = method.upper()
    try:
        url = _is_safe_url(url)
        with _make_client(timeout) as client:
            request_kwargs: Dict[str, Any] = {"headers": headers or {}}
            if json_data is not None:
                request_kwargs["json"] = json_data
            if data is not None:
                request_kwargs["content"] = (
                    data if isinstance(data, bytes) else data.encode()
                )

            response = client.request(method, url, **request_kwargs)
            text = response.text
            if len(response.content) > MAX_RESPONSE_BYTES:
                text = text[: MAX_RESPONSE_BYTES] + "\n...[响应超限截断]"
            result = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "text": text,
                "elapsed": response.elapsed.total_seconds(),
            }
            try:
                result["json"] = response.json()
            except Exception:
                result["json"] = None
            return result
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}