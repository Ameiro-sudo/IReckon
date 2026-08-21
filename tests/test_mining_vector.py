"""挖矿检测器与向量库映射逻辑测试(补覆盖率盲区，不触真实 chromadb)。"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest

from app.security.mining import MiningDetector
from app.knowledge.vector import VectorStore, _validate_collection


# ---------- MiningDetector ----------


@pytest.fixture
def detector():
    return MiningDetector()


@pytest.mark.parametrize(
    "cmdline",
    [
        "./xmrig --donate-level 1",
        "stratum+tcp://pool.example:3333 -u user",
        "stratumssl://missing-separator 也不行但 stratum+ssl://pool:443 可以",
        "ethminer -G",
        "/opt/miner.py --start",
        "--algo randomx --url stratum+ssl://x.com:443",
        "下载自 POOL.SUPPORTXMR.COM 的任务",  # 大小写不敏感
        "f2pool.com 报告",
    ],
)
def test_detect_positives(detector, cmdline):
    assert detector.scan_command_line(cmdline) is True


@pytest.mark.parametrize(
    "cmdline",
    [
        "",
        "python main.py --serve",
        "我的 miner 游戏服务器",
        "deploy.sh normal",
        "git push origin master",
    ],
)
def test_detect_negatives(detector, cmdline):
    assert detector.scan_command_line(cmdline) is False


def test_scan_processes_with_fake_psutil(monkeypatch, detector):
    class FakeProc:
        def __init__(self, pid, cmdline):
            self.info = {"pid": pid, "cmdline": cmdline}

    class FakePsutil:
        NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        AccessDenied = type("AccessDenied", (Exception,), {})

        @staticmethod
        def process_iter(fields):
            yield FakeProc(1, ["python", "main.py"])
            yield FakeProc(2, ["./xmrig", "-o", "pool"])
            p = FakeProc(3, None)
            raise_self = FakePsutil.AccessDenied()

            def boom(*a, **k):
                raise raise_self

            p.cmdline = property(boom)
            yield p

    import types

    fake = types.SimpleNamespace(
        **{
            "process_iter": FakePsutil.process_iter,
            "NoSuchProcess": FakePsutil.NoSuchProcess,
            "AccessDenied": FakePsutil.AccessDenied,
        }
    )
    monkeypatch.setitem(sys.modules, "psutil", fake)
    hits = asyncio.run(detector.scan_processes())
    assert len(hits) == 1 and hits[0][0] == 2


def test_scan_processes_without_psutil(monkeypatch, detector):
    monkeypatch.setitem(sys.modules, "psutil", None)  # import 将抛 ImportError
    assert asyncio.run(detector.scan_processes()) == []


# ---------- vector._validate_collection / 映射逻辑 ----------


@pytest.mark.parametrize("name", ["kb_patterns", "kb-A_b9", "a" * 64])
def test_validate_collection_ok(name):
    assert _validate_collection(name) == name


@pytest.mark.parametrize("name", ["", "有空格", "多字节✨", "a" * 65])
def test_validate_collection_rejects(name):
    with pytest.raises(ValueError):
        _validate_collection(name)


def _bare_store():
    """绕过 __init__(避免真实 chromadb)，仅装配协作件。"""
    store = VectorStore.__new__(VectorStore)
    store._locks = {}
    store._collections = {}
    return store


class FakeCollection:
    def __init__(self, query_result=None):
        self.added = []
        self._qr = query_result or {
            "ids": [["i1", "i2"]],
            "documents": [["d1", "d2"]],
            "metadatas": [[{"t": 1}, {"t": 2}]],
            "distances": [[0.1, 0.2]],
        }

    def add(self, ids, documents, metadatas):
        self.added.append((ids, documents, metadatas))

    def query(self, query_texts, n_results):
        ids = self._qr["ids"][0][:n_results]
        return {
            "ids": [ids],
            "documents": [self._qr["documents"][0][:n_results]],
            "metadatas": [self._qr["metadatas"][0][:n_results]],
            "distances": [self._qr["distances"][0][:n_results]],
        }


def test_add_documents_delegates_under_lock():
    store = _bare_store()
    fake = FakeCollection()
    store._client = None
    store._get_collection = lambda name: fake
    asyncio.run(store.add_documents("kb_x", ["id1"], ["doc1"], [{"m": 1}]))
    assert fake.added == [(["id1"], ["doc1"], [{"m": 1}])]


def test_search_maps_results():
    store = _bare_store()
    store._get_collection = lambda name: FakeCollection()
    out = asyncio.run(store.search("kb_x", "查询", n_results=2))
    assert [o["id"] for o in out] == ["i1", "i2"]
    assert out[0]["distance"] == 0.1 and out[0]["metadata"] == {"t": 1}


def test_search_clamps_n_results():
    store = _bare_store()
    store._get_collection = lambda name: FakeCollection()
    out = asyncio.run(store.search("kb_x", "q", n_results=999))
    assert len(out) <= 100


def test_search_tolerates_missing_optional_fields():
    store = _bare_store()

    class Sparse(FakeCollection):
        def query(self, query_texts, n_results):
            return {
                "ids": [["only-id"]],
                "documents": [],
                "metadatas": [],
                "distances": [],
            }

    store._get_collection = lambda name: Sparse()
    out = asyncio.run(store.search("kb_x", "q"))
    assert (
        out[0]["document"] == ""
        and out[0]["metadata"] == {}
        and out[0]["distance"] == 0
    )
