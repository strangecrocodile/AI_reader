"""掌握度计算测试：公式、权重、防刷分与状态流转。

覆盖：无事件 / 仅进入 / 部分阅读 / 读完全章 / 提问互动 / 自测正确率 /
非法锚点与重复上报 / 掌握度只增不减 / 教材总进度回写。
"""
import pytest

from app.db import Database
from app.services import progress as progress_service

BOOK_ID = "b1"
CHAPTER_ID = "b1-ch1"
BODY_ANCHORS = [f"{CHAPTER_ID}-s{i}" for i in range(1, 5)]  # 4 段正文
HEADING_ANCHOR = f"{CHAPTER_ID}-s5"


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "progress.db")
    database.init()
    database.add_book(
        {"id": BOOK_ID, "title": "测试教材", "created_at": "2026-01-01T00:00:00+00:00"}
    )
    database.add_chapters(
        [
            {
                "id": CHAPTER_ID,
                "book_id": BOOK_ID,
                "num": 1,
                "title": "第1章 函数与极限",
                "page_start": 1,
                "page_end": 2,
                "full_text": "",
            },
            {
                "id": "b1-ch2",
                "book_id": BOOK_ID,
                "num": 2,
                "title": "第2章 导数与微分",
                "page_start": 3,
                "page_end": 4,
                "full_text": "",
            },
        ]
    )
    sections = [
        {
            "id": anchor,
            "book_id": BOOK_ID,
            "chapter_id": CHAPTER_ID,
            "seq": index,
            "text": f"第 {index} 段正文。",
            "page": 1,
            "kind": "p",
        }
        for index, anchor in enumerate(BODY_ANCHORS, start=1)
    ]
    sections.append(
        {
            "id": HEADING_ANCHOR,
            "book_id": BOOK_ID,
            "chapter_id": CHAPTER_ID,
            "seq": 5,
            "text": "1.1 函数的概念",
            "page": 1,
            "kind": "heading",
        }
    )
    database.add_sections(sections)
    database.add_anchors(
        [
            {
                "id": section["id"],
                "book_id": BOOK_ID,
                "chapter_id": CHAPTER_ID,
                "section_id": section["id"],
                "text": section["text"],
                "page": section["page"],
            }
            for section in sections
        ]
    )
    return database


def read(db, anchors):
    return progress_service.record_event(db, BOOK_ID, CHAPTER_ID, "read", anchor_ids=anchors)


def ask(db, question):
    return progress_service.record_event(db, BOOK_ID, CHAPTER_ID, "ask", question=question)


def quiz(db, correct):
    return progress_service.record_event(db, BOOK_ID, CHAPTER_ID, "quiz", correct=correct)


# ---------- 基础状态 ----------


def test_no_events_means_planned_and_zero_mastery(db):
    result = progress_service.compute_progress(db, BOOK_ID, CHAPTER_ID)

    assert result["status"] == "planned"
    assert result["mastery"] == 0
    assert result["signals"] == {
        "paragraphsRead": 0,
        "paragraphsTotal": 4,
        "askCount": 0,
        "quizCount": 0,
        "quizAccuracy": None,
        "completed": False,
    }


def test_open_event_marks_learning_without_inflating_mastery(db):
    result = progress_service.record_event(db, BOOK_ID, CHAPTER_ID, "open")

    assert result["status"] == "learning"
    assert result["mastery"] == 0, "只是打开章节，不该凭空产生掌握度"


# ---------- 覆盖度 ----------


def test_reading_every_paragraph_uses_only_coverage_weight(db):
    result = read(db, BODY_ANCHORS)

    assert result["signals"]["paragraphsRead"] == 4
    assert result["signals"]["paragraphsTotal"] == 4
    # 无自测记录时：覆盖度 66.7 + 互动度 33.3
    assert [(item["key"], item["weight"]) for item in result["breakdown"]] == [
        ("coverage", 66.7),
        ("engagement", 33.3),
        ("quiz", 0.0),
    ]
    assert result["computed"] == 67
    assert result["status"] == "learning"
    assert "自测权重" in result["note"]


def test_partial_reading_scores_proportionally(db):
    result = read(db, BODY_ANCHORS[:2])

    assert result["signals"]["paragraphsRead"] == 2
    assert result["computed"] == 33  # 0.5 × 66.7


