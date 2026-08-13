"""成本追踪与死循环检测测试。"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from app.engine.cost import CostTracker
from app.engine.detector import LoopDetector


def test_cost_tracker_budget_exceeded(monkeypatch):
    ct = CostTracker()
    ct.max_task_tokens = 100
    import asyncio

    r1 = asyncio.run(ct.add_usage("t1", 60, 0.0))
    assert r1 is False
    r2 = asyncio.run(ct.add_usage("t1", 60, 0.0))
    assert r2 is True
    assert ct.get_task_usage("t1") == 120


def test_cost_tracker_monthly_warning(monkeypatch):
    ct = CostTracker()
    ct.monthly_warning_threshold = 50
    import asyncio

    asyncio.run(ct.add_usage("t2", 100, 0.0))
    assert ct._monthly_usage[ct._current_month()] >= 100


def test_cost_tracker_is_over_budget():
    ct = CostTracker()
    ct.max_task_tokens = 100
    ct._task_usage["t3"] = 150
    import asyncio

    assert asyncio.run(ct.is_over_budget("t3")) is True
    assert asyncio.run(ct.is_over_budget("t-other")) is False


def test_loop_detector_short_history():
    ld = LoopDetector()
    import asyncio

    assert asyncio.run(ld.check_loop("t", ["a", "b"])) is False


def test_loop_detector_identical_outputs(monkeypatch):
    ld = LoopDetector()
    ld.max_rounds = 3
    ld.similarity_threshold = 0.9
    import asyncio

    outputs = ["same output"] * 5
    assert asyncio.run(ld.check_loop("t", outputs)) is True


def test_loop_detector_distinct_outputs():
    ld = LoopDetector()
    ld.max_rounds = 3
    import asyncio

    outputs = ["alpha", "beta", "gamma", "delta"]
    assert asyncio.run(ld.check_loop("t", outputs)) is False
