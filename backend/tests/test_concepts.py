"""知识点抽取与概念图谱测试。

覆盖：规则回退取名、LLM 结果清洗（非法锚点/伪概念/去重）、LLM 异常回退、
抽取缓存、跨章概念合并、前置边与未解析前置、顺序边不重复。
"""
import json

import pytest

from app.db import Database
from app.llm.client import LLMError, extract_json_array
from app.services import concepts as cs

BOOK = {"id": "b1", "title": "测试教材", "created_at": "2026-01-01T00:00:00+00:00"}


class FakeCloudLLM:
    """可控的云端 LLM 替身：回复固定文本，并记录调用次数。"""

    kind = "cloud"
    name = "fake-cloud"

    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def chat(self, messages, temperature=0.3, max_tokens=1500):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "concepts.db")
    database.init()
    database.add_book(BOOK)
    database.add_chapters(
        [
            {
                "id": "b1-ch1",
                "book_id": "b1",
                "num": 1,
                "title": "第一章 极限",
                "page_start": 1,
                "page_end": 2,
                "full_text": "",
            },
            {
                "id": "b1-ch2",
                "book_id": "b1",
                "num": 2,
                "title": "第二章 导数",
                "page_start": 3,
                "page_end": 4,
                "full_text": "",
            },
        ]
    )
    return database


def seed_chapter(database, chapter_id, paragraphs, page=1):
    sections = [
        {
            "id": f"{chapter_id}-s{i + 1}",
            "book_id": "b1",
            "chapter_id": chapter_id,
            "seq": i + 1,
            "text": text,
            "page": page,
            "kind": "p",
        }
        for i, text in enumerate(paragraphs)
    ]
    anchors = [
        {
            "id": s["id"],
            "book_id": "b1",
            "chapter_id": chapter_id,
            "section_id": s["id"],
            "text": s["text"],
            "page": s["page"],
        }
        for s in sections
    ]
    database.add_sections(sections)
    database.add_anchors(anchors)
    return sections, anchors


# ---------- 规则回退 ----------


def test_rule_extract_takes_head_noun_as_concept_name():
    paragraphs = [
        {"anchor": "s1", "text": "我们把 1 称为这个数列的极限，尽管每一项都不等于 1。"},
        {"anchor": "s2", "text": "就称 y 是关于 x 的一个函数，记作 y = f(x)。"},
        {"anchor": "s3", "text": "把这个数定义为函数在点 x₀ 处的瞬时变化率，也就是导数。"},
    ]

    result = cs.rule_extract(paragraphs, "b1-ch1")

    assert [c["concept"] for c in result] == ["极限", "函数", "瞬时变化率"]
    assert [c["anchors"] for c in result] == [["s1"], ["s2"], ["s3"]]
    assert all(c["definition"] for c in result)
    assert all(c["prerequisites"] == [] for c in result)
    assert [c["id"] for c in result] == ["b1-ch1-kp001", "b1-ch1-kp002", "b1-ch1-kp003"]


def test_rule_extract_ignores_paragraphs_without_definition_marker():
    paragraphs = [{"anchor": "s1", "text": "本节先回顾函数的基本概念，再讨论极限。"}]

    assert cs.rule_extract(paragraphs, "b1-ch1") == []


def test_paragraphs_of_skips_headings_formulas_and_short_text():
    sections = [
        {"id": "s1", "kind": "heading"},
        {"id": "s2", "kind": "formula"},
        {"id": "s3", "kind": "p"},
        {"id": "s4", "kind": "p"},
    ]
    anchors = [
        {"id": "s1", "section_id": "s1", "text": "1.1 函数的概念"},
        {"id": "s2", "section_id": "s2", "text": "f(x) = 2x + 1"},
        {"id": "s3", "section_id": "s3", "text": "短句"},
        {"id": "s4", "section_id": "s4", "text": "我们把 1 称为这个数列的极限，尽管它不等于 1。"},
    ]

    result = cs.paragraphs_of(sections, anchors)

    assert result == [{"anchor": "s4", "text": anchors[3]["text"]}]


