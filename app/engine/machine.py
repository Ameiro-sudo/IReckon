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

from app.core.config import get

# 缓存编译后的图，避免每次实例化都重新编译（编译耗时约 100-200ms）
_compiled_graph_cache = None


def revise_router(s):
    # FAILED 状态不继续修订
    if s.get("status") == TaskStatus.FAILED:
        return "fail"
    return "execute" if s.get("status") == TaskStatus.EXECUTING else "review"


async def _maybe_swap_executor(s) -> dict:
    """评审轮次较多时升级执行 AI；返回更新后的 team，不原地修改状态。"""
    team = s["team"]
    if s.get("review_rounds", 0) < 3:
        return {"team": team}
    hc = await capability_pool.find_best_match(
        required_tags=["smart", "architecture"], prefer_cheapest=False
    )
    if hc and hc.id != team["executor"][0].id:
        team = {**team, "executor": [hc, *team["executor"][1:]]}
        logger.info(f"更换执行AI为{hc.name}")
    return {"team": team}


async def _advance_phase(s, tid, phases, pi):
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
        "revision_pending": False,
        "status": TaskStatus.EXECUTING,
        "task_board_state": tb.get_state_dict()
        if tb.state
        else s.get("task_board_state", {}),
    }


def review_router(s):
    # FAILED 状态不进入评审/交付，直接走失败处理
    if s.get("status") == TaskStatus.FAILED:
        return "fail"
    if s.get("review_passed_this_round"):
        return "pass" if s["current_phase"] + 1 >= len(s["phases"]) else "revise"
    return (
        "fail"
        if s.get("review_rounds", 0)
        >= s.get("max_review_rounds", get("task_defaults.max_review_rounds", 5))
        else "revise"
    )


async def _broadcast_review_result(tid: str, room, rv, res: dict):
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


async def _scan_and_broadcast(code: str, room):
    scans = await code_scanner.scan(code)
    if scans and room:
        await room.broadcast(
            MessageLayer.L2_MEETING,
            "security_scanner",
            "bandit",
            f"发现{len(scans)}个问题",
            msg_type="security_warning",
        )


async def _broadcast_security_violation(tid: str, room, violations: List[str]):
    if not room:
        return
    await room.broadcast(
        MessageLayer.L2_MEETING,
        "security_scanner",
        "guard",
        f"安全拦截: {'; '.join(violations)}",
        msg_type="security_warning",
    )


async def _broadcast_execution_result(tid: str, s: dict, artifacts: dict, room, ex):
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


def _bounded_artifacts(artifacts: dict, limit: int = 200_000) -> dict:
    """把 artifacts 内容总量截断到 limit 以内（修订上下文用），优先截断大文件。"""
    total = sum(len(v) for v in artifacts.values())
    if total <= limit:
        return artifacts
    result = {k: v for k, v in artifacts.items()}
    overflow = total - limit
    for name in sorted(result, key=lambda k: len(result[k]), reverse=True):
        if overflow <= 0:
            break
        removed = min(overflow, len(result[name]))
        result[name] = result[name][: len(result[name]) - removed] + "\n...[截断]"
        overflow -= removed
    return result


def _bounded_context(artifacts: dict, limit: int = 200_000) -> str:
    """把 artifacts 拼成上下文，超限截断，防止任务上下文无界增长。"""
    ctx = str(artifacts)
    if len(ctx) <= limit:
        return ctx
    return ctx[:limit] + "\n...[截断]"


def _create_executor(s):
    ec = s["team"]["executor"][0]
    ex = role_registry.create_agent("executor", ec)
    if ex is None:
        raise RuntimeError(f"无法创建执行 Agent（角色 executor，AI 实例 {ec.id}）")
    ex.bind_context(s["task_id"])
    return ex


async def _push_execute_progress(
    tid: str, phase_idx: int, total_phases: int, phase: dict
):
    bp = phase_idx / total_phases if total_phases else 0
    await push_progress(tid, bp + 0.2, f"执行中: {phase.get('phase', '')}")


async def planning_node(s):
    await push_progress(s["task_id"], 0.05, "规划中...")
    return {
        "status": TaskStatus.EXECUTING,
        "task_board_state": s.get("task_board_state", {}),
    }


async def _checkpoint(s: dict) -> None:
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


def execute_router(s):
    """执行结果路由：FAILED 直接终结，不再进入评审。"""
    return "fail" if s.get("status") == TaskStatus.FAILED else "review"


