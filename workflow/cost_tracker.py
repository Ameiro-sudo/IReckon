"""
成本追踪器
累计 Token 消耗，达预算上限时返回阻断信号
"""

from typing import Dict
from datetime import datetime
from loguru import logger
from core.config_manager import config_manager


class CostTracker:
    def __init__(self):
        self.budget_limit = config_manager.get("task_defaults.budget_limit_usd", 1.0)
        self.monthly_warning_threshold = config_manager.get(
            "task_defaults.monthly_token_warning_threshold", 50000
        )
        self._monthly_usage: Dict[str, int] = {}

    async def add_usage(self, task_id: str, tokens: int, cost: float):
        """记录一次 API 调用消耗"""
        logger.debug(f"任务 {task_id} 消耗 {tokens} tokens, 成本 ${cost:.4f}")
        now = self._current_month()
        self._monthly_usage[now] = self._monthly_usage.get(now, 0) + tokens
        if self._monthly_usage[now] > self.monthly_warning_threshold:
            logger.warning(
                f"月度 Token 消耗 {self._monthly_usage[now]} 超过告警阈值 {self.monthly_warning_threshold}"
            )

    async def is_over_budget(self, task_id: str) -> bool:
        # 实际需从数据库统计，此处作为占位
        return False

    def _current_month(self) -> str:
        return datetime.utcnow().strftime("%Y-%m")


cost_tracker = CostTracker()