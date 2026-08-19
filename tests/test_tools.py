"""内置工具测试:注册入库(幂等)、regex_helper 邮箱操作、dsh 工具入口。"""

from pathlib import Path

import pytest_asyncio

from app.core.database import db
from app.tools.builtin.dsh_harness.dsh_harness import dsh_task
from app.tools.builtin.regex_helper.regex_helper import PATTERNS, regex_helper
from app.tools.registry import register_builtin_tools

ROOT = Path(__file__).parent.parent.resolve()
BUILTIN_DIR = str(ROOT / "app" / "tools" / "builtin")

VALID_EMAILS = [
    "user@example.com",
    "a.b_c-d%+e@sub.domain.co.uk",
    "first.last@example-domain.org",
]

INVALID_EMAILS = [
    "",
    "plainaddress",
    "user@",
    "@example.com",
    "user@example",
    "user name@example.com",
    "user@exam ple.com",
    "user@@example.com",
]

EMAIL_RE = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"


@pytest_asyncio.fixture(scope="function")
async def seeded_db(session_db):
    yield session_db


async def test_register_builtin_tools(seeded_db):
    count_before = await db.fetch_one("SELECT COUNT(*) FROM tool_parts")
    await register_builtin_tools(BUILTIN_DIR)
    count_after = await db.fetch_one("SELECT COUNT(*) FROM tool_parts")
    assert count_after[0] >= count_before[0]
    assert count_after[0] >= 8


async def test_register_builtin_tools_idempotent(seeded_db):
    await register_builtin_tools(BUILTIN_DIR)
    count1 = (await db.fetch_one("SELECT COUNT(*) FROM tool_parts"))[0]
    await register_builtin_tools(BUILTIN_DIR)
    count2 = (await db.fetch_one("SELECT COUNT(*) FROM tool_parts"))[0]
    assert count1 == count2


async def test_register_missing_dir_does_not_raise(seeded_db):
    await register_builtin_tools("/nonexistent/dir")


def test_email_pattern_exists():
    assert "email" in PATTERNS


def test_validate_valid_emails():
    for email in VALID_EMAILS:
        assert regex_helper("validate", "email", email) is True, email


def test_validate_invalid_emails():
    for email in INVALID_EMAILS:
        assert regex_helper("validate", "email", email) is False, email


def test_validate_unknown_pattern():
    result = regex_helper("validate", "unknown_pattern", "x")
    assert isinstance(result, str)
    assert "unknown_pattern" in result


def test_match_extracts_emails():
    text = "请联系 support@example.com 或 dev@team.io 获取帮助"
    assert regex_helper("match", EMAIL_RE, text) == [
        "support@example.com",
        "dev@team.io",
    ]


def test_search_first_email():
    text = "a@x.com 与 b@y.org 都有效"
    assert regex_helper("search", EMAIL_RE, text) == "a@x.com"


def test_replace_email():
    text = "发送到 old@example.com"
    result = regex_helper("replace", EMAIL_RE, "new@example.com", text)
    assert result == "发送到 new@example.com"


def test_dsh_task_missing_task():
    result = dsh_task("")
    assert result["ok"] is False
    assert "task" in result["error"]