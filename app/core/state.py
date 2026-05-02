import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import aiofiles
from loguru import logger

from .config import config_manager


class StateManager:
    def __init__(self, task_id: str):
        self.task_id = task_id
        data_dir = Path(config_manager.get("system.data_dir", "./data"))
        self.states_dir = data_dir / "states" / task_id
        self.states_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_interval = config_manager.get("persistence.snapshot_interval_seconds", 60)
        self.max_snapshots = config_manager.get("persistence.max_snapshots_per_task", 20)

    def _default_serializer(self, obj: Any, depth: int = 0) -> Any:
        if depth > 5:
            return str(obj)

        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Path):
            return str(obj)
        if hasattr(obj, "to_dict") and callable(obj.to_dict):
            return obj.to_dict()
        if hasattr(obj, "__dict__"):
            result = {}
            for k, v in vars(obj).items():
                if not k.startswith("_"):
                    result[k] = self._default_serializer(v, depth + 1)
            return result
        raise TypeError(f"Type {type(obj)} not serializable")

    async def save_snapshot(self, state: Dict[str, Any]) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        snapshot_file = self.states_dir / f"snapshot_{timestamp}.json"

        state_copy = state.copy()
        state_copy["_meta"] = {
            "task_id": self.task_id,
            "timestamp": timestamp,
            "utc_time": datetime.now(timezone.utc).isoformat()
        }

        try:
            json_str = json.dumps(
                state_copy,
                default=lambda o: self._default_serializer(o),
                ensure_ascii=False,
                indent=2
            )
        except TypeError as e:
            logger.error(f"状态序列化失败: {e}")
            json_str = json.dumps({
                "_meta": state_copy["_meta"],
                "error": "State serialization failed"
            })

        async with aiofiles.open(snapshot_file, "w", encoding="utf-8") as f:
            await f.write(json_str)

        logger.debug(f"状态快照已保存: {snapshot_file}")

        snapshots = sorted(self.states_dir.glob("snapshot_*.json"))
        if len(snapshots) > self.max_snapshots:
            for old in snapshots[:-self.max_snapshots]:
                old.unlink()

    async def load_latest_snapshot(self) -> Optional[Dict[str, Any]]:
        snapshots = sorted(self.states_dir.glob("snapshot_*.json"))
        if not snapshots:
            return None

        latest = snapshots[-1]
        try:
            async with aiofiles.open(latest, "r", encoding="utf-8") as f:
                content = await f.read()
            state = json.loads(content)
            logger.info(f"从快照恢复任务状态: {latest}")
            return state
        except json.JSONDecodeError as e:
            logger.error(f"快照文件损坏: {latest}, 错误: {e}")
            return None
        except Exception as e:
            logger.error(f"加载快照失败: {e}")
            return None

    async def cleanup(self) -> None:
        try:
            await asyncio.to_thread(shutil.rmtree, self.states_dir, ignore_errors=True)
            logger.info(f"已清理任务状态目录: {self.states_dir}")
        except Exception as e:
            logger.warning(f"清理状态目录失败: {e}")
