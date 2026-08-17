from typing import Dict
from datetime import datetime, timezone
from loguru import logger
from app.core.config import config_manager
class CostTracker:
    def __init__(self):
        self.budget_limit = config_manager.get("task_defaults.budget_limit_usd", 1.0)
        self.monthly_warning_threshold = config_manager.get(
            "task_defaults.monthly_token_warning_threshold", 50000
        )
        self.max_task_tokens = config_manager.get(
            "task_defaults.max_task_tokens_per_task", 200000
        )
        self._monthly_usage: Dict[str, int] = {}
        self._task_usage: Dict[str, int] = {}

    async def add_usage(self, task_id: str, tokens: int, cost: float) -> bool:
        """记录任务消耗；返回是否已超预算。"""
        logger.debug(f"任务 {task_id} 消耗 {tokens} tokens, 成本 ${cost:.4f}")
        try:
            from app.core.database import db

            await db.add_usage(task_id, tokens, cost)
        except Exception as e:
            logger.warning(f"用量落库失败: {e}")
        now = self._current_month()
        self._monthly_usage[now] = self._monthly_usage.get(now, 0) + tokens
        if self._monthly_usage[now] > self.monthly_warning_threshold:
            logger.warning(
                f"月度 Token 消耗 {self._monthly_usage[now]} 超过告警阈值 {self.monthly_warning_threshold}"
            )

        task_total = self._task_usage.get(task_id, 0) + tokens
        self._task_usage[task_id] = task_total
        if task_total > self.max_task_tokens:
            logger.warning(
                f"任务 {task_id} 已消耗 {task_total} tokens，超过任务上限 {self.max_task_tokens}"
            )
            return True
        return False

    async def is_over_budget(self, task_id: str) -> bool:
        return self._task_usage.get(task_id, 0) > self.max_task_tokens

    def get_task_usage(self, task_id: str) -> int:
        return self._task_usage.get(task_id, 0)

    async def get_summary(self) -> Dict:
        """聚合用量：内存 + 数据库持久化数据。"""
        try:
            from app.core.database import db

            return await db.get_usage_summary()
        except Exception as e:
            logger.warning(f"用量汇总失败: {e}")
        return {"total_tokens": 0, "total_cost": 0.0}

    def _current_month(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")


cost_tracker = CostTracker()
