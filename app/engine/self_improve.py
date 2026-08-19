import asyncio
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import List, Dict, Optional, Tuple
from loguru import logger
from jinja2 import Environment, FileSystemLoader

from app.core.config import config_manager
from app.engine.registry import role_registry
from app.llm.pool import capability_pool

get = config_manager.get


class SelfImprover:
    def __init__(self):
        self._enabled = get("self_update.enabled", True)
        self._max_files = get("self_update.max_files_per_round", 5)
        self._branch_prefix = get(
            "self_update.branch_prefix", "self-improve"
        )
        template_dir = Path(__file__).parent.parent.parent / "config" / "prompts"
        if template_dir.exists():
            self._jinja_env = Environment(
                loader=FileSystemLoader(str(template_dir)), autoescape=True
            )
        else:
            self._jinja_env = None
        self._blacklist = set(
            get(
                "self_update.file_blacklist",
                ["config/config.yaml", "data/", "app/security/", "app/core/updater.py"],
            )
        )

    async def analyze(self, task_id: str) -> Dict:
        if not self._enabled:
            return {"success": False, "error": "自我改进已关闭"}

        files = self._list_source_files()
        if not files:
            return {"success": False, "error": "没有可分析的源文件"}

        executor = await self._get_executor(task_id)
        if not executor:
            return {"success": False, "error": "无法获取 Executor agent"}

        analysis_prompt = self._build_analysis_prompt(files)
        analysis = await executor.think(analysis_prompt, temperature=0.3)
        return self._parse_analysis(analysis)

    async def _get_executor(self, task_id: str):
        supported_tags = get("ai_pool.instances", [])
        if supported_tags:
            cap = await capability_pool.find_best_match(
                required_tags=["coding", "smart"]
            )
        else:
            caps = await capability_pool.get_all()
            cap = caps[0] if caps else None

        if not cap:
            return None

        executor = role_registry.create_agent("executor", cap)
        if executor is None:
            return None

        executor.bind_context(task_id)
        return executor

    def _list_source_files(self) -> List[Dict]:
        base = Path(__file__).parent.parent.parent
        files = []
        for pattern in [
            "app/**/*.py",
            "ui/**/*.py",
            "config/**/*.yaml",
            "config/**/*.j2",
            "config/**/*.json",
        ]:
            for f in base.glob(pattern):
                rel = str(f.relative_to(base)).replace("\\", "/")
                if self._is_blacklisted(rel):
                    continue
                if f.stat().st_size > 50000:
                    continue
                files.append({"path": rel, "size": f.stat().st_size})
        return files

    def _is_blacklisted(self, rel: str) -> bool:
        rel = rel.replace("\\", "/")
        for b in self._blacklist:
            b = b.rstrip("/")
            if rel == b or rel.startswith(b + "/"):
                return True
        return False

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
        m = re.search(r"(\d+)\s*个文件", analysis)
        count = int(m.group(1)) if m else (analysis.count("文件") if "文件" in analysis else 0)
        return {
            "success": True,
            "analysis": analysis,
            "changes_proposed": count,
        }

    async def apply_improvements(self, task_id: str, analysis: Dict) -> Dict:
        if not analysis.get("success"):
            return analysis

        branch_name = f"{self._branch_prefix}/{task_id[:8]}"
        if not await asyncio.to_thread(self._git_create_branch, branch_name):
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
        if not await asyncio.to_thread(self._git_commit, commit_msg):
            return {"success": False, "error": "git 提交失败"}

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

    def _apply_patches(
        self, response: str, source_files: Dict[str, str]
    ) -> Dict[str, str]:
        result = {}
        current_file: Optional[str] = None
        current_content: List[str] = []
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

        blacklisted = [p for p in result if self._is_blacklisted(p)]
        for p in blacklisted:
            del result[p]

        allowed = {k: v for k, v in result.items() if k in source_files}
        if len(allowed) > self._max_files:
            allowed = dict(list(allowed.items())[: self._max_files])

        return allowed

    def _run_git(self, *args: str, timeout: int = 30) -> Tuple[int, str]:
        """执行 git 命令，返回 (returncode, 合并输出)；异常返回 (-1, 错误信息)。"""
        base = Path(__file__).parent.parent.parent
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=base,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            out = (getattr(proc, "stdout", None) or "") + (
                getattr(proc, "stderr", None) or ""
            )
            # 注意：只能 rstrip —— git status --porcelain 首行以空格开头（" M file"），
            # strip() 会吃掉该空格导致路径解析错位
            return proc.returncode, out.rstrip()
        except Exception as e:
            logger.error(f"git {' '.join(args)} 执行失败: {e}")
            return -1, str(e)

    def _git_create_branch(self, branch_name: str) -> bool:
        """创建改进分支；失败（如分支已存在）必须中止，绝不继续在当前分支提交。"""
        rc, out = self._run_git("checkout", "-b", branch_name)
        if rc != 0:
            logger.error(f"创建分支 {branch_name} 失败: {out}")
            return False
        return True

    def _git_status_changed_paths(self) -> List[str]:
        """解析 git status --porcelain，返回已修改/新增文件路径列表。"""
        rc, out = self._run_git("status", "--porcelain")
        if rc != 0:
            logger.error(f"git status 失败: {out}")
            return []
        paths = []
        for line in out.splitlines():
            if len(line) < 4:
                continue
            p = line[3:].strip()
            # 重命名格式: R  old -> new，取新路径
            if " -> " in p:
                p = p.split(" -> ")[-1].strip()
            if p:
                paths.append(p)
        return paths

    def _is_excluded_path(self, rel: str) -> bool:
        """提交白名单过滤：黑名单 + data/ + *.key + *.db + .env 一律排除。"""
        p = PurePosixPath(rel.replace("\\", "/"))
        if self._is_blacklisted(rel):
            return True
        if p.parts and p.parts[0] == "data":
            return True
        if any(part == ".env" for part in p.parts):
            return True
        if p.suffix in (".key", ".db"):
            return True
        return False

    def _git_commit(self, message: str) -> bool:
        """白名单提交：仅 add 黑名单之外、且未排除（data/、*.key、*.db、.env）的文件。"""
        changed = self._git_status_changed_paths()
        allow = [p for p in changed if not self._is_excluded_path(p)]
        if not allow:
            logger.warning("没有符合白名单的变更文件，跳过提交")
            return False
        for p in allow:
            rc, out = self._run_git("add", "--", p)
            if rc != 0:
                logger.error(f"git add {p} 失败: {out}")
                return False
        rc, out = self._run_git("commit", "-m", message)
        if rc != 0:
            logger.error(f"git commit 失败: {out}")
            return False
        logger.info(f"已提交 {len(allow)} 个文件: {message}")
        return True

    async def push_to_remote(self) -> bool:
        """推送当前分支到远端；获取分支或推送失败均返回 False。"""
        try:
            base = Path(__file__).parent.parent.parent
            proc = await asyncio.to_thread(
                subprocess.run,
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=base,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if getattr(proc, "returncode", -1) != 0:
                logger.error("获取当前分支失败")
                return False
            branch = (getattr(proc, "stdout", None) or "").strip()
            if not branch or branch == "master":
                logger.warning("当前在 master 分支，不自动推送")
                return False
            proc2 = await asyncio.to_thread(
                subprocess.run,
                ["git", "push", "-u", "origin", branch],
                cwd=base,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if getattr(proc2, "returncode", -1) != 0:
                logger.error(
                    f"推送分支 {branch} 失败: {(getattr(proc2, 'stderr', None) or '')[:300]}"
                )
                return False
            logger.info(f"已推送分支: {branch}")
            return True
        except Exception as e:
            logger.error(f"推送失败: {e}")
            return False


self_improver = SelfImprover()
