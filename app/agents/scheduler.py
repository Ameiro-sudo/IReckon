from typing import List, Dict, Any, Set

from loguru import logger

from .base import BaseAgent
from app.llm.pool import AICapability, capability_pool
from app.engine.room import meeting_room_manager, MessageLayer
from app.engine.board import TaskBoard
from app.utils import create_jinja_env
from app.utils.json_utils import extract_json


class SchedulerAgent(BaseAgent):
    def __init__(self, capability: AICapability):
        self.jinja_env = create_jinja_env()
        system_prompt = self._build_system_prompt()
        super().__init__(
            role="scheduler", capability=capability, system_prompt=system_prompt
        )

    def _build_system_prompt(self) -> str:
        return """你是一个高级任务调度员，负责把用户的自然语言需求转化为可执行的软件项目计划，并组建合适的 AI 团队。

【职责】
1. 解析用户需求：识别核心功能、技术约束、隐含要求；需求模糊时选择最合理的解释，并在 summary 中注明假设。
2. 判定任务复杂度：simple / medium / complex。
3. 拆解执行阶段（复杂度感知，禁止过度规划）。
4. 制定招募计划：从能力池为各阶段挑选角色，给出技能标签偏好与成本策略。
5. 输出结构化《任务计划书》（JSON）。

【复杂度判定标准】
- simple：单文件脚本、小工具、单页面。只规划 1~2 个阶段（implementation + 可选 delivery），不要独立的"需求分析"阶段。
- medium：多文件小项目、含简单交互。可包含"设计 + 实现 + 审查"。
- complex：完整系统、多模块/多服务、需要测试与交付流水线。才使用完整多阶段（需求分析、设计、实现、测试、交付）。
- 阶段数量与需求复杂度和产出规模成正比；宁可少拆，不可过拆。

【招募原则】
- 只招募必要角色：simple 任务不要招募 creative / tool_manager。
- required_tags 给出该阶段最关键的 1~3 个技能标签（如 python, web, architecture, cli）。
- prefer_cheap=true 用于简单/低风险阶段；审查、架构等质量敏感阶段用 prefer_cheap=false。
- estimated_budget_usd 与 estimated_tokens 按复杂度合理估算，禁止虚高。

【输出格式（必须严格遵守）】
只输出一个 JSON 对象，禁止输出代码围栏（```）、注释或任何解释性文字。

JSON 结构示例：
{
  "task_name": "待办事项 CLI",
  "summary": "命令行待办管理工具，支持增删改查与 JSON 持久化（假设：无多用户需求）",
  "complexity": "simple",
  "estimated_budget_usd": 0.5,
  "phases": [
    {
      "phase": "implementation",
      "description": "实现 CLI 待办工具：增删改查 + JSON 持久化",
      "expected_artifacts": ["todo.py", "README.md"],
      "required_roles": ["executor"],
      "skill_tags": ["python", "cli"],
      "estimated_tokens": 4000
    }
  ],
  "recruitment_plan": {
    "executor": {"count": 1, "required_tags": ["python"], "prefer_cheap": true},
    "reviewer_correctness": {"count": 1, "required_tags": ["careful"], "prefer_cheap": true}
  }
}

可选角色：executor, reviewer_efficiency, reviewer_correctness, creative, tool_manager, deliverer。
"""

    async def parse_requirement(
        self, user_request: str, capabilities: str = ""
    ) -> Dict[str, Any]:
        cap_note = (
            "可用 AI 能力池（招募计划中的 required_tags 应尽量从这些实例的标签中选取）：\n"
            + capabilities
            if capabilities
            else ""
        )
        prompt = f"""用户需求：
{user_request}

{cap_note}

请按系统提示中的 JSON 结构输出《任务计划书》。只输出 JSON。
"""

        response = await self.think(prompt, temperature=0.2, infinite_retry=True)
        plan = extract_json(response)
        if plan and isinstance(plan, dict):
            logger.info(f"任务计划解析成功: {plan.get('task_name')}")
            return plan
        logger.error(f"解析调度 AI 返回的 JSON 失败:\n原始响应: {response}")
        return {
            "task_name": "未命名任务",
            "summary": user_request[:100],
            "complexity": "medium",
            "phases": [{"phase": "开发", "required_roles": ["executor"]}],
            "recruitment_plan": {"executor": {"count": 1}},
        }

    async def recruit_team(
        self, recruitment_plan: Dict[str, Any]
    ) -> Dict[str, List[AICapability]]:
        team = {}
        global_assigned_ids: Set[str] = set()

        for role, spec in recruitment_plan.items():
            count = spec.get("count", 1)
            required_tags = spec.get("required_tags", [])
            prefer_cheap = spec.get("prefer_cheap", False)

            candidates = []
            for _ in range(count):
                cap = await capability_pool.find_best_match(
                    required_tags=required_tags,
                    exclude_ids=global_assigned_ids,
                    prefer_cheapest=prefer_cheap,
                )
                if cap:
                    candidates.append(cap)
                    global_assigned_ids.add(cap.id)
                else:
                    cap = await capability_pool.find_best_match(
                        prefer_cheapest=prefer_cheap,
                    )
                    if cap:
                        logger.warning(
                            f"角色 {role} 标签不匹配({required_tags})，复用能力实例 {cap.id}"
                        )
                        candidates.append(cap)
                    else:
                        logger.error(f"无法为角色 {role} 找到合适的能力实例")
            team[role] = candidates
        return team

    async def execute(self, user_request: str, task_id: str) -> Dict[str, Any]:
        self.bind_context(task_id=task_id)

        caps = await capability_pool.get_all()
        cap_desc = "\n".join(
            f"- {c.id}: {c.name} ({c.model}) tags={c.tags} max_context={c.max_context}"
            for c in caps
        )
        plan = await self.parse_requirement(user_request, cap_desc)

        recruitment = plan.get("recruitment_plan", {})
        if not recruitment:
            recruitment = {
                "executor": {"count": 1},
                "reviewer_correctness": {"count": 1},
            }
        team = await self.recruit_team(recruitment)

        room = await meeting_room_manager.create_room(task_id)
        for role, members in team.items():
            for cap in members:
                room.add_member(role, cap.id)

        task_board = TaskBoard(task_id)
        await task_board.initialize(plan, team)
        await task_board.broadcast_to_room(room)

        announcement = self._generate_announcement(plan, team)
        self.add_message("assistant", announcement)
        if self.context:
            await room.broadcast(
                MessageLayer.L1_PUBLIC, "scheduler", self.context.agent_id, announcement
            )

        return {
            "plan": plan,
            "team": team,
            "room_id": room.room_id,
            "announcement": announcement,
            "task_board_state": task_board.get_state_dict(),
        }

    def _generate_announcement(
        self, plan: Dict[str, Any], team: Dict[str, List]
    ) -> str:
        lines = [
            f"[任务启动] {plan.get('task_name', '新任务')}",
            f"[概述] {plan.get('summary', '')}",
            f"[复杂度] {plan.get('complexity', 'medium')}",
            "",
            "[已招募团队]",
        ]
        for role, members in team.items():
            if members:
                names = ", ".join([m.name for m in members])
                lines.append(f"  - {role}: {names}")
        lines.append("")
        lines.append("[开始执行第一阶段]")
        return "\n".join(lines)
