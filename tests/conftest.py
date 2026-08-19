"""共享测试环境:临时工作目录、数据库会话与公共构造器。"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
TMP_HOME = Path(tempfile.mkdtemp(prefix="ireckon-tests-"))

shutil.copytree(ROOT / "config", TMP_HOME / "config")
os.environ["IRECKON_HOME"] = str(TMP_HOME)
os.chdir(TMP_HOME)
sys.path.insert(0, str(ROOT))

import pytest_asyncio
from loguru import logger

logger.remove()


def make_cap(**overrides):
    """构造最小可用的 AI 实例,overrides 可覆盖任意字段。"""
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
    """内存版能力池:按标签/排除集合查找,不触数据库。"""

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


def _get_db():
    """懒加载数据库实例,避免不需要数据库的测试加载 aiosqlite/cryptography。"""
    from app.core.database import db

    return db


@pytest_asyncio.fixture(scope="session")
async def session_db():
    db = _get_db()
    await db.connect()
    yield db
    await db.close()