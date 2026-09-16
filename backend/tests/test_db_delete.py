"""删教材的存储层测试：重点是**别留下孤儿**。

为什么单独一个文件盯着这件事：`sections` / `anchors` / `explanations` / `plans`
这四张表没有指向 `books` 的外键，`ON DELETE CASCADE` 管不到它们。而
`PRAGMA foreign_keys = ON` 会让「靠级联」看起来是有效的——测试必须逐表直查，
不能只断言 `get_book(...) is None`（那在留下 4000 条孤儿时也照样通过）。
"""
import pytest

from app.db import Database

#: 没有外键指向 books 的四张表——删书必须显式清掉
ORPHAN_PRONE = ("sections", "anchors", "explanations", "plans")


def _seed(database: Database, book_id: str) -> None:
    """造一本带完整下游数据的书（含四张无外键表）。"""
    database.add_book({"id": book_id, "title": f"教材{book_id}", "created_at": "2026-01-01T00:00:00+00:00"})
    chapter_id = f"{book_id}-ch1"
    database.add_chapters(
        [
            {
                "id": chapter_id,
                "book_id": book_id,
                "num": 1,
                "title": "第1章 标题",
                "page_start": 1,
                "page_end": 3,
                "full_text": "正文",
            }
        ]
    )
    section_id = f"{book_id}-s1-1"
    database.add_sections(
        [
            {
                "id": section_id,
                "book_id": book_id,
                "chapter_id": chapter_id,
                "seq": 1,
                "text": "第一段",
                "page": 1,
                "kind": "p",
            }
        ]
    )
    database.add_anchors(
        [
            {
                "id": section_id,
                "book_id": book_id,
                "chapter_id": chapter_id,
                "section_id": section_id,
                "text": "第一段",
                "page": 1,
            }
        ]
    )
    database.upsert_explanation(book_id, chapter_id, {"outline": ["知识点"]}, "mock")
    database.upsert_plan(book_id, {"days": []}, "mock")
    database.upsert_concepts(book_id, chapter_id, {"concepts": [{"name": "概念"}]}, "mock")
    database.upsert_chapter_progress(book_id, chapter_id, "learning", 30)
    database.add_learning_event(book_id, chapter_id, "open")
    database.add_thread(
        {
            "id": f"{book_id}-th1",
            "book_id": book_id,
            "chapter_id": chapter_id,
            "anchor_id": section_id,
            "selected_text": "第一段",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )
    database.add_thread_message(f"{book_id}-th1", "user", "为什么？")


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "delete.db")
    database.init()
    _seed(database, "keep")
    _seed(database, "drop")
    return database


def _count(database: Database, table: str, book_id: str) -> int:
    with database.connect() as conn:
        return conn.execute(f"SELECT count(*) FROM {table} WHERE book_id=?", (book_id,)).fetchone()[0]


def test_delete_book_removes_every_child_table(db):
    db.delete_book("drop")

    assert db.get_book("drop") is None
    assert db.chapters_of("drop") == []
    for table in ORPHAN_PRONE:
        assert _count(db, table, "drop") == 0, f"{table} 里还留着已删教材的行"


def test_delete_book_removes_events_progress_and_threads(db):
    """这几张表有外键级联，但仍然逐张确认——级联一旦被谁关掉不会有人发现。"""
    db.delete_book("drop")

    for table in ("learning_events", "chapter_progress", "concepts", "threads"):
        assert _count(db, table, "drop") == 0, f"{table} 里还留着已删教材的行"
    assert db.get_thread("drop-th1") is None
    assert db.thread_messages("drop-th1") == []


def test_delete_book_leaves_other_books_intact(db):
    """删除必须精确到一本书。写坏 WHERE 的代价是用户丢一整架书。"""
    before = {table: _count(db, table, "keep") for table in ORPHAN_PRONE}

    db.delete_book("drop")

    assert db.get_book("keep") is not None
    assert len(db.chapters_of("keep")) == 1
    for table, count in before.items():
        assert _count(db, table, "keep") == count, f"{table} 里另一本教材的数据被误删"
    assert db.get_thread("keep-th1") is not None


def test_delete_book_is_idempotent(db):
    """删两次不该报错——路由层靠 `get_book` 先判 404，存储层只需不炸。"""
    db.delete_book("drop")
    db.delete_book("drop")

    assert db.get_book("drop") is None


def test_delete_book_keeps_ocr_task_history(db):
    """`ocr_tasks` 是有意保留的任务日志：它记录了「这本教材是怎么来的」。
    删掉教材后 book_id 会成为悬空字符串，但没有任何代码 join 它。"""
    db.add_ocr_task(
        {
            "id": "t1",
            "status": "done",
            "filename": "scan.pdf",
            "title": "扫描教材",
            "total_pages": 10,
            "done_pages": 10,
            "book_id": "drop",
            "message": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )

    db.delete_book("drop")

    task = db.get_ocr_task("t1")
    assert task is not None
    assert task["book_id"] == "drop"
