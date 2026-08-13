"""配置模块测试：YAML 加载、环境变量展开。"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest

from app.core.config import ConfigManager


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


def test_env_var_expansion():
    os.environ["FREELMAPI_KEY"] = "test-key-123"
    cm = ConfigManager()
    cm.reload()
    inst = cm.get("ai_pool.instances")[0]
    assert inst["api_key"] == "test-key-123"


def test_env_var_expansion_missing_is_empty():
    os.environ.pop("FREELMAPI_KEY", None)
    cm = ConfigManager()
    cm.reload()
    inst = cm.get("ai_pool.instances")[0]
    assert inst["api_key"] == ""


def test_config_path_resolution():
    cm = ConfigManager()
    assert cm.config_path.name == "config.yaml"
    assert cm.config_path.exists()
