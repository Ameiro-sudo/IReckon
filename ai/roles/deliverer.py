"""
交付 AI
"""

from pathlib import Path
from typing import Dict, Any
from datetime import datetime

from ai.roles.base_agent import BaseAgent
from ai.capability_pool import AICapability
from workflow.role_registry import register_role
from core.config_manager import config_manager
from loguru import logger


@register_role("deliverer", {
    "description": "交付AI，负责打包产物、归档、生成交付报告",
    "default_required_tags": ["general"],
})
class DelivererAgent(BaseAgent):
    __role_name__ = "deliverer"

    def __init__(self, capability: AICapability):
        system_prompt = """你是交付专员，负责打包交付物。

工作：
1. 收集产出文件，整理到输出目录
2. 生成 READY.txt
3. 生成交付报告
"""
        super().__init__(role="deliverer", capability=capability, system_prompt=system_prompt)

    async def package(
        self,
        task_id: str,
        artifacts: Dict[str, str],
        project_info: Dict[str, Any]
    ) -> str:
        output_dir = Path(config_manager.get("system.output_dir", "./data/outputs"))
        task_output_dir = output_dir / task_id
        task_output_dir.mkdir(parents=True, exist_ok=True)

        for filename, content in artifacts.items():
            file_path = task_output_dir / filename
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

        ready_content = self._generate_ready_txt(project_info, artifacts.keys())
        ready_path = task_output_dir / "READY.txt"
        with open(ready_path, "w", encoding="utf-8") as f:
            f.write(ready_content)

        logger.info(f"交付物已打包到: {task_output_dir}")
        return str(task_output_dir)

    def _generate_ready_txt(self, project_info: Dict[str, Any], files: list) -> str:
        lines = [
            f"项目：{project_info.get('task_name', '未命名')}",
            f"交付时间：{datetime.now().isoformat()}",
            "",
            "文件列表：",
        ]
        for f in files:
            lines.append(f"  - {f}")
        lines.extend([
            "",
            "使用方法：",
            project_info.get('usage', '请参考各文件'),
            "",
            "注意事项：",
            project_info.get('notes', '无'),
        ])
        return "\n".join(lines)

    async def execute(self, delivery_data: Dict[str, Any]) -> Dict[str, Any]:
        output_path = await self.package(
            delivery_data["task_id"],
            delivery_data["artifacts"],
            delivery_data.get("project_info", {})
        )
        return {"output_path": output_path, "status": "success"}