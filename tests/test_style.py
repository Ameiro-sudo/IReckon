"""StyleEngine 补测 + 嵌套主题修复验证。

真实主题 schema 是 role_mapping[role]（name/style/avatar），旧代码直读顶层键
导致风格注入恒为空——本文件同时锁定修复后行为与加载器路径。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest

import app.engine.style as style_mod
from app.engine.style import StyleEngine, style_engine


def _engine():
    """裸实例：绕过进程级单例，_themes 置 None 走惰性加载。"""
    e = object.__new__(StyleEngine)
    e._themes = None
    return e


@pytest.fixture()
def theme_cwd(tmp_path, monkeypatch):
    """把模块 __file__ 指到 tmp 包结构并 chdir——加载器的首选路径(包相对)与
    cwd 回退路径都落进 tmp，不碰仓库真实主题；真实主题另有专属回归用例。"""
    tdir = tmp_path / "config" / "themes"
    tdir.mkdir(parents=True)
    fake_mod_file = tmp_path / "_pkg" / "engine" / "style.py"
    monkeypatch.setattr(style_mod, "__file__", str(fake_mod_file))
    monkeypatch.chdir(tmp_path)
    return tdir


def _write_theme(tdir, stem, data):
    (tdir / f"{stem}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def test_singleton_identity():
    assert StyleEngine() is style_engine


@pytest.fixture()
def fresh_singleton(theme_cwd):
    """重置进程级单例并保存/恢复原状态——全量运行时其他测试可能已初始化过它。"""
    cls = style_mod.StyleEngine
    saved = cls._instance
    saved_state = None
    if saved is not None:
        saved_state = (
            getattr(saved, "_init", False),
            getattr(saved, "_themes", None),
        )
        cls._instance = None
    yield theme_cwd
    # 无论原先是否已初始化都复位：saved=None 时置回 None 让下一次调用重新走真实加载
    cls._instance = saved
    if saved is not None and saved_state is not None:
        saved._init, saved._themes = saved_state


def test_double_init_keeps_state(fresh_singleton):
    _write_theme(fresh_singleton, "a", {"name": "A"})
    e = StyleEngine()
    assert e.get_theme("a")["name"] == "A"  # 首次 init 触发加载
    e.__init__()  # 二次 __init__ 应被 _init 守卫拦下，已加载主题不清空
    assert e.get_theme("a")["name"] == "A"


def test_lazy_load_reads_real_schema_and_skips_broken(theme_cwd, monkeypatch):
    _write_theme(
        theme_cwd,
        "nested",
        {
            "name": "嵌套主题",
            "role_mapping": {
                "executor": {"name": "开发小张", "style": "专业、偶尔吐槽"}
            },
        },
    )
    (theme_cwd / "broken.json").write_text("{broken", encoding="utf-8")
    e = _engine()
    assert e.get_theme("nested")["name"] == "嵌套主题"  # 惰性加载成功
    assert "broken" not in e._themes  # 坏 JSON 跳过不炸
    # 修复点：角色数据从 role_mapping[role] 读取（默认主题钉到 nested）
    monkeypatch.setattr(style_mod, "get", lambda k, d=None: "nested")
    assert e.render_role_name("executor") == "开发小张"
    assert e.render_style("executor") == "专业、偶尔吐槽"


def test_missing_themes_dir_yields_empty(theme_cwd, monkeypatch):
    monkeypatch.chdir(theme_cwd.parent)  # 无 config/themes → 告警回退
    e = _engine()
    e.get_theme("anything")
    assert e._themes == {}


def test_get_theme_unknown_falls_back_to_catgirl_then_empty(theme_cwd):
    _write_theme(theme_cwd, "other", {"name": "Other"})
    e = _engine()
    assert e.get_theme("不存在") == {}  # 无 catgirl 可回退 → {}
    _write_theme(theme_cwd, "catgirl", {"name": "猫娘风"})
    e2 = _engine()
    assert e2.get_theme("不存在")["name"] == "猫娘风"  # 有 catgirl 则回退命中


def test_render_defaults_for_unknown_role(theme_cwd, monkeypatch):
    _write_theme(
        theme_cwd,
        "t",
        {"name": "主题名", "role_mapping": {"scheduler": {"name": "管家"}}},
    )
    monkeypatch.setattr(style_mod, "get", lambda k, d=None: "t")
    e = _engine()
    assert e.render_role_name("未知角色") == "主题名"  # 条目缺失回退顶层 name
    assert e.render_style("未知角色") == "" and e.render_avatar("未知角色") == ""
    assert e.render_role_name("scheduler") == "管家"


def test_flat_legacy_theme_still_supported(theme_cwd, monkeypatch):
    # 旧扁平格式（无 role_mapping）向后兼容：顶层键兜底
    _write_theme(theme_cwd, "flat", {"name": "FlatName", "style": "傲娇"})
    monkeypatch.setattr(style_mod, "get", lambda k, d=None: "flat")
    e = _engine()
    assert e.render_role_name("any") == "FlatName"
    assert e.render_style("any") == "傲娇"


def test_injection_matrix(theme_cwd, monkeypatch):
    _write_theme(
        theme_cwd,
        "rich",
        {
            "name": "R",
            "role_mapping": {
                "executor": {"style": "傲娇且严格"},
                "creative": {"style": "活泼"},
                "learner": {},  # 有条目但无 style → 注入为空
            },
        },
    )
    monkeypatch.setattr(style_mod, "get", lambda k, d=None: "rich")
    e = _engine()
    full = e.generate_agent_prompt_injection("executor")
    assert "傲娇" in full and "严格" in full and "短句" in full
    lively = e.generate_agent_prompt_injection("creative")
    assert "活泼" in lively and "喵" in lively and "傲娇" not in lively
    assert e.generate_agent_prompt_injection("learner") == ""
    assert e.generate_agent_prompt_injection("不存在角色") == ""


def test_repo_real_themes_load_and_shape():
    # 真仓主题（catgirl/programmer）按嵌套 schema 可被正确消费——回归锁定
    e = StyleEngine()
    prog = e.get_theme("programmer")
    if not prog:
        pytest.skip("programmer 主题不存在")
    assert e.render_style("reviewer_efficiency", prog) != ""
    assert "严格" in e.generate_agent_prompt_injection(
        "reviewer_efficiency", "programmer"
    )
