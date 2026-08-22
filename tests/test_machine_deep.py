"""engine/machine.py 深水区补测（第一批）：路由器全分支、评审轮次升级、
artifacts 截断边界、广播助手四件套。节点级集成用例见后续批次。"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import app.engine.machine as machine_mod
from app.engine.machine import (
    _bounded_artifacts,
    _bounded_context,
    _entry_router,
    _maybe_swap_executor,
    execute_router,
    review_router,
    revise_router,
)
from app.engine.tasks import TaskStatus


# ---------- 路由器 ----------


def test_revise_router_branches():
    assert revise_router({"status": TaskStatus.FAILED}) == "fail"
    assert revise_router({"status": TaskStatus.EXECUTING}) == "execute"
    assert revise_router({"status": TaskStatus.REVIEWING}) == "review"


def test_execute_router_branches():
    assert execute_router({"status": TaskStatus.FAILED}) == "fail"
    assert execute_router({"status": TaskStatus.EXECUTING}) == "review"


def test_entry_router_revision_pending():
    assert _entry_router({"revision_pending": True}) == "revise"
    assert _entry_router({"revision_pending": False}) == "execute"


def test_review_router_full_matrix():
    fail = {"status": TaskStatus.FAILED}
    assert review_router(fail) == "fail"

    def st(passed, phase, nphases, rounds, maxr=5):
        return {
            "status": TaskStatus.REVIEWING,
            "review_passed_this_round": passed,
            "current_phase": phase,
            "phases": [{} for _ in range(nphases)],
            "review_rounds": rounds,
            "max_review_rounds": maxr,
        }

    # 通过且已是最后阶段 → pass；通过但还有阶段 → revise 再来一轮
    assert review_router(st(True, 1, 2, 1)) == "pass"
    assert review_router(st(True, 0, 2, 1)) == "revise"
    # 未通过：达到上限 → fail；未达上限 → revise
    assert review_router(st(False, 0, 2, 5)) == "fail"
    assert review_router(st(False, 0, 2, 2)) == "revise"


# ---------- _maybe_swap_executor 评审升级 ----------


class _Cap:
    def __init__(self, cid, name=""):
        self.id = cid
        self.name = name or cid


def _team(head_id):
    return {"executor": [_Cap(head_id), _Cap("bench")], "learner": [_Cap("l1")]}


@pytest.fixture()
def pool(monkeypatch):
    class FakePool:
        def __init__(self):
            self.next = None

        async def find_best_match(self, **kw):
            return self.next

    fp = FakePool()
    monkeypatch.setattr(machine_mod, "capability_pool", fp)
    return fp


async def test_swap_below_three_rounds_noop(pool):
    team = _team("weak")
    out = await _maybe_swap_executor({"team": team, "review_rounds": 2})
    assert out["team"]["executor"][0].id == "weak"


async def test_swap_upgrades_to_stronger_head(pool):
    pool.next = _Cap("smart-1", "SmartAI")
    s = {"team": _team("weak"), "review_rounds": 3}
    out = await _maybe_swap_executor(s)
    ids = [x.id for x in out["team"]["executor"]]
    assert ids == [
        "smart-1",
        "bench",
    ]  # 新头位+原次位保留
    assert out["team"] is not s["team"]  # 不原地修改


async def test_swap_same_id_keeps_order(pool):
    pool.next = _Cap("head")
    s = {"team": _team("head"), "review_rounds": 4}
    out = await _maybe_swap_executor(s)
    assert [c.id for c in out["team"]["executor"]][0] == "head"


async def test_swap_no_candidate_found(pool):
    pool.next = None
    s = {"team": _team("head"), "review_rounds": 3}
    out = await _maybe_swap_executor(s)
    assert out["team"]["executor"][0].id == "head"


# ---------- artifacts 截断 ----------


def test_bounded_artifacts_under_limit_unchanged():
    a = {"a.py": "code"}
    assert _bounded_artifacts(a, limit=1000) is a


def test_bounded_artifacts_truncates_largest_first():
    big = "B" * 500
    small = "S" * 10
    out = _bounded_artifacts({"big.py": big, "s.py": small}, limit=100)
    assert out["big.py"].endswith("\n...[截断]")
    assert len(out["big.py"]) < len(big)
    assert out["s.py"] == small  # 小文件不动，优先截最大


def test_bounded_context_truncates_with_marker():
    ctx = _bounded_context({"k": "v" * 300}, limit=50)
    assert ctx.endswith("\n...[截断]") and len(ctx) == 58
    short = _bounded_context({"k": "v"}, limit=1000)
    assert short.startswith("{'k'") and "[截断]" not in short


# ---------- 广播助手 ----------


class FakeRoom:
    def __init__(self):
        self.calls = []

    async def broadcast(
        self,
        layer=None,
        sender_role=None,
        sender_id=None,
        content=None,
        msg_type=None,
        metadata=None,
    ):
        self.calls.append(
            dict(
                sender_role=sender_role,
                sender_id=sender_id,
                content=content,
                msg_type=msg_type,
            )
        )


class FakeRV:
    def __init__(self, role="reviewer_correctness"):
        self.role = role
        self.context = SimpleNamespace(agent_id="rv-1")


class FakeEX:
    context = SimpleNamespace(agent_id="ex-1")


async def test_broadcast_review_result_none_room_noop():
    await machine_mod._broadcast_review_result("t", None, FakeRV(), {})


async def test_broadcast_review_result_two_messages():
    room = FakeRoom()
    await machine_mod._broadcast_review_result(
        "t", room, FakeRV(), {"passed": True, "feedback": "很好"}
    )
    assert len(room.calls) == 2
    assert room.calls[0]["content"] == "开始审查..."
    assert "[reviewer_correctness] 结论:通过" in room.calls[1]["content"]
    assert "很好" in room.calls[1]["content"]


async def test_scan_and_broadcast_only_when_findings_and_room(monkeypatch):
    sent = []
    room = FakeRoom()

    async def _bc(*a, **kw):
        keys = ("layer", "sender_role", "sender_id", "content")
        rec = {keys[i]: a[i] for i in range(min(len(a), 4))}
        rec.update(kw)
        sent.append(rec)

    room.broadcast = _bc

    async def no_scans(code):
        return []

    async def with_scans(code):
        return [{"issue": "x"}]

    monkeypatch.setattr(machine_mod.code_scanner, "scan", no_scans)
    await machine_mod._scan_and_broadcast("clean", room)
    assert sent == []  # 无发现不广播

    monkeypatch.setattr(machine_mod.code_scanner, "scan", with_scans)
    await machine_mod._scan_and_broadcast("dirty", room)
    assert sent and sent[0]["msg_type"] == "security_warning"
    assert "发现1个问题" in sent[0]["content"]

    await machine_mod._scan_and_broadcast("dirty", None)  # 无房间也不炸


async def test_broadcast_security_violation_guard_and_message():
    sent = []
    room = FakeRoom()

    async def _bc(*a, **kw):
        keys = ("layer", "sender_role", "sender_id", "content")
        rec = {keys[i]: a[i] for i in range(min(len(a), 4))}
        rec.update(kw)
        sent.append(rec)

    room.broadcast = _bc

    await machine_mod._broadcast_security_violation("t", None, ["x"])  # None 房间
    assert sent == []
    await machine_mod._broadcast_security_violation("t", room, ["挖矿", "黑名单依赖"])
    assert sent and "安全拦截: 挖矿; 黑名单依赖" in sent[0]["content"]
    assert sent[0]["sender_role"] == "security_scanner"


async def test_broadcast_execution_result_none_room_noop():
    await machine_mod._broadcast_execution_result(
        "t",
        {"phases": [{"description": "d"}], "current_phase": 0},
        {},
        None,
        FakeEX(),
    )


async def test_broadcast_execution_result_sends_start_and_code():
    sent = []
    room = FakeRoom()

    async def _bc(*a, **kw):
        keys = ("layer", "sender_role", "sender_id", "content")
        rec = {keys[i]: a[i] for i in range(min(len(a), 4))}
        rec.update(kw)
        sent.append(rec)

    room.broadcast = _bc
    s = {"phases": [{"phase": "dev", "description": "实现登录"}], "current_phase": 0}
    await machine_mod._broadcast_execution_result(
        "t", s, {"a.py": "print(1)"}, room, FakeEX()
    )
    assert sent[0]["content"] == "开始执行: 实现登录"
    assert sent[1]["msg_type"] == "code" and "print(1)" in sent[1]["content"]


# ---------- 批二：节点级集成 ----------

from app.engine.board import TaskBoardState, TaskPhase  # noqa: E402


def _tb_state(tid="node-t", phase=TaskPhase.EXECUTING):
    return TaskBoardState(
        task_id=tid,
        phase=phase,
        current_stage=0,
        total_stages=2,
        stage_name="dev",
        stage_goal="开发",
        expected_artifacts=["code"],
        completed_work=[],
        pending_actions=[],
        active_roles={},
        last_update="",
        notes="",
    )


class FakeTB:
    def __init__(self, tid="node-t", phase=TaskPhase.EXECUTING):
        self.state = _tb_state(tid, phase)
        self.updates = []

    async def update(self, **kw):
        self.updates.append(kw)
        for k, v in kw.items():
            if k == "advance_stage":
                continue
            setattr(self.state, k, v)
        if kw.get("completed_work") is not None or "completed_work" in kw:
            pass
        return self.state

    async def broadcast_to_room(self, room):
        pass

    def get_state_dict(self):
        return self.state.to_dict()


class FakeAgent:
    def __init__(self, role, result=None, debug_result=None):
        self.role = role
        self.context = SimpleNamespace(agent_id=f"{role}-1")
        self.result = result or {}
        self.debug_result = debug_result
        self.bound = None
        self.calls = []

    def bind_context(self, tid):
        self.bound = tid

    async def execute(self, task_data):
        self.calls.append(task_data)
        return dict(self.result)

    async def debug_code(self, artifacts, feedback):
        self.calls.append(("debug", dict(artifacts), feedback))
        return self.debug_result


class FakeRegistry:
    def __init__(self, mapping):
        self.mapping = mapping

    def create_agent(self, role, cap):
        item = self.mapping.get(role)
        if item is None:
            return None
        agent = item() if callable(item) else item
        return agent


@pytest.fixture()
def node_env(monkeypatch):
    """节点级通用替身环境：看板/房间/进度/检查点全替身。"""
    pushed = []

    async def _pp(tid, p, msg):
        pushed.append((tid, round(p, 2), msg))

    monkeypatch.setattr(machine_mod, "push_progress", _pp)

    snaps = []

    class FakeSM:
        def __init__(self, tid):
            self.tid = tid

        async def save_snapshot(self, s):
            snaps.append((self.tid, s))

    monkeypatch.setattr(machine_mod, "StateManager", FakeSM)

    board = FakeTB()

    class FakeTBCls:
        @staticmethod
        async def from_state_dict(tid, d):
            return board

    monkeypatch.setattr(machine_mod, "TaskBoard", FakeTBCls)

    sent = []
    room = FakeRoom()

    async def _bc(*a, **kw):
        keys = ("layer", "sender_role", "sender_id", "content")
        rec = {keys[i]: a[i] for i in range(min(len(a), 4))}
        rec.update(kw)
        sent.append(rec)

    room.broadcast = _bc

    class MRM:
        async def get_room(self, tid):
            return room

    monkeypatch.setattr(machine_mod, "meeting_room_manager", MRM())
    return SimpleNamespace(
        board=board,
        room=room,
        pushed=pushed,
        snaps=snaps,
        sent=sent,
        registry_map={},
    )


def _clean_engine():
    """安全检测中性化的引擎：挖矿不命中、供应链放行。"""
    eng = machine_mod.WorkflowEngine()
    eng._mining_detector = SimpleNamespace(scan_command_line=lambda code: False)

    async def allow(code):
        return True

    eng._supply_firewall = SimpleNamespace(check=allow)
    return eng


@pytest.fixture()
def registry(node_env, monkeypatch):
    reg = FakeRegistry(node_env.registry_map)
    monkeypatch.setattr(machine_mod, "role_registry", reg)
    return reg


def _base_state(**kw):
    st = {
        "task_id": "node-t",
        "user_request": "需求",
        "plan": {"task_name": "T"},
        "current_phase": 0,
        "phases": [
            {"phase": "dev", "description": "实现功能", "expected_artifacts": ["a.py"]}
        ],
        "team": {"executor": [SimpleNamespace(id="ex-cap")]},
        "artifacts": {},
        "messages": [],
        "status": TaskStatus.EXECUTING,
        "review_rounds": 0,
        "max_review_rounds": 5,
        "last_code": "",
        "review_feedback": "",
        "review_passed_this_round": False,
        "revision_pending": False,
        "error": None,
        "task_board_state": {},
        "complexity": "simple",
    }
    st.update(kw)
    return st


async def test_planning_node_pushes_and_returns_executing(node_env, monkeypatch):
    out = await machine_mod.planning_node(_base_state())
    assert out["status"] == TaskStatus.EXECUTING
    assert node_env.pushed and node_env.pushed[0][2] == "规划中..."


async def test_checkpoint_skips_without_task_id(monkeypatch):
    snaps = []

    class FakeSM:
        def __init__(self, tid):
            snaps.append(("init", tid))

        async def save_snapshot(self, s):
            snaps.append(("save", s))

    monkeypatch.setattr(machine_mod, "StateManager", FakeSM)
    await machine_mod._checkpoint({})
    assert snaps == []  # 无 task_id 直接返回


async def test_checkpoint_saves_snapshot_and_updates_status(monkeypatch):
    events = []

    class FakeSM:
        def __init__(self, tid):
            self.tid = tid

        async def save_snapshot(self, s):
            events.append(("snap", s["task_id"]))

    monkeypatch.setattr(machine_mod, "StateManager", FakeSM)

    async def fake_execute(sql, *params):
        events.append(("db", params[0]))

    monkeypatch.setattr(machine_mod.db, "execute", fake_execute)
    await machine_mod._checkpoint({"task_id": "t-ckpt", "status": TaskStatus.REVIEWING})
    assert ("snap", "t-ckpt") in events
    db_ev = [e for e in events if e[0] == "db"]
    assert db_ev and TaskStatus.REVIEWING.value in db_ev[0][1]


async def test_checkpoint_swallows_db_errors(monkeypatch):
    class FakeSM:
        def __init__(self, tid):
            pass

        async def save_snapshot(self, s):
            raise RuntimeError("disk full")

    monkeypatch.setattr(machine_mod, "StateManager", FakeSM)

    async def boom(sql, *params):
        raise RuntimeError("locked")

    monkeypatch.setattr(machine_mod.db, "execute", boom)
    await machine_mod._checkpoint(
        {"task_id": "t-x", "status": "executing"}
    )  # 不抛即通过


async def test_execute_node_failed_short_circuit(registry, node_env):
    eng = machine_mod.WorkflowEngine()
    out = await eng.execute_node(_base_state(status=TaskStatus.FAILED))
    assert out["status"] == TaskStatus.FAILED
    assert not fake_engine_calls(registry)


def fake_engine_calls(registry):
    return [a for a in registry.mapping.values() if getattr(a, "calls", None)]


async def test_execute_node_phase_exhausted_returns_completed(registry, node_env):
    eng = machine_mod.WorkflowEngine()
    st = _base_state(current_phase=5)  # 越界
    out = await eng.execute_node(st)
    assert out["status"] == TaskStatus.COMPLETED


async def test_execute_node_happy_path_reviewing(registry, node_env, monkeypatch):
    ex = FakeAgent("executor", result={"artifacts": {"a.py": "print('ok')\n"}})
    registry.mapping["executor"] = lambda: ex

    async def no_scans(code):
        return []

    monkeypatch.setattr(machine_mod.code_scanner, "scan", no_scans)

    async def check_false(tid, hist):
        return False

    monkeypatch.setattr(machine_mod.loop_detector, "check_loop", check_false)

    eng = _clean_engine()
    out = await eng.execute_node(_base_state())
    assert out["status"] == TaskStatus.REVIEWING
    assert out["last_code"].startswith("print")
    assert out["messages"][0]["role"] == "executor"
    assert any(u.get("completed_work") for u in node_env.board.updates)


async def test_execute_node_loop_detected_fails(registry, node_env, monkeypatch):
    registry.mapping["executor"] = lambda: FakeAgent(
        "executor", result={"artifacts": {"a.py": "x"}}
    )

    async def looping(tid, hist):
        return True

    monkeypatch.setattr(machine_mod.loop_detector, "check_loop", looping)
    eng = _clean_engine()
    out = await eng.execute_node(_base_state())
    assert out["status"] == TaskStatus.FAILED and out["error"] == "死循环"


async def test_execute_node_security_violation_fails_with_broadcast(
    registry, node_env, monkeypatch
):
    registry.mapping["executor"] = lambda: FakeAgent(
        "executor", result={"artifacts": {"m.py": "import xmr"}}
    )

    class MiningHit:
        def scan_command_line(self, code):
            return ["xmrig"]

    eng = machine_mod.WorkflowEngine()
    eng._mining_detector = MiningHit()
    out = await eng.execute_node(_base_state())
    assert out["status"] == TaskStatus.FAILED and "挖矿" in out["error"]
    assert any("安全拦截" in c["content"] for c in node_env.sent)
