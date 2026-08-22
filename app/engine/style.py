import json
from pathlib import Path
from typing import Dict, Optional

from loguru import logger

from app.core.config import get


class StyleEngine:
    _instance: Optional["StyleEngine"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_init") and self._init:
            return
        self._init = True
        self._themes: Optional[Dict[str, Dict]] = None  # 延迟加载

    def _load_themes(self):
        theme_dir = Path(__file__).parent.parent.parent / "config" / "themes"
        if not theme_dir.exists():
            theme_dir = Path("config/themes")
        if theme_dir.exists():
            for file in theme_dir.glob("*.json"):
                try:
                    with open(file, "r", encoding="utf-8") as f:
                        theme = json.load(f)
                        self._themes[file.stem] = theme
                    logger.debug(f"加载主题: {theme.get('name', file.stem)}")
                except Exception as e:
                    logger.error(f"加载主题失败 {file}: {e}")
        else:
            logger.warning(f"主题目录不存在: {theme_dir}")

    def _ensure_themes(self) -> None:
        """首次访问时才加载主题文件。"""
        if self._themes is None:
            self._themes = {}
            self._load_themes()

    def get_theme(self, name=None):
        self._ensure_themes()
        name = name or get("ui.theme", "catgirl")
        return self._themes.get(name, self._themes.get("catgirl", {}))

    def _role_entry(self, role, theme=None):
        """取角色条目：主题文件的实际 schema 是 role_mapping[role]（name/style/avatar），
        顶层同名键仅作旧扁平格式回退——此前直读顶层导致风格注入恒为空（潜伏 bug）。"""
        t = theme or self.get_theme()
        mapping = t.get("role_mapping")
        entry = mapping.get(role) if isinstance(mapping, dict) else None
        if not isinstance(entry, dict):
            entry = {}
        return t, entry

    def render_role_name(self, role, theme=None):
        t, entry = self._role_entry(role, theme)
        return entry.get("name", t.get("name", role))

    def render_avatar(self, role, theme=None):
        t, entry = self._role_entry(role, theme)
        return entry.get("avatar", t.get("avatar", ""))

    def render_style(self, role, theme=None):
        t, entry = self._role_entry(role, theme)
        return entry.get("style", t.get("style", ""))

    def generate_agent_prompt_injection(self, role, theme_name=None):
        style = self.render_style(role, self.get_theme(theme_name))
        if not style:
            return ""
        injections = []
        if "傲娇" in style:
            injections.append("你略带傲娇，但保持专业。")
        if "活泼" in style:
            injections.append("你活泼开朗，偶尔可用'喵~'。")
        if "严格" in style:
            injections.append("你严格认真，一针见血。")
        injections.append("非代码输出尽量用短句，不超过3句话。")
        return "\n".join(injections)


style_engine = StyleEngine()
