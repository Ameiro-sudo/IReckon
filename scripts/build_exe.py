import os
import shutil
import subprocess
import sys
from pathlib import Path

DIST = Path("dist") / "IReckon"
BUILD = Path("build")

# 打包时从 config/ 排除的文件：本地真实配置可能含 API 密钥与自动生成的
# api_token，烧进发行包即绕过 git 直接泄漏；运行时缺失主配置会自动回退
# config.example.yaml（见 app/core/config.py），功能无损。
_CONFIG_STAGE_EXCLUDES = (
    "config.yaml",
    ".pre-commit-config.yaml",
    "__pycache__",
)


def stage_config() -> Path:
    """把随包分发的配置模板白名单化拷贝到独立暂存目录，返回该目录路径。"""
    src = Path("config")
    dst = BUILD / "config-staged"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*_CONFIG_STAGE_EXCLUDES))
    return dst


def verify_dist_no_local_config() -> None:
    """构建后校验：产物中不得出现任何 config.yaml（防真实配置混入发行包）。"""
    leaks = list(DIST.rglob("config.yaml"))
    if leaks:
        for p in leaks:
            print(f"安全错误: 发行包中检测到本地配置 {p}")
        print("构建中止：请检查打包来源目录是否被污染。")
        sys.exit(1)


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

    cfg_dir = stage_config()

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name",
        "IReckon",
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD),
        "--specpath",
        str(BUILD),
        "--add-data",
        f"{cfg_dir.as_posix()}{os.pathsep}config",
        "--add-data",
        f"frontend/dist{os.pathsep}frontend/dist",
        "--hidden-import",
        "app.web.api",
        "--hidden-import",
        "app.web.push",
        "--hidden-import",
        "app.engine.self_improve",
        "--hidden-import",
        "app.engine.style",
        "--hidden-import",
        "app.engine.learner",
        "--hidden-import",
        "app.engine.registry",
        "--hidden-import",
        "app.engine.tasks",
        "--hidden-import",
        "app.engine.room",
        "--hidden-import",
        "app.engine.machine",
        "--hidden-import",
        "app.engine.board",
        "--hidden-import",
        "app.engine.detector",
        "--hidden-import",
        "app.engine.cost",
        "--hidden-import",
        "app.agents.base",
        "--hidden-import",
        "app.agents.executor",
        "--hidden-import",
        "app.agents.scheduler",
        "--hidden-import",
        "app.agents.reviewer",
        "--hidden-import",
        "app.agents.creative",
        "--hidden-import",
        "app.agents.deliverer",
        "--hidden-import",
        "app.agents.learner",
        "--hidden-import",
        "app.agents.tool_manager",
        "--hidden-import",
        "app.agents.content_filter",
        "--hidden-import",
        "app.llm.client",
        "--hidden-import",
        "app.llm.pool",
        "--hidden-import",
        "app.tools.registry",
        "--hidden-import",
        "app.tools.library",
        "--hidden-import",
        "app.tools.assembler",
        "--hidden-import",
        "app.security.scanner",
        "--hidden-import",
        "app.security.filter",
        "--hidden-import",
        "app.security.sandbox",
        "--hidden-import",
        "app.security.mining",
        "--hidden-import",
        "app.security.supply",
        "--hidden-import",
        "app.knowledge.vector",
        "--hidden-import",
        "app.knowledge.files",
        "--hidden-import",
        "app.core.updater",
        "--hidden-import",
        "uvicorn",
        "--hidden-import",
        "uvicorn.protocols",
        "--hidden-import",
        "uvicorn.server",
        "--hidden-import",
        "uvicorn.loops",
        "--hidden-import",
        "uvicorn.loops.auto",
        "--hidden-import",
        "multipart",
        "--hidden-import",
        "watchdog",
        "--hidden-import",
        "aiosqlite",
        "--hidden-import",
        "jinja2",
        "--collect-submodules",
        "chromadb",
        "--collect-data",
        "litellm",
        "--collect-all",
        "app",
        "--collect-all",
        "webview",
        "--hidden-import",
        "clr",
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
echo   Web UI: http://localhost:8000
echo.
echo 关闭此窗口即可停止服务
echo.
pause >nul
"""
    (DIST / "IReckon" / "启动IReckon.bat").write_text(content, encoding="gbk")
    print("启动脚本已创建")


def main():
    clean()
    build()
    verify_dist_no_local_config()
    create_launcher()
    size = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
    print(f"\n打包完成! 输出: {DIST}")
    print(f"   总大小: {size / 1024 / 1024:.0f} MB")
    print(f"   运行 {DIST / 'IReckon' / '启动IReckon.bat'} 即可启动")


if __name__ == "__main__":
    main()
