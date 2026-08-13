"""执行器代码解析逻辑测试：多文件产物、补丁、diff 应用。"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from app.agents.executor import ExecutorAgent
from app.llm.pool import AICapability


def make_executor():
    cap = AICapability(
        id="t1",
        name="Test",
        endpoint="http://localhost:1/v1",
        model="auto",
        api_key="",
        tags=["python"],
        max_context=4096,
    )
    return ExecutorAgent(cap)


def test_parse_single_file():
    ex = make_executor()
    out = ex._parse_artifacts("print('hello')")
    assert out == {"main.py": "print('hello')"}


def test_parse_multi_file():
    ex = make_executor()
    text = "//// filename: a.py\nprint(1)\n//// filename: b.py\nprint(2)"
    out = ex._parse_artifacts(text)
    assert set(out.keys()) == {"a.py", "b.py"}
    assert out["a.py"] == "print(1)"
    assert out["b.py"] == "print(2)"


def test_parse_artifacts_strips_markdown_fences():
    ex = make_executor()
    text = '//// filename: a.py\n```python\nprint(1)\n```\n//// filename: b.py\nplain text'
    out = ex._parse_artifacts(text)
    assert out["a.py"] == "print(1)"
    assert out["b.py"] == "plain text"


def test_parse_artifacts_cleans_filename_backticks():
    ex = make_executor()
    text = '//// filename: src/main.py```\n```python\nprint(1)\n```'
    out = ex._parse_artifacts(text)
    assert "src/main.py" in out
    assert out["src/main.py"] == "print(1)"


def test_syntax_errors_detection():
    ex = make_executor()
    assert ex._syntax_errors({"ok.py": "def f():\n    pass"}) == []
    errs = ex._syntax_errors({"bad.py": "def f(:", "note.md": "## x"})
    assert len(errs) == 1
    assert "bad.py" in errs[0]


def test_parse_patches_multiple_files():
    ex = make_executor()
    text = (
        "PATCH: a.py\n"
        "@@ -1,3 +1,3 @@\n"
        " print(1)\n"
        "-print(2)\n"
        "+print(22)\n"
        "PATCH: b.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-x = 1\n"
        "+x = 2\n"
    )
    patches = ex._parse_patches(text)
    assert set(patches.keys()) == {"a.py", "b.py"}
    assert "-print(2)" in patches["a.py"]


def test_apply_unified_diff():
    ex = make_executor()
    original = "a\nb\nc\n"
    patch = "@@ -1,3 +1,3 @@\n a\n-b\n+c\n"
    result = ex._apply_unified_diff(original, patch)
    assert result == "a\nc\nc\n"


def test_apply_diff_add_line():
    ex = make_executor()
    original = "x = 1\n"
    patch = "@@ -1,1 +1,2 @@\n x = 1\n+y = 2\n"
    result = ex._apply_unified_diff(original, patch)
    assert result == "x = 1\ny = 2\n"
