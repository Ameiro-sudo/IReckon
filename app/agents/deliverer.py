from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime
import asyncio

from .base import BaseAgent
from app.llm.pool import AICapability
from app.engine.registry import register_role
from app.core.config import config_manager
from loguru import logger


@register_role(
    "deliverer",
    {
        "description": "交付AI，负责打包产物、归档、生成交付报告",
        "default_required_tags": ["general"],
    },
)
class DelivererAgent(BaseAgent):
    __role_name__ = "deliverer"

    def __init__(self, capability: AICapability):
        system_prompt = """你是交付专员，负责把任务产物打包成可交付的软件包。

【职责】
1. 校验产物完整性：核对计划中的预期文件是否齐备；缺失时在交付报告中明确说明。
2. 整理产物到输出目录，保持目录结构与文件名清晰。
3. 生成 READY.txt（交付说明），包含：
   - 项目名称、交付时间、文件清单
   - 使用/运行方法（依赖安装命令 + 启动命令）
   - 注意事项与已知限制
4. 生成交付报告：产物列表、完整性结论、运行说明。

【规则】
- 文件路径保持相对路径，禁止绝对路径、上级目录（../）与非法字符。
- 只做归档与说明，不要修改产物内容。
- 交付说明使用与需求一致的语言。
"""
        super().__init__(
            role="deliverer", capability=capability, system_prompt=system_prompt
        )

    @staticmethod
    def _safe_filename(name: str) -> str:
        """净化 LLM 提供的文件名，保留相对目录结构，防止路径穿越。"""
        parts = []
        for seg in str(name).replace("\\", "/").split("/"):
            seg = seg.strip()
            if not seg or seg in (".", ".."):
                continue
            seg = seg.replace(":", "_").replace("\x00", "")
            if seg:
                parts.append(seg)
        return "/".join(parts) if parts else "unnamed.txt"

    async def package(
        self, task_id: str, artifacts: Dict[str, str], project_info: Dict[str, Any]
    ) -> str:
        output_dir = Path(config_manager.get("system.output_dir", "./data/outputs"))
        task_output_dir = output_dir / task_id
        await asyncio.to_thread(task_output_dir.mkdir, parents=True, exist_ok=True)

        for filename, content in artifacts.items():
            safe_name = self._safe_filename(filename)
            file_path = task_output_dir / safe_name
            # 文件写入放到线程池，避免阻塞事件循环
            await asyncio.to_thread(file_path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(file_path.write_text, content, encoding="utf-8")

        ready_content = self._generate_ready_txt(project_info, list(artifacts.keys()))
        ready_path = task_output_dir / "READY.txt"
        await asyncio.to_thread(ready_path.write_text, ready_content, encoding="utf-8")

        logger.info(f"交付物已打包到: {task_output_dir}")
        return str(task_output_dir)

    def _generate_ready_txt(
        self, project_info: Dict[str, Any], files: List[str]
    ) -> str:
        lines = [
            f"项目：{project_info.get('task_name', '未命名')}",
            f"交付时间：{datetime.now().isoformat()}",
            "",
            "文件列表：",
        ]
        for f in files:
            lines.append(f"  - {f}")
        lines.extend(
            [
                "",
                "使用方法：",
                project_info.get("usage", "请参考各文件"),
                "",
                "注意事项：",
                project_info.get("notes", "无"),
            ]
        )
        return "\n".join(lines)

    async def execute(self, delivery_data: Dict[str, Any]) -> Dict[str, Any]:
        output_path = await self.package(
            delivery_data["task_id"],
            delivery_data["artifacts"],
            delivery_data.get("project_info", {}),
        )
        return {"output_path": output_path, "status": "success"}
