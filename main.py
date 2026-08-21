#!/usr/bin/env python3
"""IReckon 主入口：初始化各模块并启动后端服务。"""

import asyncio
import io
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser

from app.core.database import db
from app.core.logger import setup_logging, log_banner, logger
from app.core.updater import updater
from app.llm.pool import capability_pool
from app.engine.learner import idle_loop
from app.web.auth import ensure_token, warn_if_insecure
from app.web.push import log_consumer
from app.tools.registry import register_builtin_tools

from app.core.config import config_manager  # noqa: F401  # 测试通过模块属性访问
from app.core.config import get

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
DIST_DIR = os.path.join(FRONTEND_DIR, "dist")


def _utf8_stream(stream):
    """确保输出流使用 UTF-8 编码，避免控制台/重定向时中文乱码。

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
    """检查是否有新版本可用。"""
    if not updater.should_check():
        return
    updater.mark_checked()
    version = await updater.check()
    if version:
        logger.info(f"发现新版本 v{version}，请运行 python scripts/update.py 进行更新")


class IReckonApp:
    """IReckon 应用主类，负责初始化与生命周期管理。"""

    def __init__(self):
        self._shutdown_event = asyncio.Event()
        self._tasks = []
        self._frontend_proc = None
        self._shutdown_started = False
        self._server = None

    async def initialize(self):
        setup_logging()
        logger.info(f"启动 { get('system.name')} v{ get('system.version')}")

        # 确保存在 API token（首次启动自动生成并持久化），控制台明示
        api_token = ensure_token()
        if os.environ.get("IRECKON_API_TOKEN", "").strip():
            logger.info("API 鉴权已启用（token 来自环境变量 IRECKON_API_TOKEN）")
        else:
            log_banner(
                "API 访问令牌",
                [
                    f"{api_token}",
                    "打开前端后在登录页粘贴此令牌；也可在 config.yaml 的",
                    "security.api_token 中固定，或设置环境变量 IRECKON_API_TOKEN。",
                ],
            )
        warn_if_insecure()

        await _check_update()
        await db.connect()
        await capability_pool.refresh()
        await register_builtin_tools()

        self._tasks.append(asyncio.create_task(idle_loop.run()))
        self._tasks.append(asyncio.create_task(log_consumer()))

        # 源码运行且未构建前端产物（或显式指定开发模式）时启动独立 dev server；
        # 否则由 FastAPI 直接托管 frontend/dist 静态文件。
        dev_mode = os.environ.get("IRECKON_DEV_FRONTEND", "") == "1"
        if not getattr(sys, "frozen", False) and (dev_mode or not os.path.isdir(DIST_DIR)):
            self._start_frontend()
        elif not os.path.isdir(DIST_DIR):
            logger.warning("frontend/dist 不存在，请先执行 cd frontend && npm run build")
        logger.info("系统初始化完成")

    def _start_frontend(self):
        npm_path = shutil.which("npm")
        npx_path = shutil.which("npx")
        if npm_path is None and npx_path is None:
            logger.warning("npm/npx 未安装或不可用，前端无法启动")
            return

        if not os.path.exists(os.path.join(FRONTEND_DIR, "node_modules")):
            logger.info("正在安装前端依赖...")
            cmd = ["npm", "install"] if npm_path else ["npx", "npm", "install"]
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=FRONTEND_DIR,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                stdout = proc.stdout.strip()
                if stdout:
                    log_banner("npm install 输出", stdout.splitlines())
            except subprocess.CalledProcessError as e:
                logger.warning(f"前端依赖安装失败: {e.returncode} {e.stderr}")
                return
            except (FileNotFoundError, OSError) as e:
                logger.warning(f"前端依赖安装无法执行({cmd[0]}): {e}")
                return

        logger.info("启动Vue前端...")
        bin_vite = os.path.join(FRONTEND_DIR, "node_modules", ".bin", "vite")
        vite_js = os.path.join(FRONTEND_DIR, "node_modules", "vite", "bin", "vite.js")
        if os.path.exists(bin_vite):
            cmds = [["npm", "run", "dev"], ["npx", "vite", "--host", "127.0.0.1", "--port", "3000"]]
        elif os.path.exists(vite_js) and shutil.which("node"):
            cmds = [["node", vite_js, "--host", "127.0.0.1", "--port", "3000"]]
        elif npm_path:
            cmds = [["npm", "run", "dev"]]
        else:
            cmds = []
        tried = []
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
                    cwd=FRONTEND_DIR,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                logger.info(f"前端已启动: {' '.join(cmd)}")
                return
            except (FileNotFoundError, OSError) as e:
                tried.append((cmd, str(e)))

        logger.warning(f"前端启动失败，尝试命令: {tried}")
        self._frontend_proc = None

    async def shutdown(self):
        if self._shutdown_started:
            return
        self._shutdown_started = True

        logger.info("正在关闭系统...")
        self._shutdown_event.set()

        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        if self._frontend_proc:
            self._frontend_proc.terminate()
            try:
                self._frontend_proc.wait(timeout=5)
            except Exception:
                self._frontend_proc.kill()

        await db.close()
        logger.info("系统已关闭")

    @property
    def shutdown_event(self):
        return self._shutdown_event


async def start_backend(app: "IReckonApp"):
    """启动 FastAPI 后端服务。"""
    import uvicorn

    host = get("server.host", "127.0.0.1")
    port = get("server.port", 8000)

    config = uvicorn.Config(
        "app.web.api:app",
        host=host,
        port=port,
        log_level="warning",
        loop="asyncio",
        access_log=False,
        log_config=None,
    )

    lan_ip = _get_lan_ip()
    # 仅输出实际可访问的地址：绑定 127.0.0.1 时局域网不可达
    lan_exposed = host not in ("127.0.0.1", "localhost", "::1")
    if app._frontend_proc:
        banner_lines = [
            f"后端 API   http://{host}:{port}",
            f"前端界面   { get('server.frontend_dev_url', 'http://127.0.0.1:3000')} (开发模式)",
        ]
    else:
        # 生产模式：FastAPI 同端口托管前端，前后端合一
        banner_lines = [f"Web 服务   http://{host}:{port} (前端 + API)"]
    if lan_exposed and lan_ip:
        banner_lines.append(f"局域网访问 http://{lan_ip}:{port}")
    banner_lines.append(f"健康检查   http://{host}:{port}/api/health")
    log_banner(
        f"IReckon v{ get('system.version')} 已启动",
        banner_lines,
    )

    if get("server.open_browser", False):
        webbrowser.open(f"http://{host}:{port}")
    try:
        app._server = uvicorn.Server(config)
        await app._server.serve()
    except SystemExit as exc:
        logger.warning(f"uvicorn exited with code {exc.code}")
    except Exception:
        logger.exception("启动后端服务时发生异常")
    finally:
        app._shutdown_event.set()


async def start_backend_embedded(
    app: "IReckonApp", ready: threading.Event, port_holder: dict, closing: threading.Event
):
    """嵌入式模式后端：uvicorn 绑定 127.0.0.1 随机端口，窗口关闭时优雅退出。"""
    import uvicorn

    config = uvicorn.Config(
        "app.web.api:app",
        host="127.0.0.1",
        port=0,
        log_level="warning",
        loop="asyncio",
        access_log=False,
        log_config=None,
    )
    server = uvicorn.Server(config)
    app._server = server

    async def _watch_close() -> None:
        while not closing.is_set():
            await asyncio.sleep(0.2)
        server.should_exit = True

    watcher = asyncio.create_task(_watch_close())
    serve_task = asyncio.create_task(server.serve())
    try:
        while not serve_task.done() and not getattr(server, "servers", None):
            await asyncio.sleep(0.05)
        if serve_task.done():
            serve_task.result()
        port = server.servers[0].sockets[0].getsockname()[1]
        port_holder["port"] = port
        log_banner(
            f"IReckon v{ get('system.version')} 已启动(嵌入式)",
            [f"Web UI   http://127.0.0.1:{port}", "关闭窗口即退出"],
        )
        ready.set()
        await serve_task
    except Exception:
        logger.exception("启动后端服务时发生异常")
    finally:
        watcher.cancel()
        app._shutdown_event.set()


async def main():
    app = IReckonApp()
    await app.initialize()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(app.shutdown()))
        except NotImplementedError:
            pass

    backend_task = asyncio.create_task(start_backend(app))
    backend_task.add_done_callback(
        lambda task: app.shutdown_event.set() if not app._shutdown_event.is_set() else None
    )
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


async def _serve_once(
    ready: threading.Event, port_holder: dict, closing: threading.Event
) -> None:
    """嵌入式(打包 exe)模式的服务协程：初始化 + uvicorn 随机端口 + 优雅退出。"""
    app_obj = IReckonApp()
    await app_obj.initialize()
    try:
        await start_backend_embedded(app_obj, ready, port_holder, closing)
    finally:
        await app_obj.shutdown()


def run_embedded() -> None:
    """打包(exe)入口：嵌入式 WebView 窗口 + 随机端口自通信，不打开外部浏览器。"""
    import webview

    ready = threading.Event()
    port_holder: dict = {}
    closing = threading.Event()
    thread = threading.Thread(
        target=lambda: asyncio.run(_serve_once(ready, port_holder, closing)),
        daemon=True,
    )
    thread.start()
    if not ready.wait(timeout=60):
        logger.error("后端服务 60 秒内未就绪，退出")
        closing.set()
        thread.join(timeout=5)
        return

    port = port_holder.get("port")
    if not port:
        logger.error("未获取到服务端口，退出")
        closing.set()
        thread.join(timeout=5)
        return

    try:
        window = webview.create_window(
            "IReckon AI Factory",
            url=f"http://127.0.0.1:{port}",
            width=1280,
            height=820,
            min_size=(960, 600),
        )
        if window is None:
            raise RuntimeError("无法创建嵌入式窗口")
        window.events.closed += closing.set
        webview.start()
    except Exception:
        logger.exception("嵌入式界面启动失败，回退到控制台模式")
        closing.set()
        thread.join(timeout=15)
        log_banner(
            "IReckon 控制台模式",
            [
                f"Web UI   http://127.0.0.1:{port}",
                "关闭此窗口或 Ctrl+C 即可退出",
            ],
        )
        closing2 = threading.Event()
        thread2 = threading.Thread(
            target=lambda: asyncio.run(_serve_once2(closing2)), daemon=True
        )
        thread2.start()
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            closing2.set()
            thread2.join(timeout=15)
        return
    closing.set()
    thread.join(timeout=15)


async def _serve_once2(closing: threading.Event) -> None:
    """控制台回退模式：固定默认端口 8000，等待 Ctrl+C。"""
    app_obj = IReckonApp()
    await app_obj.initialize()
    try:
        await start_backend(app_obj)
    finally:
        await app_obj.shutdown()


def run_cli():
    """命令行入口：打包版走嵌入式窗口(随机端口)，源码版走常规服务。"""
    if getattr(sys, "frozen", False):
        run_embedded()
        return
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run_cli()
