import asyncio, time
from datetime import datetime
from loguru import logger
from core.config_manager import config_manager
from ai.capability_pool import capability_pool
from ai.roles.learner import LearnerAgent

class IdleLearningLoop:
    def __init__(self):
        self.idle_trigger_minutes = config_manager.get("learning.idle_trigger_minutes",30)
        self._last_task_time = time.time()
        self._learning = False
        self._learn_count = 0
        self._last_reset_date = datetime.utcnow().date()
        self.max_learn_sessions_per_day = 10

    async def run(self):
        logger.info(f"空闲学习循环已启动，触发间隔: {self.idle_trigger_minutes} 分钟")
        while True:
            await asyncio.sleep(60)
            today = datetime.utcnow().date()
            if today != self._last_reset_date:
                self._learn_count = 0; self._last_reset_date = today
            if self._learning: continue
            if time.time()-self._last_task_time > self.idle_trigger_minutes*60 and self._learn_count<self.max_learn_sessions_per_day:
                logger.info(f"空闲学习 ({self._learn_count+1}/{self.max_learn_sessions_per_day})")
                asyncio.create_task(self._start_learning())

    async def _start_learning(self):
        self._learning=True; self._learn_count+=1
        try:
            cap = await capability_pool.find_best_match(required_tags=["cheap"], prefer_cheapest=True)
            if not cap:
                all_caps = await capability_pool.get_all()
                if not all_caps: return
                cap = all_caps[0]
            learner = LearnerAgent(cap); learner.bind_context("idle-learn")
            url = config_manager.get("learning.source_whitelist",["https://github.com/trending"])[0]
            result = await learner.learn_from_source(url, "分析 GitHub Trending 高星项目，提炼设计模式。")
            logger.info(f"学习完成: {result.get('summary','')[:100]}...")
        except Exception as e: logger.error(f"学习异常: {e}")
        finally: self._learning=False

    def notify_task_started(self): self._last_task_time = time.time()

idle_loop = IdleLearningLoop()