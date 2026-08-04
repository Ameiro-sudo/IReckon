#!/usr/bin/env python3
"""
IReckon 主入口文件 (๑•̀ᴗ-)✧
项目的启动点，整合所有模块让系统跑起来～
"""

import asyncio, io, logging, os, signal, socket, subprocess, sys, webbrowser

# 让输出更乖，不闹脾气～ (防止编码问题)
os.environ["UVICORN_ACCESS_LOGGING"] = "0"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
logging.basicConfig(handlers=[], level=logging.WARNING)

# 导入各个模块，它们都是系统的小零件～
from app.core.logger import setup_logging, logger
from app.core.database import db
from app.core.config import config_manager
from app.core.updater import updater
from app.llm.client import capability_pool
from app.engine.tasks import task_manager
from app.engine.learner import idle_loop
from app.web.ws import log_consumer
from app.tools.registry import register_builtin_tools


def _get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return None

class IReckonApp:
    """IReckon 应用主类，统筹管理整个系统～"""
    
    def __init__(self):
        self._shutdown_event = asyncio.Event()  # 关闭信号灯～
        self._tasks = []                          # 存放后台任务们
        self._frontend_proc = None                # 前端进程（Vue酱～）

    async def initialize(self):
        """初始化所有组件，系统要开始工作啦！"""
        setup_logging()
        logger.info(f"启动 {config_manager.get('system.name')} v{config_manager.get('system.version')}")
        
        await self._check_update()        # 检查更新（看看有没有新版本呀～）
        await db.connect()                # 连接数据库
        await capability_pool.refresh()   # 刷新AI能力池
        await register_builtin_tools()    # 注册内置工具
        
        # 启动后台任务们～
        self._tasks.append(asyncio.create_task(idle_loop.run()))    # 空闲学习loop
        self._tasks.append(asyncio.create_task(log_consumer()))     # 日志消费者
        
        # 非打包模式（源码运行）时启动独立前端进程
        if not getattr(sys, 'frozen', False):
            self._start_frontend()
        logger.info("系统初始化完成")

    def _start_frontend(self):
        """启动 Vue 前端界面～"""
        root = os.path.dirname(os.path.abspath(__file__))
        frontend_dir = os.path.join(root, "frontend")
        
        # 检查npm是否可用
        try:
            subprocess.run(["npm", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("npm未安装，前端无法启动喵～")
            return
        
        # 检查node_modules是否存在，不存在则安装
        if not os.path.exists(os.path.join(frontend_dir, "node_modules")):
            logger.info("正在安装前端依赖...")
            try:
                subprocess.run(
                    ["npm", "install"],
                    cwd=frontend_dir,
                    capture_output=True,
                    check=True
                )
            except subprocess.CalledProcessError as e:
                logger.warning(f"前端依赖安装失败: {e}")
                return
        
        # 启动Vue前端
        logger.info("启动Vue前端...")
        self._frontend_proc = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=frontend_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
    
    async def _check_update(self):
        """检查更新，看看有没有新版本可以玩呀～"""
        if not updater.should_check():
            return
        updater.mark_checked()
        version = await updater.check()
        if version:
            logger.info(f"发现新版本 v{version}，请运行 python scripts/update.py 进行更新")

    async def shutdown(self):
        """优雅地关闭系统，各回各家各找各妈～"""
        logger.info("正在关闭系统...")
        self._shutdown_event.set()
        
        # 取消所有后台任务
        for task in self._tasks:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
        
        # 关闭前端进程
        if self._frontend_proc:
            self._frontend_proc.terminate()
            try: self._frontend_proc.wait(timeout=5)
            except: self._frontend_proc.kill()
        
        await db.close()
        logger.info("系统已关闭")


async def start_backend():
    """启动 FastAPI 后端服务～"""
    import uvicorn
    
    # 把 uvicorn 的日志关掉，让它安静如鸡～
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        log = logging.getLogger(name)
        log.handlers = []
        log.propagate = False
    
    host = config_manager.get("server.host", "0.0.0.0")
    port = config_manager.get("server.port", 8000)
    
    config = uvicorn.Config("app.web.api:app", host=host, port=port, log_level="warning", loop="asyncio", access_log=False)
    
    # 打印启动信息，超酷炫的！
    lan_ip = _get_lan_ip()
    lan_line = f"  局域网访问  http://{lan_ip}:{port}\n" if lan_ip else ""
    logger.info(f"\n{'='*46}\n  IReckon v{config_manager.get('system.version')} 已启动\n{'='*46}\n"
                f"  后端 API   http://{host}:{port}\n"
                f"  交互文档   http://{host}:{port}/docs\n"
                f"  前端界面   http://{host}:{port}\n"
                f"{lan_line}"
                f"  健康检查   http://{host}:{port}/api/health\n"
                f"{'='*46}")
    
    webbrowser.open(f"http://{host}:{port}")  # 自动打开浏览器，懒人福利！
    await uvicorn.Server(config).serve()


async def main():
    """主函数，一切的开始！"""
    app = IReckonApp()
    await app.initialize()
    
    # 设置信号处理，按 Ctrl+C 也可以优雅退出哦～
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try: loop.add_signal_handler(sig, lambda: asyncio.create_task(app.shutdown()))
        except NotImplementedError: pass
    
    # 启动后端，然后等待关闭信号
    backend_task = asyncio.create_task(start_backend())
    try: await app._shutdown_event.wait()
    finally:
        backend_task.cancel()
        try: await backend_task
        except asyncio.CancelledError: pass
        await app.shutdown()


if __name__ == "__main__":
    # 发射！启动！
    asyncio.run(main())