# ---------- LLM 抽取与清洗 ----------


def test_extract_json_array_tolerates_fence_and_noise():
    raw = '好的，结果如下：\n```json\n[{"concept": "导数"}]\n```\n以上。'

    assert extract_json_array(raw) == [{"concept": "导数"}]


def test_extract_json_array_rejects_non_array():
    with pytest.raises(LLMError):
        extract_json_array('{"concept": "导数"}')


def test_normalize_concepts_filters_and_dedupes():
    raw = [
        {
            "concept": "导数",
            "definition": "函数在一点处的瞬时变化率。",
            "prerequisites": ["极限", "导数", "极限"],
            "anchors": ["s1", "不存在的锚点"],
        },
        {"concept": "导数", "definition": "重复概念应被去掉。", "anchors": ["s2"]},
        {"concept": "因此我们", "definition": "伪概念。", "anchors": ["s1"]},
        {"concept": "这是一个特别长的概念名称超过十六个字", "definition": "太长。", "anchors": ["s1"]},
        {"concept": "切线斜率", "definition": "", "anchors": ["s1"]},
        {"concept": "微分", "definition": "函数增量的线性主部。", "anchors": ["s1", "s2"]},
    ]

    result = cs.normalize_concepts(raw, {"s1", "s2"}, "b1-ch1")

    assert [c["concept"] for c in result] == ["导数", "微分"]
    assert result[0]["prerequisites"] == ["极限"]
    assert result[0]["anchors"] == ["s1"]
    assert result[1]["anchors"] == ["s1", "s2"]


def test_llm_extract_falls_back_to_rule_on_invalid_json(db):
    _, anchors = seed_chapter(
        db,
        "b1-ch1",
        ["我们把 1 称为这个数列的极限，尽管它不等于 1。"],
    )
    llm = FakeCloudLLM("抱歉，我无法按要求输出。")

    payload = cs.extract_concepts(db, llm, db.get_chapter("b1", "b1-ch1"), db.sections_of("b1", "b1-ch1"), anchors)

    assert payload["method"] == "rule"
    assert [c["concept"] for c in payload["concepts"]] == ["极限"]


def test_llm_extract_uses_cloud_result_when_valid(db):
    _, anchors = seed_chapter(
        db,
        "b1-ch1",
        ["一个数列的通项无限接近某个常数时就称它收敛，这个常数就是极限。"],
    )
    reply = json.dumps(
        [
            {
                "concept": "极限",
                "definition": "数列通项无限接近的那个常数。",
                "prerequisites": [],
                "anchors": ["b1-ch1-s1"],
            }
        ],
        ensure_ascii=False,
    )
    llm = FakeCloudLLM(reply)

    payload = cs.extract_concepts(db, llm, db.get_chapter("b1", "b1-ch1"), db.sections_of("b1", "b1-ch1"), anchors)

    assert payload["method"] == "llm"
    assert payload["concepts"][0]["concept"] == "极限"
    assert payload["concepts"][0]["anchors"] == ["b1-ch1-s1"]


def test_mock_llm_never_calls_model_and_uses_rule(db):
    from app.llm.client import MockLLM

    _, anchors = seed_chapter(db, "b1-ch1", ["我们把 1 称为这个数列的极限。"])
    llm = MockLLM()

    payload = cs.extract_concepts(db, llm, db.get_chapter("b1", "b1-ch1"), db.sections_of("b1", "b1-ch1"), anchors)

    assert payload["method"] == "rule"
    assert payload["model"] == "mock-rule"


