"""
公共工具模块
"""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from typing import Optional


def get_prompt_template_dir() -> Path:
    """获取prompt模板目录，兼容不同运行路径"""
    template_dir = Path("config/prompts")
    if template_dir.exists():
        return template_dir
    # 尝试从当前文件位置向上查找
    return Path(__file__).parent.parent.parent / "config/prompts"


def create_jinja_env() -> Environment:
    """创建Jinja2环境"""
    return Environment(loader=FileSystemLoader(str(get_prompt_template_dir())))


def load_template(template_name: str) -> str:
    """加载模板文件"""
    env = create_jinja_env()
    return env.get_template(template_name).render()