#!/usr/bin/env python3
"""快速功能测试：创建并运行一个简单任务"""
import sys, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.logger import setup_logging, logger
from app.core.database import db
from app.llm.pool import capability_pool
from app.engine.tasks import task_manager


async def run_test():
    setup_logging()
    await db.connect()
    await capability_pool.refresh()
    caps = await capability_pool.get_all()
    if not caps:
        logger.error("没有可用 AI 实例，测试终止")
        return False

    logger.info("创建测试任务...")
    task_id = await task_manager.create_task("用 Python 写一个 hello world 函数并返回字符串")
    logger.info(f"启动任务 {task_id} ...")
    await task_manager.start_task(task_id)

    timeout = 300
    elapsed = 0
    while task_id in task_manager._running and elapsed < timeout:
        await asyncio.sleep(2)
        elapsed += 2
        logger.info(f"等待任务完成... ({elapsed}s)")

    if task_id not in task_manager._running:
        row = await db.fetch_one("SELECT status FROM tasks WHERE task_id = ?", (task_id,))
        status = row[0] if row else "未知"
        if status == 'completed':
            logger.info("✓ 测试通过：任务成功完成")
            return True
        else:
            logger.error(f"✗ 测试失败：任务状态为 {status}")
            return False
    else:
        logger.error("✗ 测试超时")
        return False


if __name__ == "__main__":
    asyncio.run(run_test())