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
    """从第一个 opener 开始截取到平衡闭合的块。"""
    start = text.find(opener)
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
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


def _repair_quotes(text: str) -> str:
    """将单引号统一为双引号（LLM 常输出 Python 风格 dict）。"""
    return text.replace("'", '"')


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