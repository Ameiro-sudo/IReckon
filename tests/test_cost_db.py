"""CostTracker DB 路径补测：惰性建表/落库/回退语义/三段额度检查。

既有 test_engine.py 只覆盖内存记账；本文件用 FakeDB 打桩 app.core.database.db，
覆盖 DB 权威读、失败降级内存、月度/任务预算分支与内存字典淘汰。
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import app.core.database as database_mod
import app.engine.cost as cost_mod
from app.engine.cost import CostTracker, _current_month


class FakeDB:
    """最小数据库替身：execute 记录调用；fetch_one 按脚本队列回放。"""

    def __init__(self):
        self.execute_calls = []
        self.fetch_script = []
        self.fail_execute = False
        self.summary = {"total_tokens": 11, "total_cost": 2.5}

    async def execute(self, sql, params=None):
        if self.fail_execute:
            raise RuntimeError("db down")
        self.execute_calls.append(" ".join(str(sql).split())[:60])

    async def fetch_one(self, sql, params=None):
        if self.fetch_script:
            item = self.fetch_script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return None

    async def get_usage_summary(self):
        if self.fail_execute:
            raise RuntimeError("db down")
        return dict(self.summary)


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(database_mod, "db", db)
    return db


def _tracker(**overrides) -> CostTracker:
    ct = CostTracker()
    ct.monthly_warning_threshold = 10**9
    ct.max_task_tokens = 10**9
    ct.monthly_budget_usd = 10**9
    for k, v in overrides.items():
        setattr(ct, k, v)
    return ct


# ---------- 惰性建表与落库 ----------


async def test_ensure_table_runs_once_then_cached(fake_db):
    ct = _tracker()
    await ct.add_usage("t1", 10, 0.5)
    await ct.add_usage("t1", 5, 0.25)
    creates = [c for c in fake_db.execute_calls if c.startswith("CREATE TABLE")]
    inserts = [c for c in fake_db.execute_calls if c.startswith("INSERT")]
    assert len(creates) == 1
    assert len(inserts) == 2
    assert ct._table_ready is True


async def test_add_usage_db_failure_degrades_to_memory(fake_db):
    fake_db.fail_execute = True
    ct = _tracker()
    assert (await ct.add_usage("t1", 30, 1.0)) is False
    assert ct.get_task_usage("t1") == 30
    assert ct._monthly_usage[_current_month()] >= 30
    assert ct._table_ready is False


async def test_add_usage_true_when_crossing_task_token_limit():
    ct = _tracker(max_task_tokens=100)
    assert (await ct.add_usage("t1", 60, 0.0)) is False
    assert (await ct.add_usage("t1", 60, 0.0)) is True


async def test_memory_task_dict_evicts_oldest():
    ct = _tracker()
    ct.MAX_MEMORY_TASKS = 2
    await ct.add_usage("a", 1, 0.0)
    await ct.add_usage("b", 1, 0.0)
    await ct.add_usage("c", 1, 0.0)
    assert "a" not in ct._task_usage
    assert set(ct._task_usage) == {"b", "c"}


# ---------- DB 读：取大值兜底与失败回退 ----------


async def test_get_task_usage_takes_max_of_db_and_memory(fake_db):
    fake_db.fetch_script = [(120,)]
    ct = _tracker()
    ct._task_usage["t1"] = 50
    assert await ct.get_task_usage_async("t1") == 120
    fake_db.fetch_script = [(120,)]
    ct._task_usage["t1"] = 200
    assert await ct.get_task_usage_async("t1") == 200


async def test_get_task_usage_db_error_falls_back_to_memory(fake_db):
    fake_db.fetch_script = [RuntimeError("locked")]
    ct = _tracker()
    ct._task_usage["t1"] = 77
    assert await ct.get_task_usage_async("t1") == 77
    ct._task_usage.pop("t1")
    assert await ct.get_task_usage_async("t1") == 0


async def test_get_task_cost_takes_max_and_falls_back(fake_db):
    ct = _tracker()
    ct._task_cost["t1"] = 3.0
    fake_db.fetch_script = [(1.5,)]
    assert await ct.get_task_cost_async("t1") == 3.0
    fake_db.fetch_script = [(9.5,)]
    assert await ct.get_task_cost_async("t1") == 9.5
    fake_db.fetch_script = [RuntimeError("down")]
    assert await ct.get_task_cost_async("t1") == 3.0


async def test_monthly_usage_db_hit_and_error_fallback(fake_db):
    ct = _tracker()
    fake_db.fetch_script = [(500,)]
    assert await ct.get_monthly_usage() == 500
    fake_db.fetch_script = [RuntimeError("down")]
    ct._monthly_usage[_current_month()] = 123
    assert await ct.get_monthly_usage() == 123


async def test_monthly_cost_db_error_falls_back_to_memory(fake_db):
    ct = _tracker()
    fake_db.fetch_script = [RuntimeError("down")]
    ct._monthly_cost[_current_month()] = 4.25
    assert await ct.get_monthly_cost() == 4.25


# ---------- enforce_limits 三段额度检查（按判定顺序打桩） ----------


async def test_enforce_limits_task_token_branch(fake_db):
    ct = _tracker(max_task_tokens=100)
    fake_db.fetch_script = [(1000,)]
    msg = await ct.enforce_limits("t1")
    assert msg and "任务 Token 上限" in msg


async def test_enforce_limits_monthly_budget_branch(fake_db):
    ct = _tracker(monthly_budget_usd=50.0)
    # 判定顺序：任务 token(0) → 月度成本(99.9 命中预算闸)
    fake_db.fetch_script = [(0,), (99.9,)]
    msg = await ct.enforce_limits("t1")
    assert msg and "月度预算" in msg


async def test_enforce_limits_task_budget_branch(fake_db):
    ct = _tracker(monthly_budget_usd=50.0)
    # 顺序：任务token(0) → 月度成本(0) → tasks 表预算(5.0) → 任务成本(10.0)
    fake_db.fetch_script = [(0,), (0.0,), (5.0,), (10.0,)]
    msg = await ct.enforce_limits("t1")
    assert msg and "超过任务预算 $5.00" in msg


async def test_enforce_limits_all_clear_returns_none(fake_db):
    fake_db.fetch_script = [(0,), (0.0,), (None,)]
    assert await _tracker().enforce_limits("t1") is None


async def test_task_budget_limit_row_missing_uses_default(fake_db, monkeypatch):
    fake_db.fetch_script = [(None,)]
    real_get = cost_mod.get

    def fake_get(key, default=None):
        if key == "task_defaults.budget_limit_usd":
            return 7.5
        return real_get(key, default)

    monkeypatch.setattr(cost_mod, "get", fake_get)
    assert await _tracker()._task_budget_limit("t1") == 7.5


async def test_task_budget_limit_db_error_returns_default(fake_db):
    fake_db.fetch_script = [RuntimeError("down")]
    assert await _tracker()._task_budget_limit("t1") >= 0.0


# ---------- get_summary ----------


async def test_get_summary_passthrough(fake_db):
    out = await cost_mod.get_summary()
    assert out == {"total_tokens": 11, "total_cost": 2.5}


async def test_get_summary_failure_returns_zeros(monkeypatch):
    class _Broken:
        async def get_usage_summary(self):
            raise RuntimeError("db gone")

    monkeypatch.setattr(database_mod, "db", _Broken())
    out = await cost_mod.get_summary()
    assert out == {"total_tokens": 0, "total_cost": 0.0}
