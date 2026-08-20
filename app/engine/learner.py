import asyncio, re, time
from datetime import datetime, timezone
from typing import List, Optional
from loguru import logger
from app.llm.pool import capability_pool
from app.agents.learner import LearnerAgent

from app.core.config import get

# GitHub Trending 页面上的非仓库链接前缀（用户/组织名不会是这些词）
_NON_REPO_PREFIXES = (
    "topics",
    "collections",
    "login",
    "signup",
    "explore",
    "features",
    "settings",
    "about",
    "sponsors",
    "pricing",
    "search",
    "join",
    "events",
    "marketplace",
    "orgs",
    "site",
    "customer-stories",
)


async def _fetch_trending_repos(url: str) -> List[str]:
    """抓取 GitHub Trending 页面，提取 <owner>/<repo> 候选列表（前 20 个）。"""
    try:
        import httpx

        async with httpx.AsyncClient(
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (IReckon-Learner)"},
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            html = resp.text
    except Exception as e:
        logger.warning(f"抓取 {url} 失败，降级为直接传 URL 文本: {e}")
        return []
    candidates = []
    for match in re.findall(r'href="/([^/"]+/[^/"]+)"', html):
        owner, _, repo = match.partition("/")
        if not owner or not repo:
            continue
        if owner in _NON_REPO_PREFIXES:
            continue
        if repo.endswith(".md") or "/" in repo:
            continue
        if match not in candidates:
            candidates.append(match)
        if len(candidates) >= 20:
            break
    return candidates


class IdleLearningLoop:
    def __init__(self):
        self.idle_trigger_minutes = get("learning.idle_trigger_minutes", 30)
        self._last_task_time = time.time()
        self._learning = False
        self._learn_count = 0
        self._last_reset_date = datetime.now(timezone.utc).date()
        self.max_learn_sessions_per_day = 10
        # 持有后台学习任务引用，便于 shutdown 时取消
        self._learning_task: Optional["asyncio.Task"] = None

    async def run(self):
        logger.info(f"空闲学习循环已启动，触发间隔: {self.idle_trigger_minutes} 分钟")
        while True:
            await asyncio.sleep(60)
            today = datetime.now(timezone.utc).date()
            if today != self._last_reset_date:
                self._learn_count = 0
                self._last_reset_date = today
            if self._learning:
                continue
            if (
                time.time() - self._last_task_time > self.idle_trigger_minutes * 60
                and self._learn_count < self.max_learn_sessions_per_day
            ):
                logger.info(
                    f"空闲学习 ({self._learn_count + 1}/{self.max_learn_sessions_per_day})"
                )
                self._learning_task = asyncio.create_task(self._start_learning())

    def cancel(self):
        """取消正在进行的后台学习任务（shutdown 时调用）。"""
        if self._learning_task:
            self._learning_task.cancel()
            self._learning_task = None
            logger.info("已取消空闲学习任务")

    async def _start_learning(self):
        self._learning = True
        self._learn_count += 1
        try:
            cap = await capability_pool.find_best_match(
                required_tags=["cheap"], prefer_cheapest=True
            )
            if not cap:
                all_caps = await capability_pool.get_all()
                if not all_caps:
                    return
                cap = all_caps[0]
            learner = LearnerAgent(cap)
            learner.bind_context("idle-learn")
            # 对白名单里的每个 URL 都处理，而不是只取第一个
            for url in get(
                "learning.source_whitelist", ["https://github.com/trending"]
            ):
                repos = await _fetch_trending_repos(url)
                if repos:
                    content = (
                        "候选仓库列表（从页面提取）：\n"
                        + "\n".join(f"- {r}" for r in repos)
                        + "\n\n分析 GitHub Trending 高星项目，提炼设计模式。"
                    )
                else:
                    # 抓取失败降级为原行为：直接传 URL 文本
                    content = "分析 GitHub Trending 高星项目，提炼设计模式。"
                result = await learner.learn_from_source(url, content)
                logger.info(
                    f"学习完成: {result.get('summary', '')[:100]}... (来源: {url})"
                )
        except Exception as e:
            logger.error(f"学习异常: {e}")
        finally:
            self._learning = False
            self._learning_task = None

    def notify_task_started(self):
        self._last_task_time = time.time()


idle_loop = IdleLearningLoop()
