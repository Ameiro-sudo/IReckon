import re
from typing import Dict, Any, Tuple
from loguru import logger

from .base import BaseAgent
from app.llm.pool import AICapability
from app.engine.registry import register_role
from app.utils import create_jinja_env


@register_role(
    "executor",
    {
        "description": "执行AI，负责编写代码、调试、撰写文档，支持补丁修改",
        "default_required_tags": ["python", "coding"],
    },
)
class ExecutorAgent(BaseAgent):
    __role_name__ = "executor"

    def __init__(self, capability: AICapability):
        self.jinja_env = create_jinja_env()
        system_prompt = self._build_system_prompt()
        super().__init__(
            role="executor", capability=capability, system_prompt=system_prompt
        )

    def _build_system_prompt(self) -> str:
        return """你是一位资深软件工程师（AI 编程代理），负责把任务需求转化为可运行、可维护的高质量代码。

【语言规则】
- 注释与标识符使用与需求一致的语言（中文需求用中文注释）；代码本身遵循其语言惯例。
- 与团队沟通一律使用需求语言。

【工作原则】
1. YAGNI：只实现需求要求的内容，不要添加额外文件、功能或工程化设施。
2. 复杂度匹配：simple 任务直接产出可运行代码，不写需求文档、不生成 Dockerfile/CI/测试脚手架；hello world 就是 hello world。
3. 需求含糊时按最直接的合理解释实现，并在回复末尾用一行注明你的假设。
4. 完整交付（绝不占位）：代码必须完整可运行——禁止 TODO、pass 空壳、"..." 省略、未实现的函数签名。
5. 引用外部模块前先确认其存在，并给出安装命令（如 pip install ... / npm install ...）；不引用不存在的 API。
6. 多文件项目：公共逻辑放独立模块，避免循环导入；文件名与职责匹配，避免无关紧要的 main.py。
7. 不擅自引入与需求无关的第三方依赖。

【工作流程】
1. 复杂任务先思维链外化：问题重述 → 方案对比 → 选型理由 → 实施步骤。
2. 编写代码。
3. 交付前自检（Definition of Done）：
   - Python 代码必须能通过语法检查（无 SyntaxError）；
   - 边界条件：空输入、极端值、None、超大数据量；
   - 错误处理：给出可读的错误信息，而非裸异常；
   - 清理：无未使用变量、死代码、魔法数字、调试残留输出；
   - 多文件时逐一核对所有文件均已产出、相互引用一致。

【代码修改】
- 小改动：优先输出 unified diff 补丁，仅修改受影响代码段。格式：
  PATCH: <文件名>
  @@ -起始行,行数 +起始行,行数 @@
  上下文行
  -删除行
  +新增行
  可包含多个文件的补丁，每个文件以 `PATCH:` 开头。
- 大改动或补丁不适用：输出完整新文件（`//// filename:` 格式）。

【输出格式】
- 多文件：每个文件以 `//// filename: 相对路径` 开头，文件之间用空行分隔。
- 单文件：直接输出代码，不要用 markdown 代码围栏包裹。
- 代码与说明分离：不要在代码中间插入解释性文字；必要说明放在代码之前或之后。
"""

    async def think_before_code(self, task_description: str, constraints: list) -> str:
        prompt = f"""任务：{task_description}
约束：{", ".join(constraints) if constraints else "无"}

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

输出要求：
- 多文件：每个文件以 `//// filename: 相对路径` 开头（示例：`//// filename: todo.py`），文件之间用空行分隔。
- 单文件：直接输出代码，不要用 markdown 代码围栏包裹。
- 代码必须完整可运行：禁止 TODO、占位符或省略号。
- 引用第三方库时在代码末尾列出安装命令。
"""
        response = await self.think(prompt, temperature=0.2)
        return self._parse_artifacts(response)

    async def apply_patch(
        self, current_files: Dict[str, str], feedback: str
    ) -> Tuple[Dict[str, str], bool]:
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
                        logger.warning(
                            f"补丁指定了不存在的文件 {fname}，回退到完整重写"
                        )
                        return current_files, False
                    new_content = self._apply_unified_diff(
                        new_files[fname], patch_content
                    )
                    new_files[fname] = new_content
                logger.info("补丁应用成功")
                return new_files, True
            except Exception as e:
                logger.warning(f"补丁应用失败: {e}，回退到完整重写")
                return current_files, False
        else:
            return current_files, False

    async def debug_code(
        self, current_files: Dict[str, str], error_info: str
    ) -> Dict[str, str]:
        modified_files, success = await self.apply_patch(current_files, error_info)
        if success:
            return modified_files

        logger.info("局部修改失败，执行完整重写")
        context = "\n".join(
            [
                f"//// filename: {name}\n{content}"
                for name, content in current_files.items()
            ]
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
                current_fname = line[len("PATCH:") :].strip()
            elif current_fname is not None:
                current_lines.append(line)
        if current_fname is not None and current_lines:
            patches[current_fname] = "\n".join(current_lines)
        return patches

    def _apply_unified_diff(self, original: str, patch_text: str) -> str:
        original_lines = original.splitlines(keepends=True)
        patch_lines = patch_text.splitlines()
        result = list(original_lines)
        hunk_header_re = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")

        idx = 0
        line_offset = 0
        while idx < len(patch_lines):
            line = patch_lines[idx]
            if line.startswith("@@"):
                match = hunk_header_re.match(line)
                if not match:
                    idx += 1
                    continue
                old_start = int(match.group(1)) - 1 + line_offset
                idx += 1

                hunk_lines = []
                while (
                    idx < len(patch_lines)
                    and not patch_lines[idx].startswith("@@")
                    and not patch_lines[idx].startswith("PATCH:")
                ):
                    hunk_lines.append(patch_lines[idx])
                    idx += 1

                old_idx = old_start
                temp = []
                for h in hunk_lines:
                    if h.startswith(" "):
                        temp.append(h[1:])
                        old_idx += 1
                    elif h.startswith("-"):
                        old_idx += 1
                    elif h.startswith("+"):
                        temp.append(h[1:])
                added = sum(1 for h in hunk_lines if h.startswith("+"))
                removed = sum(1 for h in hunk_lines if h.startswith("-"))
                net_change = added - removed

                del_count = old_idx - old_start
                result[old_start : old_start + del_count] = [l + "\n" for l in temp]
                line_offset += net_change
            else:
                idx += 1
        return "".join(result)

    def _parse_artifacts(self, response: str) -> Dict[str, str]:
        artifacts = {}

        def clean(content: str) -> str:
            content = content.strip()
            if content.startswith("```"):
                lines = content.splitlines()
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip().startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()
            return content

        parts = response.split("//// filename:")
        if len(parts) == 1:
            artifacts["main.py"] = clean(response)
        else:
            for part in parts[1:]:
                lines = part.strip().split("\n", 1)
                if len(lines) >= 2:
                    filename = lines[0].strip()
                    filename = filename.strip("`").strip().strip("*").strip()
                    if not filename:
                        continue
                    content = clean(lines[1])
                    artifacts[filename] = content
        return artifacts

    def _syntax_errors(self, code_dict: Dict[str, str]) -> list[str]:
        errors = []
        for fname, content in code_dict.items():
            if not fname.endswith(".py"):
                continue
            try:
                compile(content, fname, "exec")
            except SyntaxError as e:
                errors.append(f"{fname}: {e.msg} (行 {e.lineno})")
        return errors

    async def execute(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        task_context = task_data.get("task_context", "")
        description = task_data.get("description", "")
        context = task_data.get("context", "")
        language = task_data.get("language", "python")

        # dsh Harness 执行路径：任务显式要求且 harness 可用时启用～
        if task_data.get("use_harness"):
            from app.harness import dsh_client
            from app.core.config import config_manager

            if not config_manager.get("harness.enabled", False):
                return {
                    "artifacts": {},
                    "syntax_errors": [],
                    "harness_error": "harness.enabled = false，跳过 dsh 执行路径",
                }
            if not dsh_client.available_mode():
                return {
                    "artifacts": {},
                    "syntax_errors": [],
                    "harness_error": "dsh 运行时不可用（需要 deepseek-harness-sdk 或 Node.js）",
                }

            workspace = task_data.get("workspace") or None
            result = await dsh_client.run(
                task=description,
                workspace=workspace,
                session_id=task_data.get("session_id"),
            )
            if not result.ok:
                return {
                    "artifacts": {},
                    "syntax_errors": [],
                    "harness_error": result.error,
                }
            artifacts = (
                self._parse_artifacts(result.final_response)
                if "//// filename:" in result.final_response
                else {}
            )
            return {
                "artifacts": artifacts
                or {"harness_response.md": result.final_response},
                "syntax_errors": self._syntax_errors(artifacts),
                "harness_mode": result.mode,
                "harness_session": result.session_id,
                "harness_workspace": result.workspace,
            }

        if task_context:
            context = f"{task_context}\n\n{context}" if context else task_context

        code_dict = await self.write_code(
            task_description=description,
            context=context,
            language=language,
        )

        for attempt in range(2):
            errs = self._syntax_errors(code_dict)
            if not errs:
                break
            logger.warning(f"语法检查失败(第{attempt + 1}次): {errs}")
            code_dict = await self.debug_code(
                code_dict, "请修复以下 Python 语法错误:\n" + "\n".join(errs)
            )

        errs = self._syntax_errors(code_dict)
        if errs:
            logger.error(f"语法修复失败，仍存在错误: {errs}")
        return {"artifacts": code_dict, "syntax_errors": errs}
