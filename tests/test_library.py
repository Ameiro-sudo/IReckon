"""工具零件库测试(补覆盖率盲区)：CRUD/搜索、入库扫描门禁(fail-closed与降级)。"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest

import app.security.scanner as scanner_mod
from app.tools.library import add_part, delete_part, get_part, search


def _patch_scanner(monkeypatch, available=True, findings=None):
    async def avail():
        return available

    async def scan(code, language):
        return findings or []

    monkeypatch.setattr(scanner_mod.code_scanner, "ensure_available", avail)
    monkeypatch.setattr(scanner_mod.code_scanner, "scan", scan)


async def test_add_and_get_part_roundtrip(session_db, monkeypatch):
    _patch_scanner(monkeypatch)
    pid = await add_part(
        name="加法器",
        description="两数相加",
        language="python",
        code="def add(a, b):\n    return a + b\n",
        input_schema={"a": "num"},
        output_schema={"r": "num"},
        tags=["math"],
        created_by="tester",
    )
    part = await get_part(pid)
    assert part["name"] == "加法器"
    assert part["input_schema"] == {"a": "num"}
    assert part["tags"] == ["math"]
    assert part["created_by"] == "tester"


async def test_get_part_missing_returns_none(session_db):
    assert await get_part("part-deadbeef") is None


async def test_delete_part(session_db, monkeypatch):
    _patch_scanner(monkeypatch)
    pid = await add_part("t", "d", "python", "x = 1", {}, {}, [], "t")
    assert await delete_part(pid) is True
    assert await get_part(pid) is None
    assert await delete_part(pid) is False  # 二次删除


async def test_search_by_query_and_tag(session_db, monkeypatch):
    _patch_scanner(monkeypatch)
    p1 = await add_part(
        "哈希计算", "计算md5", "python", "def h():\n    pass\n", {}, {}, ["crypto"], "t"
    )
    p2 = await add_part(
        "日期格式化",
        "格式化日期",
        "python",
        "def d():\n    pass\n",
        {},
        {},
        ["time"],
        "t",
    )

    by_name = await search(query="哈希")
    assert [p["part_id"] for p in by_name] == [p1]
    by_tag = await search(tags=["time"])
    assert [p["part_id"] for p in by_tag] == [p2]
    both = await search(query="不存在的东西")
    assert both == []


# ---------- 入库扫描门禁 ----------


async def test_add_part_fail_closed_when_scanner_unavailable(session_db, monkeypatch):
    _patch_scanner(monkeypatch, available=False)
    with pytest.raises(ValueError, match="fail-closed"):
        await add_part("x", "d", "python", "code", {}, {}, [], "t")


async def test_add_part_scan_fail_open_degrades(session_db, monkeypatch):
    _patch_scanner(monkeypatch, available=False)

    # get 在 library.py 中是 from-import 的本地绑定，必须打在它的命名空间
    import app.tools.library as lib_mod

    orig_get = lib_mod.get

    def fake_get(key, default=None):
        if key == "security.scan_fail_open":
            return True
        return orig_get(key, default)

    monkeypatch.setattr(lib_mod, "get", fake_get)
    pid = await add_part("降级入库", "d", "python", "code", {}, {}, [], "t")
    assert pid.startswith("part-")


async def test_add_part_high_risk_rejected(session_db, monkeypatch):
    findings = [
        {"issue_severity": "HIGH", "issue_text": "eval 使用"},
        {"issue_severity": "LOW", "issue_text": "小问题"},
    ]
    _patch_scanner(monkeypatch, available=True, findings=findings)
    with pytest.raises(ValueError, match="高危"):
        await add_part("危险零件", "d", "python", "eval('1')", {}, {}, [], "t")


async def test_add_part_low_findings_pass(session_db, monkeypatch):
    findings = [{"severity": "LOW", "issue_text": "小问题"}]
    _patch_scanner(monkeypatch, available=True, findings=findings)
    pid = await add_part("安全零件", "d", "python", "x=1", {}, {}, [], "t")
    assert pid.startswith("part-")


async def test_add_part_scan_crash_passes_with_log(session_db, monkeypatch):
    async def broken_avail():
        raise RuntimeError("扫描器炸了")

    monkeypatch.setattr(scanner_mod.code_scanner, "ensure_available", broken_avail)
    # 扫描环节异常按"放行但记录"处理(与 fail-closed 的"不可用"语义区分)
    pid = await add_part("容错入库", "d", "python", "code", {}, {}, [], "t")
    assert pid.startswith("part-")
