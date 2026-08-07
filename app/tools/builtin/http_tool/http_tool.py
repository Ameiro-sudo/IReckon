"""
HTTP request helper.
Provides GET, POST, PUT, DELETE wrappers using httpx.
"""

import httpx
from typing import Optional, Dict, Any, Union

DEFAULT_TIMEOUT = 15.0


def _make_client(timeout: float = DEFAULT_TIMEOUT) -> httpx.Client:
    """Create a client with a timeout."""
    return httpx.Client(timeout=httpx.Timeout(timeout))


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
            try:
                result["json"] = response.json()
            except Exception:
                result["json"] = None
            return result
    except Exception as e:
        return {"error": str(e)}
