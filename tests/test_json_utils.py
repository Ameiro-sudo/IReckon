"""json_utils 提取器测试：覆盖 LLM 输出的各种异常形态。"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from app.utils.json_utils import extract_json


def test_plain_json_object():
    assert extract_json('{"passed": true}') == {"passed": True}


def test_fenced_json():
    text = '```json\n{"passed": true}\n```'
    assert extract_json(text) == {"passed": True}


def test_surrounding_prose():
    text = '好的，审查结论如下：\n{"passed": false, "issues": ["x"]}\n以上是我的审查结果。'
    data = extract_json(text)
    assert data["passed"] is False
    assert data["issues"] == ["x"]


def test_trailing_comma():
    text = '{"passed": true, "issues": [],}'
    assert extract_json(text) == {"passed": True, "issues": []}


def test_comment_lines():
    text = '{\n// 审查结论\n"passed": false\n}'
    assert extract_json(text) == {"passed": False}


def test_balanced_nested():
    text = '{"a": {"b": [1, {"c": 2}]}, "d": "}"}'
    data = extract_json(text)
    assert data["a"]["b"][1]["c"] == 2
    assert data["d"] == "}"


def test_array_extraction():
    assert extract_json('结果是：["a", "b"] 谢谢') == ["a", "b"]


def test_invalid_returns_none():
    assert extract_json("这不是 JSON") is None
    assert extract_json("") is None
    assert extract_json(None) is None


def test_single_quotes_mixed():
    text = "{'passed': true, \"issues\": []}"
    assert extract_json(text) == {"passed": True, "issues": []}


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))