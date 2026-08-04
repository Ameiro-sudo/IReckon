import asyncio
import subprocess
from pathlib import Path
from typing import List, Dict, Optional
from loguru import logger
from jinja2 import Environment, FileSystemLoader

from app.core.config import config_manager
from app.engine.registry import role_registry
from app.llm.pool import capability_pool


class SelfImprover:
    def __init__(self):
        self._enabled = config_manager.get("self_update.enabled", True)
        self._max_files = config_manager.get("self_update.max_files_per_round", 5)
        self._branch_prefix = config_manager.get("self_update.branch_prefix", "self-improve")
        template_dir = Path(__file__).parent.parent.parent / "config" / "prompts"
        if template_dir.exists():
            self._jinja_env = Environment(loader=FileSystemLoader(str(template_dir)))
        else:
            self._jinja_env = None
        self._blacklist = set(config_manager.get("self_update.file_blacklist", [
            "config/config.yaml", "data/", "app/security/", "app/core/updater.py"
        ]))

    async def analyze(self, task_id: str) -> Dict:
        if not self._enabled:
            return {"success": False, "error": "自我改进已关闭"}

        files = self._list_source_files()
        if not files:
            return {"success": False, "error": "没有可分析的源文件"}

        executor = await self._get_executor()
        if not executor:
            return {"success": False, "error": "无法获取 Executor agent"}

        supported_tags = config_manager.get("ai_pool.instances", [])
        if supported_tags:
            cap = await capability_pool.find_best_match(required_tags=["coding", "smart"])
        else:
            caps = await capability_pool.get_all()
            cap = caps[0] if caps else None

        if not cap:
            return {"success": False, "error": "没有可用的 AI 实例"}

        analysis_prompt = self._build_analysis_prompt(files)
        await role_registry.create_agent("executor", cap).bind_context(task_id)
        executor_role = role_registry.create_agent("executor", cap)
        executor_role.bind_context(task_id)

        analysis = await executor_role.think(analysis_prompt, temperature=0.3)
        return self._parse_analysis(analysis)

    def _list_source_files(self) -> List[Dict]:
        base = Path(__file__).parent.parent.parent
        files = []
        for pattern in ["app/**/*.py", "ui/**/*.py", "config/**/*.yaml", "config/**/*.j2", "config/**/*.json"]:
            for f in base.glob(pattern):
                rel = str(f.relative_to(base))
                if any(rel.startswith(b) or rel == b for b in self._blacklist):
                    continue
                if f.stat().st_size > 50000:
                    continue
                files.append({"path": rel, "size": f.stat().st_size})
        return files

    def _build_analysis_prompt(self, files: List[Dict]) -> str:
        summary = "\n".join(f"  {f['path']} ({f['size']} bytes)" for f in files[:30])
        if len(files) > 30:
            summary += f"\n  ... 及其他 {len(files) - 30} 个文件"

        return f"""你正在分析自己的源代码，寻找改进机会。

源文件列表（共 {len(files)} 个）：
{summary}

请分析：
1. 代码质量问题（重复、冗余、不一致）
2. 缺少的功能或可能的优化
3. 潜在的 bug

对每个发现，给出文件路径、行号范围（大致）、问题和改进建议。
最多输出 3 个最重要的发现，每个发现修改不超过 5 个文件。"""

    def _parse_analysis(self, analysis: str) -> Dict:
        return {
            "success": True,
            "analysis": analysis,
            "changes_proposed": analysis.count("文件") if "文件" in analysis else 0,
        }

    async def apply_improvements(self, task_id: str, analysis: Dict) -> Dict:
        if not analysis.get("success"):
            return analysis

        branch_name = f"{self._branch_prefix}/{task_id[:8]}"
        if not self._git_create_branch(branch_name):
            return {"success": False, "error": "创建分支失败"}

        caps = await capability_pool.get_all()
        cap = caps[0] if caps else None
        if not cap:
            return {"success": False, "error": "没有可用的 AI 实例"}

        executor = role_registry.create_agent("executor", cap)
        executor.bind_context(task_id)

        source_files = {}
        for f in self._list_source_files():
            path = Path(__file__).parent.parent.parent / f["path"]
            if path.exists():
                source_files[f["path"]] = path.read_text(encoding="utf-8")

        patch_prompt = self._build_patch_prompt(analysis["analysis"], source_files)
        response = await executor.think(patch_prompt, temperature=0.2)

        patched = self._apply_patches(response, source_files)
        if not patched:
            return {"success": False, "error": "没有生成有效的修改"}

        for filepath, content in patched.items():
            full_path = Path(__file__).parent.parent.parent / filepath
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")

        commit_msg = f"self-improve: AI 自动改进 ({task_id[:8]})"
        self._git_commit(commit_msg)

        return {
            "success": True,
            "branch": branch_name,
            "files_changed": list(patched.keys()),
            "commit_message": commit_msg,
        }

    def _build_patch_prompt(self, analysis: str, source_files: Dict[str, str]) -> str:
        files_text = "\n\n".join(
            f"===== {path} =====\n{content[:2000]}"
            for path, content in list(source_files.items())[:10]
        )
        return f"""基于以下分析结果修改源代码：

{analysis}

当前文件内容：
{files_text}

请输出每个文件的修改。格式：
FILE: 相对路径
```python
修改后的完整文件内容
```

每个修改必须：
1. 是完整的文件内容（不是 diff）
2. 限制在最多 {self._max_files} 个文件
3. 不修改黑名单中的文件"""

    def _apply_patches(self, response: str, source_files: Dict[str, str]) -> Dict[str, str]:
        result = {}
        current_file = None
        current_content = []
        in_code = False

        for line in response.splitlines():
            if line.startswith("FILE:"):
                if current_file and current_content:
                    result[current_file] = "\n".join(current_content)
                current_file = line[5:].strip()
                current_content = []
                in_code = False
            elif "```" in line:
                in_code = not in_code
            elif in_code and current_file:
                current_content.append(line)

        if current_file and current_content:
            result[current_file] = "\n".join(current_content)

        blacklisted = [p for p in result if any(result[p].startswith(b) for b in self._blacklist)]
        for p in blacklisted:
            del result[p]

        allowed = {k: v for k, v in result.items() if k in source_files}
        if len(allowed) > self._max_files:
            allowed = dict(list(allowed.items())[:self._max_files])

        return allowed

    def _git_create_branch(self, branch_name: str) -> bool:
        try:
            base = Path(__file__).parent.parent.parent
            subprocess.run(["git", "checkout", "-b", branch_name], cwd=base, capture_output=True, timeout=10)
            return True
        except Exception as e:
            logger.error(f"创建分支失败: {e}")
            return False

    def _git_commit(self, message: str) -> bool:
        try:
            base = Path(__file__).parent.parent.parent
            subprocess.run(["git", "add", "-A"], cwd=base, capture_output=True, timeout=10)
            subprocess.run(["git", "commit", "-m", message], cwd=base, capture_output=True, timeout=10)
            return True
        except Exception as e:
            logger.error(f"提交失败: {e}")
            return False

    async def push_to_remote(self) -> bool:
        try:
            base = Path(__file__).parent.parent.parent
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=base, capture_output=True, text=True, timeout=10
            ).stdout.strip()
            if not branch or branch == "master":
                logger.warning("当前在 master 分支，不自动推送")
                return False
            subprocess.run(["git", "push", "-u", "origin", branch], cwd=base, capture_output=True, timeout=30)
            logger.info(f"已推送分支: {branch}")
            return True
        except Exception as e:
            logger.error(f"推送失败: {e}")
            return False


self_improver = SelfImprover()