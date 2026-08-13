"""共享测试环境：所有测试共用一个临时工作目录，避免全局单例（db/config）串目录。"""

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

from app.core.database import db
from loguru import logger

logger.remove()


@pytest_asyncio.fixture(scope="session")
async def session_db():
    await db.connect()
    yield db
    await db.close()
