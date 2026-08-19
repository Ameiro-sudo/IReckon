#!/usr/bin/env python3
"""
IReckon 主入口文件 
项目的启动点，整合所有模块让系统跑起来～
"""

import asyncio
import io
import os
import shutil
import signal
import socket
import subprocess
import sys
import webbrowser

# 统一输出编码为 UTF-8，防止 Windows 控制台/重定向时中文乱码
os.environ["UVICORN_ACCESS_LOGGING"] = "0"


def _utf8_stream(stream):
    """确保输出流使用 UTF-8 编码。

    优先就地 reconfigure（TextIOWrapper 均支持），避免重新包装导致底层
    缓冲被重复包裹而失效（例如 pytest 捕获流）。
    """
    try:
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        return stream
    except Exception:
        try:
            if stream is not None and hasattr(stream, "buffer"):
                return io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    return stream


sys.stdout = _utf8_stream(sys.stdout)
sys.stderr = _utf8_stream(sys.stderr)

# 导入各个模块，它们都是系统的小零件～
from app.core.logger import setup_logging, log_banner, logger
from app.core.database import db
from app.core.config import config_manager
from app.core.updater import updater
from app.llm.pool import capability_pool
from app.engine.learner import idle_loop
from app.web.push import log_consumer
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


async def _check_update():
    """检查更新，看看有没有新版本可以玩呀～"""
    if not updater.should_check():
        return
    updater.mark_checked()
    version = await updater.check()
    if version:
        logger.info(f"发现新版本 v{version}，请运行 python scripts/update.py 进行更新")


class IReckonApp:
    """IReckon 应用主类，统筹管理整个系统～"""
    
    def __init__(self):
        self._shutdown_event = asyncio.Event()  # 关闭信号灯～
        self._tasks = []                          # 存放后台任务们
        self._frontend_proc = None                # 前端进程（Vue酱～）
        self._shutdown_started = False            # 避免重复关闭
        self._server = None                       # 后端 uvicorn Server 实例

    async def initialize(self):
        """初始化所有组件，系统要开始工作啦！"""
        setup_logging()
        logger.info(f"启动 {config_manager.get('system.name')} v{config_manager.get('system.version')}")
        
        await _check_update()        # 检查更新（看看有没有新版本呀～）
        await db.connect()                # 连接数据库
        await capability_pool.refresh()   # 刷新AI能力池
        await register_builtin_tools()    # 注册内置工具
        
        # 启动后台任务们～
        self._tasks.append(asyncio.create_task(idle_loop.run()))    # 空闲学习loop
        self._tasks.append(asyncio.create_task(log_consumer()))     # 日志消费者
        
        # 非打包模式（源码运行）时启动独立前端进程。
        # 生产环境（存在构建产物 frontend/dist 且未设置 IRECKON_DEV_FRONTEND=1）
        # 由 FastAPI 直接托管静态前端，无需独立 dev server。
        root = os.path.dirname(os.path.abspath(__file__))
        dist_dir = os.path.join(root, "frontend", "dist")
        dev_mode = os.environ.get("IRECKON_DEV_FRONTEND", "") == "1"
        if not getattr(sys, 'frozen', False) and (dev_mode or not os.path.isdir(dist_dir)):
            self._start_frontend()
        elif not os.path.isdir(dist_dir):
            logger.warning("frontend/dist 不存在，请先执行 cd frontend && npm run build")
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
                stdout = proc.stdout.strip()
                if stdout:
                    log_banner("npm install 输出", stdout.splitlines())
            except subprocess.CalledProcessError as e:
                logger.warning(f"前端依赖安装失败: {e.returncode} {e.stderr}")
                return

        # 启动Vue前端（优先 npm run dev）
        logger.info("启动Vue前端...")
        tried = []
        vite_js = os.path.join(frontend_dir, "node_modules", "vite", "bin", "vite.js")
        bin_vite = os.path.join(frontend_dir, "node_modules", ".bin", "vite")
        if os.path.exists(bin_vite):
            cmds = [["npm", "run", "dev"], ["npx", "vite", "--host", "127.0.0.1", "--port", "3000"]]
        else:
            cmds = []
            if os.path.exists(vite_js) and shutil.which("node"):
                cmds.append(["node", vite_js, "--host", "127.0.0.1", "--port", "3000"])
            elif npm_path:
                cmds.append(["npm", "run", "dev"])
        for cmd in cmds:
            if cmd[0] == "npm" and npm_path is None:
                continue
            if cmd[0] == "npx" and npx_path is None:
                continue
            if cmd[0] == "node" and shutil.which("node") is None:
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

    @property
    def shutdown_event(self):
        return self._shutdown_event


async def start_backend(app: "IReckonApp"):
    """启动 FastAPI 后端服务～"""
    import uvicorn

    host = config_manager.get("server.host", "0.0.0.0")
    port = config_manager.get("server.port", 8000)

    config = uvicorn.Config("app.web.api:app", host=host, port=port, log_level="warning", loop="asyncio", access_log=False, log_config=None)

    # 打印启动信息
    lan_ip = _get_lan_ip()
    frontend_line = (
        f"前端界面   {config_manager.get('server.frontend_dev_url', 'http://127.0.0.1:3000')} (开发模式)"
        if app._frontend_proc
        else f"前端界面   http://{host}:{port}"
    )
    log_banner(
        f"IReckon v{config_manager.get('system.version')} 已启动",
        [
            f"后端 API   http://{host}:{port}",
            f"交互文档   http://{host}:{port}/docs",
            frontend_line,
            f"局域网访问 http://{lan_ip}:{port}" if lan_ip else "",
            f"健康检查   http://{host}:{port}/api/health",
        ],
    )
    
    if config_manager.get("server.open_browser", False):
        webbrowser.open(f"http://{host}:{port}")  # 自动打开浏览器，懒人福利！
    try:
        app._server = uvicorn.Server(config)
        await app._server.serve()
    except SystemExit as exc:
        logger.warning(f"uvicorn exited with code {exc.code}")
    except Exception:
        logger.exception("启动后端服务时发生异常")
    finally:
        app._shutdown_event.set()


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
    backend_task = asyncio.create_task(start_backend(app))
    backend_task.add_done_callback(lambda task: app.shutdown_event.set() if not app._shutdown_event.is_set() else None)
    try:
        await app._shutdown_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("收到退出信号 (Ctrl+C)，正在退出...")
    finally:
        if not backend_task.done():
            if app._server is not None:
                # 优雅停机：让 uvicorn 走正常的 lifespan.shutdown 流程
                app._server.should_exit = True
                try:
                    await asyncio.wait_for(asyncio.shield(backend_task), timeout=10)
                except asyncio.TimeoutError:
                    logger.warning("后端服务 10 秒内未退出，强制取消")
                    backend_task.cancel()
            else:
                backend_task.cancel()
        try:
            await backend_task
        except asyncio.CancelledError:
            pass
        except SystemExit as exc:
            logger.warning(f"后端任务退出 SystemExit: {exc.code}")
        await app.shutdown()


def run_cli():
    """命令行入口：等价于直接执行 `python main.py`。"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    # 发射！启动！
    run_cli()