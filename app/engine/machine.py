import asyncio
from pathlib import Path
from typing import List, Dict
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from loguru import logger
from app.llm.pool import capability_pool
from app.core.database import db
from app.core.state import StateManager
from .tasks import TaskStatus, TaskState
from .registry import role_registry
from .room import MessageLayer, meeting_room_manager
from .board import TaskBoard, TaskPhase
from .detector import loop_detector
from app.security.scanner import code_scanner
from app.security.supply import SupplyChainFirewall
from app.security.mining import MiningDetector
from app.web.push import push_progress


class WorkflowEngine:
    def __init__(self):
        self.checkpointer = MemorySaver()
        self.graph = self._build_graph()
        self.output_history: Dict[str, List[str]] = {}
        self._supply_firewall = SupplyChainFirewall()
        self._mining_detector = MiningDetector()

    def _build_graph(self):
        wf = StateGraph(TaskState)
        for n in ["planning", "execute", "review", "revise", "deliver", "handle_error"]:
            wf.add_node(n, getattr(self, f"{n}_node"))
        wf.set_entry_point("planning")
        wf.add_edge("planning", "execute")
        wf.add_edge("execute", "review")
        wf.add_conditional_edges(
            "review",
            self.review_router,
            {"pass": "deliver", "revise": "revise", "fail": "handle_error"},
        )
        wf.add_conditional_edges(
            "revise", self.revise_router, {"execute": "execute", "review": "review"}
        )
        wf.add_edge("deliver", END)
        wf.add_edge("handle_error", END)
        return wf.compile(checkpointer=self.checkpointer)

    async def _checkpoint(self, s: dict) -> None:
        """节点级持久化：保存快照 + 更新任务状态，用于暂停/恢复/崩溃恢复。"""
        tid = s.get("task_id")
        if not tid:
            return
        try:
            sm = StateManager(tid)
            await sm.save_snapshot(s)
        except Exception as e:
            logger.warning(f"任务{tid}快照保存失败: {e}")
        status = s.get("status")
        if status is not None:
            try:
                await db.execute(
                    "UPDATE tasks SET status=?, updated_at=CURRENT_TIMESTAMP WHERE task_id=?",
                    (
                        status.value if isinstance(status, TaskStatus) else str(status),
                        tid,
                    ),
                )
            except Exception as e:
                logger.warning(f"任务{tid}状态更新失败: {e}")

    async def _security_violations(self, code: str) -> List[str]:
        violations = []
        if self._mining_detector.scan_command_line(code):
            violations.append("检测到挖矿相关命令")
        if not await self._supply_firewall.check(code):
            violations.append("供应链防火墙拦截：检测到黑名单依赖")
        return violations

    async def planning_node(self, s):
        await push_progress(s["task_id"], 0.05, "规划中...")
        return {
            "status": TaskStatus.EXECUTING,
            "task_board_state": s.get("task_board_state", {}),
        }

    async def execute_node(self, s):
        tid = s["task_id"]
        phases = s["phases"]
        pi = s["current_phase"]
        if pi >= len(phases):
            return {
                "status": TaskStatus.COMPLETED,
                "task_board_state": s.get("task_board_state", {}),
            }

        phase = phases[pi]
        
        # 并行执行独立操作
        checkpoint_task = self._checkpoint(s)
        push_task = self._push_execute_progress(tid, pi, len(phases), phase)
        tb_task = TaskBoard.from_state_dict(tid, s.get("task_board_state", {}))
        room_task = meeting_room_manager.get_room(s["task_id"])
        
        await asyncio.gather(checkpoint_task, push_task)
        tb, room = await asyncio.gather(tb_task, room_task)

        if not tb.state:
            raise RuntimeError(f"TaskBoard state not available for {tid}")

        ex = self._create_executor(s)
        await asyncio.gather(
            tb.update(phase=TaskPhase.EXECUTING),
            tb.broadcast_to_room(room)
        )

        ctx = tb.state.generate_context_prompt("executor")
        result = await ex.execute(
            {
                "description": phase.get("description", ""),
                "expected_artifacts": phase.get("expected_artifacts", []),
                "context": str(s.get("artifacts", {})),
                "task_context": ctx,
            }
        )

        arts = result.get("artifacts", {})
        return await self._process_execution_result(tid, s, arts, tb, room, ex)

    async def _push_execute_progress(
        self, tid: str, phase_idx: int, total_phases: int, phase: dict
    ):
        bp = phase_idx / total_phases if total_phases else 0
        await push_progress(tid, bp + 0.2, f"执行中: {phase.get('phase', '')}")

    def _create_executor(self, s):
        ec = s["team"]["executor"][0]
        ex = role_registry.create_agent("executor", ec)
        ex.bind_context(s["task_id"])
        return ex

    async def _process_execution_result(
        self, tid: str, s: dict, artifacts: dict, tb: TaskBoard, room, ex
    ):
        await self._broadcast_execution_result(tid, s, artifacts, room, ex)
        cc = "\n".join(artifacts.values())
        self.output_history.setdefault(tid, []).append(cc)

        if await loop_detector.check_loop(tid, self.output_history[tid]):
            await push_progress(tid, 0.0, "死循环")
            return {
                "status": TaskStatus.FAILED,
                "error": "死循环",
                "task_board_state": s.get("task_board_state", {}),
            }

        violations = await self._security_violations(cc)
        if violations:
            await self._broadcast_security_violation(tid, room, violations)
            return {
                "status": TaskStatus.FAILED,
                "error": "; ".join(violations),
                "task_board_state": s.get("task_board_state", {}),
            }

        await self._scan_and_broadcast(cc, room)
        await tb.update(
            completed_work=[f"已产出: {', '.join(artifacts.keys())}"],
            pending_actions=["等待评审"],
        )
        await tb.broadcast_to_room(room)

        return {
            "last_code": cc,
            "artifacts": artifacts,
            "messages": [{"role": "executor", "content": cc}],
            "status": TaskStatus.REVIEWING,
            "review_rounds": 0,
            "task_board_state": tb.get_state_dict(),
        }

    async def _broadcast_execution_result(
        self, tid: str, s: dict, artifacts: dict, room, ex
    ):
        if not room:
            return
        cc = "\n".join(artifacts.values())
        await room.broadcast(
            MessageLayer.L2_MEETING,
            "executor",
            ex.context.agent_id,
            f"开始执行: {s['phases'][s['current_phase']].get('description', '')}",
        )
        await room.broadcast(
            MessageLayer.L2_MEETING,
            "executor",
            ex.context.agent_id,
            f"提交代码:\n```\n{cc[:500]}...\n```",
            msg_type="code",
        )

    async def _broadcast_security_violation(
        self, tid: str, room, violations: List[str]
    ):
        if not room:
            return
        await room.broadcast(
            MessageLayer.L2_MEETING,
            "security_scanner",
            "guard",
            f"安全拦截: {'; '.join(violations)}",
            msg_type="security_warning",
        )

    async def _scan_and_broadcast(self, code: str, room):
        scans = await code_scanner.scan(code)
        if scans and room:
            await room.broadcast(
                MessageLayer.L2_MEETING,
                "security_scanner",
                "bandit",
                f"发现{len(scans)}个问题",
                msg_type="security_warning",
            )

    async def review_node(self, s):
        tid, phases = s["task_id"], s["phases"]
        pi = s["current_phase"]
        bp = pi / len(phases) if phases else 0
        
        # 并行执行独立操作
        push_task = push_progress(tid, bp + 0.4, f"评审中: {phases[pi].get('phase', '')}")
        checkpoint_task = self._checkpoint(s)
        tb_task = TaskBoard.from_state_dict(tid, s.get("task_board_state", {}))
        room_task = meeting_room_manager.get_room(s["task_id"])
        
        await asyncio.gather(push_task, checkpoint_task)
        tb, room = await asyncio.gather(tb_task, room_task)

        if not tb.state:
            raise RuntimeError(f"TaskBoard state not available for {tid}")

        code = s["last_code"]
        reqs = phases[pi].get("description", "")
        reviewers = self._create_reviewers(s)

        await asyncio.gather(
            tb.update(phase=TaskPhase.REVIEWING, pending_actions=["审查中"]),
            tb.broadcast_to_room(room)
        )

        ctx = tb.state.generate_context_prompt("reviewer")
        plan = s.get("plan", {})
        scope = (
            f"\n任务复杂度: {plan.get('complexity', 'simple')}\n"
            f"原始需求: {s.get('user_request', '')}"
        )
        
        # 并行执行多个评审者
        async def run_reviewer(rv):
            return await rv.execute(
                {
                    "code": code,
                    "requirements": reqs + scope,
                    "task_context": ctx,
                }
            )
        
        reviewer_results = await asyncio.gather(
            *[run_reviewer(rv) for rv in reviewers]
        )
        
        results = list(zip(reviewers, reviewer_results))
        for rv, res in results:
            await self._broadcast_review_result(tid, room, rv, res)

        passed = all(res.get("passed", False) for _, res in results)
        fb = "\n\n".join(res.get("feedback", "") for _, res in results)

        passed = all(res.get("passed", False) for _, res in results)
        fb = "\n\n".join(res.get("feedback", "") for _, res in results)

        nr = s.get("review_rounds", 0) + 1
        if not passed and nr >= s.get("max_review_rounds", 5):
            logger.warning(
                f"任务{tid}审查 {nr} 轮仍未通过，按尽力交付处理（反馈保留在消息中）"
            )
            passed = True

        if passed:
            await tb.update(
                completed_work=tb.state.completed_work
                + [f"阶段{tb.state.current_stage + 1}通过"],
                pending_actions=[],
            )
        else:
            await tb.update(pending_actions=["修改代码"])
        await tb.broadcast_to_room(room)

        return {
            "review_feedback": fb,
            "review_rounds": nr,
            "review_passed_this_round": passed,
            "messages": [{"role": "reviewer", "content": fb}],
            "task_board_state": tb.get_state_dict(),
        }

    def _create_reviewers(self, s) -> List:
        reviewers = []
        for role in ("reviewer_correctness", "reviewer_efficiency"):
            rc = s["team"].get(role, [None])[0] or s["team"]["executor"][0]
            rv = role_registry.create_agent(role, rc)
            if rv:
                rv.bind_context(s["task_id"])
                reviewers.append(rv)
        return reviewers or [self._create_executor(s)]

    async def _broadcast_review_result(self, tid: str, room, rv, res: dict):
        if not room:
            return
        passed = res.get("passed", False)
        fb = res.get("feedback", "")
        await room.broadcast(
            MessageLayer.L2_MEETING, "reviewer", rv.context.agent_id, "开始审查..."
        )
        await room.broadcast(
            MessageLayer.L2_MEETING,
            "reviewer",
            rv.context.agent_id,
            f"[{rv.role}] 结论:{'通过' if passed else '需修改'}\n{fb}",
        )

    def review_router(self, s):
        if s.get("review_passed_this_round"):
            return "pass" if s["current_phase"] + 1 >= len(s["phases"]) else "revise"
        return (
            "fail"
            if s.get("review_rounds", 0) >= s.get("max_review_rounds", 5)
            else "revise"
        )

    async def revise_node(self, s):
        tid, phases = s["task_id"], s["phases"]
        pi = s["current_phase"]

        if s.get("review_passed_this_round"):
            return await self._advance_phase(s, tid, phases, pi)

        await self._checkpoint(s)

        tb = await TaskBoard.from_state_dict(tid, s.get("task_board_state", {}))
        if not tb.state:
            raise RuntimeError(f"TaskBoard state not available for {tid}")

        bp = pi / len(phases) if phases else 0
        await push_progress(tid, bp + 0.6, f"修订中: {phases[pi].get('phase', '')}")

        room = await meeting_room_manager.get_room(s["task_id"])
        await self._maybe_swap_executor(s)

        await tb.update(phase=TaskPhase.REVISING, pending_actions=["修改代码"])
        await tb.broadcast_to_room(room)

        return await self._perform_revision(s, tb, room)

    async def _advance_phase(self, s, tid, phases, pi):
        tb = await TaskBoard.from_state_dict(tid, s.get("task_board_state", {}))
        if tb.state:
            await tb.update(
                advance_stage=True,
                pending_actions=[f"开始阶段{tb.state.current_stage + 1}"],
            )
            room = await meeting_room_manager.get_room(s["task_id"])
            await tb.broadcast_to_room(room)
        return {
            "current_phase": pi + 1,
            "review_rounds": 0,
            "review_passed_this_round": False,
            "status": TaskStatus.EXECUTING,
            "task_board_state": tb.get_state_dict()
            if tb.state
            else s.get("task_board_state", {}),
        }

    async def _maybe_swap_executor(self, s):
        if s["review_rounds"] < 3:
            return
        hc = await capability_pool.find_best_match(
            required_tags=["smart", "architecture"], prefer_cheapest=False
        )
        if hc and hc.id != s["team"]["executor"][0].id:
            s["team"]["executor"][0] = hc
            logger.info(f"更换执行AI为{hc.name}")

    async def _perform_revision(self, s, tb, room):
        tid = s["task_id"]
        ec = s["team"]["executor"][0]
        ex = role_registry.create_agent("executor", ec)
        ex.bind_context(tid)

        if room:
            await room.broadcast(
                MessageLayer.L2_MEETING,
                "executor",
                ex.context.agent_id,
                f"修改: {s['review_feedback'][:100]}",
            )

        arts = await ex.debug_code(s["artifacts"], s["review_feedback"])
        rc = "\n".join(arts.values())

        new_basenames = {Path(k).name for k in arts}
        stale = {
            k: v
            for k, v in s.get("artifacts", {}).items()
            if Path(k).name not in new_basenames
        }
        if len(stale) != len(s.get("artifacts", {})):
            logger.info(
                f"修订后清理 {len(s.get('artifacts', {})) - len(stale)} 个过期文件"
            )
            s["artifacts"] = stale

        violations = await self._security_violations(rc)
        if violations:
            await self._broadcast_security_violation(tid, room, violations)
            return {
                "status": TaskStatus.FAILED,
                "error": "; ".join(violations),
                "task_board_state": s.get("task_board_state", {}),
            }

        scans = await code_scanner.scan(rc)
        if scans and room:
            await room.broadcast(
                MessageLayer.L2_MEETING,
                "security_scanner",
                "bandit",
                f"修订扫描发现{len(scans)}问题",
                msg_type="security_warning",
            )

        await tb.update(
            completed_work=tb.state.completed_work + ["已修订"],
            pending_actions=["等待重新评审"],
        )
        await tb.broadcast_to_room(room)

        return {
            "last_code": rc,
            "artifacts": arts,
            "review_rounds": s["review_rounds"],
            "status": TaskStatus.REVIEWING,
            "messages": [{"role": "executor", "content": f"修订后:\n{rc[:200]}..."}],
            "task_board_state": tb.get_state_dict(),
        }

    def revise_router(self, s):
        return "execute" if s.get("status") == TaskStatus.EXECUTING else "review"

    async def deliver_node(self, s):
        tid = s["task_id"]
        await push_progress(tid, 0.9, "交付中...")

        await self._checkpoint(s)

        tb = await TaskBoard.from_state_dict(tid, s.get("task_board_state", {}))
        if not tb.state:
            raise RuntimeError(f"TaskBoard state not available for {tid}")

        dc = s["team"].get("deliverer", [None])[0] or s["team"]["executor"][0]
        dv = role_registry.create_agent("deliverer", dc)
        dv.bind_context(tid)

        await tb.update(phase=TaskPhase.DELIVERING)
        room = await meeting_room_manager.get_room(s["task_id"])
        await tb.broadcast_to_room(room)

        result = await dv.execute(
            {
                "task_id": tid,
                "artifacts": s["artifacts"],
                "project_info": {
                    "task_name": s["plan"].get("task_name", "未命名"),
                    "usage": "请查看各文件",
                },
            }
        )

        await tb.update(phase=TaskPhase.COMPLETED, pending_actions=[])
        await tb.broadcast_to_room(room)

        if room:
            await room.broadcast(
                MessageLayer.L1_PUBLIC,
                "deliverer",
                dv.context.agent_id,
                f"完成! 交付物: {result['output_path']}",
            )

        await push_progress(tid, 1.0, "完成")
        self.output_history.pop(tid, None)
        return {
            "status": TaskStatus.COMPLETED,
            "messages": [{"role": "deliverer", "content": "交付完成"}],
            "task_board_state": tb.get_state_dict(),
        }

    async def handle_error_node(self, s):
        tid = s["task_id"]
        await push_progress(tid, 0.0, "失败")
        await self._checkpoint(s)
        tb = await TaskBoard.from_state_dict(tid, s.get("task_board_state", {}))
        if tb.state:
            await tb.update(phase=TaskPhase.FAILED, notes="执行失败")
            room = await meeting_room_manager.get_room(s["task_id"])
            await tb.broadcast_to_room(room)
        self.output_history.pop(tid, None)
        return {
            "status": TaskStatus.FAILED,
            "task_board_state": s.get("task_board_state", {}),
        }

    async def run(self, initial_state):
        return await self.graph.ainvoke(
            initial_state, {"configurable": {"thread_id": initial_state["task_id"]}}
        )
