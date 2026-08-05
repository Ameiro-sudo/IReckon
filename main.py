#!/usr/bin/env python3
"""
IReckon 主入口文件 (๑•̀ᴗ-)✧
项目的启动点，整合所有模块让系统跑起来～
"""

import asyncio, io, logging, os, signal, socket, subprocess, sys, time, webbrowser, shutil

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
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        if s is not None:
            s.close()

class IReckonApp:
    """IReckon 应用主类，统筹管理整个系统～"""
    
    def __init__(self):
        self._shutdown_event = asyncio.Event()  # 关闭信号灯～
        self._tasks = []                          # 存放后台任务们
        self._frontend_proc = None                # 前端进程（Vue酱～）
        self._shutdown_started = False            # 避免重复关闭

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

        npm_path = shutil.which("npm")
        npx_path = shutil.which("npx")
        if npm_path is None and npx_path is None:
            logger.warning("npm/npx 未安装或不可用，前端无法启动喵～")
            return

        if not os.path.exists(os.path.join(frontend_dir, "node_modules")):
            logger.info("正在安装前端依赖...")
            cmd = ["npm", "install"] if npm_path else ["npx", "npm", "install"]
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=frontend_dir,
                    capture_output=True,
                    text=True,
                    check=True
                )
                logger.info(proc.stdout)
            except subprocess.CalledProcessError as e:
                logger.warning(f"前端依赖安装失败: {e.returncode} {e.stderr}")
                return

        # 启动Vue前端（优先 npm run dev）
        logger.info("启动Vue前端...")
        tried = []
        cmds = [["npm", "run", "dev"], ["npx", "vite", "--host", "127.0.0.1", "--port", "3000"]]
        for cmd in cmds:
            if cmd[0] == "npm" and npm_path is None:
                continue
            if cmd[0] == "npx" and npx_path is None:
                continue
            try:
                self._frontend_proc = subprocess.Popen(
                    cmd,
                    cwd=frontend_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                logger.info(f"前端已启动: {' '.join(cmd)}")
                return
            except (FileNotFoundError, OSError) as e:
                tried.append((cmd, str(e)))

        logger.warning(f"前端启动失败，尝试命令: {tried}")
        self._frontend_proc = None
    
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
        if self._shutdown_started:
            return
        self._shutdown_started = True

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
            except Exception:
                self._frontend_proc.kill()
        
        await db.close()
        logger.info("系统已关闭")


async def start_backend(shutdown_event: asyncio.Event):
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
    logger.info(f"\n{'=' * 46}\n  IReckon v{config_manager.get('system.version')} 已启动\n{'=' * 46}\n"
                f"  后端 API   https://{host}:{port}\n"
                f"  交互https://tp://{host}:{port}/docs\n"
                f"  前端界面   http://{host}:{port}\n"
                f"{lan_line}"
                f"  健康检查   http://{host}:{port}/api/health\n"
                f"{'=' * 46}")
    
    if config_manager.get("server.open_browser", False):
        webbrowser.open(f"http://{host}:{port}")  # 自动打开浏览器，懒人福利！
    try:
        await uvicorn.Server(config).serve()
    except SystemExit as exc:
        logger.warning(f"uvicorn exited with code {exc.code}")
    except Exception:
        logger.exception("启动后端服务时发生异常")
    finally:
        shutdown_event.set()


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
    backend_task = asyncio.create_task(start_backend(app._shutdown_event))
    backend_task.add_done_callback(lambda task: app._shutdown_event.set() if not app._shutdown_event.is_set() else None)
    try:
        await app._shutdown_event.wait()
    finally:
        if not backend_task.done():
            backend_task.cancel()
            try:
                await backend_task
            except asyncio.CancelledError:
                pass
            except SystemExit as exc:
                logger.warning(f"后端任务退出 SystemExit: {exc.code}")
        await app.shutdown()


if __name__ == "__main__":
    # 发射！启动！
    asyncio.run(main())