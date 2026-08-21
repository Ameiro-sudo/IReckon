"""共享测试环境：临时 IRECKON_HOME、数据库会话与公共构造器。

设计要点：
- 环境准备（拷贝 config、注入 IRECKON_HOME、chdir）必须放在 pytest_configure
  钩子中执行：pytest 会在 preparse 阶段就加载本 conftest，若在 import 时 chdir，
  会破坏 pytest.ini 中 testpaths 的相对 glob（相对启动目录解析）；
- app.* 模块在导入时就读 config_manager，因此所有 app 导入也必须延迟到
  pytest_configure 之后（放在函数内或钩子内），避免读到真实环境的配置；
- 临时目录固定在 tests/.tmp/ireckon-home，每次运行前清空重建，
  便于调试复现且不堆积垃圾（已加入 .gitignore）；
- 公共测试助手（make_cap / FakeCapabilityPool / LogRecorder / FakeProc 等）
  从这里导出，各测试文件直接 from conftest import。
"""

import asyncio
import os
import shutil
import sys
import time
from pathlib import Path

import pytest
import pytest_asyncio

ROOT = Path(__file__).parent.parent.resolve()
RUN_DIR = ROOT / "tests" / ".tmp"
TMP_HOME = RUN_DIR / f"run-{os.getpid()}"


def pytest_configure(config):
    """在 args 解析完成后重建干净临时 home 并切换环境。

    临时目录按 pid 隔离：多个 pytest 进程可并行运行互不干扰；
    清理时只删除过期残留（>1h）与 staging 目录，避免误删并行进程。
    """
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    # 优化：仅在当前 run 目录不存在时才清理旧目录，避免每次测试都遍历
    if not TMP_HOME.exists():
        now = time.time()
        for old in RUN_DIR.glob("run-*"):
            if old.name == TMP_HOME.name:
                continue
            try:
                is_stale_stage = old.suffix == ".stage"
                if is_stale_stage or now - old.stat().st_mtime > 3600:
                    shutil.rmtree(old, ignore_errors=True)
            except OSError:
                pass

    TMP_HOME.mkdir(parents=True, exist_ok=True)

    # 优化：仅在 config 目录不存在或已变化时才复制
    dst_config = TMP_HOME / "config"
    src_config = ROOT / "config"
    if not dst_config.exists():
        shutil.copytree(src_config, dst_config)
    else:
        # 增量更新：仅复制变化的文件
        for src_file in src_config.rglob("*"):
            if src_file.is_file():
                dst_file = dst_config / src_file.relative_to(src_config)
                if (
                    not dst_file.exists()
                    or src_file.stat().st_mtime > dst_file.stat().st_mtime
                ):
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, dst_file)

    os.environ["IRECKON_HOME"] = str(TMP_HOME)
    os.chdir(TMP_HOME)
    sys.path.insert(0, str(ROOT))

    from loguru import logger

    # 关闭 loguru 默认 stderr sink，避免测试输出被日志淹没
    logger.remove()

    from app.core.config import config_manager

    config_manager.reload()


def make_cap(**overrides):
    """构造最小可用的 AI 实例，overrides 可覆盖任意字段。"""
    from app.llm.pool import AICapability

    fields = dict(
        id="t1",
        name="Test",
        endpoint="http://localhost:1/v1",
        model="auto",
        api_key="",
        tags=["python"],
        max_context=4096,
    )
    fields.update(overrides)
    return AICapability(**fields)


class FakeCapabilityPool:
    """内存版能力池：按标签/排除集合查找，不触数据库。"""

    def __init__(self, caps):
        self._caps = {c.id: c for c in caps}

    async def find_best_match(
        self, required_tags=None, exclude_ids=None, prefer_cheapest=False, **kw
    ):
        exclude_ids = exclude_ids or set()
        cands = [c for c in self._caps.values() if c.id not in exclude_ids]
        if required_tags:
            cands = [c for c in cands if all(t in c.tags for t in required_tags)]
        return cands[0] if cands else None


class LogRecorder:
    """替代 loguru logger 的测试记录器，捕获日志消息供断言。"""

    def __init__(self):
        self.messages = []

    def _add(self, level, msg):
        self.messages.append((level, str(msg)))

    def info(self, msg):
        self._add("info", msg)

    def warning(self, msg):
        self._add("warning", msg)

    def exception(self, msg):
        self._add("exception", msg)

    def error(self, msg):
        self._add("error", msg)

    def debug(self, msg):
        self._add("debug", msg)

    def has(self, *substrings):
        return any(all(s in m[1] for s in substrings) for m in self.messages)


def _get_db():
    """懒加载数据库实例，避免不需要数据库的测试加载 aiosqlite/cryptography。"""
    from app.core.database import db

    return db


@pytest.fixture(autouse=True)
def _reset_capability_pool():
    """每个测试前重置全局能力池单例状态。

    背景：CapabilityPool 是进程级单例，refresh() 有 60s 单调时钟节流。
    若某个测试在 config_manager.get 被 patch（如 make_improver 返回空实例列表）
    时触发了真实 find_best_match，单例会缓存"空池 + 刚刷新过"状态长达 60s，
    污染同进程后续所有依赖真实池的测试（且全量运行时因耗时>60s 而侥幸掩盖）。
    同时 pytest-asyncio 每个测试独立事件循环，_refresh_lock 需随循环重建
    （与 session_db 重建数据库锁同理）。
    """
    from app.llm.pool import capability_pool

    capability_pool._last_refresh = 0
    capability_pool.capabilities = {}
    capability_pool._memory_cache.clear()
    capability_pool._cache_timestamps.clear()
    capability_pool._refresh_lock = asyncio.Lock()
    yield


@pytest_asyncio.fixture
async def session_db():
    """干净的数据库会话：每个测试独立事件循环，锁与连接随循环重建。"""
    db = _get_db()
    # pytest-asyncio 下每个测试独立事件循环，数据库连接锁需随循环重建
    for lock_name in ("_connect_lock", "_write_lock"):
        if hasattr(db, lock_name):
            setattr(db, lock_name, asyncio.Lock())
    if getattr(db, "_conn", None) is not None:
        try:
            await db._conn.close()
        except Exception:
            pass
        db._conn = None
    await db.connect()
    yield db
    await db.close()


def make_fake_proc(rc, out=b"", err=b""):
    """构造 asyncio.subprocess.Process 的替身：增量读取模式可直接用。

    - rc: returncode
    - out/err: 预置到 StreamReader 的内容（readline 可消费）
    """

    class FakeProc:
        def __init__(self):
            self.returncode = rc
            self.stdout = asyncio.StreamReader()
            self.stdout.feed_data(out)
            self.stdout.feed_eof()
            self.stderr = asyncio.StreamReader()
            self.stderr.feed_data(err)
            self.stderr.feed_eof()
            self.killed = False

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            return self.returncode

    return FakeProc()
