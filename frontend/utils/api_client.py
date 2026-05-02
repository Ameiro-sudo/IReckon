import requests
from typing import List, Dict, Optional, Any
from urllib.parse import urljoin

class APIClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/') + '/'
        self.timeout = 10

    def _request(self, method: str, path: str, **kwargs) -> Optional[Dict | List]:
        url = urljoin(self.base_url, path)
        try:
            resp = requests.request(method, url, timeout=self.timeout, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            print(f"请求超时: {url}")
            return None
        except requests.exceptions.ConnectionError:
            print(f"连接失败: {url}")
            return None
        except Exception as e:
            print(f"API 请求异常: {e}")
            return None

    def get_tasks(self) -> List[Dict]:
        result = self._request("GET", "/api/tasks")
        return result if isinstance(result, list) else []

    def create_task(self, user_request: str, scheduler_cap_id: Optional[str] = None) -> Optional[Dict]:
        return self._request("POST", "/api/tasks", json={"user_request": user_request, "scheduler_cap_id": scheduler_cap_id})

    def get_messages(self, task_id: str, layer: str = "L1", limit: int = 100) -> List[Dict]:
        result = self._request("GET", f"/api/tasks/{task_id}/messages", params={"layer": layer, "limit": limit})
        return result if isinstance(result, list) else []

    def send_message(self, task_id: str, content: str, layer: str = "L1") -> Optional[Dict]:
        return self._request("POST", f"/api/tasks/{task_id}/messages", json={"content": content, "layer": layer})

    def get_ai_instances(self) -> List[Dict]:
        result = self._request("GET", "/api/ai-instances")
        return result if isinstance(result, list) else []

    def create_ai_instance(self, data: Dict) -> Optional[Dict]:
        return self._request("POST", "/api/ai-instances", json=data)

    def update_ai_instance(self, instance_id: str, data: Dict) -> Optional[Dict]:
        return self._request("PUT", f"/api/ai-instances/{instance_id}", json=data)

    def delete_ai_instance(self, instance_id: str) -> Optional[Dict]:
        return self._request("DELETE", f"/api/ai-instances/{instance_id}")

    def test_ai_instance(self, instance_id: str) -> Optional[Dict]:
        return self._request("POST", f"/api/ai-instances/{instance_id}/test")

    def update_config(self, updates: Dict[str, Any]) -> Optional[Dict]:
        return self._request("POST", "/api/config/update", json={"updates": updates})