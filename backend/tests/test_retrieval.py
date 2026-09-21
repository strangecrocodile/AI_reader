"""检索服务测试：本章内检索 vs 全书检索（本章加权）、命中带章节信息。"""
import pytest

from app.config import Settings
from app.db import Database
from app.rag.retrieval import NO_EVIDENCE_THRESHOLD, RetrievalService

BOOK_ID = "b1"
CH1 = "b1-ch1"
CH2 = "b1-ch2"
#: 两章各放一句**完全相同**的段落，用来验证全书检索里「本章优先」：
#: BM25 打分一样时，只有 `CHAPTER_BOOST` 能决定谁排前面。
SHARED_SENTENCE = "本节的重点概念都会先给出定义，再举例说明。"


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
            SHARED_SENTENCE,
        ],
        CH2: [
            "比值 Δy / Δx 称为平均变化率，它衡量一段区间的整体表现。",
            "让 Δx 趋于零，平均变化率趋近的那个数就定义为导数。",
            SHARED_SENTENCE,
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


def test_book_search_reaches_other_chapters_even_when_current_chapter_matches(retrieval):
    """本章命中 ≠ 只给本章——这正是「拿不到定义」的根因。

    教材把定义放在总论章、把例题放在具体章节是常态。旧做法（本章够了就不查全书）
    在命中本章的那一刻就停手，模型于是永远看不到那一章的定义。这里要求：本章命中的
    同时，其它章节真正相关的段落照样进结果。
    """
    result = retrieval.search_book(BOOK_ID, CH1, "函数的定义是什么")

    assert {hit["chapter_id"] for hit in result["hits"]} == {CH1, CH2}
    assert result["hits"][0]["chapter_id"] == CH1, "本章相关度最高，仍应排第一"
    assert result["scope"] == "book"


def test_book_search_prefers_current_chapter_on_ties(retrieval):
    """两章有同样的句子时本章排前面——加权只影响排序，不排除别章。"""
    result = retrieval.search_book(BOOK_ID, CH2, SHARED_SENTENCE)

    assert result["hits"][0]["chapter_id"] == CH2
    assert {hit["chapter_id"] for hit in result["hits"]} == {CH1, CH2}


def test_book_search_scope_is_chapter_when_hits_are_all_local(retrieval):
    """全落本章时 scope 报 chapter，前端据此不提示「含其他章节」。"""
    result = retrieval.search_book(BOOK_ID, CH1, "极限是什么")

    assert result["hits"]
    assert result["scope"] == "chapter"
    assert all(hit["chapter_id"] == CH1 for hit in result["hits"])
    assert result["hits"][0]["coverage"] >= NO_EVIDENCE_THRESHOLD


def test_book_search_returns_empty_when_nothing_matches(retrieval):
    result = retrieval.search_book(BOOK_ID, CH1, "今天晚上的月亮有多圆")

    assert result["hits"] == []


def test_book_search_crosses_chapters_when_current_chapter_is_silent(retrieval):
    result = retrieval.search_book(BOOK_ID, CH1, "平均变化率是什么")

    assert result["hits"][0]["chapter_id"] == CH2, "本章没讲，命中应来自第 2 章"
    assert result["hits"][0]["coverage"] >= NO_EVIDENCE_THRESHOLD
    assert result["scope"] == "book"


def test_invalidate_book_clears_caches(retrieval):
    # 全书检索建的是全书索引（_book_cache），不碰按章建的 _bm25_cache
    retrieval.search_book(BOOK_ID, CH1, "平均变化率是什么")
    assert retrieval._book_cache
    assert not retrieval._bm25_cache

    retrieval.invalidate_book(BOOK_ID)

    assert not retrieval._book_cache
    assert BOOK_ID not in retrieval._vectors_built
