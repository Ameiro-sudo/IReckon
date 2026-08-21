async def _noop_async(*a, **kw):
    return None


"""知识文件库测试(补覆盖率盲区)：类型白名单、2MB 上限、落盘+DB 双写(向量库打桩)。"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest

import app.knowledge.files as kf_mod
from app.core.database import db
from app.knowledge.files import FileKnowledgeBase, _validate_entry_type


def test_validate_type_accepts_normal():
    assert _validate_entry_type("patterns") == "patterns"
    assert _validate_entry_type("learn_notes_2") == "learn_notes_2"


@pytest.mark.parametrize(
    "bad", ["", "Patterns", "1abc", "a" * 33, "with-dash", "空 格", "../evil"]
)
def test_validate_type_rejects_bad(bad):
    with pytest.raises(ValueError):
        _validate_entry_type(bad)


async def test_add_entry_rejects_oversized_content(session_db, monkeypatch):
    kb = FileKnowledgeBase()
    monkeypatch.setattr(kf_mod.vector_store, "add_documents", _noop_async)
    with pytest.raises(ValueError, match="2MB"):
        await kb.add_entry("patterns", "太大", "x" * (2 * 1024 * 1024 + 1))


async def test_add_entry_writes_file_and_db_row(session_db, monkeypatch):
    captured = {}

    async def fake_add_documents(collection, ids, documents, metadatas):
        captured.update(
            {"collection": collection, "ids": ids, "docs": documents}
        )

    monkeypatch.setattr(kf_mod.vector_store, "add_documents", fake_add_documents)
    kb = FileKnowledgeBase()
    entry_id = await kb.add_entry(
        "patterns",
        "测试条目",
        "核心内容",
        source="unit-test",
        tags=["t1"],
    )
    # 文件落盘
    f = kb.base_dir / "patterns" / f"{entry_id}.txt"
    assert f.exists() and f.read_text(encoding="utf-8") == "核心内容"
    # DB 行存在
    row = await db.fetch_one(
        "SELECT title, source FROM knowledge_entries WHERE entry_id=?", (entry_id,)
    )
    assert row is not None and row[0] == "测试条目" and row[1] == "unit-test"
    # 向量库收到正确 collection 与文档
    assert captured["collection"] == "kb_patterns"
    assert captured["ids"] == [entry_id]
    assert captured["docs"] == ["核心内容"]


async def test_add_entry_invalid_type_raises_before_io(session_db, monkeypatch):
    monkeypatch.setattr(kf_mod.vector_store, "add_documents", _noop_async)
    kb = FileKnowledgeBase()
    with pytest.raises(ValueError, match="非法知识类型"):
        await kb.add_entry("../evil", "标题", "内容")


