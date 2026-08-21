"""核心模块测试:配置加载/环境变量展开、JSON 提取器。"""

import os

import pytest

from app.core.config import ConfigManager
from app.utils.json_utils import extract_json

from app.core.config import get


@pytest.fixture(autouse=True)
def restore_env():
    saved = os.environ.get("FREELMAPI_KEY")
    yield
    if saved is None:
        os.environ.pop("FREELMAPI_KEY", None)
    else:
        os.environ["FREELMAPI_KEY"] = saved


def test_config_loads_core_keys():
    cm = ConfigManager()
    cfg = cm.get_all()
    assert "server" in cfg
    assert "ai_pool" in cfg
    assert cfg["server"]["port"] == 8000


def test_config_env_var_expansion():
    os.environ["FREELMAPI_KEY"] = "test-key-123"
    cm = ConfigManager()
    cm.reload()
    assert get("ai_pool.instances")[0]["api_key"] == "test-key-123"


def test_config_env_var_expansion_missing_is_empty():
    os.environ.pop("FREELMAPI_KEY", None)
    cm = ConfigManager()
    cm.reload()
    assert get("ai_pool.instances")[0]["api_key"] == ""


def test_config_path_resolution():
    cm = ConfigManager()
    # 主配置存在时用 config.yaml；全新环境缺失时回退 example 模板，两者都必须可加载
    assert cm.config_path.name in ("config.yaml", "config.example.yaml")
    assert cm.config_path.exists()


def test_extract_plain_json_object():
    assert extract_json('{"passed": true}') == {"passed": True}


def test_extract_fenced_json():
    text = '```json\n{"passed": true}\n```'
    assert extract_json(text) == {"passed": True}


def test_extract_from_surrounding_prose():
    text = '好的,审查结论如下:\n{"passed": false, "issues": ["x"]}\n以上是我的审查结果。'
    data = extract_json(text)
    assert data["passed"] is False
    assert data["issues"] == ["x"]


def test_extract_trailing_comma():
    text = '{"passed": true, "issues": [],}'
    assert extract_json(text) == {"passed": True, "issues": []}


def test_extract_comment_lines():
    text = '{\n// 审查结论\n"passed": false\n}'
    assert extract_json(text) == {"passed": False}


def test_extract_balanced_nested():
    text = '{"a": {"b": [1, {"c": 2}]}, "d": "}"}'
    data = extract_json(text)
    assert data["a"]["b"][1]["c"] == 2
    assert data["d"] == "}"


def test_extract_array():
    assert extract_json('结果是:["a", "b"] 谢谢') == ["a", "b"]


def test_extract_single_quotes_mixed():
    text = "{'passed': true, \"issues\": []}"
    assert extract_json(text) == {"passed": True, "issues": []}


def test_extract_invalid_returns_none():
    assert extract_json("这不是 JSON") is None
    assert extract_json("") is None
    assert extract_json(None) is None