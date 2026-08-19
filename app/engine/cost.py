from typing import Dict, Optional
from datetime import datetime, timezone
from loguru import logger
from app.core.config import config_manager

get = config_manager.get


class CostTracker:
    """成本与用量追踪。

    - `add_usage` 同步落库 usage_log（惰性建表），内存仅作兜底与告警；
    - `get_task_usage`/`get_monthly_usage` 优先从 DB 汇总，读不到时回退内存；
    - `enforce_limits` 供任务执行前做额度检查（Token 上限 / 月度美元预算 / 任务级预算）。
    """

    MAX_MEMORY_TASKS = 5000  # 内存 task 用量字典上限，防止无界增长（DB 仍是权威）

    def __init__(self):
        self.budget_limit = get("task_defaults.budget_limit_usd", 0.0)
        self.monthly_warning_threshold = get(
            "task_defaults.monthly_token_warning_threshold", 50000
        )
        self.max_task_tokens = get("task_defaults.max_task_tokens_per_task", 1000000)
        self.monthly_budget_usd = get("cost.monthly_budget_usd", 50.0)
        self._monthly_usage: Dict[str, int] = {}
        self._monthly_cost: Dict[str, float] = {}
        self._task_usage: Dict[str, int] = {}
        self._task_cost: Dict[str, float] = {}
        self._table_ready = False

    async def _ensure_table(self) -> None:
        """惰性建表：usage_log 表（另一代理负责 database.py，此处自行确保表存在）。"""
        if self._table_ready:
            return
        try:
            from app.core.database import db

            await db.execute(
                "CREATE TABLE IF NOT EXISTS usage_log ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "task_id TEXT, tokens INTEGER, cost REAL,"
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
            self._table_ready = True
        except Exception as e:
            logger.warning(f"usage_log 表初始化失败，降级为内存记账: {e}")

    async def add_usage(self, task_id: str, tokens: int, cost: float) -> bool:
        """记录任务消耗（写 DB + 更新内存）；返回是否已超任务 Token 上限。"""
        logger.debug(f"任务 {task_id} 消耗 {tokens} tokens, 成本 ${cost:.4f}")
        await self._ensure_table()
        try:
            from app.core.database import db

            await db.execute(
                "INSERT INTO usage_log(task_id,tokens,cost) VALUES(?,?,?)",
                (task_id, tokens, cost),
            )
        except Exception as e:
            logger.warning(f"用量落库失败: {e}")

        now = self._current_month()
        self._monthly_usage[now] = self._monthly_usage.get(now, 0) + tokens
        self._monthly_cost[now] = self._monthly_cost.get(now, 0.0) + cost
        if self._monthly_usage[now] > self.monthly_warning_threshold:
            logger.warning(
                f"月度 Token 消耗 {self._monthly_usage[now]} 超过告警阈值 {self.monthly_warning_threshold}"
            )

        task_total = self._task_usage.get(task_id, 0) + tokens
        self._task_usage[task_id] = task_total
        self._task_cost[task_id] = self._task_cost.get(task_id, 0.0) + cost
        if len(self._task_usage) > self.MAX_MEMORY_TASKS:
            # 淘汰最早记录的任务，防止内存无界增长（DB 仍是权威）
            self._task_usage.pop(next(iter(self._task_usage)), None)
        if task_total > self.max_task_tokens:
            logger.warning(
                f"任务 {task_id} 已消耗 {task_total} tokens，超过任务上限 {self.max_task_tokens}"
            )
            return True
        return False

    async def enforce_limits(self, task_id: str) -> Optional[str]:
        """任务执行前的额度检查；超限返回中文错误串，未超限返回 None。"""
        # ① 任务级 Token 上限
        max_task_tokens = self.max_task_tokens
        task_tokens = await self.get_task_usage_async(task_id)
        if task_tokens > max_task_tokens:
            return (
                f"任务 {task_id} 已消耗 {task_tokens} tokens，"
                f"超过任务 Token 上限 {max_task_tokens}，执行已中止"
            )
        # ② 月度美元预算
        month_cost = await self.get_monthly_cost()
        if month_cost >= self.monthly_budget_usd:
            return (
                f"本月已消耗 ${month_cost:.2f}，超过月度预算 "
                f"${self.monthly_budget_usd:.2f}，执行已中止"
            )
        # ③ 任务级美元预算
        limit = await self._task_budget_limit(task_id)
        if limit and limit > 0:
            task_cost = await self.get_task_cost_async(task_id)
            if task_cost >= limit:
                return (
                    f"任务 {task_id} 已消耗 ${task_cost:.2f}，"
                    f"超过任务预算 ${limit:.2f}，执行已中止"
                )
        return None

    async def is_over_budget(self, task_id: str) -> bool:
        """任务是否超预算；复用 enforce_limits 判定。"""
        return (await self.enforce_limits(task_id)) is not None

    async def get_task_usage_async(self, task_id: str) -> int:
        """从 DB SUM 重建任务用量；DB 未记录时回退内存（取两者较大值兜底）。"""
        db_val = None
        try:
            await self._ensure_table()
            from app.core.database import db

            row = await db.fetch_one(
                "SELECT COALESCE(SUM(tokens),0) FROM usage_log WHERE task_id=?",
                (task_id,),
            )
            if row:
                db_val = int(row[0])
        except Exception as e:
            logger.warning(f"读取任务 {task_id} 用量失败: {e}")
        mem_val = self._task_usage.get(task_id, 0)
        return max(db_val or 0, mem_val)

    async def get_task_cost_async(self, task_id: str) -> float:
        """任务美元成本：DB SUM，DB 未记录时回退内存（取两者较大值兜底）。"""
        db_val = None
        try:
            await self._ensure_table()
            from app.core.database import db

            row = await db.fetch_one(
                "SELECT COALESCE(SUM(cost),0) FROM usage_log WHERE task_id=?",
                (task_id,),
            )
            if row:
                db_val = float(row[0])
        except Exception as e:
            logger.warning(f"读取任务 {task_id} 成本失败: {e}")
        mem_val = self._task_cost.get(task_id, 0.0)
        return max(db_val or 0.0, mem_val)

    async def get_monthly_usage(self) -> int:
        """本月 Token 用量：DB SUM（本月），读不到时回退内存。"""
        try:
            await self._ensure_table()
            from app.core.database import db

            row = await db.fetch_one(
                "SELECT COALESCE(SUM(tokens),0) FROM usage_log "
                "WHERE strftime('%Y-%m', created_at) = strftime('%Y-%m','now')"
            )
            if row:
                return int(row[0])
        except Exception as e:
            logger.warning(f"读取本月用量失败: {e}")
        return self._monthly_usage.get(self._current_month(), 0)

    async def get_monthly_cost(self) -> float:
        """本月美元成本：DB SUM，读不到时回退内存。"""
        try:
            await self._ensure_table()
            from app.core.database import db

            row = await db.fetch_one(
                "SELECT COALESCE(SUM(cost),0) FROM usage_log "
                "WHERE strftime('%Y-%m', created_at) = strftime('%Y-%m','now')"
            )
            if row:
                return float(row[0])
        except Exception as e:
            logger.warning(f"读取本月成本失败: {e}")
        return self._monthly_cost.get(self._current_month(), 0.0)

    def get_task_usage(self, task_id: str) -> int:
        """同步取任务用量（内存快照，兼容旧调用方/测试）。"""
        return self._task_usage.get(task_id, 0)

    async def _task_budget_limit(self, task_id: str) -> float:
        """任务级美元预算：优先 tasks 表 budget_limit_usd 字段，否则取配置默认。"""
        try:
            from app.core.database import db

            await self._ensure_table()
            row = await db.fetch_one(
                "SELECT budget_limit_usd FROM tasks WHERE task_id=?", (task_id,)
            )
            if row and row[0]:
                return float(row[0])
        except Exception as e:
            logger.warning(f"读取任务 {task_id} 预算失败: {e}")
        return float(get("task_defaults.budget_limit_usd", 0.0))

    async def get_summary(self) -> Dict:
        """聚合用量：数据库持久化数据。"""
        try:
            from app.core.database import db

            return await db.get_usage_summary()
        except Exception as e:
            logger.warning(f"用量汇总失败: {e}")
        return {"total_tokens": 0, "total_cost": 0.0}

    def _current_month(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")


cost_tracker = CostTracker()
