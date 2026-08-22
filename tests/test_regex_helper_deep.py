"""regex_helper 深水区补测：ReDoS 守卫、全操作分支、内置模式冒烟。"""

import pytest

from app.tools.builtin.regex_helper.regex_helper import (
    MAX_PATTERN_LEN,
    MAX_TEXT_LEN,
    PATTERNS,
    regex_helper,
)


# ---------- 各操作分支 ----------


def test_match_returns_all_hits():
    assert regex_helper("match", r"\d+", "a1b22c333") == ["1", "22", "333"]


def test_search_no_hit_returns_none():
    assert regex_helper("search", r"\d+", "无数字文本") is None


def test_split_by_delimiter():
    assert regex_helper("split", r",\s*", "a, b,c") == ["a", "b", "c"]


def test_replace_with_group_reference():
    assert regex_helper("replace", r"(\w+)@(\w+)", r"\2/\1", "user@host") == (
        "host/user"
    )


def test_escape_meta_characters():
    assert "\\" in regex_helper("escape", "a.b*")


def test_compile_returns_repr():
    out = regex_helper("compile", r"\d+")
    assert "re.compile" in out


def test_compile_reports_syntax_error():
    out = regex_helper("compile", "([)")
    assert out.startswith("正则语法错误")


def test_compile_over_length_limit():
    out = regex_helper("compile", "a" * (MAX_PATTERN_LEN + 1))
    assert str(MAX_PATTERN_LEN) in out


def test_list_patterns_returns_all_known():
    listed = regex_helper("list_patterns")
    assert sorted(listed) == sorted(PATTERNS.keys())


def test_unsupported_operation():
    assert "不支持的操作" in regex_helper("transmogrify", "x")


# ---------- ReDoS 守卫 ----------


@pytest.mark.parametrize("bad", [None, 123, b"pattern"])
def test_non_string_pattern_rejected(bad):
    assert "必须为字符串" in regex_helper("match", bad, "text")


def test_pattern_over_length_rejected():
    out = regex_helper("match", "a" * (MAX_PATTERN_LEN + 1), "x")
    assert "上限" in out


def test_text_over_length_rejected():
    out = regex_helper("match", r"\d+", "x" * (MAX_TEXT_LEN + 1))
    assert "上限" in out


def test_invalid_syntax_reported_as_regex_error():
    # 未闭合分组在 prepare 的预编译阶段抛 re.error → 顶层归入语法错误分支
    assert "正则语法错误" in regex_helper("match", "([)", "text")


@pytest.mark.parametrize("dangerous", [r"(a+)+", r"(.*)*"])
def test_nested_quantifier_redos_rejected(dangerous):
    assert "ReDoS" in regex_helper("match", dangerous, "aaaa")


def test_redos_guard_known_limitation_alternation_only():
    # 留档：守卫正则要求括号内含裸量词，"(a|aa)+"这类纯交替回溯模式暂不拦截
    # （源码注释宣称覆盖但实现未及）——本用例锁定现状防静默回归
    result = regex_helper("match", r"(a|aa)+", "aaaa")
    assert isinstance(result, list)


# ---------- 内置验证模式冒烟（正/负样本各一） ----------


@pytest.mark.parametrize(
    ("name", "positive", "negative"),
    [
        ("email", "user@example.com", "not-an-email"),
        ("url", "https://example.com/a?b=1", "ftp://example.com"),
        ("phone", "13800138000", "abc"),
        ("ipv4", "192.168.1.1", "999.999.999.999"),
        ("date", "2026-08-22", "22-08-2026"),
        ("time", "12:34:56", "not-a-time"),
        ("number", "-3.14", "1-2"),
        ("alphanumeric", "abc123", "has space"),
    ],
)
def test_validate_builtin_patterns(name, positive, negative):
    assert regex_helper("validate", name, positive) is True, name
    assert regex_helper("validate", name, negative) is False, name
