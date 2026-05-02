#!/usr/bin/env python3
import asyncio, signal
from core.logger import setup_logging, logger
from core.db import db
from core.config_manager import config_manager
from ai.capability_pool import capability_pool
from workflow.task_manager import task_manager
from workflow.idle_learner import idle_loop
from web.websocket import log_consumer
from tools.registry import register_builtin_tools

class IReckonApp:
    def __init__(self):
        self._shutdown_event = asyncio.Event()
        self._tasks = []

    async def initialize(self):
        setup_logging()
        logger.info(f"启动 {config_manager.get('system.name')} v{config_manager.get('system.version')}")
        await db.connect()
        await capability_pool.refresh()
        await register_builtin_tools()
        self._tasks.append(asyncio.create_task(idle_loop.run()))
        self._tasks.append(asyncio.create_task(log_consumer()))
        logger.info("系统初始化完成")

    async def shutdown(self):
        logger.info("正在关闭系统...")
        self._shutdown_event.set()
        for task in self._tasks:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
        await db.close()
        logger.info("系统已关闭")

async def start_backend():
    import uvicorn
    config = uvicorn.Config("web.api:app", host="0.0.0.0", port=8000, log_level="info", loop="asyncio")
    logger.info(f"后台 API 服务已启动 -> http://localhost:{8000}/docs")
    await uvicorn.Server(config).serve()

async def main():
    app = IReckonApp()
    await app.initialize()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try: loop.add_signal_handler(sig, lambda: asyncio.create_task(app.shutdown()))
        except NotImplementedError: pass
    backend_task = asyncio.create_task(start_backend())
    try: await app._shutdown_event.wait()
    finally:
        backend_task.cancel()
        try: await backend_task
        except asyncio.CancelledError: pass
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())