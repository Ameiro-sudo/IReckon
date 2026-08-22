"""StyleEngine 补测：主题懒加载/损坏容错/回退链、渲染取值、提示词注入关键词分支。

隔离手段：monkeypatch 模块级 __file__，使 Path(__file__).parent.parent.parent
落到 tmp_path（仓库真实 config/themes 恒存在，cwd 回退分支不可达）。
"""

import json

import pytest

import app.engine.style as st


@pytest.fixture
def fresh_engine(monkeypatch, tmp_path):
    """隔离单例与主题目录。"""
    orig_instance = st.StyleEngine._instance
    themes_dir = tmp_path / "config" / "themes"
    themes_dir.mkdir(parents=True)
    monkeypatch.setattr(st, "__file__", str(tmp_path / "src" / "sub" / "style.py"))
    st.StyleEngine._instance = None
    engine = st.StyleEngine()
    yield engine, themes_dir
    st.StyleEngine._instance = orig_instance


def _write_theme(themes_dir, name, payload):
    (themes_dir / f"{name}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_get_theme_lazy_loads_on_first_access(fresh_engine):
    eng, themes_dir = fresh_engine
    assert eng._themes is None  # 构造期不加载
    _write_theme(
        themes_dir,
        "catgirl",
        {"name": "猫娘", "avatar": "🐱", "style": "傲娇活泼"},
    )
    theme = eng.get_theme()
    assert theme["name"] == "猫娘" and theme["avatar"] == "🐱"


def test_get_theme_explicit_name_and_missing_falls_back(fresh_engine):
    eng, themes_dir = fresh_engine
    _write_theme(themes_dir, "strict", {"name": "严师", "style": "严格"})
    _write_theme(themes_dir, "catgirl", {"name": "猫娘", "style": "活泼"})
    assert eng.get_theme("strict")["name"] == "严师"
    # 未知名回退 catgirl
    assert eng.get_theme("不存在的")["name"] == "猫娘"


def test_corrupt_theme_file_tolerated(fresh_engine):
    eng, themes_dir = fresh_engine
    _write_theme(themes_dir, "catgirl", {"name": "猫娘"})
    (themes_dir / "broken.json").write_text("{不是JSON", encoding="utf-8")
    assert eng.get_theme()["name"] == "猫娘"


def test_missing_themes_dir_returns_empty(monkeypatch, tmp_path):
    orig_instance = st.StyleEngine._instance
    try:
        monkeypatch.setattr(st, "__file__", str(tmp_path / "a" / "b" / "style.py"))
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)  # cwd 回退分支也落空
        st.StyleEngine._instance = None
        eng = st.StyleEngine()
        eng._ensure_themes()
        assert eng._themes == {}
        assert eng.get_theme() == {}
    finally:
        st.StyleEngine._instance = orig_instance


def test_render_helpers_read_theme_fields(fresh_engine):
    eng, themes_dir = fresh_engine
    _write_theme(
        themes_dir,
        "catgirl",
        {"name": "猫娘调度员", "avatar": "🐱", "style": "傲娇"},
    )
    assert eng.render_role_name("scheduler") == "猫娘调度员"
    assert eng.render_avatar("scheduler") == "🐱"
    assert eng.render_style("scheduler") == "傲娇"
    # 显式传入 theme 时不再查库
    assert eng.render_role_name("x", {"name": "直传"}) == "直传"


def test_prompt_injection_keyword_branches(fresh_engine):
    eng, themes_dir = fresh_engine
    _write_theme(
        themes_dir,
        "catgirl",
        {"name": "n", "style": "傲娇且严格"},
    )
    out = eng.generate_agent_prompt_injection("scheduler")
    assert "傲娇" in out and "严格" in out and "短句" in out
    assert "喵" not in out  # 活泼未命中不加喵


def test_prompt_injection_empty_style_returns_empty(fresh_engine):
    eng, themes_dir = fresh_engine
    _write_theme(themes_dir, "catgirl", {"name": "n"})
    assert eng.generate_agent_prompt_injection("scheduler") == ""


def test_prompt_injection_all_keywords(fresh_engine):
    eng, themes_dir = fresh_engine
    _write_theme(
        themes_dir,
        "catgirl",
        {"name": "n", "style": "傲娇活泼严格"},
    )
    out = eng.generate_agent_prompt_injection("scheduler", "catgirl")
    assert "喵~" in out
