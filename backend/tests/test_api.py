"""API 集成测试：导入 → 列表 → 章节内容（讲解/大纲）→ 溯源问答 → 规划 → 掌握度事件。"""
import json

import pytest


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


def test_upload_rejects_unsupported_format(client):
    resp = client.post(
        "/api/books",
        files={"file": ("scan.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert resp.status_code == 415
    assert "docx" in resp.json()["detail"]


def test_upload_docx_runs_full_chain(client, demo_docx_bytes):
    """Word 教材与 PDF 共用同一条链路：入库 → 章节内容 → 知识图谱 → 溯源问答。"""
    resp = client.post(
        "/api/books",
        files={
            "file": (
                "微积分入门.docx",
                demo_docx_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert resp.status_code == 201, resp.text
    book = resp.json()
    assert "微积分" in book["title"]
    assert [c["title"] for c in book["chapters"]] == ["第1章 函数与极限", "第2章 导数与微分"]

    chapter = book["chapters"][0]
    content = client.get(f"/api/books/{book['id']}/chapters/{chapter['id']}").json()
    assert content["paragraphs"], "Word 教材应解析出原文段落"
    assert content["knowledgePoints"]
    # 标题自带「第1章」时，导语不再重复章号
    assert content["intro"] == "第1章 函数与极限　/　第 1 页"
    paragraph_ids = {seg["id"] for p in content["paragraphs"] for seg in p.get("segs", [])}
    for point in content["knowledgePoints"]:
        assert point["sourceId"] in paragraph_ids

    knowledge = client.get(f"/api/books/{book['id']}/knowledge").json()
    assert knowledge["concepts"]
    assert all(concept["definition"] for concept in knowledge["concepts"])
    assert all(concept["sourceId"] for concept in knowledge["concepts"])

    asked = client.post(
        "/api/ask",
        json={"question": "这一段说了什么？", "bookId": book["id"], "chapterId": chapter["id"]},
    ).json()
    assert asked["answer"]
    assert set(asked["sources"]) <= paragraph_ids


def test_upload_markdown_book(client, demo_markdown_bytes):
    resp = client.post(
        "/api/books",
        files={"file": ("微积分入门.md", demo_markdown_bytes, "text/markdown")},
    )
    assert resp.status_code == 201, resp.text
    book = resp.json()
    assert book["title"] == "微积分入门（Markdown 版）"
    assert len(book["chapters"]) == 3

    content = client.get(f"/api/books/{book['id']}/chapters/{book['chapters'][0]['id']}").json()
    assert content["paragraphs"]
    assert client.get(f"/api/books/{book['id']}/knowledge").json()["concepts"]


def test_upload_txt_book_with_chinese_chapter_headings(client):
    raw = "第1章 函数与极限\n极限是微积分中第一个重要的工具。\n第2章 导数与微分\n导数刻画变化率。\n".encode(
        "utf-8"
    )
    resp = client.post("/api/books", files={"file": ("教材.txt", raw, "text/plain")})

    assert resp.status_code == 201, resp.text
    book = resp.json()
    assert book["title"] == "教材"
    assert [c["title"] for c in book["chapters"]] == ["第1章 函数与极限", "第2章 导数与微分"]

    content = client.get(f"/api/books/{book['id']}/chapters/{book['chapters'][0]['id']}").json()
    assert content["intro"] == "第1章 函数与极限　/　第 1 页"


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


def test_book_bundle_write_rolls_back_on_duplicate_chapter(app):
    db = app.state.db
    book = {
        "id": "atomic-book",
        "title": "事务测试",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    chapter = {
        "id": "atomic-chapter",
        "book_id": book["id"],
        "num": 1,
        "title": "第一章",
        "page_start": 1,
        "page_end": 1,
        "full_text": "正文",
    }

    import sqlite3

    try:
        db.add_book_bundle(book, [chapter, chapter], [], [])
    except sqlite3.IntegrityError:
        pass
    else:  # pragma: no cover
        raise AssertionError("重复章节应触发事务回滚")

    assert db.get_book(book["id"]) is None


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
    assert data["sourceDetails"]
    assert data["sourceDetails"][0]["page"] > 0
    assert data["sourceDetails"][0]["id"] in data["sources"]

    chart = client.get(f"/api/books/{book['id']}/chapters/{ch['id']}").json()
    paragraph_ids = {seg["id"] for p in chart["paragraphs"] for seg in p.get("segs", [])}
    assert set(data["sources"]) <= paragraph_ids


def test_vector_search_receives_current_chapter_allowlist(app, demo_pdf_bytes):
    from fastapi.testclient import TestClient

    book = _upload(TestClient(app), demo_pdf_bytes)
    chapter = book["chapters"][0]
    retrieval = app.state.retrieval

    class FakeVector:
        def __init__(self):
            self.allowed_ids = None

        def add(self, doc_ids, texts):
            pass

        def search(self, query, k=5, allowed_ids=None):
            self.allowed_ids = set(allowed_ids or [])
            return [("foreign-section", 0.99)]

    fake = FakeVector()
    retrieval._vector = fake
    hits = retrieval.search(book["id"], chapter["id"], "导数", use_vector=True)

    assert fake.allowed_ids
    assert all(hit["section_id"] in fake.allowed_ids for hit in hits)


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


def test_ask_expands_to_other_chapters(client, demo_pdf_bytes):
    """本章没讲的内容，应扩展到全书检索并标明依据来自哪一章。"""
    book = _upload(client, demo_pdf_bytes)
    first, second = book["chapters"][0], book["chapters"][1]

    data = client.post(
        "/api/ask",
        json={"question": "平均变化率是什么？", "bookId": book["id"], "chapterId": first["id"]},
    ).json()

    assert data["scope"] == "book"
    assert data["sources"]
    detail = data["sourceDetails"][0]
    assert detail["chapterId"] == second["id"], "依据应来自第 2 章"
    assert detail["chapterTitle"] == second["title"]
    assert detail["page"] > 0


def test_ask_stays_in_chapter_when_chapter_has_evidence(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)
    chapter = book["chapters"][0]

    data = client.post(
        "/api/ask",
        json={"question": "极限是什么？", "bookId": book["id"], "chapterId": chapter["id"]},
    ).json()

    assert data["scope"] == "chapter"
    assert all(item["chapterId"] == chapter["id"] for item in data["sourceDetails"])


def _sse_frames(body: str):
    """把 SSE 响应体拆成 [(event, data)]。"""
    frames = []
    for block in body.strip().split("\n\n"):
        lines = [line for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        event = lines[0].split(":", 1)[1].strip()
        payload = json.loads(lines[1].split(":", 1)[1].strip())
        frames.append((event, payload))
    return frames


def test_ask_stream_emits_meta_delta_done(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)
    chapter = book["chapters"][1]

    resp = client.post(
        "/api/ask/stream",
        json={"question": "导数的定义是什么？", "bookId": book["id"], "chapterId": chapter["id"]},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    frames = _sse_frames(resp.text)
    events = [event for event, _ in frames]
    assert events[0] == "meta"
    assert events[-1] == "done"
    assert "delta" in events

    meta = frames[0][1]
    done = frames[-1][1]
    assert meta["evidenceCount"] >= 1
    assert meta["scope"] in {"chapter", "book"}
    # 逐块内容拼起来就是最终回答
    assert "".join(data["text"] for event, data in frames if event == "delta") == done["answer"]
    assert done["sources"]
    paragraph_ids = {
        seg["id"]
        for para in client.get(f"/api/books/{book['id']}/chapters/{chapter['id']}").json()["paragraphs"]
        for seg in para.get("segs", [])
    }
    assert set(done["sources"]) <= paragraph_ids


def test_ask_stream_reports_no_evidence(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)

    resp = client.post(
        "/api/ask/stream",
        json={
            "question": "今天晚上的月亮有多圆？",
            "bookId": book["id"],
            "chapterId": book["chapters"][0]["id"],
        },
    )

    frames = _sse_frames(resp.text)
    assert [event for event, _ in frames] == ["done"]
    done = frames[0][1]
    assert done["noEvidence"] is True
    assert done["answer"] == "教材中未找到直接依据"
    assert done["sources"] == []


def test_ask_stream_expands_to_other_chapters(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)
    first, second = book["chapters"][0], book["chapters"][1]

    resp = client.post(
        "/api/ask/stream",
        json={"question": "平均变化率是什么？", "bookId": book["id"], "chapterId": first["id"]},
    )

    meta = _sse_frames(resp.text)[0][1]
    assert meta["scope"] == "book"
    assert any(item["chapterId"] == second["id"] for item in meta["sourceDetails"])


def test_ask_stream_unknown_book_404(client):
    resp = client.post(
        "/api/ask/stream",
        json={"question": "导数是什么？", "bookId": "nope", "chapterId": "ch1"},
    )
    assert resp.status_code == 404


# ---------- 划词气泡 / 追问线程 ----------


def _create_thread(client, book, chapter_id, **extra):
    resp = client.post(
        "/api/threads",
        json={"bookId": book["id"], "chapterId": chapter_id, **extra},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_and_list_threads(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)
    chapter = book["chapters"][0]

    thread = _create_thread(
        client, book, chapter["id"], anchorId="x", selectedText="比值 Δy / Δx 的极限存在"
    )

    assert thread["id"].startswith("th-")
    assert thread["messages"] == []
    assert thread["selectedText"] == "比值 Δy / Δx 的极限存在"

    listed = client.get(f"/api/books/{book['id']}/chapters/{chapter['id']}/threads").json()
    assert [item["id"] for item in listed] == [thread["id"]]


def test_create_thread_validates_book_and_chapter(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)

    assert client.post("/api/threads", json={"bookId": "nope", "chapterId": "x"}).status_code == 404
    assert (
        client.post("/api/threads", json={"bookId": book["id"], "chapterId": "nope"}).status_code
        == 404
    )


def test_ask_with_thread_persists_exchange(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)
    chapter = book["chapters"][1]
    thread = _create_thread(client, book, chapter["id"], selectedText="比值 Δy / Δx 的极限存在")

    data = client.post(
        "/api/ask",
        json={
            "question": "导数的定义是什么？",
            "bookId": book["id"],
            "chapterId": chapter["id"],
            "selectedText": "比值 Δy / Δx 的极限存在",
            "threadId": thread["id"],
        },
    ).json()

    assert data["threadId"] == thread["id"]
    stored = client.get(f"/api/threads/{thread['id']}").json()
    assert [message["role"] for message in stored["messages"]] == ["user", "assistant"]
    assert stored["messages"][0]["text"] == "导数的定义是什么？"
    assert stored["messages"][1]["text"] == data["answer"]
    assert stored["messages"][1]["sources"] == data["sources"]


def test_ask_stream_with_thread_persists_answer(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)
    chapter = book["chapters"][1]
    thread = _create_thread(client, book, chapter["id"], selectedText="选中的原文")

    resp = client.post(
        "/api/ask/stream",
        json={
            "question": "导数的定义是什么？",
            "bookId": book["id"],
            "chapterId": chapter["id"],
            "threadId": thread["id"],
        },
    )
    frames = _sse_frames(resp.text)
    done = frames[-1][1]
    assert done["threadId"] == thread["id"]

    stored = client.get(f"/api/threads/{thread['id']}").json()
    assert [message["role"] for message in stored["messages"]] == ["user", "assistant"]
    assert stored["messages"][1]["text"] == done["answer"]


def test_thread_question_uses_thread_chapter_for_retrieval(client, demo_pdf_bytes):
    """线程绑在第 2 章：即使请求里带的是第 1 章，也按线程所属章节检索。"""
    book = _upload(client, demo_pdf_bytes)
    first, second = book["chapters"][0], book["chapters"][1]
    thread = _create_thread(client, book, second["id"], selectedText="比值 Δy / Δx 的极限存在")

    data = client.post(
        "/api/ask",
        json={
            "question": "导数的定义是什么？",
            "bookId": book["id"],
            "chapterId": first["id"],
            "threadId": thread["id"],
        },
    ).json()

    assert data["scope"] == "chapter"
    assert all(item["chapterId"] == second["id"] for item in data["sourceDetails"])


def test_ask_with_unknown_thread_404(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)

    resp = client.post(
        "/api/ask",
        json={
            "question": "导数是什么？",
            "bookId": book["id"],
            "chapterId": book["chapters"][0]["id"],
            "threadId": "th-nope",
        },
    )
    assert resp.status_code == 404


def test_ask_without_thread_stays_stateless(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)
    chapter = book["chapters"][0]

    data = client.post(
        "/api/ask",
        json={"question": "极限是什么？", "bookId": book["id"], "chapterId": chapter["id"]},
    ).json()

    assert data["threadId"] is None
    assert client.get(f"/api/books/{book['id']}/chapters/{chapter['id']}/threads").json() == []


def test_delete_thread(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)
    thread = _create_thread(client, book, book["chapters"][0]["id"], selectedText="待删除")

    assert client.delete(f"/api/threads/{thread['id']}").status_code == 204
    assert client.get(f"/api/threads/{thread['id']}").status_code == 404
    assert client.delete(f"/api/threads/{thread['id']}").status_code == 404


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


def test_knowledge_map_builds_concept_graph(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)

    resp = client.get(f"/api/books/{book['id']}/knowledge")

    assert resp.status_code == 200
    data = resp.json()
    assert data["bookId"] == book["id"]
    assert data["concepts"]
    assert data["stats"]["conceptCount"] == len(data["concepts"])
    assert data["stats"]["relationCount"] == len(data["relations"])
    assert data["stats"]["prerequisiteCount"] <= data["stats"]["relationCount"]
    assert data["stats"]["unresolvedCount"] == len(data["unresolved"])
    assert set(data["methods"]) <= {"rule", "llm"}

    concept_ids = {c["id"] for c in data["concepts"]}
    for concept in data["concepts"]:
        # 兼容旧前端字段
        assert concept["title"]
        assert concept["chapterId"]
        assert concept["sourceId"]
        # v2 概念层字段
        assert concept["definition"]
        assert concept["chapterId"] in concept["chapters"]
        assert concept["anchorCount"] == len(concept["anchors"])
        assert isinstance(concept["prerequisites"], list)

    for relation in data["relations"]:
        assert relation["type"] in {"prerequisite", "sequence"}
        assert relation["label"]
        assert relation["source"] in concept_ids and relation["target"] in concept_ids
        assert relation["source"] != relation["target"]


def test_knowledge_concepts_link_back_to_real_anchors(client, demo_pdf_bytes):
    """每个知识点的锚点必须真实存在于其章节原文，保证可回跳核对。"""
    book = _upload(client, demo_pdf_bytes)
    data = client.get(f"/api/books/{book['id']}/knowledge").json()

    anchors_by_chapter = {}
    for chapter in book["chapters"]:
        content = client.get(f"/api/books/{book['id']}/chapters/{chapter['id']}").json()
        anchors_by_chapter[chapter["id"]] = {
            seg["id"] for p in content["paragraphs"] for seg in p.get("segs", [])
        }

    for concept in data["concepts"]:
        valid = anchors_by_chapter.get(concept["chapterId"], set())
        assert concept["sourceId"] in valid
        assert set(concept["anchors"]) <= valid


def test_knowledge_extraction_is_cached_across_requests(client, demo_pdf_bytes):
    """第二次请求不应重新抽取（缓存生效），返回结构保持一致。"""
    book = _upload(client, demo_pdf_bytes)
    url = f"/api/books/{book['id']}/knowledge"

    first = client.get(url).json()
    second = client.get(url).json()

    assert first == second


def test_knowledge_map_unknown_book_404(client):
    resp = client.get("/api/books/nope/knowledge")
    assert resp.status_code == 404


def test_learning_events_recompute_mastery(client, demo_pdf_bytes):
    """掌握度由真实事件算出：进入 → 阅读 → 提问，逐级变化并同步到知识点。"""
    book = _upload(client, demo_pdf_bytes)
    chapter = book["chapters"][0]
    content = client.get(f"/api/books/{book['id']}/chapters/{chapter['id']}").json()
    anchors = [seg["id"] for para in content["paragraphs"] for seg in para.get("segs", [])]
    url = f"/api/books/{book['id']}/chapters/{chapter['id']}/events"

    opened = client.post(url, json={"kind": "open"}).json()
    assert opened["status"] == "learning"
    assert opened["mastery"] == 0, "只打开章节不该产生掌握度"

    read = client.post(url, json={"kind": "read", "anchorIds": anchors[:2]}).json()
    assert read["signals"]["paragraphsRead"] == 2
    assert read["signals"]["paragraphsTotal"] == len(anchors)
    assert read["mastery"] > opened["mastery"]
    assert sum(item["score"] for item in read["breakdown"]) == pytest.approx(read["computed"], abs=0.5)

    asked = client.post(url, json={"kind": "ask", "question": "这一段说了什么？"}).json()
    assert asked["signals"]["askCount"] == 1
    assert asked["mastery"] >= read["mastery"]

    knowledge = client.get(f"/api/books/{book['id']}/knowledge").json()
    concept = next(c for c in knowledge["concepts"] if c["chapterId"] == chapter["id"])
    assert concept["status"] == "learning"
    assert concept["mastery"] == asked["mastery"]


def test_complete_event_marks_chapter_learned(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)
    chapter_id = book["chapters"][0]["id"]
    url = f"/api/books/{book['id']}/chapters/{chapter_id}/events"

    done = client.post(url, json={"kind": "complete"}).json()

    assert done["status"] == "learned"
    assert done["signals"]["completed"] is True
    assert client.get(f"/api/books/{book['id']}").json()["chapters"][0]["status"] == "learned"


def test_learning_event_payload_validation(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)
    url = f"/api/books/{book['id']}/chapters/{book['chapters'][0]['id']}/events"

    assert client.post(url, json={"kind": "read"}).status_code == 422
    assert client.post(url, json={"kind": "read", "anchorIds": []}).status_code == 422
    assert client.post(url, json={"kind": "ask", "question": "   "}).status_code == 422
    assert client.post(url, json={"kind": "quiz"}).status_code == 422
    assert client.post(url, json={"kind": "unknown"}).status_code == 422


def test_learning_event_unknown_chapter_404(client, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes)

    resp = client.post(f"/api/books/{book['id']}/chapters/nope/events", json={"kind": "open"})

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
