import re
from typing import Dict, Any, Tuple
from loguru import logger

from .base import BaseAgent
from app.llm.pool import AICapability
from app.engine.registry import register_role
from app.utils import create_jinja_env


@register_role("executor", {
    "description": "执行AI，负责编写代码、调试、撰写文档，支持补丁修改",
    "default_required_tags": ["python", "coding"],
})
class ExecutorAgent(BaseAgent):
    __role_name__ = "executor"

    def __init__(self, capability: AICapability):
        self.jinja_env = create_jinja_env()
        system_prompt = self._build_system_prompt()
        super().__init__(role="executor", capability=capability, system_prompt=system_prompt)

    def _build_system_prompt(self) -> str:
        return """你是一位资深软件工程师，负责将需求转化为高质量代码。

工作流程：
1. 对于复杂任务，首先进行思维链外化（问题重述、方案发散、抉择、执行步骤）。
2. 编写代码时遵循以下要求：
   - 清晰、模块化、有注释
   - 包含错误处理和输入验证
   - 必要时生成多个文件，格式：//// filename: 文件名
3. 当需要修改现有代码时：
   - 优先尝试生成统一 diff 补丁（unified diff），仅修改受影响的代码段，避免重写整个文件。
   - 如果改动过大或补丁不适用，则可以输出完整新文件内容（使用 //// filename: 格式）。
   - 补丁格式如下：
   PATCH: <文件名>
   @@ -起始行,行数 +起始行,行数 @@
   上下文行
   -删除的行
   +添加的行
   上下文行- 可以包含多个文件的补丁，每个文件以 `PATCH:` 行开头。
"""

    async def think_before_code(self, task_description: str, constraints: list) -> str:
        prompt = f"""任务：{task_description}
约束：{', '.join(constraints) if constraints else '无'}

请按思维链要求输出分析：
"""
        return await self.think(prompt, temperature=0.3)

    async def write_code(
        self,
        task_description: str,
        context: str = "",
        language: str = "python",
    ) -> Dict[str, str]:
        if "简单" not in task_description and len(task_description) > 20:
            thinking = await self.think_before_code(task_description, [])
            logger.debug(f"思维链: {thinking[:200]}...")

        prompt = f"""请编写代码完成以下任务：
{task_description}

上下文：
{context}

输出要求：如果生成多个文件，请使用 `//// filename: 文件名` 分隔每个文件的内容。否则直接输出代码。
"""
        response = await self.think(prompt, temperature=0.2)
        return self._parse_artifacts(response)

    async def apply_patch(self, current_files: Dict[str, str], feedback: str) -> Tuple[Dict[str, str], bool]:
        files_desc = []
        for fname, content in current_files.items():
            files_desc.append(f"文件: {fname}\n```\n{content}\n```\n")
        all_files_text = "\n".join(files_desc)

        prompt = f"""现有文件及内容：
{all_files_text}

修改需求（反馈）：
{feedback}

请根据反馈生成统一 diff 补丁来修改相应的文件。每个补丁以 `PATCH: 文件名` 开始，后跟 unified diff 内容。
如果改动很小，请只修改涉及的行，保持其余部分不变。
如果修改过于复杂或需要重写整个文件，则不要生成补丁，直接输出完整新文件（使用 //// filename: 格式）。
"""
        response = await self.think(prompt, temperature=0.1)

        if "PATCH:" in response:
            patches = self._parse_patches(response)
            if not patches:
                logger.warning("未能解析出有效补丁")
                return current_files, False

            try:
                new_files = dict(current_files)
                for fname, patch_content in patches.items():
                    if fname not in new_files:
                        logger.warning(f"补丁指定了不存在的文件 {fname}，回退到完整重写")
                        return current_files, False
                    new_content = self._apply_unified_diff(new_files[fname], patch_content)
                    new_files[fname] = new_content
                logger.info("补丁应用成功")
                return new_files, True
            except Exception as e:
                logger.warning(f"补丁应用失败: {e}，回退到完整重写")
                return current_files, False
        else:
            return current_files, False

    async def debug_code(self, current_files: Dict[str, str], error_info: str) -> Dict[str, str]:
        modified_files, success = await self.apply_patch(current_files, error_info)
        if success:
            return modified_files

        logger.info("局部修改失败，执行完整重写")
        context = "\n".join(
            [f"//// filename: {name}\n{content}" for name, content in current_files.items()]
        )
        prompt = f"""以下代码存在问题，请修复：

【现有代码】
{context}

【错误/反馈】
{error_info}

请输出修复后的完整代码，如有多个文件请用 `//// filename:` 分隔。
"""
        response = await self.think(prompt, temperature=0.1)
        return self._parse_artifacts(response)

    def _parse_patches(self, text: str) -> Dict[str, str]:
        patches = {}
        lines = text.splitlines()
        current_fname = None
        current_lines = []
        for line in lines:
            if line.startswith("PATCH:"):
                if current_fname is not None:
                    patches[current_fname] = "\n".join(current_lines)
                    current_lines = []
                current_fname = line[len("PATCH:"):].strip()
            elif current_fname is not None:
                current_lines.append(line)
        if current_fname is not None and current_lines:
            patches[current_fname] = "\n".join(current_lines)
        return patches

    def _apply_unified_diff(self, original: str, patch_text: str) -> str:
        original_lines = original.splitlines(keepends=True)
        patch_lines = patch_text.splitlines()
        result = list(original_lines)
        hunk_header_re = re.compile(r'^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@')

        idx = 0
        line_offset = 0
        while idx < len(patch_lines):
            line = patch_lines[idx]
            if line.startswith('@@'):
                match = hunk_header_re.match(line)
                if not match:
                    idx += 1
                    continue
                old_start = int(match.group(1)) - 1 + line_offset
                idx += 1

                hunk_lines = []
                while idx < len(patch_lines) and not patch_lines[idx].startswith('@@') and not patch_lines[idx].startswith('PATCH:'):
                    hunk_lines.append(patch_lines[idx])
                    idx += 1

                old_idx = old_start
                temp = []
                for h in hunk_lines:
                    if h.startswith(' '):
                        temp.append(h[1:])
                        old_idx += 1
                    elif h.startswith('-'):
                        old_idx += 1
                    elif h.startswith('+'):
                        temp.append(h[1:])
                added = sum(1 for h in hunk_lines if h.startswith('+'))
                removed = sum(1 for h in hunk_lines if h.startswith('-'))
                net_change = added - removed

                del_count = old_idx - old_start
                result[old_start:old_start + del_count] = [l + '\n' for l in temp]
                line_offset += net_change
            else:
                idx += 1
        return ''.join(result)

    def _parse_artifacts(self, response: str) -> Dict[str, str]:
        artifacts = {}
        parts = response.split("//// filename:")
        if len(parts) == 1:
            artifacts["main.py"] = response.strip()
        else:
            for part in parts[1:]:
                lines = part.strip().split("\n", 1)
                if len(lines) >= 2:
                    filename = lines[0].strip()
                    content = lines[1].strip()
                    artifacts[filename] = content
        return artifacts

    async def execute(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        task_context = task_data.get("task_context", "")
        description = task_data.get("description", "")
        context = task_data.get("context", "")
        language = task_data.get("language", "python")

        if task_context:
            context = f"{task_context}\n\n{context}" if context else task_context

        code_dict = await self.write_code(
            task_description=description,
            context=context,
            language=language,
        )
        return {"artifacts": code_dict}