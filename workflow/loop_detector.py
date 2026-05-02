"""
死循环检测器
分析连续 N 轮执行 AI 的输出内容，计算文本相似度，超阈值则暂停任务
"""

from difflib import SequenceMatcher
from typing import List
from loguru import logger
from core.config_manager import config_manager


class LoopDetector:
    def __init__(self):
        self.max_rounds = config_manager.get("task_defaults.loop_detection_max_rounds", 5)
        self.similarity_threshold = config_manager.get("task_defaults.loop_similarity_threshold", 0.9)

    async def check_loop(self, task_id: str, recent_outputs: List[str]) -> bool:
        """返回 True 表示检测到死循环"""
        if len(recent_outputs) < self.max_rounds:
            return False

        recent = recent_outputs[-self.max_rounds:]
        for i in range(len(recent) - 1):
            for j in range(i + 1, len(recent)):
                ratio = SequenceMatcher(None, recent[i], recent[j]).ratio()
                if ratio > self.similarity_threshold:
                    logger.warning(
                        f"任务 {task_id} 检测到死循环: 输出相似度 {ratio:.2f}"
                    )
                    return True
        return False


loop_detector = LoopDetector()