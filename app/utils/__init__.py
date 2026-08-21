"""
公共工具模块
"""

from pathlib import Path
from jinja2 import Environment, FileSystemLoader


def get_prompt_template_dir() -> Path:
    """获取prompt模板目录，兼容不同运行路径"""
    template_dir = Path("config/prompts")
    if template_dir.exists():
        return template_dir
    # 尝试从当前文件位置向上查找
    return Path(__file__).parent.parent.parent / "config/prompts"


def create_jinja_env() -> Environment:
    """创建Jinja2环境"""
    return Environment(
        loader=FileSystemLoader(str(get_prompt_template_dir())), autoescape=True
    )


def load_template(template_name: str) -> str:
    """加载模板文件"""
    env = create_jinja_env()
    return env.get_template(template_name).render()  # type: ignore[no-any-return]  # jinja2 缺失时 stubs 为 Any


def make_task_title(user_request: str, max_len: int = 40) -> str:
    """从用户需求生成简短标题：取第一个句子/逗号前，超长截断。"""
    if not user_request:
        return "未命名任务"
    text = " ".join(user_request.split())
    for sep in ("\n", "。", "！", "？", "；", ",", "，", "。"):
        idx = text.find(sep)
        if idx > 0:
            text = text[:idx]
            break
    text = text.strip()
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text or "未命名任务"
