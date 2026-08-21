"""自我改进引擎：分析源码 -> AI 生成修改 -> 分支提交 -> 可选推送。

职责划分：
- 模块常量：扫描模式、黑名单、内置回退提示词
- GitResult / _run_git：git 命令执行与结果封装
- SelfImprover：编排"分析 -> 改码 -> 提交 -> 推送"全流程
"""

import asyncio
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional

from jinja2 import Environment, FileSystemLoader
from loguru import logger

from app.engine.registry import role_registry
from app.llm.pool import capability_pool
from app.utils import get_prompt_template_dir

from app.core.config import config_manager  # noqa: F401  # 测试通过模块属性访问
from app.core.config import get

# ---------- 常量 ----------

_FILE_PATTERNS = (
    "app/**/*.py",
    "ui/**/*.py",
    "config/**/*.yaml",
    "config/**/*.j2",
    "config/**/*.json",
)
_MAX_FILE_SIZE = 50000
_PROTECTED_BRANCHES = ("master", "main")
_FILE_HEADER = re.compile(r"(?i)^FILE:\s*(.+?)\s*$")

_DEFAULT_BLACKLIST = [
    "config/config.yaml",
    "data/",
    "app/security/",
    "app/core/updater.py",
]

_ANALYSIS_FALLBACK_PROMPT = """你是一位资深的软件架构师，正在对自己的源码库（IReckon）做一次严谨的代码评审。评审目的是找出真正值得修改的高价值问题，并输出可执行的修改方案。

【源文件列表】（共 {total} 个）
{summary}

评审纪律：
1. 你只能看到文件清单（路径 + 大小），看不到代码内容。请依据路径命名、扩展名与项目结构常识推断代码职责，但禁止臆造清单之外的文件或并不存在的代码；拿不准的发现须标注"需人工确认"。
2. 每个发现必须可落地：指明文件路径、大致定位（类名/函数名/行号区间），并给出具体的修改思路与理由。
3. 宁缺毋滥：只报告值得修改的问题，不为凑数输出琐碎问题；按价值从高到低排列。

按价值从高到低优先寻找：
1. 潜在 bug：异常处理缺失、资源泄漏（文件/连接/线程未关闭）、异步与竞态、边界条件、None 与空输入、路径与编码问题
2. 正确性风险：复制粘贴未改干净、逻辑分支写错、变量遮蔽、条件漏判、单测与实现不一致
3. 维护性：明显重复代码、过度耦合、魔法数字、命名不一致、死代码
4. 性能与健壮性：低效循环、无界增长、无超时的网络/IO 调用

每条发现按以下格式输出：

## 发现 1：【一句话标题】
- 严重程度：高/中/低
- 置信度：高/中/低
- 文件：路径
- 定位：类/函数 或 行号区间（大致即可）
- 问题：为什么是问题、会造成什么后果
- 建议：具体的修改方案（改动范围、关键思路）

输出要求：
- 最多输出 3 个最有价值的发现
- 每个发现涉及的修改文件数不超过 {max_files} 个
- 全部使用中文；若没有值得修改的问题，只输出一行：无"""

_PATCH_FALLBACK_PROMPT = """你是一位资深软件工程师，正在把代码评审结论落到源码上。你的任务：在保持其他代码不变的前提下，对指定文件做最小、精确的修改。

【评审结果】
{analysis}

【待修改文件内容】
{files_text}

输出格式（严格遵守）：
FILE: 相对路径
```python
修改后的完整文件内容
```
每个文件都以 `FILE: 相对路径` 开头，代码放在 ``` 围栏内，文件之间用空行分隔。

修改纪律：
1. 只修改与评审结果直接相关的部分；其余代码必须逐字节保持原样，禁止顺手重构、重命名或调整格式。
2. 输出的是完整文件内容，不是 diff、不是摘要；禁止省略任何行或用省略号代替。
3. 文件必须保持完整可运行：禁止 TODO、占位符、未实现的函数签名。
4. 限制在最多 {max_files} 个文件；未出现在【待修改文件内容】中的文件一律不要输出。
5. 黑名单文件（config/config.yaml、data/、app/security/、app/core/updater.py 等）禁止修改。
6. 语言与注释风格与文件原有内容保持一致。"""


