"""全书搜索：用户心里已经有目标，只想把它找出来。

与问答是两条不同的需求：问答要的是「我没懂，给我讲」，搜索要的是「我知道书里有这句，
帮我定位」。此前只有前者，于是想找一个位置只能提一个问题，再从回答的依据里倒推。
"""
import pytest

from app.config import Settings
from app.main import create_app
from app.llm.client import MockLLM


@pytest.fixture
def book_client(tmp_path):
    """一本两章的书：定义在第 1 章，例题在第 2 章（教材的常见排布）。"""
    settings = Settings(data_dir=tmp_path)
    settings.embedding_url = ""
    settings.embedding_api_key = ""
    settings.auto_demo = False
    app = create_app(settings=settings, db_path=tmp_path / "s.db", llm=MockLLM())

    database = app.state.db
    database.add_book({"id": "bk1", "title": "搜索测试教材", "created_at": "2026-01-01T00:00:00+00:00"})
    database.add_chapters([
        {"id": "c1", "book_id": "bk1", "num": 1, "title": "第1章 总论", "page_start": 1, "page_end": 4, "full_text": ""},
        {"id": "c2", "book_id": "bk1", "num": 2, "title": "第2章 例题", "page_start": 5, "page_end": 9, "full_text": ""},
    ])
    database.add_sections([
        {"id": "s1", "book_id": "bk1", "chapter_id": "c1", "seq": 1, "page": 2,
         "kind": "p", "text": "梯度消失指的是反向传播时梯度逐层变小，深层网络因此难以训练。"},
        {"id": "s2", "book_id": "bk1", "chapter_id": "c1", "seq": 2, "page": 3,
         "kind": "p", "text": "激活函数的选择会影响梯度的尺度，这也是一个常见话题。"},
        {"id": "s3", "book_id": "bk1", "chapter_id": "c2", "seq": 1, "page": 6,
         "kind": "p", "text": "例题：当网络很深时，梯度消失会让靠近输入的层几乎不更新。"},
    ])

    from fastapi.testclient import TestClient

    return TestClient(app), "bk1"


def test_search_returns_located_paragraphs_with_anchor_and_chapter(book_client):
    client, book_id = book_client

    res = client.get(f"/api/books/{book_id}/search", params={"q": "梯度消失"})

    assert res.status_code == 200
    body = res.json()
    assert body["query"] == "梯度消失"
    assert body["total"] >= 2
    hit = next(h for h in body["hits"] if h["anchorId"] == "s1")
    # 这四样齐了前端才能「跳过去并高亮」
    assert hit["chapterId"] == "c1"
    assert hit["chapterTitle"] == "第1章 总论"
    assert hit["page"] == 2
    assert "梯度消失" in hit["text"]


def test_search_finds_matches_across_chapters(book_client):
    """定义在第 1 章、例题在第 2 章——搜索必须两边都给，否则就是在替用户漏书。"""
    client, book_id = book_client

    hits = client.get(f"/api/books/{book_id}/search", params={"q": "梯度消失"}).json()["hits"]

    assert {h["chapterId"] for h in hits} == {"c1", "c2"}


def test_search_result_does_not_depend_on_any_current_chapter(book_client):
    """搜索不做本章加权：同一句话搜两次，结果必须一样。

    这正是它与问答共用检索链路、但不共用「本章优先」的原因。
    """
    client, book_id = book_client

    first = client.get(f"/api/books/{book_id}/search", params={"q": "梯度"}).json()
    second = client.get(f"/api/books/{book_id}/search", params={"q": "梯度"}).json()

    assert [h["anchorId"] for h in first["hits"]] == [h["anchorId"] for h in second["hits"]]


def test_empty_query_returns_empty_list_not_an_error(book_client):
    """用户清空输入框不该看到一个报错。"""
    client, book_id = book_client

    res = client.get(f"/api/books/{book_id}/search", params={"q": "   "})

    assert res.status_code == 200
    assert res.json() == {"query": "", "total": 0, "hits": []}


def test_no_match_returns_empty_list(book_client):
    client, book_id = book_client

    body = client.get(f"/api/books/{book_id}/search", params={"q": "量子纠缠"}).json()

    assert body["total"] == 0
    assert body["hits"] == []


def test_limit_is_clamped(book_client):
    """limit 是外部输入，不能让它变成「一次取十万段」。"""
    client, book_id = book_client

    body = client.get(f"/api/books/{book_id}/search", params={"q": "梯度", "limit": 9999}).json()

    assert len(body["hits"]) <= 50


def test_search_on_missing_book_is_404(book_client):
    client, _ = book_client

    assert client.get("/api/books/nope/search", params={"q": "梯度"}).status_code == 404
