"""
String toolbox helper.
Provides common string transformation and inspection operations.
"""

import re
import textwrap
from typing import Any, Callable, Dict

_MAX_INPUT_LEN = 100 * 1024
_MAX_PATTERN_LEN = 512


def _safe_format(s: str, *args, **kwargs) -> Any:
    """仅允许简单 {name} 占位符，拒绝属性/下标访问（防信息泄露）。"""
    if "__" in s or "." in s or "[" in s or "]" in s:
        return "格式模板不允许属性/下标访问"
    return s.format(*args, **kwargs)


def _check_pattern(pattern: str) -> None:
    if not isinstance(pattern, str):
        raise ValueError("pattern 必须为字符串")
    if len(pattern) > _MAX_PATTERN_LEN:
        raise ValueError(f"pattern 超过 {_MAX_PATTERN_LEN} 字符上限")


def _regex_search(pattern: str, s: str) -> Any:
    _check_pattern(pattern)
    m = re.search(pattern, s)
    return m.group() if m else None


def _regex_findall(pattern: str, s: str) -> Any:
    _check_pattern(pattern)
    return re.findall(pattern, s)


def _regex_sub(pattern: str, repl: str, s: str) -> Any:
    _check_pattern(pattern)
    return re.sub(pattern, repl, s)


OPERATIONS: Dict[str, Callable[..., Any]] = {
    "upper": lambda s: s.upper(),
    "lower": lambda s: s.lower(),
    "capitalize": lambda s: s.capitalize(),
    "title": lambda s: s.title(),
    "swapcase": lambda s: s.swapcase(),
    "strip": lambda s, chars=None: s.strip(chars) if chars else s.strip(),
    "lstrip": lambda s, chars=None: s.lstrip(chars) if chars else s.lstrip(),
    "rstrip": lambda s, chars=None: s.rstrip(chars) if chars else s.rstrip(),
    "replace": lambda s, old, new: s.replace(old, new),
    "count": lambda s, sub: s.count(sub),
    "find": lambda s, sub: s.find(sub),
    "rfind": lambda s, sub: s.rfind(sub),
    "index": lambda s, sub: s.index(sub),
    "rindex": lambda s, sub: s.rindex(sub),
    "startswith": lambda s, prefix: s.startswith(prefix),
    "endswith": lambda s, suffix: s.endswith(suffix),
    "split": lambda s, sep=None, maxsplit=-1: (
        s.split(sep, maxsplit) if sep else s.split()
    ),
    "rsplit": lambda s, sep=None, maxsplit=-1: (
        s.rsplit(sep, maxsplit) if sep else s.rsplit()
    ),
    "join": lambda sep, *args: sep.join(args),
    "partition": lambda s, sep: s.partition(sep),
    "rpartition": lambda s, sep: s.rpartition(sep),
    "format": _safe_format,
    "template": lambda template, **kwargs: _safe_format(template, **kwargs),
    "isalpha": lambda s: s.isalpha(),
    "isdigit": lambda s: s.isdigit(),
    "isalnum": lambda s: s.isalnum(),
    "isspace": lambda s: s.isspace(),
    "islower": lambda s: s.islower(),
    "isupper": lambda s: s.isupper(),
    "istitle": lambda s: s.istitle(),
    "len": lambda s: len(s),
    "reverse": lambda s: s[::-1],
    "truncate": lambda s, max_len, suffix="...": (
        s[:max_len] + suffix if len(s) > max_len else s
    ),
    "wrap": lambda s, width=70: textwrap.wrap(s, width),
    "dedent": lambda s: textwrap.dedent(s),
    "indent": lambda s, prefix="    ": textwrap.indent(s, prefix),
    "regex_findall": _regex_findall,
    "regex_search": _regex_search,
    "regex_sub": _regex_sub,
}


def string_toolbox(operation: str, *args, **kwargs):
    """Execute a string toolbox operation."""
    if operation not in OPERATIONS:
        return f"Unsupported operation: {operation}. Supported: {', '.join(sorted(OPERATIONS.keys()))}"
    try:
        for arg in args:
            if isinstance(arg, str) and len(arg) > _MAX_INPUT_LEN:
                return f"输入字符串超过 {_MAX_INPUT_LEN} 字符上限"
        return OPERATIONS[operation](*args, **kwargs)
    except Exception as e:
        return f"Error performing string operation: {e}"