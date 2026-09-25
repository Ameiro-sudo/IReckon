"""TaskBoard 补测：状态往返、上下文提示词、初始化/推进/越界、加载容错、UPSERT 与广播。

深水区（原 test_board_deep.py 已并入）：load 回退链、advance_stage 翻页与交付回退、
可选字段 setter、UPSERT 冲突回退、广播守卫、from_state_dict 分支。"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import app.engine.board as board_mod
from app.engine.board import (
    TaskBoard,
    TaskBoardState,
    TaskPhase,
)
from app.engine.room import MessageLayer


@pytest.fixture
def push_room():
    """记录 broadcast 调用的会议室替身。"""

    class FakeRoom:
        def __init__(self):
            self.pushed = []

        async def broadcast(self, **kwargs):
            self.pushed.append(kwargs)

    return FakeRoom()


PLAN = {
    "phases": [
        {
            "phase": "编码",
            "description": "完成核心功能",
            "expected_artifacts": ["a.py"],
        },
        {
            "phase": "审查",
            "description": "双流水线审查",
            "expected_artifacts": ["review.md"],
        },
    ]
}


def _team():
    class M:
        def __init__(self, id):
            self.id = id

    return {"executor": [M("exec-1")], "reviewer": []}  # 空成员列表不计入


def _plan(phases=None):
    return {
        "phases": phases
        or [
            {"phase": "dev", "description": "开发", "expected_artifacts": ["code"]},
            {"phase": "test", "description": "测试", "expected_artifacts": []},
        ]
    }


async def _seed_state_row(session_db, tid, state_dict):
    await session_db.execute(
        "INSERT INTO task_board_states (task_id, state_json) VALUES (?, ?)",
        (tid, json.dumps(state_dict, ensure_ascii=False)),
    )


def _state_dict(phase="executing"):
    return {
        "task_id": "bd-1",
        "phase": phase,
        "current_stage": 0,
        "total_stages": 2,
        "stage_name": "dev",
        "stage_goal": "开发",
        "expected_artifacts": ["code"],
        "completed_work": [],
        "pending_actions": ["执行阶段 dev"],
        "active_roles": {},
        "last_update": "2026-08-22T00:00:00+00:00",
        "notes": "",
    }


# ---------- TaskBoardState ----------


def test_state_dict_roundtrip_preserves_phase_enum():
    s = TaskBoardState(task_id="t1", phase=TaskPhase.REVIEWING, stage_name="审")
    data = s.to_dict()
    assert data["phase"] == "reviewing"  # 枚举序列化为值
    s2 = TaskBoardState.from_dict(dict(data))
    assert s2.phase is TaskPhase.REVIEWING
    assert s2.task_id == "t1"


def test_context_prompt_includes_sections_conditionally():
    s = TaskBoardState(
        task_id="t-ctx",
        current_stage=1,
        total_stages=3,
        stage_name="执行",
        stage_goal="把事情做完",
        expected_artifacts=["out.zip"],
        completed_work=["方案确认"],
        pending_actions=["写代码"],
    )
    p = s.generate_context_prompt(for_role="executor")
    assert "任务ID: t-ctx" in p
    assert "阶段 2/3 - 执行" in p
    assert "已完成工作: 方案确认" in p
    assert "待办行动: 写代码" in p
    assert "你当前的角色是: executor" in p


def test_context_prompt_empty_sections_show_placeholder():
    s = TaskBoardState(task_id="t-empty")
    p = s.generate_context_prompt(for_role="r")
    assert "预期产出: 无" in p
    assert "已完成工作" not in p and "待办行动" not in p


# ---------- initialize / update ----------


async def test_initialize_maps_plan_and_team(session_db):
    board = TaskBoard("t-init")
    state = await board.initialize(PLAN, _team())
    assert state.total_stages == 2
    assert state.stage_name == "编码"
    assert state.stage_goal == "完成核心功能"
    assert state.expected_artifacts == ["a.py"]
    assert state.active_roles == {"executor": "exec-1"}  # 空成员列表跳过
    assert board._phases == PLAN["phases"]
    row = await session_db.fetch_one(
        "SELECT state_json FROM task_board_states WHERE task_id = 't-init'"
    )
    assert row is not None  # 已落库


async def test_initialize_without_phases_uses_defaults(session_db):
    board = TaskBoard("t-nophase")
    state = await board.initialize({}, {})
    assert state.total_stages == 0
    assert state.stage_name == "默认"


async def test_update_without_init_raises(session_db):
    with pytest.raises(ValueError, match="not initialized"):
        await TaskBoard("t-nope").update(notes="x")


async def test_advance_stage_pulls_next_phase_then_delivers(session_db):
    board = TaskBoard("t-adv")
    await board.initialize(PLAN, _team())
    s = await board.update(advance_stage=True)
    assert s.current_stage == 1
    assert s.stage_name == "审查"  # 拉取下一阶段字段
    assert s.expected_artifacts == ["review.md"]
    s = await board.update(advance_stage=True)
    assert s.current_stage == 2  # 越过最后阶段
    assert s.stage_name == "交付" and s.pending_actions == ["完成最终交付"]


async def test_update_partial_fields_and_notes(session_db):
    board = TaskBoard("t-partial")
    await board.initialize(PLAN, _team())
    s = await board.update(completed_work=["第一步"], notes="顺利")
    assert s.completed_work == ["第一步"]
    assert s.notes == "顺利"
    assert s.stage_goal == "完成核心功能"  # 未传字段保持原值


# ---------- load 容错 ----------


async def test_load_missing_returns_none(session_db):
    assert await TaskBoard("从未存在").load() is None


async def test_load_roundtrip_with_bad_snapshot_tolerated(session_db):
    await session_db.execute(
        "INSERT INTO tasks(task_id, user_request, status, config_snapshot)"
        " VALUES ('t-load', '需求', 'executing', '{不是JSON')"
    )
    board = TaskBoard("t-load")
    await board.initialize(PLAN, _team())
    board.state = None
    state = await board.load()
    assert state is not None
    assert state.stage_name == "编码"
    assert board._phases == []  # 快照解析失败仅告警，阶段列表为空


async def test_persist_upsert_keeps_single_row(session_db):
    board = TaskBoard("t-upsert")
    await board.initialize(PLAN, _team())
    await board.update(notes="第二次更新")
    rows = await session_db.fetch_all(
        "SELECT state_json FROM task_board_states WHERE task_id = 't-upsert'"
    )
    assert len(rows) == 1
    assert "第二次更新" in rows[0][0]


# ---------- 广播与字典出口 ----------


async def test_broadcast_to_room_none_skips():
    board = TaskBoard("t-bc")
    await board.broadcast_to_room(None)  # 不抛即通过


async def test_broadcast_to_room_sends_l2_summary(push_room, session_db):
    board = TaskBoard("t-bc2")
    await board.initialize(PLAN, _team())
    await board.broadcast_to_room(push_room)
    assert len(push_room.pushed) == 1
    call = push_room.pushed[0]
    assert call["layer"] is MessageLayer.L2_MEETING
    assert call["msg_type"] == "task_board_update"
    assert "[任务状态更新]" in call["content"]
    assert call["metadata"]["state"]["task_id"] == "t-bc2"


async def test_get_state_dict_empty_before_init():
    assert TaskBoard("t-x").get_state_dict() == {}


async def test_from_state_dict_with_dict_skips_db(session_db):
    s = TaskBoardState(task_id="t-fsd", phase=TaskPhase.DELIVERING)
    board = await TaskBoard.from_state_dict("t-fsd", s.to_dict())
    assert board.state.phase is TaskPhase.DELIVERING


# ---------- 深水区：load 回退链（原 test_board_deep.py 并入） ----------


async def test_load_restores_state_and_phases(session_db):
    await _seed_state_row(session_db, "bd-1", _state_dict())
    await session_db.execute(
        "INSERT INTO tasks(task_id,user_request,title,status,file_refs,config_snapshot)"
        " VALUES ('bd-1','r','t','executing','[]',?)",
        (json.dumps(_plan()),),
    )
    board = TaskBoard("bd-1")
    st = await board.load()
    assert st.phase == TaskPhase.EXECUTING and st.total_stages == 2
    assert board._phases[0]["phase"] == "dev"


async def test_load_malformed_config_snapshot_warns_empty_phases(session_db):
    await _seed_state_row(session_db, "bd-2", _state_dict())
    await session_db.execute(
        "INSERT INTO tasks(task_id,user_request,title,status,file_refs,config_snapshot)"
        " VALUES ('bd-2','r','t','executing','[]','{broken')",
    )
    board = TaskBoard("bd-2")
    st = await board.load()
    assert st is not None and board._phases == []


async def test_load_no_row_returns_none():
    assert await TaskBoard("ghost-01").load() is None


# ---------- 深水区：advance 翻页与可选 setter ----------


async def test_advance_stage_walks_phases_then_delivery(session_db):
    board = TaskBoard("adv-1")
    await board.initialize(_plan(), {"executor": [type("M", (), {"id": "m1"})()]})
    # 第 0→1 阶段：从 _phases 取下一阶段元数据
    st = await board.update(advance_stage=True)
    assert st.current_stage == 1
    assert st.stage_name == "test" and st.stage_goal == "测试"
    assert st.pending_actions == ["执行阶段 test"]
    # 越过末阶段 → 交付回退
    st = await board.update(advance_stage=True)
    assert st.current_stage == 2 and st.stage_name == "交付"
    assert st.pending_actions == ["完成最终交付"] and st.expected_artifacts == []


async def test_update_optional_setters_and_empty_notes_guard(session_db):
    board = TaskBoard("opt-1")
    await board.initialize(_plan(), {})
    st = await board.update(
        stage_goal="新目标",
        expected_artifacts=["a"],
        completed_work=["w1"],
        pending_actions=["p1"],
        notes="备注一",
    )
    assert st.stage_goal == "新目标" and st.expected_artifacts == ["a"]
    assert st.completed_work == ["w1"] and st.pending_actions == ["p1"]
    assert st.notes == "备注一"
    st2 = await board.update(notes="")  # 空 notes 不清空已有值
    assert st2.notes == "备注一"


# ---------- 深水区：UPSERT 冲突回退、广播守卫、from_state_dict 分支 ----------


async def test_persist_upsert_conflict_falls_back_to_delete_insert(
    session_db, monkeypatch
):
    monkeypatch.setattr(board_mod, "_board_index_ensured", False)
    board = TaskBoard("conf-1")
    await board.initialize(_plan(), {})
    real_execute = session_db.execute
    calls = []

    async def flaky_execute(sql, *params):
        calls.append(sql.strip().split("(")[0][:40])
        if (
            sql.lstrip().startswith("INSERT INTO task_board_states")
            and "ON CONFLICT" in sql
        ):
            raise Exception("forced conflict failure")
        return await real_execute(sql, *params)

    monkeypatch.setattr(session_db, "execute", flaky_execute)
    await board.update(notes="二次更新")
    # 回退路径：DELETE + 裸 INSERT 均已执行，数据仍可 load 回读
    restored = await TaskBoard("conf-1").load()
    assert restored.notes == "二次更新"
    assert any("DELETE FROM task_board_states" in c for c in calls)


async def test_broadcast_guards(session_db):
    board = TaskBoard("bcast-1")
    await board.broadcast_to_room(None)  # 房间未初始化 → 告警跳过
    sent = []

    class FakeRoom:
        async def broadcast(self, **kw):
            sent.append(kw)

    await board.broadcast_to_room(FakeRoom())  # state 为 None → 直接返回
    assert sent == []
    await board.initialize(_plan(), {})
    await board.broadcast_to_room(FakeRoom())
    assert sent and sent[0]["msg_type"] == "task_board_update"
    assert sent[0]["metadata"]["state"]["task_id"] == "bcast-1"


async def test_from_state_dict_branches(session_db):
    # 有 state_dict → 直接反序列化；缺 phases 时从 tasks.config_snapshot 补
    await session_db.execute(
        "INSERT INTO tasks(task_id,user_request,title,status,file_refs,config_snapshot)"
        " VALUES ('fsd-1','r','t','paused','[]',?)",
        (json.dumps(_plan()),),
    )
    sd = _state_dict()
    sd["total_stages"] = 0  # 触发 _phases 为空的补取路径
    board = await TaskBoard.from_state_dict("fsd-1", sd)
    assert board.state.phase == TaskPhase.EXECUTING
    assert board._phases and board._phases[-1]["phase"] == "test"

    # 无 state_dict → 走 load()（无行 → state 保持 None）
    empty = await TaskBoard.from_state_dict("fsd-none", {})
    assert empty.state is None

    # config_snapshot 坏 JSON → 静默空 phases（250-251）
    await session_db.execute(
        "INSERT INTO tasks(task_id,user_request,title,status,file_refs,config_snapshot)"
        " VALUES ('fsd-2','r','t','paused','[]','not-json')",
    )
    b2 = await TaskBoard.from_state_dict("fsd-2", dict(sd, total_stages=0))
    assert b2._phases == []


async def test_from_dict_rejects_unknown_phase():
    bad = _state_dict()
    bad["phase"] = "不存在的阶段"
    with pytest.raises(ValueError):
        TaskBoardState.from_dict(bad)
