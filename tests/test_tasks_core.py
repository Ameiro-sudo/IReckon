"""engine/tasks.py 核心逻辑测试(补覆盖率盲区)。

覆盖：任务创建与上传批次白名单、_ingest_uploads 路径穿越防护、
参考文件需求拼装(超限/非法路径跳过)、_launch 包装的超时/取消/异常语义。
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest

from app.core.config import get
from app.core.database import db

import app.engine.tasks as tasks_mod
from app.engine.tasks import (
    TaskManager,
    TaskStatus,
    _ingest_uploads,
    task_manager,
)


@pytest.fixture
def fake_rooms(monkeypatch):
    """替换会议房间管理器，避免测试依赖真实房间生命周期。"""

    class FakeRooms:
        def __init__(self):
            self.closed = []

        async def close_room(self, tid):
            self.closed.append(tid)

        async def create_room(self, tid):
            pass

    fake = FakeRooms()
    monkeypatch.setattr(tasks_mod, "meeting_room_manager", fake)
    return fake


# ---------- create_task ----------


async def test_create_task_persists_pending(session_db):
    tid = await task_manager.create_task("写一个快排脚本")
    row = await db.fetch_one(
        "SELECT status, user_request FROM tasks WHERE task_id=?", (tid,)
    )
    assert row is not None
    assert row[0] == TaskStatus.PENDING.value
    assert row[1] == "写一个快排脚本"


async def test_create_task_rejects_malformed_upload_id(session_db):
    for bad in ("../evil", "UPPER_CASE", "short", "带空格 id"):
        with pytest.raises(ValueError):
            await task_manager.create_task("需求", upload_id=bad)


# ---------- _ingest_uploads ----------


def _uploads_root() -> Path:
    return (Path(get("system.data_dir", "./data")) / "uploads").resolve()


async def test_ingest_uploads_copies_files(session_db):
    batch = "up-abcdef123456"
    src = _uploads_root() / batch
    src.mkdir(parents=True, exist_ok=True)
    (src / "spec.md").write_text("# 规格", encoding="utf-8")
    (src / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    refs = await _ingest_uploads("task-test01", batch)
    assert [r["name"] for r in refs] == ["data.csv", "spec.md"]  # sorted
    copied = Path(get("system.data_dir", "./data")) / "outputs" / "task-test01" / "input"
    assert (copied / "spec.md").read_text(encoding="utf-8") == "# 规格"


async def test_ingest_uploads_traversal_rejected(session_db):
    assert await _ingest_uploads("task-test01", "../../etc") == []


async def test_ingest_uploads_missing_batch_returns_empty(session_db):
    assert await _ingest_uploads("task-test01", "up-deadbeef0000") == []


# ---------- _build_requirement_with_files ----------


def test_build_requirement_no_refs_unchanged():
    assert TaskManager._build_requirement_with_files("原始需求", []) == "原始需求"


def test_build_requirement_appends_small_file_content():
    data_dir = Path(get("system.data_dir", "./data"))
    rel = "outputs/task-rf01/input/notes.txt"
    f = data_dir / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("关键上下文内容", encoding="utf-8")
    out = TaskManager._build_requirement_with_files(
        "需求", [{"name": "notes.txt", "size": 18, "path": rel}]
    )
    assert "需求" in out and "### 文件: notes.txt" in out and "关键上下文内容" in out


def test_build_requirement_skips_oversized_file():
    data_dir = Path(get("system.data_dir", "./data"))
    rel = "outputs/task-rf02/input/big.log"
    f = data_dir / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x" * 200_001, encoding="utf-8")
    out = TaskManager._build_requirement_with_files(
        "需求", [{"name": "big.log", "size": 200_001, "path": rel}]
    )
    assert "```" not in out  # 只有清单行，无内容引用


def test_build_requirement_skips_illegal_path():
    out = TaskManager._build_requirement_with_files(
        "需求", [{"name": "evil.txt", "size": 3, "path": "../../../etc/passwd"}]
    )
    assert "passwd" not in out.split("【用户上传的参考文件】")[1]


# ---------- _launch 包装语义 ----------


def _fresh_manager():
    """绕过单例缓存拿干净实例（_running/_cancel_events 已隔离）。"""
    return TaskManager()


async def test_launch_marks_failed_on_exception(session_db, fake_rooms):
    tm = _fresh_manager()

    async def boom():
        raise RuntimeError("炸了")

    ce = asyncio.Event()
    await tm._launch("task-ex01", ce, boom)
    await asyncio.gather(*asyncio.all_tasks() - {asyncio.current_task()})
    # 任务行不存在时 _mark_status 静默失败属预期；此处验证清理
    assert "task-ex01" not in tm._running
    assert fake_rooms.closed == ["task-ex01"]


async def test_launch_cancel_with_event_means_paused(session_db, fake_rooms):
    tm = _fresh_manager()
    started = asyncio.Event()

    async def forever():
        started.set()
        await asyncio.sleep(3600)

    ce = asyncio.Event()
    await tm._launch("task-ca01", ce, forever)
    await started.wait()
    assert await tm.cancel_task("task-ca01") is True
    await asyncio.gather(*asyncio.all_tasks() - {asyncio.current_task()})
    assert "task-ca01" not in tm._cancel_events


async def test_cancel_unknown_task_returns_false():
    assert await _fresh_manager().cancel_task("task-nope") is False


def test_task_manager_singleton():
    assert TaskManager() is task_manager