@dataclass(frozen=True)
class GitResult:
    """git 命令执行结果：returncode + 合并输出。"""

    returncode: int
    output: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _render_template(env: Environment, name: str, fallback: str, **kwargs) -> str:
    """渲染 jinja2 模板，失败时回退到内置文本。"""
    try:
        return env.get_template(name).render(**kwargs)  # type: ignore[no-any-return]  # jinja2 缺失时 stubs 为 Any
    except Exception as e:
        logger.warning(f"模板 {name} 渲染失败，使用内置默认: {e}")
        return fallback.format(**kwargs)


def _split_file_blocks(response: str) -> Dict[str, str]:
    """把 AI 输出切成 {路径: 代码块内容}；容忍缺少收尾围栏。"""
    blocks: Dict[str, str] = {}
    current_file: Optional[str] = None
    current_content: List[str] = []
    in_code = False

    for line in response.splitlines():
        m = _FILE_HEADER.match(line)
        if m:
            if current_file and current_content:
                blocks[current_file] = "\n".join(current_content)
            current_file = m.group(1).replace("\\", "/")
            current_content = []
            in_code = False
        elif line.strip().startswith("```"):
            in_code = not in_code
        elif in_code and current_file:
            current_content.append(line)

    if current_file and current_content:
        blocks[current_file] = "\n".join(current_content)
    return blocks


def _parse_analysis(analysis: str) -> Dict:
    m = re.search(r"(\d+)\s*个文件", analysis)
    count = (
        int(m.group(1)) if m else (analysis.count("文件") if "文件" in analysis else 0)
    )
    return {
        "success": True,
        "analysis": analysis,
        "changes_proposed": count,
    }


async def _get_executor(task_id: str):
    """优先挑选 coding+smart 标签的实例，其次回退到任意可用实例。"""
    cap = await capability_pool.find_best_match(required_tags=["coding", "smart"])
    if cap is None:
        caps = await capability_pool.get_all()
        cap = caps[0] if caps else None
    if cap is None:
        return None

    executor = role_registry.create_agent("executor", cap)
    if executor is None:
        return None

    executor.bind_context(task_id)
    return executor


