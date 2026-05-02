"""
调度 AI (老调)
负责：解析用户需求，拆解任务，招募成员，协调进度
"""

import json
import asyncio
from typing import List, Dict, Any, Optional, Set
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from loguru import logger

from ai.roles.base_agent import BaseAgent
from ai.capability_pool import AICapability, capability_pool
from workflow.meeting_room import meeting_room_manager, MessageLayer
from workflow.task_board import TaskBoard
from core.config_manager import config_manager


class SchedulerAgent(BaseAgent):
    """调度 AI"""

    def __init__(self, capability: AICapability):
        template_dir = Path("config/prompts")
        if not template_dir.exists():
            template_dir = Path(__file__).parent.parent.parent / "config/prompts"
        self.jinja_env = Environment(loader=FileSystemLoader(str(template_dir)))

        system_prompt = self._build_system_prompt()
        super().__init__(role="scheduler", capability=capability, system_prompt=system_prompt)

    def _build_system_prompt(self) -> str:
        return """你是一个高级任务调度员（老调），负责将用户的自然语言需求转化为可执行的软件项目计划，并组建合适的 AI 团队。

你的职责：
1. 解析用户需求，识别核心功能、技术约束、隐含要求。
2. 将任务拆解为清晰的阶段（需求分析、设计、编码、测试、交付）。
3. 根据任务特点，从能力池中为每个阶段招募合适的 AI 角色（执行员、评审员、创意师等）。
4. 输出结构化的《绩效任务计划书》，包含角色分配、里程碑、预期产出。

输出格式要求：使用 JSON 结构，便于程序解析。同时提供人类可读的摘要。

在招募时，你需要考虑：
- 任务的复杂度（简单脚本 vs 完整项目）
- 预算限制（成本优先 vs 质量优先）
- 所需技能标签（如 python, web, architecture）

能力池信息将在每次任务启动时通过用户消息提供。
"""

    async def parse_requirement(self, user_request: str) -> Dict[str, Any]:
        prompt = f"""用户需求：
{user_request}

请分析需求并输出 JSON 格式的任务计划书。JSON 结构如下：
{{
    "task_name": "简短任务名",
    "summary": "一句话概括",
    "complexity": "simple|medium|complex",
    "estimated_budget_usd": 0.0,
    "phases": [
        {{
            "phase": "phase_name",
            "description": "阶段目标",
            "expected_artifacts": ["文件1", "文件2"],
            "required_roles": ["executor", "reviewer_correctness"],
            "skill_tags": ["python", "fastapi"],
            "estimated_tokens": 5000
        }}
    ],
    "recruitment_plan": {{
        "executor": {{"count": 1, "required_tags": [], "prefer_cheap": false}},
        "reviewer_efficiency": {{"count": 1, "required_tags": ["architecture"]}},
        ...
    }}
}}

注意：required_roles 可选值：executor, reviewer_efficiency, reviewer_correctness, creative, tool_manager, deliverer。
"""

        response = await self.think(prompt, temperature=0.2, infinite_retry=True)
        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0].strip()
            plan = json.loads(json_str)
            logger.info(f"任务计划解析成功: {plan.get('task_name')}")
            return plan
        except json.JSONDecodeError as e:
            logger.error(f"解析调度 AI 返回的 JSON 失败: {e}\n原始响应: {response}")
            return {
                "task_name": "未命名任务",
                "summary": user_request[:100],
                "complexity": "medium",
                "phases": [{"phase": "开发", "required_roles": ["executor"]}],
                "recruitment_plan": {"executor": {"count": 1}},
            }

    async def recruit_team(self, recruitment_plan: Dict[str, Any]) -> Dict[str, List[AICapability]]:
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
                    logger.error(f"无法为角色 {role} 找到合适的能力实例")
            team[role] = candidates
        return team

    async def execute(self, user_request: str, task_id: str) -> Dict[str, Any]:
        self.bind_context(task_id=task_id)

        # 1. 解析需求
        plan = await self.parse_requirement(user_request)

        # 2. 招募团队
        recruitment = plan.get("recruitment_plan", {})
        if not recruitment:
            recruitment = {"executor": {"count": 1}, "reviewer_correctness": {"count": 1}}
        team = await self.recruit_team(recruitment)

        # 3. 创建会议室
        room = await meeting_room_manager.create_room(task_id)
        for role, members in team.items():
            for cap in members:
                room.add_member(role, cap.id)

        # 4. 初始化任务看板
        task_board = TaskBoard(task_id)
        board_state = await task_board.initialize(plan, team)
        await task_board.broadcast_to_room(room)

        # 5. 生成公告
        announcement = self._generate_announcement(plan, team)
        self.add_message("assistant", announcement)
        await room.broadcast(
            MessageLayer.L1_PUBLIC,
            "scheduler", self.context.agent_id,
            announcement
        )

        return {
            "plan": plan,
            "team": team,
            "room_id": room.room_id,
            "announcement": announcement,
            "task_board_state": task_board.get_state_dict(),
        }

    def _generate_announcement(self, plan: Dict[str, Any], team: Dict[str, List]) -> str:
        lines = [
            f"📋 任务启动：{plan.get('task_name', '新任务')}",
            f"📝 概述：{plan.get('summary', '')}",
            f"🎯 复杂度：{plan.get('complexity', 'medium')}",
            "",
            "👥 已招募团队：",
        ]
        for role, members in team.items():
            if members:
                names = ", ".join([m.name for m in members])
                lines.append(f"  - {role}: {names}")
        lines.append("")
        lines.append("📌 开始执行第一阶段...")
        return "\n".join(lines)