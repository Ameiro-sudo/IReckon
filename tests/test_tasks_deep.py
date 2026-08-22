"""engine/tasks.py 深水区补测：上传摄取、参考文件拼装、启动守卫、
取消/超时/异常矩阵、resume_task 全流程（团队重建/回退链/错误矩阵）。

隔离策略：TaskManager 单例用 object.__new__ 构造裸实例；config 读取经
monkeypatch tasks_mod.get 指向受控字典；调度器/工作流引擎/会议室以替身注入。
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import app.engine.tasks as tasks_mod
from app.engine.tasks import TaskManager, TaskStatus, _ingest_uploads


def _tm() -> TaskManager:
    tm = object.__new__(TaskManager)
    tm._running = {}
    tm._cancel_events = {}
    return tm


@pytest.fixture()
def fake_cfg(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    (data_dir / "uploads").mkdir(parents=True)
    cfg = {
        "system.data_dir": str(data_dir),
        "task_defaults.max_task_duration_seconds": 3600,
        "task_defaults.max_review_rounds": 5,
        "ui.theme": "catgirl",
    }
    monkeypatch.setattr(tasks_mod, "get", lambda k, d=None: cfg.get(k, d))
    return data_dir


@pytest.fixture()
def marks(monkeypatch):
    seen = []

    async def fake_mark(tid, status):
        seen.append((tid, status.value))

    monkeypatch.setattr(tasks_mod, "_mark_status", fake_mark)
    return seen


@pytest.fixture()
def rooms(monkeypatch):
    events = []

    class FakeMRM:
        async def create_room(self, tid):
            events.append(("create", tid))

        async def close_room(self, tid):
            events.append(("close", tid))

    monkeypatch.setattr(tasks_mod, "meeting_room_manager", FakeMRM())
    return events


# ---------- _ingest_uploads ----------


def test_ingest_skips_traversal_and_missing_dir(fake_cfg):
    assert asyncio.run(_ingest_uploads("t1", "../evil")) == []  # 穿越拒绝
    assert asyncio.run(_ingest_uploads("t1", "no-such-batch")) == []  # 目录缺失


def test_ingest_copies_files_skips_dirs_and_errors(fake_cfg, monkeypatch):
    batch = fake_cfg / "uploads" / "batch01"
    batch.mkdir(parents=True)
    (batch / "a.txt").write_text("hello", encoding="utf-8")
    (batch / "b.md").write_text("# md", encoding="utf-8")
    (batch / "sub").mkdir()  # 非文件条目应跳过

    real_copy2 = __import__("shutil").copy2

    def flaky_copy(src, dst):
        if Path(src).name == "a.txt":
            raise OSError("disk full")
        return real_copy2(src, dst)

    monkeypatch.setattr(tasks_mod.shutil, "copy2", flaky_copy)
    refs = asyncio.run(_ingest_uploads("tid-copy", "batch01"))
    # a.txt 拷贝失败被跳过并告警，仅 b.md 入引用
    assert [r["name"] for r in refs] == ["b.md"]
    assert refs[0]["path"] == "outputs/tid-copy/input/b.md"


# ---------- create_task ----------


async def test_create_task_rejects_bad_upload_id(session_db, fake_cfg):
    with pytest.raises(ValueError):
        await TaskManager().create_task("需求", upload_id="UP!!")


async def test_create_task_inserts_pending_row(session_db, fake_cfg):
    tid = await TaskManager().create_task("写个爬虫")
    row = await session_db.fetch_one(
        "SELECT status,title,user_request FROM tasks WHERE task_id=?", (tid,)
    )
    assert row is not None
    assert row[0] == TaskStatus.PENDING.value
    assert row[2] == "写个爬虫"
    assert (
        json.loads(
            (
                await session_db.fetch_one(
                    "SELECT file_refs FROM tasks WHERE task_id=?", (tid,)
                )
            )[0]
        )
        == []
    )


# ---------- _build_requirement_with_files ----------


def _mk_file(data_dir, rel, size=10, text=None):
    p = data_dir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if text is not None:
        p.write_text(text, encoding="utf-8")
    else:
        p.write_bytes(b"x" * size)
    return p


def test_build_requirement_no_refs_identity():
    assert TaskManager._build_requirement_with_files("原始需求", []) == "原始需求"


def test_build_requirement_appends_small_files(fake_cfg):
    _mk_file(fake_cfg, "outputs/t1/input/a.py", text="print(1)")
    refs = [
        {"name": "a.py", "size": 8, "path": "outputs/t1/input/a.py"},
        {
            "name": "ghost.py",
            "size": 3,
            "path": "outputs/t1/input/ghost.py",
        },  # 实文件不存在
    ]
    out = TaskManager._build_requirement_with_files("做件事", refs)
    assert out.startswith("做件事")
    assert "- a.py (8 bytes)" in out  # 清单两行都列（ghost 仅列清单不贴内容）
    assert "### 文件: a.py" in out and "print(1)" in out
    assert "### 文件: ghost.py" not in out


def test_build_requirement_skips_traversal_and_oversize(fake_cfg):
    _mk_file(fake_cfg, "outputs/t2/input/big.bin", size=200_001)
    refs = [
        {"name": "evil", "size": 1, "path": "../../../etc/passwd"},
        {"name": "big.bin", "size": 200_001, "path": "outputs/t2/input/big.bin"},
    ]
    out = TaskManager._build_requirement_with_files("需求", refs)
    assert out.startswith("需求")
    assert "- big.bin (200001 bytes)" in out  # 清单行列出
    assert "### 文件:" not in out  # 穿越+超限的内容块全部跳过


def test_build_requirement_unreadable_entry_skipped(fake_cfg, monkeypatch):
    _mk_file(fake_cfg, "outputs/t3/input/a.txt", text="secret")
    refs = [{"name": "a.txt", "size": 6, "path": "outputs/t3/input/a.txt"}]

    def boom(self, *a, **kw):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_text", boom)
    out = TaskManager._build_requirement_with_files("需求", refs)
    monkeypatch.undo()
    assert "- a.txt (6 bytes)" in out  # 清单行列出
    assert "### 文件:" not in out  # read_text 异常 → 内容块 continue 分支


# ---------- start_task / cancel_task ----------


def test_start_task_guard_when_already_running():
    tm = _tm()
    sentinel = object()
    tm._running["t9"] = sentinel
    asyncio.run(tm.start_task("t9"))
    assert "t9" not in tm._cancel_events  # 已在跑：直接返回不再登记


async def test_cancel_task_returns_false_for_unknown():
    assert await _tm().cancel_task("不存在") is False


async def test_cancel_task_cancels_running():
    tm = _tm()
    ce = asyncio.Event()
    tm._cancel_events["t1"] = ce

    async def forever():
        await asyncio.sleep(3600)

    task = asyncio.create_task(forever())
    tm._running["t1"] = task
    assert await tm.cancel_task("t1") is True
    await asyncio.sleep(0)
    assert task.cancelled()


# ---------- _launch 错误矩阵 ----------


async def test_launch_marks_failed_on_generic_error(marks, rooms, monkeypatch):
    tm = _tm()

    async def body():
        raise ValueError("执行爆炸")

    await tm._launch("tE", asyncio.Event(), body)
    await asyncio.sleep(0.05)
    assert marks == [("tE", "failed")]
    assert "tE" not in tm._running and "tE" not in tm._cancel_events
    assert ("close", "tE") in rooms


async def test_launch_timeout_marks_failed(marks, rooms, fake_cfg, monkeypatch):
    monkeypatch.setattr(tasks_mod, "get", lambda k, d=None: 0.05)
    tm = _tm()

    async def body():
        await asyncio.sleep(0.5)

    await tm._launch("tT", asyncio.Event(), body)
    await asyncio.sleep(0.4)
    assert ("tT", "failed") in marks


async def test_launch_cancel_semantics_paused_vs_failed(marks, rooms):
    tm = _tm()

    async def hang():
        await asyncio.sleep(3600)

    ce_on = asyncio.Event()
    ce_on.set()  # 用户主动取消（事件已置位）→ PAUSED
    await tm._launch("tP", ce_on, hang)
    await asyncio.sleep(
        0.01
    )  # 让包装任务实际进入挂起点，否则 cancel 早于首拍=未执行即取消
    tm._running["tP"].cancel()
    await asyncio.gather(
        *asyncio.all_tasks() - {asyncio.current_task()}, return_exceptions=True
    )
    assert ("tP", "paused") in marks

    ce_off = asyncio.Event()  # 外部取消（事件未置位）→ FAILED
    await tm._launch("tF", ce_off, hang)
    await asyncio.sleep(0.01)
    tm._running["tF"].cancel()
    await asyncio.gather(
        *asyncio.all_tasks() - {asyncio.current_task()}, return_exceptions=True
    )
    assert ("tF", "failed") in marks


async def test_launch_success_cleans_up_without_fail_mark(marks, rooms):
    tm = _tm()

    async def body():
        return "done"

    await tm._launch("tOK", asyncio.Event(), body)
    await asyncio.sleep(0.05)
    assert marks == []  # 成功路径不打 failed
    assert "tOK" not in tm._running
    assert ("close", "tOK") in rooms


# ---------- resume_task 全流程 ----------

import app.engine.machine as machine_mod  # noqa: E402
from app.core.state import StateManager  # noqa: E402
from app.llm.pool import AICapability  # noqa: E402
from conftest import make_cap  # noqa: E402


class FakeEngine:
    instances = []

    def __init__(self):
        self.seen_state = None
        self.exc = None
        self.result = {"status": TaskStatus.COMPLETED}
        FakeEngine.instances.append(self)

    async def run(self, state):
        self.seen_state = state
        if self.exc is not None:
            raise self.exc
        return self.result


@pytest.fixture()
def fake_engine(monkeypatch):
    FakeEngine.instances = []
    monkeypatch.setattr(machine_mod, "WorkflowEngine", FakeEngine)

    class FakeBoard:
        def __init__(self):
            pass

        def get_state_dict(self):
            return {}

    async def _from_state_dict(tid, d):
        return FakeBoard()

    monkeypatch.setattr(tasks_mod.TaskBoard, "from_state_dict", _from_state_dict)
    return FakeEngine


def _paused_snapshot(**extra):
    snap = {
        "user_request": "续跑需求",
        "plan": {"task_name": "P"},
        "current_phase": 1,
        "phases": [{"phase": "dev", "description": "d"}],
        "team": {},
        "artifacts": {"a.py": "code"},
        "messages": [{"role": "user", "content": "hi"}],
        "status": TaskStatus.PAUSED.value,
        "review_rounds": 1,
        "max_review_rounds": 5,
        "last_code": "x=1",
        "review_feedback": "ok",
        "review_passed_this_round": False,
        "revision_pending": False,
        "error": None,
        "task_board_state": {"cols": []},
    }
    snap.update(extra)
    return snap


async def _save_snap(tid, snap):
    await StateManager(tid).save_snapshot(snap)


async def test_resume_running_task_returns_false():
    tm = _tm()
    tm._running["t"] = asyncio.create_task(asyncio.sleep(3600))
    assert await tm.resume_task("t") is False
    tm._running["t"].cancel()


async def test_resume_without_snapshot_returns_false():
    assert await _tm().resume_task("无快照任务-0001") is False


async def test_resume_completed_snapshot_rejected(session_db):
    tid = "completed-01"
    await _save_snap(tid, _paused_snapshot(status=TaskStatus.COMPLETED.value))
    assert await _tm().resume_task(tid) is False


async def test_resume_happy_path_rebuilds_team_and_state(
    session_db, fake_cfg, fake_engine, rooms, monkeypatch
):
    tid = "happy-01"
    cap_found = make_cap(id="capX")
    snapshot = _paused_snapshot(
        team={
            "executor": [
                {"id": "capX"},  # 池内命中分支
                {  # 池未命中 → AICapability(**cd) 回退分支
                    "id": "ghost-id",
                    "name": "N",
                    "endpoint": "http://x/v1",
                    "model": "m",
                    "api_key": "",
                    "tags": [],
                    "max_context": 100,
                },
            ],
            "learner": ["raw-string-passthrough"],  # 非 dict 原样保留分支
        }
    )
    await _save_snap(tid, snapshot)

    async def fake_get_by_id(cid):
        return cap_found if cid == "capX" else None

    monkeypatch.setattr(tasks_mod.capability_pool, "get_by_id", fake_get_by_id)

    tm = _tm()
    assert await tm.resume_task(tid) is True
    assert ("create", tid) in rooms
    await asyncio.gather(
        *asyncio.all_tasks() - {asyncio.current_task()}, return_exceptions=True
    )

    st = fake_engine.instances[-1].seen_state
    assert st["status"] == TaskStatus.PAUSED  # 从快照恢复执行态
    team = st["team"]
    assert team["executor"][0] is cap_found
    assert isinstance(team["executor"][1], AICapability)
    assert team["learner"] == ["raw-string-passthrough"]
    assert st["phases"] == [{"phase": "dev", "description": "d"}]
    # 收尾：状态落库（任务行不存在时 UPDATE 为 no-op，不作断言项）+ 房间关闭 + 簿记清理
    assert ("close", tid) in rooms
    assert tid not in tm._running and tid not in tm._cancel_events


async def test_resume_empty_phases_gets_default(
    fake_cfg, fake_engine, rooms, monkeypatch
):
    tid = "nophases-01"
    snap = _paused_snapshot(phases=[])
    await _save_snap(tid, snap)

    async def fake_get_by_id(cid):
        return None

    monkeypatch.setattr(tasks_mod.capability_pool, "get_by_id", fake_get_by_id)
    tm = _tm()
    assert await tm.resume_task(tid) is True
    await asyncio.gather(
        *asyncio.all_tasks() - {asyncio.current_task()}, return_exceptions=True
    )
    st = fake_engine.instances[-1].seen_state
    assert st["phases"] == [
        {"phase": "默认", "description": snap["user_request"]}
    ]  # 空阶段回退默认注入


async def test_resume_engine_error_marks_failed(
    session_db, fake_cfg, fake_engine, rooms, monkeypatch, marks
):
    tid = "err-01"
    await _save_snap(tid, _paused_snapshot())

    class RaisingEngine(FakeEngine):
        def __init__(self):
            super().__init__()
            RaisingEngine.last = self

        async def run(self, state):
            raise RuntimeError("恢复即炸")

    monkeypatch.setattr(machine_mod, "WorkflowEngine", RaisingEngine)
    tm = _tm()
    assert await tm.resume_task(tid) is True
    await asyncio.gather(
        *asyncio.all_tasks() - {asyncio.current_task()}, return_exceptions=True
    )
    assert ("err-01", "failed") in marks
    assert ("close", "err-01") in rooms
