from typing import List, Dict, Any, Optional
import asyncio
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from loguru import logger
from ai.capability_pool import AICapability, capability_pool
from workflow.task_manager import TaskStatus, TaskState
from workflow.role_registry import role_registry
from workflow.meeting_room import MeetingRoom, MessageLayer
from workflow.task_board import TaskBoard, TaskPhase
from workflow.loop_detector import loop_detector
from security.code_scanner import code_scanner
from web.websocket import push_progress

class WorkflowEngine:
    def __init__(self):
        self.checkpointer = MemorySaver()
        self.graph = self._build_graph()
        self.output_history: Dict[str, List[str]] = {}

    def _build_graph(self):
        wf = StateGraph(TaskState)
        for n in ["planning", "execute", "review", "revise", "deliver", "handle_error"]:
            wf.add_node(n, getattr(self, f"{n}_node"))
        wf.set_entry_point("planning")
        wf.add_edge("planning", "execute")
        wf.add_edge("execute", "review")
        wf.add_conditional_edges("review", self.review_router, {"pass": "deliver", "revise": "revise", "fail": "handle_error"})
        wf.add_conditional_edges("revise", self.revise_router, {"execute": "execute", "review": "review"})
        wf.add_edge("deliver", END)
        wf.add_edge("handle_error", END)
        return wf.compile(checkpointer=self.checkpointer)

    async def planning_node(self, s):
        await push_progress(s["task_id"], 0.05, "规划中...")
        return {"status": TaskStatus.EXECUTING, "task_board_state": s.get("task_board_state", {})}

    async def execute_node(self, s):
        tid, tp = s["task_id"], len(s["phases"])
        pi = s["current_phase"]
        if pi >= tp:
            return {"status": TaskStatus.COMPLETED, "task_board_state": s.get("task_board_state", {})}
        phase = s["phases"][pi]
        bp = pi / tp if tp else 0
        await push_progress(tid, bp + 0.2, f"执行中: {phase.get('phase', '')}")
        tb = await TaskBoard.from_state_dict(tid, s.get("task_board_state", {}))
        if not tb.state:
            raise RuntimeError(f"TaskBoard state not available for {tid}")
        room = s.get("room")
        ec = s["team"]["executor"][0]
        ex = role_registry.create_agent("executor", ec)
        ex.bind_context(tid)
        await tb.update(phase=TaskPhase.EXECUTING)
        await tb.broadcast_to_room(room)
        ctx = tb.state.generate_context_prompt("executor")
        if room:
            await room.broadcast(MessageLayer.L2_MEETING, "executor", ex.context.agent_id, f"开始执行: {phase.get('description', '')}")
        result = await ex.execute({
            "description": phase.get("description", ""),
            "expected_artifacts": phase.get("expected_artifacts", []),
            "context": str(s.get("artifacts", {})),
            "task_context": ctx,
        })
        arts = result.get("artifacts", {})
        cc = "\n".join(arts.values())
        self.output_history.setdefault(tid, []).append(cc)
        if await loop_detector.check_loop(tid, self.output_history[tid]):
            await push_progress(tid, 0.0, "死循环")
            return {"status": TaskStatus.FAILED, "error": "死循环", "task_board_state": s.get("task_board_state", {})}
        scans = await code_scanner.scan(cc)
        if scans and room:
            await room.broadcast(MessageLayer.L2_MEETING, "security_scanner", "bandit", f"发现{len(scans)}个问题", msg_type="security_warning")
        if room:
            await room.broadcast(MessageLayer.L2_MEETING, "executor", ex.context.agent_id, f"提交代码:\n```\n{cc[:500]}...\n```", msg_type="code")
        await tb.update(completed_work=[f"已产出: {', '.join(arts.keys())}"], pending_actions=["等待评审"])
        await tb.broadcast_to_room(room)
        return {
            "last_code": cc, "artifacts": arts, "messages": [{"role": "executor", "content": cc}],
            "status": TaskStatus.REVIEWING, "review_rounds": 0, "task_board_state": tb.get_state_dict(),
        }

    async def review_node(self, s):
        tid, tp = s["task_id"], len(s["phases"])
        pi = s["current_phase"]
        bp = pi / tp if tp else 0
        await push_progress(tid, bp + 0.4, f"评审中: {s['phases'][pi].get('phase', '')}")
        tb = await TaskBoard.from_state_dict(tid, s.get("task_board_state", {}))
        if not tb.state:
            raise RuntimeError(f"TaskBoard state not available for {tid}")
        code, reqs = s["last_code"], s["phases"][pi].get("description", "")
        room = s.get("room")
        rc = s["team"].get("reviewer_correctness", [None])[0] or s["team"]["executor"][0]
        rv = role_registry.create_agent("reviewer_correctness", rc)
        rv.bind_context(tid)
        await tb.update(phase=TaskPhase.REVIEWING, pending_actions=["审查中"])
        await tb.broadcast_to_room(room)
        ctx = tb.state.generate_context_prompt("reviewer")
        if room:
            await room.broadcast(MessageLayer.L2_MEETING, "reviewer", rv.context.agent_id, "开始审查...")
        res = await rv.execute({"code": code, "requirements": reqs, "task_context": ctx})
        passed, fb = res.get("passed", False), res.get("feedback", "")
        if room:
            await room.broadcast(MessageLayer.L2_MEETING, "reviewer", rv.context.agent_id, f"结论:{'通过' if passed else '需修改'}\n{fb}")
        if passed:
            await tb.update(completed_work=tb.state.completed_work + [f"阶段{tb.state.current_stage + 1}通过"], pending_actions=[])
        else:
            await tb.update(pending_actions=["修改代码"])
        await tb.broadcast_to_room(room)
        nr = s.get("review_rounds", 0) + 1
        return {
            "review_feedback": fb, "review_rounds": nr, "review_passed_this_round": passed,
            "messages": [{"role": "reviewer", "content": fb}], "task_board_state": tb.get_state_dict(),
        }

    def review_router(self, s):
        if s.get("review_passed_this_round"):
            return "pass" if s["current_phase"] + 1 >= len(s["phases"]) else "revise"
        return "fail" if s.get("review_rounds", 0) >= s.get("max_review_rounds", 5) else "revise"

    async def revise_node(self, s):
        tid, tp = s["task_id"], len(s["phases"])
        pi = s["current_phase"]
        bp = pi / tp if tp else 0
        await push_progress(tid, bp + 0.6, f"修订中: {s['phases'][pi].get('phase', '')}")
        tb = await TaskBoard.from_state_dict(tid, s.get("task_board_state", {}))
        if not tb.state:
            raise RuntimeError(f"TaskBoard state not available for {tid}")
        room = s.get("room")
        if s.get("review_passed_this_round"):
            await tb.update(advance_stage=True, pending_actions=[f"开始阶段{tb.state.current_stage + 1}"])
            await tb.broadcast_to_room(room)
            return {
                "current_phase": s["current_phase"] + 1, "review_rounds": 0,
                "review_passed_this_round": False, "status": TaskStatus.EXECUTING,
                "task_board_state": tb.get_state_dict(),
            }
        if s["review_rounds"] >= 3:
            hc = await capability_pool.find_best_match(required_tags=["smart", "architecture"], prefer_cheapest=False)
            if hc and hc.id != s["team"]["executor"][0].id:
                s["team"]["executor"][0] = hc
                logger.info(f"更换执行AI为{hc.name}")
        await tb.update(phase=TaskPhase.REVISING, pending_actions=["修改代码"])
        await tb.broadcast_to_room(room)
        ec = s["team"]["executor"][0]
        ex = role_registry.create_agent("executor", ec)
        ex.bind_context(tid)
        if room:
            await room.broadcast(MessageLayer.L2_MEETING, "executor", ex.context.agent_id, f"修改: {s['review_feedback'][:100]}")
        arts = await ex.debug_code(s["artifacts"], s["review_feedback"])
        rc = "\n".join(arts.values())
        scans = await code_scanner.scan(rc)
        if scans and room:
            await room.broadcast(MessageLayer.L2_MEETING, "security_scanner", "bandit", f"修订扫描发现{len(scans)}问题", msg_type="security_warning")
        await tb.update(completed_work=tb.state.completed_work + ["已修订"], pending_actions=["等待重新评审"])
        await tb.broadcast_to_room(room)
        return {
            "last_code": rc, "artifacts": arts, "review_rounds": s["review_rounds"],
            "status": TaskStatus.REVIEWING, "messages": [{"role": "executor", "content": f"修订后:\n{rc[:200]}..."}],
            "task_board_state": tb.get_state_dict(),
        }

    def revise_router(self, s):
        return "execute" if s.get("status") == TaskStatus.EXECUTING else "review"

    async def deliver_node(self, s):
        tid = s["task_id"]
        await push_progress(tid, 0.9, "交付中...")
        tb = await TaskBoard.from_state_dict(tid, s.get("task_board_state", {}))
        if not tb.state:
            raise RuntimeError(f"TaskBoard state not available for {tid}")
        dc = s["team"].get("deliverer", [None])[0] or s["team"]["executor"][0]
        dv = role_registry.create_agent("deliverer", dc)
        dv.bind_context(tid)
        await tb.update(phase=TaskPhase.DELIVERING)
        room = s.get("room")
        await tb.broadcast_to_room(room)
        result = await dv.execute({
            "task_id": tid, "artifacts": s["artifacts"],
            "project_info": {"task_name": s["plan"].get("task_name", "未命名"), "usage": "请查看各文件"},
        })
        await tb.update(phase=TaskPhase.COMPLETED, pending_actions=[])
        await tb.broadcast_to_room(room)
        if room:
            await room.broadcast(MessageLayer.L1_PUBLIC, "deliverer", dv.context.agent_id, f"完成! 交付物: {result['output_path']}")
        await push_progress(tid, 1.0, "完成")
        self.output_history.pop(tid, None)
        return {"status": TaskStatus.COMPLETED, "messages": [{"role": "deliverer", "content": "交付完成"}], "task_board_state": tb.get_state_dict()}

    async def error_node(self, s):
        tid = s["task_id"]
        await push_progress(tid, 0.0, "失败")
        tb = await TaskBoard.from_state_dict(tid, s.get("task_board_state", {}))
        if tb.state:
            await tb.update(phase=TaskPhase.FAILED, notes="执行失败")
            room = s.get("room")
            await tb.broadcast_to_room(room)
        self.output_history.pop(tid, None)
        return {"status": TaskStatus.FAILED, "task_board_state": s.get("task_board_state", {})}

    async def run(self, initial_state):
        return await self.graph.ainvoke(initial_state, {"configurable": {"thread_id": initial_state["task_id"]}})