def test_heading_anchors_do_not_count_as_paragraphs(db):
    result = read(db, [HEADING_ANCHOR])

    assert result["signals"]["paragraphsTotal"] == 4, "小节标题不计入覆盖度分母"
    assert result["signals"]["paragraphsRead"] == 0
    assert result["computed"] == 0


def test_unknown_anchor_ids_are_ignored(db):
    result = read(db, ["不存在的锚点", "ch9-s1"])

    assert result["signals"]["paragraphsRead"] == 0
    assert db.learning_events_of(BOOK_ID, CHAPTER_ID) == []


def test_duplicate_read_reports_are_stored_once(db):
    read(db, BODY_ANCHORS[:2])
    result = read(db, BODY_ANCHORS[:2])

    assert result["signals"]["paragraphsRead"] == 2
    assert len(db.learning_events_of(BOOK_ID, CHAPTER_ID)) == 2


# ---------- 互动与自测 ----------


def test_reading_all_and_asking_twice_reaches_learned(db):
    read(db, BODY_ANCHORS)
    ask(db, "为什么一定要取极限？")
    result = ask(db, "平均变化率和导数是什么关系？")

    # 66.7 + 33.3 × (2/5) = 80
    assert result["signals"]["askCount"] == 2
    assert result["computed"] == 80
    assert result["status"] == "learned"


def test_repeated_questions_count_once_and_cap_at_five(db):
    read(db, BODY_ANCHORS)
    ask(db, "同一个问题")
    ask(db, "同一个问题")
    assert progress_service.compute_progress(db, BOOK_ID, CHAPTER_ID)["signals"]["askCount"] == 1

    for index in range(8):
        ask(db, f"第 {index} 个不同问题")
    result = progress_service.compute_progress(db, BOOK_ID, CHAPTER_ID)

    assert result["signals"]["askCount"] == 9, "提问数如实记录"
    engagement = next(item for item in result["breakdown"] if item["key"] == "engagement")
    assert engagement["value"] == 1.0, "但计分时封顶 5 次，防止刷分"


def test_quiz_events_restore_quiz_weight(db):
    read(db, BODY_ANCHORS)
    ask(db, "问题一")
    result = quiz(db, True)

    assert [(item["key"], item["weight"]) for item in result["breakdown"]] == [
        ("coverage", 50.0),
        ("engagement", 25.0),
        ("quiz", 25.0),
    ]
    # 50 + 25 × 0.2 + 25 = 80
    assert result["computed"] == 80
    assert result["status"] == "learned"
    assert result["note"] == "已计入自测正确率"


def test_quiz_accuracy_blends_correct_and_wrong_answers(db):
    read(db, BODY_ANCHORS)
    quiz(db, True)
    quiz(db, True)
    result = quiz(db, False)

    assert result["signals"]["quizCount"] == 3
    assert result["signals"]["quizAccuracy"] == 0.667
    # 50 + 0 + 25 × 0.667 ≈ 66.7
    assert result["computed"] == 67


def test_breakdown_scores_add_up_to_computed_mastery(db):
    read(db, BODY_ANCHORS[:3])
    ask(db, "问题一")
    quiz(db, True)
    result = quiz(db, False)

    assert sum(item["score"] for item in result["breakdown"]) == pytest.approx(
        result["computed"], abs=0.5
    )


# ---------- 状态与回写 ----------


def test_complete_event_marks_learned_even_without_reading(db):
    result = progress_service.record_event(db, BOOK_ID, CHAPTER_ID, "complete")

    assert result["status"] == "learned"
    assert result["signals"]["completed"] is True


def test_mastery_never_decreases_below_manual_override(db):
    db.upsert_chapter_progress(BOOK_ID, CHAPTER_ID, "learning", 90)

    result = read(db, BODY_ANCHORS[:1])

    assert result["computed"] == 17  # 0.25 × 66.7
    assert result["mastery"] == 90, "生效值只增不减，但 computed 如实反映事件"


def test_book_progress_is_average_of_chapters(db):
    read(db, BODY_ANCHORS)  # 第 1 章 67%
    result = progress_service.refresh_progress(db, BOOK_ID, CHAPTER_ID)

    book = db.get_book(BOOK_ID)
    assert result["mastery"] == 67
    assert round(book["progress_pct"]) == 34  # 两章平均：(67 + 0) / 2
