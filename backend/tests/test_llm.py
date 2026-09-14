"""模型输出解析契约与「解析失败 → 规则回退」测试。

覆盖：`extract_json` / `extract_json_array` 的类型校验（非对象、非数组、围栏、杂讯），
以及 lesson / plan 在模型返回合法但结构不对的 JSON 时**回退规则生成，而不是抛错**。

回归背景：`extract_json` 原先不做类型校验，`[1, 2]` 是合法 JSON 所以能通过，
但调用方的 `.get()` 会抛 `AttributeError`——不在它们的回退捕获列表内，直接 500。
"""
import pytest

from app.db import Database
from app.llm.client import LLMError, extract_json, extract_json_array
from app.services import lesson as lesson_service
from app.services import plan as plan_service

BOOK_ID = "b1"
CHAPTER_ID = "b1-ch1"


class FakeCloudLLM:
    """可控的云端 LLM 替身：返回固定文本，用来触发各种解析失败路径。"""

    kind = "cloud"
    name = "fake-cloud"

    def __init__(self, reply):
        self.reply = reply

    def chat(self, messages, temperature=0.3, max_tokens=1500):
        return self.reply


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "llm.db")
    database.init()
    sections = [
        {
            "id": f"{CHAPTER_ID}-s{i}",
            "book_id": BOOK_ID,
            "chapter_id": CHAPTER_ID,
            "seq": i,
            "text": f"第 {i} 段教材原文，用于验证解析失败后的规则回退。",
            "page": i,
            "kind": "p",
        }
        for i in range(1, 4)
    ]
    database.add_book_bundle(
        {"id": BOOK_ID, "title": "测试教材", "created_at": "2026-01-01T00:00:00+00:00"},
        [
            {
                "id": CHAPTER_ID,
                "book_id": BOOK_ID,
                "num": 1,
                "title": "第1章 测试",
                "page_start": 1,
                "page_end": 3,
                "full_text": "".join(s["text"] for s in sections),
            }
        ],
        sections,
        [
            {
                "id": s["id"],
                "book_id": BOOK_ID,
                "chapter_id": CHAPTER_ID,
                "section_id": s["id"],
                "text": s["text"],
                "page": s["page"],
            }
            for s in sections
        ],
    )
    return database


def test_extract_json_rejects_json_array():
    """`[1, 2]` 是合法 JSON 但不是对象，必须抛 LLMError 而不是留给调用方崩。"""
    with pytest.raises(LLMError):
        extract_json("[1, 2]")


def test_extract_json_rejects_non_json():
    with pytest.raises(LLMError):
        extract_json("模型今天不太想输出 JSON")


def test_extract_json_tolerates_fence_and_surrounding_noise():
    assert extract_json('说明如下：\n```json\n{"items": [1]}\n```\n以上。') == {"items": [1]}


def test_extract_json_array_rejects_output_without_array():
    with pytest.raises(LLMError):
        extract_json_array("模型今天没有输出数组")


def test_extract_json_array_lifts_array_out_of_object():
    """容忍模型把数组包在对象里（`{"items": [...]}`）：只取数组本身。"""
    assert extract_json_array('{"items": [{"concept": "极限"}]}') == [{"concept": "极限"}]


def test_lesson_falls_back_when_model_returns_json_array(db):
    """模型返回 JSON 数组时，备课回退规则生成而不是 500。"""
    chapter = db.chapters_of(BOOK_ID)[0]
    payload = lesson_service.get_lesson(
        db,
        FakeCloudLLM("[1, 2]"),
        chapter,
        db.sections_of(BOOK_ID, CHAPTER_ID),
        db.anchors_of(BOOK_ID, CHAPTER_ID),
    )

    assert payload["points"], "应回退到规则生成的讲解，而不是空结果"
    assert payload["overview"]


def test_plan_falls_back_when_model_returns_json_array(db):
    """模型返回 JSON 数组时，学习计划回退规则生成而不是 500。"""
    plan = plan_service.get_plan(
        db, FakeCloudLLM("[1, 2]"), db.get_book(BOOK_ID), db.chapters_of(BOOK_ID)
    )

    assert plan["items"], "应回退到规则生成的学习计划"
