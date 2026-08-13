import asyncio, uuid, operator, json
from typing import Dict, Any, Optional, TypedDict, List, Annotated
from enum import Enum
from loguru import logger
from app.core.state import StateManager
from app.core.database import db
from app.core.config import config_manager
from app.agents.scheduler import SchedulerAgent
from app.llm.pool import capability_pool, AICapability
from .room import meeting_room_manager
from .board import TaskBoard
from .learner import idle_loop


class TaskStatus(Enum):
    PENDING = "pending"
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    REVISING = "revising"
    DELIVERING = "delivering"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class TaskState(TypedDict):
    task_id: str
    user_request: str
    plan: Dict[str, Any]
    current_phase: int
    phases: List[Dict[str, Any]]
    team: Dict[str, List[AICapability]]
    artifacts: Annotated[Dict[str, str], operator.ior]
    messages: Annotated[List[Dict], operator.add]
    status: TaskStatus
    review_rounds: int
    max_review_rounds: int
    last_code: str
    review_feedback: str
    review_passed_this_round: bool
    error: Optional[str]
    task_board_state: Dict[str, Any]


class TaskManager:
    _instance: Optional["TaskManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_init") and self._init:
            return
        self._init = True
        self._running: Dict[str, asyncio.Task] = {}
        self._cancel_events: Dict[str, asyncio.Event] = {}

    async def create_task(self, req: str) -> str:
        tid = f"task-{uuid.uuid4().hex[:8]}"
        await db.execute(
            "INSERT INTO tasks(task_id,user_request,status) VALUES(?,?,?)",
            (tid, req, TaskStatus.PENDING.value),
        )
        return tid

    async def _launch(self, tid: str, ce: asyncio.Event, body):
        """统一的任务执行包装：超时/取消/异常处理 + 状态落库 + 资源清理。"""

        async def _run():
            try:
                md = config_manager.get("task_defaults.max_task_duration_seconds", 3600)
                await asyncio.wait_for(body(), timeout=md)
            except asyncio.TimeoutError:
                logger.error(f"任务{tid}超时")
                await self._mark_status(tid, TaskStatus.FAILED)
            except asyncio.CancelledError:
                # 用户取消 -> 暂停，保留快照以便恢复
                status = TaskStatus.PAUSED if ce.is_set() else TaskStatus.FAILED
                logger.info(f"任务{tid}被取消，状态: {status.value}")
                await self._mark_status(tid, status)
            except Exception as e:
                logger.exception(f"任务{tid}异常: {e}")
                await self._mark_status(tid, TaskStatus.FAILED)
            finally:
                self._running.pop(tid, None)
                self._cancel_events.pop(tid, None)
                await meeting_room_manager.close_room(tid)

        self._running[tid] = asyncio.create_task(_run())

    async def _mark_status(self, tid: str, status: TaskStatus):
        try:
            await db.execute(
                "UPDATE tasks SET status=?, updated_at=CURRENT_TIMESTAMP WHERE task_id=?",
                (status.value, tid),
            )
        except Exception as e:
            logger.warning(f"任务{tid}状态更新失败: {e}")

    async def start_task(self, tid: str, scid: Optional[str] = None):
        if tid in self._running:
            return
        ce = asyncio.Event()
        self._cancel_events[tid] = ce
        await self._launch(tid, ce, lambda: self._execute_task(tid, scid, ce))

    async def _execute_task(self, tid, scid, ce):
        idle_loop.notify_task_started()
        row = await db.fetch_one(
            "SELECT user_request FROM tasks WHERE task_id=?", (tid,)
        )
        if not row:
            raise ValueError(f"任务{tid}不存在")
        req = row[0]
        cap = (
            await capability_pool.get_by_id(scid)
            if scid
            else (await capability_pool.get_all())[0]
        )
        sch = SchedulerAgent(cap)
        sch.bind_context(tid, cancellation_event=ce)
        sr = await sch.execute(req, tid)
        plan, team = sr["plan"], sr["team"]
        phases = plan.get("phases")
        if not phases:
            raise ValueError(f"任务{tid}计划为空，无法执行")
        tbs = sr.get("task_board_state", {})
        await db.execute(
            "UPDATE tasks SET status=?,config_snapshot=? WHERE task_id=?",
            (TaskStatus.EXECUTING.value, json.dumps(plan, ensure_ascii=False), tid),
        )
        st: TaskState = {
            "task_id": tid,
            "user_request": req,
            "plan": plan,
            "current_phase": 0,
            "phases": phases,
            "team": team,
            "artifacts": {},
            "messages": [],
            "status": TaskStatus.EXECUTING,
            "review_rounds": 0,
            "max_review_rounds": 5,
            "last_code": "",
            "review_feedback": "",
            "review_passed_this_round": False,
            "error": None,
            "task_board_state": tbs,
        }
        from .machine import WorkflowEngine

        sm = StateManager(tid)
        await sm.save_snapshot(st)
        engine = WorkflowEngine()
        fs = await engine.run(st)
        await sm.save_snapshot(fs)
        await db.execute(
            "UPDATE tasks SET status=?,updated_at=CURRENT_TIMESTAMP WHERE task_id=?",
            (fs["status"].value, tid),
        )

    async def cancel_task(self, tid: str) -> bool:
        if tid in self._cancel_events:
            self._cancel_events[tid].set()
        if tid in self._running:
            self._running[tid].cancel()
            return True
        return False

    async def resume_task(self, tid: str) -> bool:
        if tid in self._running:
            return False
        sm = StateManager(tid)
        snap = await sm.load_latest_snapshot()
        if not snap:
            return False
        snap_status = snap.get("status")
        if snap_status in (TaskStatus.COMPLETED.value, TaskStatus.COMPLETED):
            logger.warning(f"任务{tid}已完成，无需恢复")
            return False

        ce = asyncio.Event()
        self._cancel_events[tid] = ce
        await meeting_room_manager.create_room(tid)
        task_board = await TaskBoard.from_state_dict(
            tid, snap.get("task_board_state", {})
        )
        team = {}
        for role, caps_data in snap.get("team", {}).items():
            team[role] = []
            for cd in caps_data:
                if isinstance(cd, dict):
                    c = await capability_pool.get_by_id(cd.get("id"))
                    if c:
                        team[role].append(c)
                    else:
                        team[role].append(AICapability(**cd))
                else:
                    team[role].append(cd)
        resumed_state: TaskState = {
            "task_id": tid,
            "user_request": snap.get("user_request", ""),
            "plan": snap.get("plan", {}),
            "current_phase": snap.get("current_phase", 0),
            "phases": snap.get("phases", []),
            "team": team,
            "artifacts": snap.get("artifacts", {}),
            "messages": snap.get("messages", []),
            "status": TaskStatus(snap.get("status", "executing")),
            "review_rounds": snap.get("review_rounds", 0),
            "max_review_rounds": snap.get("max_review_rounds", 5),
            "last_code": snap.get("last_code", ""),
            "review_feedback": snap.get("review_feedback", ""),
            "review_passed_this_round": snap.get("review_passed_this_round", False),
            "error": snap.get("error"),
            "task_board_state": task_board.get_state_dict(),
        }
        if not resumed_state["phases"]:
            resumed_state["phases"] = [
                {"phase": "默认", "description": resumed_state["user_request"]}
            ]

        from .machine import WorkflowEngine

        engine = WorkflowEngine()

        async def _run_resumed():
            try:
                md = config_manager.get("task_defaults.max_task_duration_seconds", 3600)
                final = await asyncio.wait_for(engine.run(resumed_state), timeout=md)
                await sm.save_snapshot(final)
                await db.execute(
                    "UPDATE tasks SET status=? WHERE task_id=?",
                    (final["status"].value, tid),
                )
            except asyncio.TimeoutError:
                logger.error(f"任务{tid}恢复后超时")
                await self._mark_status(tid, TaskStatus.FAILED)
            except asyncio.CancelledError:
                status = TaskStatus.PAUSED if ce.is_set() else TaskStatus.FAILED
                await self._mark_status(tid, status)
            except Exception as e:
                logger.exception(f"恢复失败: {e}")
                await self._mark_status(tid, TaskStatus.FAILED)
            finally:
                self._running.pop(tid, None)
                self._cancel_events.pop(tid, None)
                await meeting_room_manager.close_room(tid)

        self._running[tid] = asyncio.create_task(_run_resumed())
        return True


task_manager = TaskManager()
