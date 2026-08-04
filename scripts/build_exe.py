import os
import shutil
import subprocess
import sys
from pathlib import Path

DIST = Path("dist") / "IReckon"
BUILD = Path("build")


def clean():
    for d in [DIST, BUILD]:
        if d.exists():
            shutil.rmtree(d)


def build():
    print("=== 构建 IReckon 单体 EXE ===")

    frontend_dist = Path("frontend") / "dist"
    if not frontend_dist.is_dir():
        print("错误: 前端产物 frontend/dist/ 不存在，请先运行 npm run build")
        sys.exit(1)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "IReckon",
        "--distpath", str(DIST),
        "--workpath", str(BUILD),
        "--add-data", f"config{os.pathsep}config",
        "--add-data", f"frontend/dist{os.pathsep}frontend/dist",
        "--hidden-import", "app.web.api",
        "--hidden-import", "app.web.ws",
        "--hidden-import", "app.web.push",
        "--hidden-import", "app.engine.self_improve",
        "--hidden-import", "app.engine.style",
        "--hidden-import", "app.engine.learner",
        "--hidden-import", "app.engine.registry",
        "--hidden-import", "app.engine.tasks",
        "--hidden-import", "app.engine.room",
        "--hidden-import", "app.engine.machine",
        "--hidden-import", "app.engine.board",
        "--hidden-import", "app.engine.detector",
        "--hidden-import", "app.engine.cost",
        "--hidden-import", "app.agents.base",
        "--hidden-import", "app.agents.executor",
        "--hidden-import", "app.agents.scheduler",
        "--hidden-import", "app.agents.reviewer",
        "--hidden-import", "app.agents.creative",
        "--hidden-import", "app.agents.deliverer",
        "--hidden-import", "app.agents.learner",
        "--hidden-import", "app.agents.tool_manager",
        "--hidden-import", "app.agents.content_filter",
        "--hidden-import", "app.llm.client",
        "--hidden-import", "app.llm.pool",
        "--hidden-import", "app.tools.registry",
        "--hidden-import", "app.tools.library",
        "--hidden-import", "app.tools.assembler",
        "--hidden-import", "app.security.scanner",
        "--hidden-import", "app.security.filter",
        "--hidden-import", "app.security.sandbox",
        "--hidden-import", "app.security.mining",
        "--hidden-import", "app.security.supply",
        "--hidden-import", "app.knowledge.vector",
        "--hidden-import", "app.knowledge.files",
        "--hidden-import", "app.core.updater",
        "--hidden-import", "uvicorn",
        "--hidden-import", "uvicorn.protocols",
        "--hidden-import", "uvicorn.server",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "multipart",
        "--hidden-import", "watchdog",
        "--hidden-import", "aiosqlite",
        "--hidden-import", "jinja2",
        "--collect-submodules", "chromadb",
        "--collect-all", "app",
        "--noconfirm",
        "--onedir",
        "--console",
        "main.py",
    ]

    subprocess.check_call(cmd)
    print("EXE 构建完成")


def create_launcher():
    content = """@echo off
title IReckon AI Factory
echo ============================================
echo   IReckon AI Factory
echo ============================================
echo.
start "" "%~dp0IReckon.exe"
echo.
echo   Backend: http://localhost:8000/docs
echo   Frontend: http://localhost:8000
echo.
timeout /t 5 /nobreak >nul
start http://localhost:8000
echo 关闭此窗口即可停止服务
echo.
pause >nul
"""
    (DIST / "启动IReckon.bat").write_text(content, encoding="gbk")
    print("启动脚本已创建")


def main():
    clean()
    build()
    create_launcher()
    size = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
    print(f"\n打包完成! 输出: {DIST}")
    print(f"   总大小: {size / 1024 / 1024:.0f} MB")
    print(f"   运行 {DIST / '启动IReckon.bat'} 即可启动")


if __name__ == "__main__":
    main()
