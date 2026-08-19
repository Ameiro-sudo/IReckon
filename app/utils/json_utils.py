"""健壮的 JSON 提取工具：应对 LLM 输出"犯病"的各种情况。

支持：
- 去掉 markdown 代码围栏（```json ... ```）
- 去掉前后解释性文字
- 定位第一个平衡的 { } / [ ] 块
- 修复常见小问题（尾随逗号、单双引号混用、注释行）
"""

import json
import re
from typing import Any, Optional

_MARKDOWN_FENCE = re.compile(r"```(?:json|javascript|js)?\s*", re.IGNORECASE)
_JSON_OBJECT = re.compile(r"\{")
_JSON_ARRAY = re.compile(r"\[")


def _strip_code_fence(text: str) -> str:
    """移除 markdown 代码围栏与前后包裹的说明文字。"""
    text = text.strip()
    if text.startswith("```"):
        text = _MARKDOWN_FENCE.sub("", text, count=1)
    if text.rstrip().endswith("```"):
        text = text.rstrip()[:-3].rstrip()
    return text.strip()


def _strip_comments(text: str) -> str:
    """去掉 JSON 中的 // 行注释（LLM 常犯）。仅处理行首注释，避免误伤字符串。"""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        lines.append(line)
    return "\n".join(lines)


def _balance_trim(text: str, opener: str, closer: str) -> Optional[str]:
    """从第一个 opener 开始截取到平衡闭合的块。

    识别双引号与单引号字符串边界：被 '...' 包裹的区域整体跳过，
    避免把字符串里的撇号/括号误当成结构字符。
    """
    start = text.find(opener)
    if start == -1:
        return None
    depth = 0
    in_str = False
    quote = ""
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
            continue
        if ch in "\"'":
            in_str = True
            quote = ch
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _repair(text: str) -> str:
    """尝试修复常见 JSON 问题。"""
    # 尾随逗号
    text = re.sub(r",\s*([}\]])", r"\1", text)
    # 控制字符
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    return text


_UNQUOTED_KEY = re.compile(r"([{,\s])([A-Za-z_][A-Za-z0-9_]*)(\s*:)")


def _repair_quotes(text: str) -> str:
    """修复未加引号的 key（LLM 常输出 Python 风格 dict）。

    仅把 { / 逗号 / 空白 后紧跟的裸 key 包成双引号；整体跳过引号字符串区域，
    避免把单引号内的撇号（如 don't）误改成双引号破坏内容。
    """
    out: list = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            # 引号字符串（含转义）整体跳过
            quote = ch
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == quote:
                    j += 1
                    break
                j += 1
            if quote == "'":
                # 单引号字符串转为双引号（转义内部双引号/反斜杠），
                # 使 Python 风格 dict 的字符串值可被 json 解析
                inner = text[i + 1 : j - 1]
                escaped = inner.replace("\\", "\\\\").replace('"', '\\"')
                out.append('"' + escaped + '"')
            else:
                out.append(text[i:j])
            i = j
            continue
        m = _UNQUOTED_KEY.match(text, i)
        if m:
            out.append(text[i : m.start(2)])
            out.append('"')
            out.append(m.group(2))
            out.append('"')
            i = m.end(2)
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def extract_json(text: str) -> Any:
    """从 LLM 输出中提取并解析第一个 JSON 对象或数组。失败返回 None。"""
    if not text:
        return None
    candidate = _strip_comments(_strip_code_fence(text))
    for opener, closer in [("{", "}"), ("[", "]")]:
        block = _balance_trim(candidate, opener, closer)
        if block is None:
            continue
        strategies = (block, _repair(block), _repair_quotes(_repair(block)))
        for attempt in strategies:
            try:
                return json.loads(attempt)
            except json.JSONDecodeError:
                continue
    return None


def parse_json_field(text: str, key: str, default: Any = None) -> Any:
    """提取 JSON 中的某个字段（顶层）。"""
    data = extract_json(text)
    if isinstance(data, dict):
        return data.get(key, default)
    return default
