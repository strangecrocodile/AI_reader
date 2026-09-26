"""笔记：绑在原文锚点上，跳得回、跟着教材一起删。

判据的重点在两条约束上：
- **不接受乱报的锚点**——收下一条指向不存在位置的笔记，「回到原文」就永远是坏的；
- **跟着教材一起被删**——`notes` 有指向 books 的外键，但删书是逐表显式删的，
  漏一张表就会留下孤儿（`test_db_delete.py` 盯的就是这件事）。
"""
import pytest

from app.config import Settings
from app.llm.client import MockLLM
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path)
    settings.embedding_url = ""
    settings.embedding_api_key = ""
    settings.auto_demo = False
    app = create_app(settings=settings, db_path=tmp_path / "n.db", llm=MockLLM())

    db = app.state.db
    db.add_book({"id": "bk1", "title": "笔记测试教材", "created_at": "2026-01-01T00:00:00+00:00"})
    db.add_chapters([
        {"id": "c1", "book_id": "bk1", "num": 1, "title": "第1章 函数", "page_start": 1, "page_end": 3, "full_text": ""},
        {"id": "c2", "book_id": "bk1", "num": 2, "title": "第2章 极限", "page_start": 4, "page_end": 6, "full_text": ""},
    ])
    db.add_sections([
        {"id": "s1", "book_id": "bk1", "chapter_id": "c1", "seq": 1, "page": 1,
         "kind": "p", "text": "函数是一种对应关系。"},
        {"id": "s2", "book_id": "bk1", "chapter_id": "c2", "seq": 1, "page": 4,
         "kind": "p", "text": "极限描述的是趋势。"},
    ])

    from fastapi.testclient import TestClient

    return TestClient(app)


def _create(client, **overrides):
    payload = {
        "bookId": "bk1",
        "chapterId": "c1",
        "anchorId": "s1",
        "quotedText": "函数是一种对应关系",
        "body": "这里要和上一章的映射一起看。",
    }
    payload.update(overrides)
    return client.post("/api/notes", json=payload)


def test_create_and_list_a_note(client):
    res = _create(client)

    assert res.status_code == 201
    note = res.json()
    assert note["anchorId"] == "s1"
    assert note["body"] == "这里要和上一章的映射一起看。"
    assert note["id"]

    listed = client.get("/api/books/bk1/chapters/c1/notes").json()
    assert [n["id"] for n in listed] == [note["id"]]


def test_note_is_scoped_to_its_chapter(client):
    _create(client)

    assert len(client.get("/api/books/bk1/chapters/c1/notes").json()) == 1
    assert client.get("/api/books/bk1/chapters/c2/notes").json() == []


def test_book_notes_carry_the_chapter_title(client):
    """跨章列出来时，每条笔记都得说清自己属于哪一章，否则列表没法读。"""
    _create(client)
    _create(client, chapterId="c2", anchorId="s2", quotedText="极限描述的是趋势", body="趋势不等于取值。")

    notes = client.get("/api/books/bk1/notes").json()

    assert len(notes) == 2
    assert {n["chapterTitle"] for n in notes} == {"第1章 函数", "第2章 极限"}


def test_anchor_from_another_chapter_is_rejected(client):
    """乱报锚点要被挡住：收下它，「回到原文」就永远跳不到东西。"""
    res = _create(client, anchorId="s2")  # s2 属于 c2

    assert res.status_code == 422
    assert "无法记录笔记" in res.json()["detail"]
    assert client.get("/api/books/bk1/chapters/c1/notes").json() == []


def test_empty_body_is_rejected(client):
    """空笔记只会变成列表里的噪音。"""
    res = _create(client, body="   ")

    assert res.status_code == 422


def test_note_without_anchor_is_allowed(client):
    """整章感想不绑定具体段落，也是合法的笔记。"""
    res = _create(client, anchorId="", quotedText="", body="这一章整体在讲什么，先记个大纲。")

    assert res.status_code == 201
    assert res.json()["anchorId"] == ""


def test_update_changes_body_only(client):
    note = _create(client).json()

    res = client.patch(f"/api/notes/{note['id']}", json={"body": "改过的内容"})

    assert res.status_code == 200
    updated = res.json()
    assert updated["body"] == "改过的内容"
    # 锚点是笔记的身份，不该被改写
    assert updated["anchorId"] == note["anchorId"]
    assert updated["quotedText"] == note["quotedText"]


def test_update_missing_note_is_404(client):
    assert client.patch("/api/notes/nope", json={"body": "x"}).status_code == 404


def test_delete_note(client):
    note = _create(client).json()

    assert client.delete(f"/api/notes/{note['id']}").status_code == 204
    assert client.get("/api/books/bk1/chapters/c1/notes").json() == []
    assert client.delete(f"/api/notes/{note['id']}").status_code == 404


def test_notes_on_missing_book_are_404(client):
    assert client.get("/api/books/nope/notes").status_code == 404
    assert _create(client, bookId="nope").status_code == 404


def test_deleting_the_book_takes_its_notes_with_it(client):
    """笔记有外键，但删书是逐表显式删的——漏一张表就留下孤儿。"""
    _create(client)
    _create(client, chapterId="c2", anchorId="s2", body="第二章的笔记")

    assert client.delete("/api/books/bk1").status_code == 204

    db = client.app.state.db
    assert db.notes_of_book("bk1") == []
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM notes").fetchone()[0] == 0
