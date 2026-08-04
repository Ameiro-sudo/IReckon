#!/usr/bin/env python3
import asyncio, signal
from app.core.logger import setup_logging, logger
from app.core.database import db
from app.core.config import config_manager
from app.core.updater import updater
from app.llm.client import capability_pool
from app.engine.tasks import task_manager
from app.engine.learner import idle_loop
from app.web.ws import log_consumer
from app.tools.registry import register_builtin_tools

class IReckonApp:
    def __init__(self):
        self._shutdown_event = asyncio.Event()
        self._tasks = []

    async def initialize(self):
        setup_logging()
        logger.info(f"启动 {config_manager.get('system.name')} v{config_manager.get('system.version')}")
        await self._check_update()
        await db.connect()
        await capability_pool.refresh()
        await register_builtin_tools()
        self._tasks.append(asyncio.create_task(idle_loop.run()))
        self._tasks.append(asyncio.create_task(log_consumer()))
        logger.info("系统初始化完成")

    async def _check_update(self):
        if not updater.should_check():
            return
        updater.mark_checked()
        version = await updater.check()
        if version:
            logger.info(f"发现新版本 v{version}，请运行 python scripts/update.py 进行更新")

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
    host = config_manager.get("server.host", "0.0.0.0")
    port = config_manager.get("server.port", 8000)
    log_level = config_manager.get("server.log_level", "info")
    config = uvicorn.Config("app.web.api:app", host=host, port=port, log_level=log_level, loop="asyncio")
    logger.info(f"后台 API 服务已启动 -> http://{host}:{port}/docs")
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