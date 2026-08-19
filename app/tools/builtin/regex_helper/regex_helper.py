"""
工具零件：正则表达式助手
提供常用正则验证、提取、替换、生成等操作。
ReDoS 防护：限制 pattern/text 长度，预编译校验语法，拒绝嵌套重复的危险模式。
"""

import re

MAX_PATTERN_LEN = 512
MAX_TEXT_LEN = 50 * 1024

PATTERNS = {
    "email": r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$",
    "url": r"https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+",
    "phone": r"^\+?[\d\s-]{7,15}$",
    "ipv4": r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$",
    "date": r"^\d{4}-\d{2}-\d{2}$",
    "time": r"^\d{2}:\d{2}(:\d{2})?$",
    "number": r"^-?\d+(\.\d+)?$",
    "alphanumeric": r"^[a-zA-Z0-9]+$",
}

# 嵌套量词 / 歧义交替（如 (a+)+、(a|a)+、(.+)*）——经典 ReDoS 模式
_REDOS_PATTERN = re.compile(r"\(\s*[^()]*[+*][^()]*\)\s*[+*]")


class _ReDoSGuard:
    @staticmethod
    def prepare(pattern: str, text: str) -> tuple:
        if not isinstance(pattern, str) or not isinstance(text, str):
            raise ValueError("pattern 与 text 必须为字符串")
        if len(pattern) > MAX_PATTERN_LEN:
            raise ValueError(f"pattern 超过 {MAX_PATTERN_LEN} 字符上限")
        if len(text) > MAX_TEXT_LEN:
            raise ValueError(f"text 超过 {MAX_TEXT_LEN} 字符上限")
        # 先编译验证语法
        re.compile(pattern)
        # 拒绝嵌套重复的危险模式
        if _REDOS_PATTERN.search(pattern):
            raise ValueError("拒绝执行可能存在 ReDoS 风险的正则模式")
        return pattern, text


def regex_helper(operation: str, *args, **kwargs):
    try:
        if operation == "validate":
            pattern_name = args[0]
            text = args[1]
            if pattern_name in PATTERNS:
                _, text = _ReDoSGuard.prepare(PATTERNS[pattern_name], text)
                return bool(re.match(PATTERNS[pattern_name], text))
            else:
                return f"未知验证模式: {pattern_name}"

        elif operation == "match":
            pattern, text = args[0], args[1]
            pattern, text = _ReDoSGuard.prepare(pattern, text)
            return re.findall(pattern, text)

        elif operation == "search":
            pattern, text = args[0], args[1]
            pattern, text = _ReDoSGuard.prepare(pattern, text)
            m = re.search(pattern, text)
            return m.group(0) if m else None

        elif operation == "replace":
            pattern, repl, text = args[0], args[1], args[2]
            pattern, text = _ReDoSGuard.prepare(pattern, text)
            return re.sub(pattern, repl, text)

        elif operation == "split":
            pattern, text = args[0], args[1]
            pattern, text = _ReDoSGuard.prepare(pattern, text)
            return re.split(pattern, text)

        elif operation == "escape":
            return re.escape(args[0])

        elif operation == "compile":
            pattern = args[0]
            if len(pattern) > MAX_PATTERN_LEN:
                return f"pattern 超过 {MAX_PATTERN_LEN} 字符上限"
            try:
                return str(re.compile(pattern))
            except re.error as e:
                return f"正则语法错误: {e}"

        elif operation == "list_patterns":
            return list(PATTERNS.keys())

        else:
            return f"不支持的操作: {operation}"
    except re.error as e:
        return f"正则语法错误: {e}"
    except Exception as e:
        return f"运算出错: {e}"