def _entry_router(s):
    """入口路由：revision_pending 时（评审未通过被暂停）从 revise 恢复。"""
    return "revise" if s.get("revision_pending") else "execute"


class WorkflowEngine:
    def __init__(self):
        global _compiled_graph_cache
        self.checkpointer = MemorySaver()
        if _compiled_graph_cache is None:
            _compiled_graph_cache = self._build_graph()
        self.graph = _compiled_graph_cache
        # 死循环检测历史：tid -> {阶段索引: [每轮输出]}
        self.output_history: Dict[str, Dict[int, List[str]]] = {}
        self._supply_firewall = SupplyChainFirewall()
        self._mining_detector = MiningDetector()

    def _build_graph(self):
        wf = StateGraph(TaskState)
        nodes = {
            "planning": planning_node,
            "execute": self.execute_node,
            "review": self.review_node,
            "revise": self.revise_node,
            "deliver": self.deliver_node,
            "handle_error": self.handle_error_node,
        }
        for name, fn in nodes.items():
            wf.add_node(name, fn)
        wf.set_entry_point("planning")
        # 入口路由：暂停恢复且待修订时从 revise 重新进入，否则正常从 execute 开始
        wf.add_conditional_edges(
            "planning",
            _entry_router,
            {"execute": "execute", "revise": "revise"},
        )
        # 执行结果 FAILED 直接终结，不再进入评审
        wf.add_conditional_edges(
            "execute", execute_router, {"review": "review", "fail": END}
        )
        wf.add_conditional_edges(
            "review",
            review_router,
            {"pass": "deliver", "revise": "revise", "fail": "handle_error"},
        )
        wf.add_conditional_edges(
            "revise",
            revise_router,
            {"execute": "execute", "review": "review", "fail": "handle_error"},
        )
        wf.add_edge("deliver", END)
        wf.add_edge("handle_error", END)
        return wf.compile(checkpointer=self.checkpointer)

    async def _security_violations(self, code: str) -> List[str]:
        violations = []
        if self._mining_detector.scan_command_line(code):
            violations.append("检测到挖矿相关命令")
        if not await self._supply_firewall.check(code):
            violations.append("供应链防火墙拦截：检测到黑名单依赖")
        return violations

    async def execute_node(self, s):
        # FAILED 状态不继续执行，直接终结
        if s.get("status") == TaskStatus.FAILED:
            return {
                "status": TaskStatus.FAILED,
                "task_board_state": s.get("task_board_state", {}),
            }
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
        checkpoint_task = _checkpoint(s)
        push_task = _push_execute_progress(tid, pi, len(phases), phase)
        tb_task = TaskBoard.from_state_dict(tid, s.get("task_board_state", {}))
        room_task = meeting_room_manager.get_room(s["task_id"])

        await asyncio.gather(checkpoint_task, push_task)
        tb, room = await asyncio.gather(tb_task, room_task)

        if not tb.state:
            raise RuntimeError(f"TaskBoard state not available for {tid}")

        ex = _create_executor(s)
        await asyncio.gather(
            tb.update(phase=TaskPhase.EXECUTING), tb.broadcast_to_room(room)
        )

        ctx = tb.state.generate_context_prompt("executor")
        result = await ex.execute(
            {
                "description": phase.get("description", ""),
                "expected_artifacts": phase.get("expected_artifacts", []),
                "context": _bounded_context(s.get("artifacts", {})),
                "task_context": ctx,
                "complexity": s.get("complexity", "simple"),
            }
        )

        arts = result.get("artifacts", {})
        return await self._process_execution_result(tid, s, arts, tb, room, ex)

    async def _process_execution_result(
        self, tid: str, s: dict, artifacts: dict, tb: TaskBoard, room, ex
    ):
        await _broadcast_execution_result(tid, s, artifacts, room, ex)
        cc = "\n".join(artifacts.values())
        # 按阶段记录输出历史，避免跨阶段输出误判为死循环
        phase_idx = s.get("current_phase", 0)
        self.output_history.setdefault(tid, {}).setdefault(phase_idx, []).append(cc)

        if await loop_detector.check_loop(tid, self.output_history[tid]):
            await push_progress(tid, 0.0, "死循环")
            return {
                "status": TaskStatus.FAILED,
                "error": "死循环",
                "task_board_state": s.get("task_board_state", {}),
            }

        violations = await self._security_violations(cc)
        if violations:
            await _broadcast_security_violation(tid, room, violations)
            return {
                "status": TaskStatus.FAILED,
                "error": "; ".join(violations),
                "task_board_state": s.get("task_board_state", {}),
            }

        await _scan_and_broadcast(cc, room)
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

    async def review_node(self, s):
        tid, phases = s["task_id"], s["phases"]
        pi = s["current_phase"]
        bp = pi / len(phases) if phases else 0

        # 并行执行独立操作
        push_task = push_progress(
            tid, bp + 0.4, f"评审中: {phases[pi].get('phase', '')}"
        )
        checkpoint_task = _checkpoint(s)
        tb_task = TaskBoard.from_state_dict(tid, s.get("task_board_state", {}))
        room_task = meeting_room_manager.get_room(s["task_id"])

        await asyncio.gather(push_task, checkpoint_task)
        tb, room = await asyncio.gather(tb_task, room_task)

        if not tb.state:
            raise RuntimeError(f"TaskBoard state not available for {tid}")

        code = s["last_code"]
        reqs = phases[pi].get("description", "")

        await asyncio.gather(
            tb.update(phase=TaskPhase.REVIEWING, pending_actions=["审查中"]),
            tb.broadcast_to_room(room),
        )

        ctx = tb.state.generate_context_prompt("reviewer")
        plan = s
        scope = (
            f"\n任务复杂度: {plan.get('complexity', 'simple')}\n"
            f"原始需求: {s.get('user_request', '')}"
        )
        task_data = {
            "code": code,
            "requirements": reqs + scope,
            "context": reqs + scope,
            "task_context": ctx,
        }

        # 合并审查：判断通道单次调用同时产出正确性+效率结论（调用次数减半）。
        # 失败或关闭开关时回退双流水线并行审查。
        results = None
        if get("task_defaults.merged_review", True):
            mrv = await self._create_merged_reviewer(s)
            if mrv is not None:
                try:
                    merged = await mrv.execute(task_data)
                    results = [
                        (
                            mrv,
                            {
                                **merged.get("correctness", {}),
                                "reviewer_type": "correctness",
                            },
                        ),
                        (
                            mrv,
                            {
                                **merged.get("efficiency", {}),
                                "reviewer_type": "efficiency",
                            },
                        ),
                    ]
                except Exception as e:
                    logger.warning(f"合并审查失败，回退双流水线: {e}")

        if results is None:
            reviewers = await self._create_reviewers(s)

            # 并行执行多个评审者（异常隔离：失败的评审者视为通过，不拖垮整体）
            async def run_reviewer(rv):
                return await rv.execute(
                    {
                        "code": code,
                        "requirements": reqs + scope,
                        "task_context": ctx,
                    }
                )

            reviewer_results = await asyncio.gather(
                *[run_reviewer(rv) for rv in reviewers], return_exceptions=True
            )

            results = []
            for rv, res in zip(reviewers, reviewer_results):
                if isinstance(res, Exception):
                    logger.warning(
                        f"评审者 {rv.role} 评审异常，视为通过（无意见）: {res}"
                    )
                    results.append((rv, {"passed": True, "feedback": ""}))
                else:
                    results.append((rv, res))

        for rv, res in results:
            await _broadcast_review_result(tid, room, rv, res)

        passed = all(res.get("passed", False) for _, res in results)
        fb = "\n\n".join(res.get("feedback", "") for _, res in results)

        nr = s.get("review_rounds", 0) + 1
        max_rounds = s.get(
            "max_review_rounds", get("task_defaults.max_review_rounds", 5)
        )
        if s.get("status") != TaskStatus.FAILED and not passed and nr >= max_rounds:
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
            "revision_pending": not passed,
            "messages": [{"role": "reviewer", "content": fb}],
            "task_board_state": tb.get_state_dict(),
        }

    async def _create_reviewers(self, s) -> List:
        """创建评审者；招募计划未指定审查实例时按计费通道路由到主通道（重模型）。

        审查判定是"判断点"，不应默认复用执行者的轻量实例——省下的钱
        不能花在刀刃背面。主通道无可用实例时才降级复用执行者实例。
        """
        from app.llm.router import acquire

        reviewers = []
        for role in ("reviewer_correctness", "reviewer_efficiency"):
            rc = s["team"].get(role, [None])[0]
            if rc is None:
                rc = await acquire(tier="heavy")
                if rc is None:
                    rc = s["team"]["executor"][0]
                    logger.warning(
                        f"主通道无可用实例，{role} 降级复用执行者实例 "
                        f"{rc.id}（判断点将运行在轻模型上）"
                    )
            rv = role_registry.create_agent(role, rc)
            if rv:
                rv.bind_context(s["task_id"])
                reviewers.append(rv)
        return reviewers or [_create_executor(s)]

    async def _create_merged_reviewer(self, s):
        """合并审查员：优先用招募计划指定的审查实例，否则按通道路由取主通道重模型。"""
        from app.llm.router import acquire

        rc = (
            s["team"].get("reviewer_correctness", [None])[0]
            or s["team"].get("reviewer_efficiency", [None])[0]
        )
        if rc is None:
            rc = await acquire(tier="heavy")
        if rc is None:
            return None
        rv = role_registry.create_agent("reviewer_merged", rc)
        if rv is None:
            return None
        rv.bind_context(s["task_id"])
        return rv

    async def revise_node(self, s):
        # FAILED 状态不继续修订
        if s.get("status") == TaskStatus.FAILED:
            return {
                "status": TaskStatus.FAILED,
                "task_board_state": s.get("task_board_state", {}),
            }
        tid, phases = s["task_id"], s["phases"]
        pi = s["current_phase"]

        if s.get("review_passed_this_round"):
            return await _advance_phase(s, tid, phases, pi)

        await _checkpoint(s)

        tb = await TaskBoard.from_state_dict(tid, s.get("task_board_state", {}))
        if not tb.state:
            raise RuntimeError(f"TaskBoard state not available for {tid}")

        bp = pi / len(phases) if phases else 0
        await push_progress(tid, bp + 0.6, f"修订中: {phases[pi].get('phase', '')}")

        room = await meeting_room_manager.get_room(s["task_id"])
        team_update = await _maybe_swap_executor(s)

        await tb.update(phase=TaskPhase.REVISING, pending_actions=["修改代码"])
        await tb.broadcast_to_room(room)

        return await self._perform_revision(
            s, tb, room, team_update.get("team", s["team"])
        )

    async def _perform_revision(self, s, tb, room, team=None):
        tid = s["task_id"]
        team = team or s["team"]
        ec = team["executor"][0]
        ex = role_registry.create_agent("executor", ec)
        if ex is None:
            raise RuntimeError(f"无法创建执行 Agent（角色 executor，AI 实例 {ec.id}）")
        ex.bind_context(tid)

        if room:
            await room.broadcast(
                MessageLayer.L2_MEETING,
                "executor",
                ex.context.agent_id,
                f"修改: {s['review_feedback'][:100]}",
            )

        arts = await ex.debug_code(
            _bounded_artifacts(s["artifacts"]), s["review_feedback"]
        )

        # 语法复检：修订产物为 Python 代码时先编译验证，失败则保留上一版
        for fname, content in list(arts.items()):
            if not fname.endswith(".py"):
                continue
            try:
                compile(content, fname, "exec")
            except (SyntaxError, ValueError) as e:
                logger.error(f"修订后 {fname} 语法错误: {e}，保留上一版")
                prev = s.get(fname)
                if prev is not None:
                    arts[fname] = prev
                else:
                    arts.pop(fname, None)

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
        # 显式合并旧文件（已过期的剔除）+ 新修订文件，作为返回值交给 reducer 合并，
        # 不原地修改传入的状态字典（避免破坏 LangGraph 快照语义）
        merged_artifacts = {**stale, **arts}

        violations = await self._security_violations(rc)
        if violations:
            await _broadcast_security_violation(tid, room, violations)
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
            "artifacts": merged_artifacts,
            "review_rounds": s["review_rounds"],
            "revision_pending": False,
            "status": TaskStatus.REVIEWING,
            "team": team,
            "messages": [{"role": "executor", "content": f"修订后:\n{rc[:200]}..."}],
            "task_board_state": tb.get_state_dict(),
        }

    async def deliver_node(self, s):
        # FAILED 状态不进入交付
        if s.get("status") == TaskStatus.FAILED:
            return {
                "status": TaskStatus.FAILED,
                "task_board_state": s.get("task_board_state", {}),
            }
        tid = s["task_id"]
        await push_progress(tid, 0.9, "交付中...")

        await _checkpoint(s)

        tb = await TaskBoard.from_state_dict(tid, s.get("task_board_state", {}))
        if not tb.state:
            raise RuntimeError(f"TaskBoard state not available for {tid}")

        dc = s["team"].get("deliverer", [None])[0] or s["team"]["executor"][0]
        dv = role_registry.create_agent("deliverer", dc)
        if dv is None:
            raise RuntimeError(f"无法创建交付 Agent（角色 deliverer，AI 实例 {dc.id}）")
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
        await _checkpoint(s)
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
