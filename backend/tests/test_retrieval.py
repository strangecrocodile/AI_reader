"""检索服务测试：本章优先、必要时跨章扩展、命中带章节信息。"""
import pytest

from app.config import Settings
from app.db import Database
from app.rag.retrieval import NO_EVIDENCE_THRESHOLD, RetrievalService

BOOK_ID = "b1"
CH1 = "b1-ch1"
CH2 = "b1-ch2"


@pytest.fixture
def retrieval(tmp_path, monkeypatch):
    # 测试不依赖外部嵌入服务：显式关掉向量通道，只测 BM25 与检索范围
    monkeypatch.delenv("EMBEDDING_URL", raising=False)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)

    database = Database(tmp_path / "retrieval.db")
    database.init()
    database.add_book(
        {"id": BOOK_ID, "title": "检索测试教材", "created_at": "2026-01-01T00:00:00+00:00"}
    )
    database.add_chapters(
        [
            {
                "id": CH1,
                "book_id": BOOK_ID,
                "num": 1,
                "title": "第1章 函数与极限",
                "page_start": 1,
                "page_end": 2,
                "full_text": "",
            },
            {
                "id": CH2,
                "book_id": BOOK_ID,
                "num": 2,
                "title": "第2章 导数与微分",
                "page_start": 3,
                "page_end": 4,
                "full_text": "",
            },
        ]
    )
    texts = {
        CH1: [
            "函数的定义是：对每个 x 都有唯一的 y 与之对应。",
            "极限描述的是趋势，而不是某一个具体取值。",
        ],
        CH2: [
            "比值 Δy / Δx 称为平均变化率，它衡量一段区间的整体表现。",
            "让 Δx 趋于零，平均变化率趋近的那个数就定义为导数。",
        ],
    }
    sections = []
    for chapter_id, items in texts.items():
        for seq, text in enumerate(items, start=1):
            sections.append(
                {
                    "id": f"{chapter_id}-s{seq}",
                    "book_id": BOOK_ID,
                    "chapter_id": chapter_id,
                    "seq": seq,
                    "text": text,
                    "page": 1,
                    "kind": "p",
                }
            )
    database.add_sections(sections)
    return RetrievalService(database, Settings())


def test_chapter_search_keeps_chapter_id(retrieval):
    hits = retrieval.search(BOOK_ID, CH1, "极限是什么")

    assert hits
    assert hits[0]["chapter_id"] == CH1
    assert hits[0]["coverage"] >= NO_EVIDENCE_THRESHOLD


def test_scoped_search_stays_in_chapter_when_evidence_is_local(retrieval):
    result = retrieval.search_scoped(BOOK_ID, CH1, "极限是什么")

    assert result["scope"] == "chapter"
    assert all(hit["chapter_id"] == CH1 for hit in result["hits"])


def test_scoped_search_expands_to_other_chapters_when_chapter_is_silent(retrieval):
    result = retrieval.search_scoped(BOOK_ID, CH1, "平均变化率是什么")

    assert result["scope"] == "book"
    assert result["hits"]
    assert result["hits"][0]["chapter_id"] == CH2, "本章没讲，应回退到第 2 章的证据"
    assert result["hits"][0]["coverage"] >= NO_EVIDENCE_THRESHOLD


def test_scoped_search_returns_empty_when_nothing_matches(retrieval):
    result = retrieval.search_scoped(BOOK_ID, CH1, "今天晚上的月亮有多圆")

    assert result["hits"] == []


def test_invalidate_book_clears_caches(retrieval):
    # 本章无依据的提问才会触发全书索引构建
    retrieval.search_scoped(BOOK_ID, CH1, "平均变化率是什么")
    assert retrieval._bm25_cache and retrieval._book_cache

    retrieval.invalidate_book(BOOK_ID)

    assert not retrieval._bm25_cache
    assert not retrieval._book_cache
    assert BOOK_ID not in retrieval._vectors_built
