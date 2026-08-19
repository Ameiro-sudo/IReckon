from difflib import SequenceMatcher
from typing import List, Union, Dict
from loguru import logger
from app.core.config import config_manager

get = config_manager.get


class LoopDetector:
    def __init__(self):
        self.max_rounds = get("task_defaults.loop_detection_max_rounds", 8)
        self.similarity_threshold = get("task_defaults.loop_similarity_threshold", 0.95)
        # 大文本性能保护：每轮输出只比较前 N 个字符
        self.max_compare_chars = 20000

    async def check_loop(
        self,
        task_id: str,
        recent_outputs: Union[List[str], Dict[int, List[str]]],
    ) -> bool:
        """按阶段比较输出，检测死循环。

        兼容旧接口：直接传 List[str] 时视为单个阶段；新调用方传
        Dict[阶段索引, List[str]]，各阶段独立判定。
        """
        if isinstance(recent_outputs, dict):
            for phase_idx, outputs in recent_outputs.items():
                if self._check_phase(task_id, outputs):
                    return True
            return False
        return self._check_phase(task_id, recent_outputs)

    def _check_phase(self, task_id: str, outputs: List[str]) -> bool:
        if len(outputs) < self.max_rounds:
            return False

        recent = [
            (o or "")[: self.max_compare_chars] for o in outputs[-self.max_rounds :]
        ]
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
