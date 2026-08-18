"""
String toolbox helper.
Provides common string transformation and inspection operations.
"""

import re
import textwrap
from typing import Any, Callable, Dict

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
    "format": lambda s, *args, **kwargs: s.format(*args, **kwargs),
    "template": lambda template, **kwargs: template.format(**kwargs),
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
    "regex_findall": lambda pattern, s: re.findall(pattern, s),
    "regex_search": lambda pattern, s: (
        m.group() if (m := re.search(pattern, s)) else None
    ),
    "regex_sub": lambda pattern, repl, s: re.sub(pattern, repl, s),
}


def string_toolbox(operation: str, *args, **kwargs):
    """Execute a string toolbox operation."""
    if operation not in OPERATIONS:
        return f"Unsupported operation: {operation}. Supported: {', '.join(sorted(OPERATIONS.keys()))}"
    try:
        return OPERATIONS[operation](*args, **kwargs)
    except Exception as e:
        return f"Error performing string operation: {e}"