class SelfImprover:
    """自我改进引擎：分析源码 -> AI 生成修改 -> 分支提交 -> 可选推送。"""

    def __init__(self):
        self._enabled = get("self_update.enabled", True)
        self._max_files = get("self_update.max_files_per_round", 5)
        self._branch_prefix = get("self_update.branch_prefix", "self-improve")
        self._jinja_env = Environment(  # nosec B701: 模板渲染 LLM 提示词纯文本，非 HTML 输出
            loader=FileSystemLoader(str(get_prompt_template_dir())),
            autoescape=False,
        )
        self._blacklist = set(get("self_update.file_blacklist", _DEFAULT_BLACKLIST))
        self._base_dir = Path(__file__).parent.parent.parent

    # ========== 对外 API ==========

    async def analyze(self, task_id: str) -> Dict:
        """让 AI 评审源码清单，输出高价值问题与修改方案。"""
        if not self._enabled:
            return self._fail("自我改进已关闭")

        files = self._list_source_files()
        if not files:
            return self._fail("没有可分析的源文件")

        executor = await _get_executor(task_id)
        if not executor:
            return self._fail("无法获取 Executor agent")

        try:
            analysis = await executor.think(
                self._build_analysis_prompt(files), temperature=0.3
            )
        except Exception as e:
            logger.error(f"自我改进分析失败: {e}")
            return self._fail(f"AI 分析失败: {e}")
        return _parse_analysis(analysis)

    async def apply_improvements(self, task_id: str, analysis: Dict) -> Dict:
        """把评审结论落地：建分支 -> AI 生成修改 -> 写入 -> 白名单提交。"""
        if not analysis.get("success") or not analysis.get("analysis"):
            return analysis

        branch_name = f"{self._branch_prefix}/{task_id[:8]}"
        if not await asyncio.to_thread(self._git_create_branch, branch_name):
            return self._fail("创建分支失败")

        executor = await _get_executor(task_id)
        if not executor:
            return self._fail("没有可用的 AI 实例")

        source_files = self._read_source_files()
        if not source_files:
            return self._fail("没有可读取的源文件")

        patch_prompt = self._build_patch_prompt(analysis["analysis"], source_files)
        try:
            response = await executor.think(patch_prompt, temperature=0.2)
        except Exception as e:
            logger.error(f"生成修改失败: {e}")
            return self._fail(f"AI 修改失败: {e}")

        patched = self._apply_patches(response, source_files)
        if not patched:
            return self._fail("没有生成有效的修改")

        try:
            self._write_files(patched)
        except OSError as e:
            logger.error(f"写入修改文件失败: {e}")
            return self._fail(f"写入文件失败: {e}")

        commit_msg = f"self-improve: AI 自动改进 ({task_id[:8]})"
        if not await asyncio.to_thread(self._git_commit, commit_msg):
            return self._fail("git 提交失败")

        return {
            "success": True,
            "branch": branch_name,
            "files_changed": list(patched.keys()),
            "commit_message": commit_msg,
        }

    async def push_to_remote(self) -> bool:
        """推送当前分支到远端；获取分支、受保护分支或推送失败均返回 False。"""
        res = await asyncio.to_thread(
            self._run_git, "rev-parse", "--abbrev-ref", "HEAD"
        )
        if not res.ok:
            logger.error(f"获取当前分支失败: {res.output}")
            return False

        branch = res.output.strip()
        if not branch or branch in _PROTECTED_BRANCHES:
            logger.warning(f"当前在 {branch or '未知'} 分支，不自动推送")
            return False

        res = await asyncio.to_thread(
            self._run_git, "push", "-u", "origin", branch, timeout=60
        )
        if not res.ok:
            logger.error(f"推送分支 {branch} 失败: {res.output[:300]}")
            return False
        logger.info(f"已推送分支: {branch}")
        return True

    # ========== 内部工具 ==========

    @staticmethod
    def _fail(message: str) -> Dict:
        return {"success": False, "error": message}

    # ---------- 源文件扫描 ----------

    def _list_source_files(self) -> List[Dict]:
        """扫描可分析的源文件清单；黑名单与超限文件一律跳过。"""
        files = []
        for pattern in _FILE_PATTERNS:
            for f in self._base_dir.glob(pattern):
                rel = str(f.relative_to(self._base_dir)).replace("\\", "/")
                if self._is_blacklisted(rel):
                    continue
                try:
                    size = f.stat().st_size
                except OSError as e:
                    logger.warning(f"读取文件信息失败 {rel}: {e}")
                    continue
                if size > _MAX_FILE_SIZE:
                    continue
                files.append({"path": rel, "size": size})
        return files

    def _is_blacklisted(self, rel: str) -> bool:
        """前缀/精确匹配黑名单；目录条目匹配其下所有文件。"""
        rel = rel.replace("\\", "/")
        for b in self._blacklist:
            b = b.rstrip("/")
            if rel == b or rel.startswith(b + "/"):
                return True
        return False

    def _read_source_files(self) -> Dict[str, str]:
        """读取清单内所有文件内容；单文件失败仅告警不中断。"""
        source_files = {}
        for f in self._list_source_files():
            path = self._base_dir / f["path"]
            try:
                source_files[f["path"]] = path.read_text(encoding="utf-8")
            except OSError as e:
                logger.warning(f"读取源文件失败 {f['path']}: {e}")
        return source_files

    # ---------- 提示词构建 ----------

    def _build_analysis_prompt(self, files: List[Dict]) -> str:
        summary = "\n".join(f"  {f['path']} ({f['size']} bytes)" for f in files[:30])
        if len(files) > 30:
            summary += f"\n  ... 及其他 {len(files) - 30} 个文件"
        return _render_template(
            self._jinja_env,
            "self_improve.j2",
            _ANALYSIS_FALLBACK_PROMPT,
            files=files[:30],
            total=len(files),
            max_files=self._max_files,
            summary=summary,
        )

    def _build_patch_prompt(self, analysis: str, source_files: Dict[str, str]) -> str:
        files_text = "\n\n".join(
            f"===== {path} =====\n{content[:2000]}"
            for path, content in list(source_files.items())[:10]
        )
        return _render_template(
            self._jinja_env,
            "self_improve_patch.j2",
            _PATCH_FALLBACK_PROMPT,
            analysis=analysis,
            files_text=files_text,
            max_files=self._max_files,
        )

    # ---------- 结果解析 ----------

    def _apply_patches(
        self, response: str, source_files: Dict[str, str]
    ) -> Dict[str, str]:
        """解析 AI 输出并过滤：黑名单/未知路径/空内容/无变化一律丢弃。"""
        patched = {}
        for path, content in _split_file_blocks(response).items():
            content = content.strip("\n")
            if self._accept_patch(path, content, source_files):
                patched[path] = content

        if len(patched) > self._max_files:
            logger.warning(f"修改文件数超过上限，截断为前 {self._max_files} 个")
            patched = dict(list(patched.items())[: self._max_files])
        return patched

    def _accept_patch(
        self, path: str, content: str, source_files: Dict[str, str]
    ) -> bool:
        if self._is_blacklisted(path):
            logger.warning(f"跳过黑名单文件: {path}")
            return False
        if path not in source_files:
            logger.warning(f"跳过不在源文件清单中的路径: {path}")
            return False
        if not content.strip():
            return False
        if content == source_files[path].rstrip("\n"):
            return False
        return True

    def _write_files(self, patched: Dict[str, str]) -> None:
        """把修改写入磁盘；目录不存在时自动创建。"""
        base_resolved = self._base_dir.resolve()
        for filepath, content in patched.items():
            full_path = (self._base_dir / filepath).resolve()
            if not full_path.is_relative_to(base_resolved):
                logger.warning(f"拒绝越界写入（路径穿越防护）: {filepath}")
                continue
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")

    # ---------- git 操作 ----------

    def _run_git(self, *args: str, timeout: int = 30) -> GitResult:
        """执行 git 命令；异常统一封装为 returncode=-1 的结果。"""
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=self._base_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            out = (getattr(proc, "stdout", None) or "") + (
                getattr(proc, "stderr", None) or ""
            )
            # 注意：只能 rstrip —— git status --porcelain 首行以空格开头（" M file"），
            # strip() 会吃掉该空格导致路径解析错位
            return GitResult(proc.returncode, out.rstrip())
        except Exception as e:
            logger.error(f"git {' '.join(args)} 执行失败: {e}")
            return GitResult(-1, str(e))

    def _git_create_branch(self, branch_name: str) -> bool:
        """创建改进分支；失败（如分支已存在）必须中止，绝不继续在当前分支提交。"""
        res = self._run_git("checkout", "-b", branch_name)
        if not res.ok:
            logger.error(f"创建分支 {branch_name} 失败: {res.output}")
            return False
        return True

    def _git_status_changed_paths(self) -> List[str]:
        """解析 git status --porcelain，返回已修改/新增文件路径列表。"""
        res = self._run_git("status", "--porcelain")
        if not res.ok:
            logger.error(f"git status 失败: {res.output}")
            return []

        paths = []
        for line in res.output.splitlines():
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

        res = self._run_git("add", "--", *allow)
        if not res.ok:
            logger.error(f"git add 失败: {res.output}")
            return False

        res = self._run_git("commit", "-m", message)
        if not res.ok:
            logger.error(f"git commit 失败: {res.output}")
            return False

        logger.info(f"已提交 {len(allow)} 个文件: {message}")
        return True


self_improver = SelfImprover()
