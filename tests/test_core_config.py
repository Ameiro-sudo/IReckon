"""ConfigManager 深水区补测：dotenv 加载、回退链、哈希短路、解析容错、
save_value 行级写回矩阵、掩码、热加载 handler 与监视器生命周期。

隔离策略：ConfigManager 是进程级单例，一律用 ``object.__new__`` 构造裸实例
（跳过 __init__，不启动真实 watchdog 线程），路径全部指向 tmp_path，
环境变量用 IRECKON_TCFG_ 前缀防串扰。
"""

import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.core.config as cfg_mod
from app.core.config import (
    ConfigChangeHandler,
    ConfigManager,
    _load_dotenv_file,
)


# ---------- 工具 ----------


def make_cm(config_dir: Path) -> ConfigManager:
    """构造指向 tmp 目录的裸实例：无观察者、无全局单例副作用。"""
    cm = object.__new__(ConfigManager)
    cm._initialized = True
    cm._config_lock = threading.RLock()
    cm._observer = None
    cm._config_hash = None
    cm.base_dir = config_dir.parent
    cm.config_path = config_dir / "config.yaml"
    cm.example_path = config_dir / "config.example.yaml"
    cm._source_note = ""
    cm.config = {}
    return cm


@pytest.fixture()
def scrub_env():
    """记录并清理测试期间新加的 IRECKON_TCFG_* 环境变量。"""
    before = set(os.environ)
    yield
    for key in set(os.environ) - before:
        if key.startswith("IRECKON_TCFG_"):
            os.environ.pop(key, None)


# ---------- _load_dotenv_file ----------


def test_load_dotenv_missing_file_returns_zero(tmp_path):
    assert _load_dotenv_file(tmp_path / ".env") == 0


def test_load_dotenv_parses_skips_and_precedence(tmp_path, scrub_env):
    marker = "IRECKON_TCFG_EXISTING"
    os.environ[marker] = "shell-wins"
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# 注释行\n"
        "\n"
        "no_equals_line\n"
        f'{marker}="from-file"\n'
        'IRECKON_TCFG_A="quoted value"\n'
        "IRECKON_TCFG_B='single'\n"
        "IRECKON_TCFG_C=plain\n"
        "BAD KEY=x\n",
        encoding="utf-8",
    )
    loaded = _load_dotenv_file(env_file)
    assert loaded == 3  # 已存在的变量不计入也不覆盖
    assert os.environ[marker] == "shell-wins"
    assert os.environ["IRECKON_TCFG_A"] == "quoted value"
    assert os.environ["IRECKON_TCFG_B"] == "single"
    assert os.environ["IRECKON_TCFG_C"] == "plain"


def test_load_dotenv_empty_result_no_debug_noise(tmp_path):
    # 全部是注释/空行 → loaded=0，文件存在但不产生任何载入
    env_file = tmp_path / ".env"
    env_file.write_text("# only comment\n\n", encoding="utf-8")
    assert _load_dotenv_file(env_file) == 0


# ---------- _resolve_base_dir ----------


def test_resolve_base_dir_prefers_ireckon_home(tmp_path, monkeypatch):
    monkeypatch.setenv("IRECKON_HOME", str(tmp_path))
    assert ConfigManager._resolve_base_dir() == tmp_path.resolve()


