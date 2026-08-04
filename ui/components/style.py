import streamlit as st
from pathlib import Path
import json

def load_theme(theme_name: str) -> dict:
    theme_path = Path("config/themes") / f"{theme_name}.json"
    if theme_path.exists():
        with open(theme_path, "r", encoding="utf-8") as f:
            return json.load(f)
    fallback_path = Path(__file__).parent.parent.parent / "config" / "themes" / f"{theme_name}.json"
    if fallback_path.exists():
        with open(fallback_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "name": "默认",
        "role_mapping": {
            "scheduler": {"name": "调度官", "avatar": "📋"},
            "executor": {"name": "工程师", "avatar": "💻"},
            "reviewer_efficiency": {"name": "架构喵", "avatar": "🏗️"},
            "reviewer_correctness": {"name": "测试喵", "avatar": "🔬"},
            "user": {"name": "你", "avatar": "👤"},
        }
    }

def get_theme(theme_name: str) -> dict:
    return load_theme(theme_name)

def inject_custom_css():
    st.markdown("""
    <style>
    .stApp {
        background-color: #0e1117;
        color: #e0e0e0;
    }
    section[data-testid="stSidebar"] {
        background-color: #1a1c23;
    }
    .stChatMessage {
        border-radius: 18px !important;
    }
    .stButton button {
        border-radius: 8px;
        background-color: #2e7d32;
        color: white;
    }
    </style>
    """, unsafe_allow_html=True)
