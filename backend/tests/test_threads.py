"""追问线程测试：创建、追加消息、标题、排序与删除。"""
import pytest

from app.db import Database
from app.services import threads as thread_service

BOOK_ID = "b1"
CH1 = "b1-ch1"
CH2 = "b1-ch2"


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "threads.db")
    database.init()
    database.add_book(
        {"id": BOOK_ID, "title": "测试教材", "created_at": "2026-01-01T00:00:00+00:00"}
    )
    database.add_chapters(
        [
            {
                "id": chapter_id,
                "book_id": BOOK_ID,
                "num": index,
                "title": f"第{index}章 标题",
                "page_start": index,
                "page_end": index,
                "full_text": "",
            }
            for index, chapter_id in enumerate([CH1, CH2], start=1)
        ]
    )
    return database


def test_create_thread_binds_selection(db):
    thread = thread_service.create_thread(db, BOOK_ID, CH1, anchor_id="b1-ch1-s2", selected_text="比值 Δy / Δx 的极限存在")

    assert thread["id"].startswith("th-")
    assert thread["bookId"] == BOOK_ID
    assert thread["chapterId"] == CH1
    assert thread["anchorId"] == "b1-ch1-s2"
    assert thread["selectedText"] == "比值 Δy / Δx 的极限存在"
    assert thread["messages"] == []
    assert thread["title"].startswith("比值 Δy / Δx")


def test_get_thread_returns_none_for_unknown(db):
    assert thread_service.get_thread(db, "th-nope") is None


def test_append_message_records_sources_and_scope(db):
    thread = thread_service.create_thread(db, BOOK_ID, CH1, selected_text="选中的原文")

    thread_service.append_message(db, thread["id"], "user", "这段想表达什么？")
    thread_service.append_exchange(
        db,
        thread["id"],
        "导数是什么？",
        {
            "answer": "导数是瞬时变化率 [1]。",
            "sources": ["b1-ch2-s1"],
            "sourceDetails": [
                {"id": "b1-ch2-s1", "page": 3, "text": "…", "chapterId": CH2, "chapterTitle": "第2章 标题"}
            ],
            "scope": "book",
        },
    )

    loaded = thread_service.get_thread(db, thread["id"])
    # append_message 一条 + append_exchange 一问一答
    assert [message["role"] for message in loaded["messages"]] == ["user", "user", "assistant"]
    answer = loaded["messages"][-1]
    assert answer["text"] == "导数是瞬时变化率 [1]。"
    assert answer["sources"] == ["b1-ch2-s1"]
    assert answer["sourceDetails"][0]["chapterId"] == CH2
    assert answer["scope"] == "book"
    # 标题优先用选中原文
    assert loaded["title"] == "选中的原文"


def test_title_falls_back_to_first_question(db):
    thread = thread_service.create_thread(db, BOOK_ID, CH1)
    thread_service.append_message(db, thread["id"], "user", "这个概念与上一章有什么关系？")

    assert thread_service.get_thread(db, thread["id"])["title"] == "这个概念与上一章有什么关系？"


def test_list_threads_is_scoped_and_ordered_by_recent(db):
    first = thread_service.create_thread(db, BOOK_ID, CH1, selected_text="第一条")
    second = thread_service.create_thread(db, BOOK_ID, CH1, selected_text="第二条")
    thread_service.create_thread(db, BOOK_ID, CH2, selected_text="别的章节")
    thread_service.append_message(db, first["id"], "user", "把第一条顶上来")

    listed = thread_service.list_threads(db, BOOK_ID, CH1)

    assert [thread["id"] for thread in listed] == [first["id"], second["id"]]


def test_delete_thread_removes_messages(db):
    thread = thread_service.create_thread(db, BOOK_ID, CH1, selected_text="待删除")
    thread_service.append_message(db, thread["id"], "user", "问题")

    assert thread_service.delete_thread(db, thread["id"]) is True
    assert thread_service.get_thread(db, thread["id"]) is None
    assert db.thread_messages(thread["id"]) == []
    assert thread_service.delete_thread(db, thread["id"]) is False