def test_extract_concepts_is_cached_per_chapter(db):
    _, anchors = seed_chapter(db, "b1-ch1", ["我们把 1 称为这个数列的极限。"])
    llm = FakeCloudLLM(
        json.dumps([{"concept": "极限", "definition": "数列逼近的常数。", "anchors": ["b1-ch1-s1"]}])
    )
    chapter = db.get_chapter("b1", "b1-ch1")
    sections = db.sections_of("b1", "b1-ch1")

    first = cs.extract_concepts(db, llm, chapter, sections, anchors)
    second = cs.extract_concepts(db, llm, chapter, sections, anchors)

    assert llm.calls == 1
    assert first == second


# ---------- 建图 ----------


def _block(chapter_id, concepts, method="llm"):
    return {
        "chapter_id": chapter_id,
        "chapter_title": f"{chapter_id} 标题",
        "method": method,
        "concepts": concepts,
    }


def _concept(name, prerequisites=None, anchors=None, definition="定义。"):
    return {
        "concept": name,
        "definition": definition,
        "prerequisites": prerequisites or [],
        "anchors": anchors or [],
    }


def test_build_graph_merges_same_concept_across_chapters():
    graph = cs.build_concept_graph(
        [
            _block("c1", [_concept("极限", anchors=["s1"], definition="第一处定义。")]),
            _block("c2", [_concept("极限", anchors=["s2", "s3"])]),
        ],
        {"c1": {"status": "learned", "mastery": 100}, "c2": {"status": "learning", "mastery": 40}},
    )

    assert len(graph["concepts"]) == 1
    node = graph["concepts"][0]
    assert node["id"] == "极限"
    assert node["chapters"] == ["c1", "c2"]
    assert node["anchors"] == ["s1", "s2", "s3"]
    assert node["anchorCount"] == 3
    assert node["status"] == "learned"
    assert node["mastery"] == 100
    # 保留旧字段，前端旧代码仍可直接渲染
    assert node["title"] == "极限"
    assert node["chapterId"] == "c1"
    assert node["sourceId"] == "s1"
    assert node["summary"] == "第一处定义。"


def test_build_graph_builds_prerequisite_edges_and_unresolved():
    graph = cs.build_concept_graph(
        [
            _block(
                "c1",
                [
                    _concept("导数", prerequisites=["极限", "函数"]),
                    _concept("极限"),
                ],
            )
        ]
    )

    edges = {(r["source"], r["target"]): r for r in graph["relations"]}
    assert edges[("导数", "极限")]["type"] == "prerequisite"
    assert edges[("导数", "极限")]["label"] == "前置"
    # 教材里没有「函数」这个节点 → 进入 unresolved
    assert ("导数", "函数") not in edges
    assert graph["unresolved"] == [{"name": "函数", "requiredBy": ["导数"]}]
    assert graph["stats"]["prerequisiteCount"] == 1
    assert graph["stats"]["unresolvedCount"] == 1


def test_build_graph_adds_sequence_edges_without_duplicating_prerequisite_edges():
    graph = cs.build_concept_graph(
        [
            _block(
                "c1",
                [
                    _concept("极限"),
                    _concept("导数", prerequisites=["极限"]),
                    _concept("微分"),
                ],
            )
        ]
    )

    pairs = [(r["source"], r["target"], r["type"]) for r in graph["relations"]]
    # 「极限 → 导数」已有前置边（导数依赖极限），不再重复补顺序边
    assert pairs == [
        ("导数", "极限", "prerequisite"),
        ("导数", "微分", "sequence"),
    ]


def test_build_graph_skips_self_prerequisite_and_reports_stats():
    graph = cs.build_concept_graph(
        [_block("c1", [_concept("导数", prerequisites=["导数", "极限"]), _concept("极限")])]
    )

    assert all(r["source"] != r["target"] for r in graph["relations"])
    assert graph["stats"] == {
        "conceptCount": 2,
        "learnedCount": 0,
        "relationCount": 1,
        "prerequisiteCount": 1,
        "unresolvedCount": 0,
    }
    assert graph["methods"] == ["llm"]
