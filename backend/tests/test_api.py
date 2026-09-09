"""API 集成测试：导入 → 列表 → 章节内容（讲解/大纲）→ 溯源问答 → 规划。"""


def _upload(client, data):
    resp = client.post("/api/books", files={"file": ("demo.pdf", data, "application/pdf")})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_upload_and_list_books(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)
    assert book["id"]
    assert "微积分" in book["title"]
    assert len(book["chapters"]) >= 2
    assert book["chapters"][0]["isToday"] is True
    assert book["plan"]["remaining"]

    books = client.get("/api/books").json()
    assert any(b["id"] == book["id"] for b in books)


def test_chapter_content_with_lesson(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)
    for ch in book["chapters"]:
        resp = client.get(f"/api/books/{book['id']}/chapters/{ch['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["heading"] == ch["title"]
        assert data["paragraphs"], "应有原文段落"
        paragraph_ids = {seg["id"] for p in data["paragraphs"] for seg in p.get("segs", [])}
        # 讲解与大纲必须引用真实锚点
        for kp in data["knowledgePoints"]:
            assert kp["sourceId"] in paragraph_ids
            assert kp["title"]
            assert kp["body"]
        for item in data["outline"]:
            assert item["sourceId"] in paragraph_ids
        break


def test_ask_with_evidence(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)
    ch = book["chapters"][1]
    resp = client.post(
        "/api/ask",
        json={"question": "导数的定义是什么？", "bookId": book["id"], "chapterId": ch["id"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"]
    assert data["sources"], "应返回教材依据锚点"

    chart = client.get(f"/api/books/{book['id']}/chapters/{ch['id']}").json()
    paragraph_ids = {seg["id"] for p in chart["paragraphs"] for seg in p.get("segs", [])}
    assert set(data["sources"]) <= paragraph_ids


def test_ask_no_evidence(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)
    ch = book["chapters"][0]
    resp = client.post(
        "/api/ask",
        json={"question": "今天晚上的月亮有多圆？", "bookId": book["id"], "chapterId": ch["id"]},
    )
    data = resp.json()
    assert data["answer"] == "教材中未找到直接依据"
    assert data["sources"] == []


def test_ask_unknown_book_404(client, demo_pdf_bytes):
    resp = client.post(
        "/api/ask",
        json={"question": "导数是什么？", "bookId": "nope", "chapterId": "ch1"},
    )
    assert resp.status_code == 404


def test_plan_generation(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)
    resp = client.post(f"/api/books/{book['id']}/plan")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == len(book["chapters"])
    for item in items:
        assert item["goal"]
        assert item["duration_minutes"] > 0

    # 缓存幂等
    again = client.post(f"/api/books/{book['id']}/plan").json()
    assert again["items"] == items


def test_knowledge_map_aggregates_lesson_points(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)

    resp = client.get(f"/api/books/{book['id']}/knowledge")

    assert resp.status_code == 200
    data = resp.json()
    assert data["bookId"] == book["id"]
    assert data["concepts"]
    assert data["stats"]["conceptCount"] == len(data["concepts"])
    assert data["stats"]["relationCount"] == len(data["relations"])
    for concept in data["concepts"]:
        assert concept["title"]
        assert concept["chapterId"]
        assert concept["sourceId"]


def test_knowledge_map_unknown_book_404(client):
    resp = client.get("/api/books/nope/knowledge")
    assert resp.status_code == 404
