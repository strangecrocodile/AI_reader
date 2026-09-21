"""问答证据的组织方式：从全书取材，上限 10 段。

需求是「从教材所有相关内容里提炼」，这要求模型真的拿到那些内容，于是有两道约束：

1. 证据来自**全书**，不是「本章优先、本章够了就停」——教材把总述与定义放在靠前的
   总论章、把例题放在具体章节是常态，停在第一处命中就永远拿不到定义；
2. 上限 **10 段**（早先是 3 段）。实测 3 段约 480 字，材料不够提炼；全书 top-10 约
   1600 字且条条是教材原文，第 12 名才开始出现明显无关的段落。

反过来也要钉住：不相关的章节不会被硬塞进来（BM25 零分的段落不进结果），否则「取 10 段」
就成了「凑 10 段」。
"""
import pytest

from app.config import Settings
from app.db import Database
from app.rag.retrieval import RetrievalService
from app.services import ask

BOOK_ID = "b1"
CH1 = "b1-ch1"
CH2 = "b1-ch2"
CH3 = "b1-ch3"
#: 只在第 1、2 章出现的查询词，第 3 章完全没有
TOPIC = "聚类分析"
SECTIONS_PER_CHAPTER = 6


@pytest.fixture
def store(tmp_path, monkeypatch):
    """一张手工造的书：两章各 6 段都讲了 TOPIC，第 3 章一句没提。"""
    monkeypatch.delenv("EMBEDDING_URL", raising=False)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)

    db = Database(tmp_path / "evidence.db")
    db.init()
    db.add_book({"id": BOOK_ID, "title": "证据组织测试教材", "created_at": "2026-01-01T00:00:00+00:00"})
    db.add_chapters(
        [
            {"id": cid, "book_id": BOOK_ID, "num": num, "title": title,
             "page_start": 1, "page_end": 9, "full_text": ""}
            for num, (cid, title) in enumerate(
                [(CH1, "第1章 总论"), (CH2, "第2章 方法"), (CH3, "第3章 附录")], start=1
            )
        ]
    )

    sections = []
    for cid in (CH1, CH2):
        for seq in range(1, SECTIONS_PER_CHAPTER + 1):
            sections.append(
                {
                    "id": f"{cid}-s{seq}",
                    "book_id": BOOK_ID,
                    "chapter_id": cid,
                    "seq": seq,
                    "text": f"{TOPIC}的第 {seq} 条说明：样本按相似度归并成若干类别。",
                    "page": seq,
                    "kind": "p",
                }
            )
    for seq in (1, 2):
        sections.append(
            {
                "id": f"{CH3}-s{seq}",
                "book_id": BOOK_ID,
                "chapter_id": CH3,
                "seq": seq,
                "text": f"附录第 {seq} 页：今天是晴天，无关内容。",
                "page": seq,
                "kind": "p",
            }
        )
    db.add_sections(sections)
    # 与 `services/ingest.py` 一致：锚点 id 就是段落 id（前端回跳、按锚点直取都靠它）
    db.add_anchors(
        [
            {
                "id": s["id"],
                "book_id": BOOK_ID,
                "chapter_id": s["chapter_id"],
                "section_id": s["id"],
                "text": s["text"],
                "page": s["page"],
            }
            for s in sections
        ]
    )
    return db


@pytest.fixture
def retrieval(store):
    return RetrievalService(store, Settings())


def test_evidence_spans_the_whole_book_up_to_ten(store, retrieval):
    """一次问答能拿到 10 段、且跨章——这才是「从全书相关内容里提炼」的材料量。"""
    prepared = ask._retrieve(store, retrieval, BOOK_ID, CH1, TOPIC)

    assert prepared is not None
    evidence = prepared["evidence"]
    assert len(evidence) == ask.MAX_EVIDENCE == 10
    assert {item["chapter_id"] for item in evidence} == {CH1, CH2}
    assert prepared["scope"] == "book"
    assert len(prepared["sourceDetails"]) == len(evidence)


def test_evidence_carries_page_and_chapter_for_traceability(store, retrieval):
    """每段都得带页码和章节名——依据不可核对就等于没有依据。"""
    evidence = ask._retrieve(store, retrieval, BOOK_ID, CH1, TOPIC)["evidence"]

    for item in evidence:
        assert item["anchor_id"]
        assert isinstance(item["page"], int)
        assert item["text"]
        assert item["chapter_title"].startswith("第")
        # 前端回跳用的是同一个 id：锚点 id 与段落 id 同值
        assert store.get_anchor(item["anchor_id"])["text"] == item["text"]


def test_irrelevant_chapter_is_not_padded_in(store, retrieval):
    """上限是 10 段，不是「凑够 10 段」：与问题零重合的章节不该进证据。"""
    evidence = ask._retrieve(store, retrieval, BOOK_ID, CH1, TOPIC)["evidence"]

    assert CH3 not in {item["chapter_id"] for item in evidence}
