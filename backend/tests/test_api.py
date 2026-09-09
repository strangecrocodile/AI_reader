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


def test_upload_rejects_non_pdf(client):
    resp = client.post(
        "/api/books",
        files={"file": ("notes.txt", b"plain text", "text/plain")},
    )
    assert resp.status_code == 415


def test_upload_rejects_empty_file(client):
    resp = client.post(
        "/api/books",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert resp.status_code == 400


def test_uploading_two_books_keeps_both_books_readable(client, demo_pdf_bytes):
    first = _upload(client, demo_pdf_bytes)
    second = _upload(client, demo_pdf_bytes)

    assert first["id"] != second["id"]
    assert first["chapters"][0]["id"] != second["chapters"][0]["id"]
    assert client.get(
        f"/api/books/{first['id']}/chapters/{first['chapters'][0]['id']}"
    ).status_code == 200
    assert client.get(
        f"/api/books/{second['id']}/chapters/{second['chapters'][0]['id']}"
    ).status_code == 200


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


def test_chapter_progress_updates_knowledge_status_and_book_progress(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)
    chapter_id = book["chapters"][0]["id"]

    resp = client.post(
        f"/api/books/{book['id']}/chapters/{chapter_id}/progress",
        json={"status": "learning", "mastery": 35},
    )

    assert resp.status_code == 200
    assert resp.json()["mastery"] == 35
    knowledge = client.get(f"/api/books/{book['id']}/knowledge").json()
    chapter_concepts = [c for c in knowledge["concepts"] if c["chapterId"] == chapter_id]
    assert chapter_concepts
    assert all(c["status"] == "learning" and c["mastery"] == 35 for c in chapter_concepts)

    refreshed = client.get(f"/api/books/{book['id']}").json()
    assert refreshed["progressText"] == "18% 已完成"


def test_chapter_progress_does_not_lower_mastery(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)
    chapter_id = book["chapters"][0]["id"]
    url = f"/api/books/{book['id']}/chapters/{chapter_id}/progress"

    client.post(url, json={"status": "learning", "mastery": 42})
    resp = client.post(url, json={"status": "learning", "mastery": 10})

    assert resp.json()["mastery"] == 42


def test_learned_progress_is_not_downgraded_by_revisiting(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)
    chapter_id = book["chapters"][0]["id"]
    url = f"/api/books/{book['id']}/chapters/{chapter_id}/progress"

    client.post(url, json={"status": "learned", "mastery": 100})
    resp = client.post(url, json={"status": "learning", "mastery": 15})

    assert resp.json()["status"] == "learned"
    assert resp.json()["mastery"] == 100
    refreshed = client.get(f"/api/books/{book['id']}").json()
    assert refreshed["chapters"][0]["status"] == "learned"
    assert refreshed["chapters"][0]["progressPct"] == 100
