"""
轻量级形式化任务看板
由调度 AI 维护，提供任务状态的结构化视图
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional
from enum import Enum
from datetime import datetime
import json

from app.core.database import db
from app.core.logger import logger


class TaskPhase(Enum):
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    REVISING = "revising"
    DELIVERING = "delivering"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskBoardState:
    task_id: str
    phase: TaskPhase = TaskPhase.PLANNING
    current_stage: int = 0
    total_stages: int = 1
    stage_name: str = ""
    stage_goal: str = ""
    expected_artifacts: List[str] = field(default_factory=list)
    completed_work: List[str] = field(default_factory=list)
    pending_actions: List[str] = field(default_factory=list)
    active_roles: Dict[str, str] = field(default_factory=dict)
    last_update: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["phase"] = self.phase.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskBoardState":
        data["phase"] = TaskPhase(data["phase"])
        return cls(**data)

    def generate_context_prompt(self, for_role: str) -> str:
        lines = [
            "【任务状态看板】",
            f"任务ID: {self.task_id}",
            f"整体进度: 阶段 {self.current_stage + 1}/{self.total_stages} - {self.stage_name}",
            f"当前阶段目标: {self.stage_goal}",
            f"预期产出: {', '.join(self.expected_artifacts) if self.expected_artifacts else '无'}",
        ]
        if self.completed_work:
            lines.append(f"已完成工作: {'; '.join(self.completed_work)}")
        if self.pending_actions:
            lines.append(f"待办行动: {'; '.join(self.pending_actions)}")
        lines.append(f"更新时间: {self.last_update}")
        lines.append("")
        lines.append(f"你当前的角色是: {for_role}")
        lines.append("请根据以上状态，专注于完成分配给该角色的具体任务。")
        return "\n".join(lines)


class TaskBoard:
    def __init__(self, task_id: str):
        self.task_id = task_id
        self.state: Optional[TaskBoardState] = None
        self._phases: List[Dict] = []

    async def initialize(self, plan: Dict[str, Any], team: Dict[str, List]) -> TaskBoardState:
        self._phases = plan.get("phases", [])
        total_stages = len(self._phases)
        first_phase = self._phases[0] if self._phases else {"phase": "默认", "description": ""}

        active_roles = {}
        for role, members in team.items():
            if members:
                active_roles[role] = members[0].id

        self.state = TaskBoardState(
            task_id=self.task_id,
            phase=TaskPhase.EXECUTING,
            current_stage=0,
            total_stages=total_stages,
            stage_name=first_phase.get("phase", "未知阶段"),
            stage_goal=first_phase.get("description", ""),
            expected_artifacts=first_phase.get("expected_artifacts", []),
            completed_work=[],
            pending_actions=[f"执行阶段 {first_phase.get('phase')}"],
            active_roles=active_roles,
            last_update=datetime.utcnow().isoformat(),
            notes="任务初始化完成"
        )
        await self._persist()
        logger.info(f"[{self.task_id}] 任务看板初始化")
        return self.state

    async def load(self) -> Optional[TaskBoardState]:
        row = await db.fetch_one(
            "SELECT state_json FROM task_board_states WHERE task_id = ? ORDER BY updated_at DESC LIMIT 1",
            (self.task_id,)
        )
        if row:
            self.state = TaskBoardState.from_dict(json.loads(row[0]))
            plan_row = await db.fetch_one("SELECT config_snapshot FROM tasks WHERE task_id = ?", (self.task_id,))
            if plan_row and plan_row[0]:
                plan = json.loads(plan_row[0])
                self._phases = plan.get("phases", [])
            return self.state
        return None

    async def update(
        self,
        phase: Optional[TaskPhase] = None,
        advance_stage: bool = False,
        stage_goal: Optional[str] = None,
        expected_artifacts: Optional[List[str]] = None,
        completed_work: Optional[List[str]] = None,
        pending_actions: Optional[List[str]] = None,
        notes: str = ""
    ) -> TaskBoardState:
        if self.state is None:
            await self.load()
            if self.state is None:
                raise ValueError("TaskBoard not initialized")

        if phase:
            self.state.phase = phase

        if advance_stage:
            self.state.current_stage += 1
            if self.state.current_stage < self.state.total_stages and self._phases:
                next_phase = self._phases[self.state.current_stage]
                self.state.stage_name = next_phase.get("phase", "")
                self.state.stage_goal = next_phase.get("description", "")
                self.state.expected_artifacts = next_phase.get("expected_artifacts", [])
                self.state.pending_actions = [f"执行阶段 {self.state.stage_name}"]
            else:
                self.state.stage_name = "交付"
                self.state.stage_goal = "打包产物，生成交付报告"
                self.state.expected_artifacts = []
                self.state.pending_actions = ["完成最终交付"]

        if stage_goal is not None:
            self.state.stage_goal = stage_goal
        if expected_artifacts is not None:
            self.state.expected_artifacts = expected_artifacts
        if completed_work is not None:
            self.state.completed_work = completed_work
        if pending_actions is not None:
            self.state.pending_actions = pending_actions
        if notes:
            self.state.notes = notes

        self.state.last_update = datetime.utcnow().isoformat()
        await self._persist()
        return self.state

    async def _persist(self):
        await db.execute(
            "INSERT INTO task_board_states (task_id, state_json) VALUES (?, ?)",
            (self.task_id, json.dumps(self.state.to_dict(), ensure_ascii=False))
        )

    async def broadcast_to_room(self, room):
        if room is None:
            logger.warning(f"[{self.task_id}] 会议室未初始化，跳过状态广播")
            return
        if not self.state:
            return
        from .room import MessageLayer
        summary = self.state.generate_context_prompt(for_role="全体成员")
        await room.broadcast(
            layer=MessageLayer.L2_MEETING,
            sender_role="scheduler",
            sender_id="task_board",
            content=f"📋 任务状态更新\n\n{summary}",
            msg_type="task_board_update",
            metadata={"state": self.state.to_dict()}
        )

    def get_state_dict(self) -> Dict[str, Any]:
        return self.state.to_dict() if self.state else {}

    @classmethod
    async def from_state_dict(cls, task_id: str, state_dict: Dict[str, Any]) -> "TaskBoard":
        board = cls(task_id)
        if state_dict:
            board.state = TaskBoardState.from_dict(state_dict)
        else:
            await board.load()
        if board.state and not board._phases:
            plan_row = await db.fetch_one("SELECT config_snapshot FROM tasks WHERE task_id = ?", (task_id,))
            if plan_row and plan_row[0]:
                plan = json.loads(plan_row[0])
                board._phases = plan.get("phases", [])
        return board