def test_resolve_base_dir_meipass_branch(tmp_path, monkeypatch):
    monkeypatch.delenv("IRECKON_HOME", raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert ConfigManager._resolve_base_dir() == tmp_path.resolve()


def test_resolve_base_dir_falls_back_to_cwd(monkeypatch):
    monkeypatch.delenv("IRECKON_HOME", raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", None, raising=False)
    assert ConfigManager._resolve_base_dir() == Path.cwd().resolve()


# ---------- 单例与代理 ----------


def test_singleton_identity():
    assert ConfigManager() is ConfigManager()


def test_module_proxy_delegates_get():
    from app.core.config import config_manager

    assert config_manager.get("不存在键_xyz", "默认值") == "默认值"


# ---------- _load_config 回退链与容错 ----------


def test_load_config_missing_both_uses_empty(tmp_path):
    cm = make_cm(tmp_path)
    cm._load_config()
    assert cm.config == {}
    assert cm._source_note == ""
    assert cm.config_path.name == "config.yaml"


def test_load_config_falls_back_to_example(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        "server:\n  port: 9999\n", encoding="utf-8"
    )
    cm = make_cm(tmp_path)
    cm._load_config()
    assert cm._source_note == "example"
    assert cm.get("server.port") == 9999


def test_load_config_switches_back_when_main_reappears(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        "server:\n  port: 9999\n", encoding="utf-8"
    )
    cm = make_cm(tmp_path)
    cm._load_config()
    assert cm.config_path.name == "config.example.yaml"
    # 主配置重新出现（如 auth 回写 token）→ 切回主配置
    (tmp_path / "config.yaml").write_text("server:\n  port: 8000\n", encoding="utf-8")
    cm._load_config()
    assert cm.config_path.name == "config.yaml"
    assert cm.get("server.port") == 8000


def test_load_config_hash_short_circuit_vs_force_reexpand(tmp_path, scrub_env):
    (tmp_path / "config.yaml").write_text(
        'sec:\n  key: "${IRECKON_TCFG_K:-fallback}"\n', encoding="utf-8"
    )
    os.environ.pop("IRECKON_TCFG_K", None)
    cm = make_cm(tmp_path)
    cm._load_config()
    assert cm.get("sec.key") == "fallback"
    # 文件字节不变 → 非强制加载被哈希短路，环境变量变更不生效
    os.environ["IRECKON_TCFG_K"] = "changed"
    cm._load_config()
    assert cm.get("sec.key") == "fallback"
    # 强制重载绕过短路，重新展开
    cm._load_config(force=True)
    assert cm.get("sec.key") == "changed"


def test_load_config_parse_failure_keeps_previous_good(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("sec:\n  n: 1\n", encoding="utf-8")
    cm = make_cm(tmp_path)
    cm._load_config()
    assert cm.get("sec.n") == 1
    # 编辑器半写入状态 → 解析失败保留上一份好配置
    cfg.write_text("{broken", encoding="utf-8")
    cm._load_config(force=True)
    assert cm.get("sec.n") == 1


def test_load_config_parse_failure_without_previous_gives_empty(tmp_path):
    (tmp_path / "config.yaml").write_text("{broken", encoding="utf-8")
    cm = make_cm(tmp_path)
    cm._load_config()
    assert cm.config == {}


# ---------- ${VAR:-default} 展开 ----------


def test_expand_env_vars_default_syntax(tmp_path, scrub_env):
    cm = make_cm(tmp_path)
    os.environ.pop("IRECKON_TCFG_V", None)
    assert cm._expand_env_vars("${IRECKON_TCFG_V:-fb}") == "fb"
    os.environ["IRECKON_TCFG_V"] = "real"
    assert cm._expand_env_vars("${IRECKON_TCFG_V:-fb}") == "real"


def test_expand_env_vars_walks_dicts_lists(tmp_path, scrub_env):
    cm = make_cm(tmp_path)
    os.environ["IRECKON_TCFG_N"] = "v"
    data = {"a": ["${IRECKON_TCFG_N}", "lit"], "b": {"c": "${IRECKON_TCFG_N}"}, "d": 1}
    out = cm._expand_env_vars(data)
    assert out == {"a": ["v", "lit"], "b": {"c": "v"}, "d": 1}
    assert data["a"] == ["${IRECKON_TCFG_N}", "lit"]  # 原输入不被原地修改


# ---------- save_value 行级写回 ----------

SAVE_YAML = (
    "server:\n"
    "  host: 0.0.0.0\n"
    "  port: 8000\n"
    "\n"
    "# 顶部注释\n"
    "auth:\n"
    '  api_key: "old"  # 行内注释\n'
    "  token: t0\n"
)


def test_save_value_rejects_non_section_key(tmp_path):
    cm = make_cm(tmp_path)
    with pytest.raises(ValueError):
        cm.save_value("onlysection", 1)
    with pytest.raises(ValueError):
        cm.save_value("a.b.c", 1)


def test_save_value_rewrites_in_place_preserving_comments(tmp_path):
    (tmp_path / "config.yaml").write_text(SAVE_YAML, encoding="utf-8")
    cm = make_cm(tmp_path)
    cm._load_config()
    assert cm.save_value("auth.api_key", "new-key") is True
    text = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert 'api_key: "new-key"  # 行内注释' in text  # 值替换+行内注释保留
    assert "port: 8000" in text and "# 顶部注释" in text  # 其余内容原样
    assert cm.get("auth.api_key") == "new-key"  # 写回后强制重载生效
    assert not list(tmp_path.glob("*.tmp"))  # 临时文件已原子替换消化


def test_save_value_missing_key_returns_false(tmp_path):
    (tmp_path / "config.yaml").write_text(SAVE_YAML, encoding="utf-8")
    cm = make_cm(tmp_path)
    cm._load_config()
    assert cm.save_value("auth.no_such_key", 1) is False


def test_save_value_materializes_main_from_example(tmp_path):
    example = tmp_path / "config.example.yaml"
    example.write_text('auth:\n  api_key: "old"\n', encoding="utf-8")
    cm = make_cm(tmp_path)
    cm.config_path = example  # 处于 example 回退态
    cm.example_path = example
    assert cm.save_value("auth.api_key", "fresh") is True
    # 物化出 config.yaml 并写入其中；模板保持原样（防止把运行时密钥写进 git 跟踪文件）
    main = tmp_path / "config.yaml"
    assert main.exists()
    assert cm.config_path == main.resolve()
    assert "fresh" in main.read_text(encoding="utf-8")
    assert "fresh" not in example.read_text(encoding="utf-8")


def test_save_value_materialize_failure_returns_false(tmp_path):
    cm = make_cm(tmp_path)
    # 处于回退态但 example 缺失 → 物化读模板失败
    cm.config_path = tmp_path / "config.example.yaml"
    cm.example_path = cm.config_path
    assert cm.save_value("auth.api_key", "x") is False


def test_save_value_read_failure_returns_false(tmp_path):
    # config_path 是目录（名为 config.yaml）→ 读文本失败走兜底
    # （不先 _load_config：read_bytes 在其 try 块外，目录形态会在加载期就炸）
    (tmp_path / "config.yaml").mkdir()
    cm = make_cm(tmp_path)
    cm._config_hash = "dummy"  # 跳过哈希比对路径，直接测写回兜底
    assert cm.save_value("auth.api_key", "x") is False


def test_save_value_write_failure_returns_false(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(SAVE_YAML, encoding="utf-8")
    cm = make_cm(tmp_path)
    cm._load_config()

    def boom(self, target):
        raise OSError("disk gone")

    monkeypatch.setattr(Path, "replace", boom)
    try:
        assert cm.save_value("auth.token", "x") is False
    finally:
        monkeypatch.undo()
        for leftover in tmp_path.glob("*.yaml.tmp"):
            leftover.unlink(missing_ok=True)
    assert "token: t0" in (tmp_path / "config.yaml").read_text(encoding="utf-8")


# ---------- get / get_all / get_redacted ----------


def test_get_traverses_and_defaults_safely(tmp_path):
    cm = make_cm(tmp_path)
    cm.config = {"a": {"b": 1}, "scalar": 7}
    assert cm.get("a.b") == 1
    assert cm.get("a.x", "dflt") == "dflt"
    assert cm.get("scalar.deep", "dflt") == "dflt"  # 穿透非 dict 节点安全返回默认
    assert cm.get("", "root-miss") == "root-miss"


def test_get_all_returns_independent_deepcopy(tmp_path):
    cm = make_cm(tmp_path)
    cm.config = {"a": {"b": [1, 2]}}
    snapshot = cm.get_all()
    snapshot["a"]["b"].append(3)
    assert cm.get("a.b") == [1, 2]


def test_get_redacted_masks_sensitive_keys_recursively(tmp_path):
    cm = make_cm(tmp_path)
    cm.config = {
        "ai_pool": {
            "API_KEY": "secret1",
            "Token": "secret2",
            "client_secret": "secret3",
            "my_password": "secret4",
            "credential_id": "secret5",
            "normal": "visible",
            "instances": [{"api_key": "k2", "model": "m"}],
        },
    }
    red = cm.get_redacted()
    inst = red["ai_pool"]["instances"][0]
    assert red["ai_pool"]["API_KEY"] == "***"
    assert red["ai_pool"]["Token"] == "***"
    assert red["ai_pool"]["client_secret"] == "***"
    assert red["ai_pool"]["my_password"] == "***"
    assert red["ai_pool"]["credential_id"] == "***"
    assert red["ai_pool"]["normal"] == "visible"
    assert inst["api_key"] == "***" and inst["model"] == "m"
    assert cm.get("ai_pool.API_KEY") == "secret1"  # 原配置不受影响


# ---------- 监视器生命周期与热加载 handler ----------


def test_start_watcher_unavailable_logs_and_skips(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg_mod, "WATCHDOG_AVAILABLE", False)
    cm = make_cm(tmp_path)
    cm._start_watcher()
    assert cm._observer is None


def test_start_watcher_schedule_failure_degrades(tmp_path, monkeypatch):
    class ExplodingObserver:
        def schedule(self, *a, **kw):
            raise RuntimeError("no fs events")

    monkeypatch.setattr(cfg_mod, "WATCHDOG_AVAILABLE", True)
    monkeypatch.setattr(cfg_mod, "Observer", ExplodingObserver)
    cm = make_cm(tmp_path)
    cm._start_watcher()
    assert cm._observer is None  # 降级为手动重载而非崩溃


class FakeObserver:
    def __init__(self):
        self.stopped = False
        self.joined = False

    def stop(self):
        self.stopped = True

    def join(self, timeout=None):
        self.joined = timeout == 1.0


def test_shutdown_stops_observer_and_none_is_noop(tmp_path):
    cm = make_cm(tmp_path)
    cm.shutdown()  # observer 为 None 时静默返回
    obs = FakeObserver()
    cm._observer = obs
    cm.shutdown()
    assert obs.stopped and obs.joined
    cm._observer = None


def test_change_handler_only_reloads_main_config(tmp_path, monkeypatch):
    cm = make_cm(tmp_path)
    calls = []
    monkeypatch.setattr(cm, "_load_config", lambda *a, **kw: calls.append(1))
    handler = ConfigChangeHandler(cm)

    handler.on_modified(SimpleNamespace(is_directory=True, src_path=str(tmp_path)))
    handler.on_modified(
        SimpleNamespace(is_directory=False, src_path=str(tmp_path / "other.yaml"))
    )
    assert calls == []  # 目录事件与非主配置文件均忽略

    handler.on_modified(
        SimpleNamespace(is_directory=False, src_path=str(tmp_path / "config.yaml"))
    )
    assert len(calls) == 1  # 主配置变更触发重载
