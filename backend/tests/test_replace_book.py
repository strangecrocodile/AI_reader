"""「重新上传并替换本书」：换内容，不换用户的学习记录。

这条路径唯一的存在理由就是「保住记录」——所以测试的重点不是「新内容进来了」
（那和普通上传没区别），而是**旧记录还在**：

- 章节进度、学习事件、追问线程、笔记一条都不能少；
- 章节行必须走 UPDATE：`PRAGMA foreign_keys = ON` 而这几张表都带
  `ON DELETE CASCADE`，先删章节行再插会把它们一起级联删光；
- 生成物缓存（讲解 / 计划 / 知识点 / 自测）必须清掉——那是按旧段落生成的；
- 解析失败时旧教材一个字都不能动。
"""
import io

from docx import Document

from app.services.ingest import REPLACE_SCANNED_MESSAGE


def _docx(chapters):
    """造一本 Word 教材：chapters = [(章标题, [段落...])]。"""
    document = Document()
    for title, paragraphs in chapters:
        document.add_heading(title, level=1)
        for text in paragraphs:
            document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

FIRST = _docx(
    [
        ("第1章 函数与极限", ["极限描述无限逼近的过程，是微积分的第一件工具。", "函数是描述对应关系的工具。"]),
        ("第2章 导数与微分", ["导数刻画变化率，几何意义是切线斜率。"]),
    ]
)
SECOND = _docx(
    [
        ("第1章 函数与极限", ["极限描述无限逼近的过程，是微积分的第一件工具。", "补充：连续函数在闭区间上必定取得最大值。"]),
        ("第2章 导数与微分", ["导数刻画变化率，几何意义是切线斜率。"]),
        ("第3章 积分", ["定积分是曲边梯形的面积。"]),
    ]
)

#: 同一段文字被挤到了别的序号上（前面插了一句）：锚点 id 变、原文没变。
SHIFTED = _docx(
    [
        (
            "第1章 函数与极限",
            ["新增的一句前言。", "极限描述无限逼近的过程，是微积分的第一件工具。", "函数是描述对应关系的工具。"],
        ),
        ("第2章 导数与微分", ["导数刻画变化率，几何意义是切线斜率。"]),
    ]
)


def _upload(client, data=FIRST, filename="微积分入门.docx"):
    res = client.post("/api/books", files={"file": (filename, data, DOCX_TYPE)})
    assert res.status_code == 201, res.text
    return res.json()


def _replace(client, book_id, data=SECOND, filename="微积分入门.docx"):
    return client.post(
        f"/api/books/{book_id}/replace",
        files={"file": (filename, data, DOCX_TYPE)},
    )


def _seed_learning(client, app, book):
    """给这本书铺上「用户自己的东西」：进度、事件、线程、笔记。"""
    chapter_id = book["chapters"][0]["id"]
    anchor_id = book["chapters"][0] and _first_anchor(app, book, chapter_id)

    client.post(
        f"/api/books/{book['id']}/chapters/{chapter_id}/events",
        json={"kind": "read", "anchorIds": [anchor_id]},
    )
    client.post(
        f"/api/books/{book['id']}/chapters/{chapter_id}/events",
        json={"kind": "ask", "question": "极限是什么？"},
    )
    thread = client.post(
        "/api/threads",
        json={
            "bookId": book["id"],
            "chapterId": chapter_id,
            "anchorId": anchor_id,
            "selectedText": "极限描述无限逼近的过程，是微积分的第一件工具。",
        },
    ).json()
    note = client.post(
        "/api/notes",
        json={
            "bookId": book["id"],
            "chapterId": chapter_id,
            "anchorId": anchor_id,
            "quotedText": "极限描述无限逼近的过程，是微积分的第一件工具。",
            "body": "这句要背下来。",
        },
    ).json()
    return {"chapterId": chapter_id, "anchorId": anchor_id, "threadId": thread["id"], "noteId": note["id"]}


def _first_anchor(app, book, chapter_id):
    anchors = app.state.db.anchors_of(book["id"], chapter_id)
    return anchors[0]["id"]


def _counts(client, book_id, chapter_id):
    return {
        "threads": len(client.get(f"/api/books/{book_id}/chapters/{chapter_id}/threads").json()),
        "notes": len(client.get(f"/api/books/{book_id}/chapters/{chapter_id}/notes").json()),
    }


def test_replace_swaps_content_and_keeps_learning_records(client, app):
    book = _upload(client)
    seeded = _seed_learning(client, app, book)
    chapter_id = seeded["chapterId"]

    res = _replace(client, book["id"])

    assert res.status_code == 200, res.text
    body = res.json()
    # 新内容进来了：多了一章
    assert [c["title"] for c in body["chapters"]] == ["第1章 函数与极限", "第2章 导数与微分", "第3章 积分"]
    assert body["replace"]["chaptersAdded"] == 1
    assert body["replace"]["chaptersUpdated"] == 2

    # 记录还在：事件、线程、笔记一条不少
    assert _counts(client, book["id"], chapter_id) == {"threads": 1, "notes": 1}
    progress = client.get(f"/api/books/{book['id']}").json()["chapters"][0]
    assert progress["progressPct"] > 0, "读过的段落该还在掌握度里"


def test_replace_updates_chapter_rows_instead_of_recreating_them(client, app):
    """章节行必须 UPDATE。先删后插会顺着外键级联把进度/线程/笔记一起删掉。"""
    book = _upload(client)
    seeded = _seed_learning(client, app, book)

    _replace(client, book["id"])

    thread = client.get(f"/api/threads/{seeded['threadId']}")
    assert thread.status_code == 200, "线程被级联删了"
    assert client.get(f"/api/notes").status_code in (200, 405)  # 列表接口在新版是 /books/{id}/notes
    notes = client.get(f"/api/books/{book['id']}/notes").json()
    assert len(notes) == 1
    # 章节表里还是同一个 id（没有换新 id）
    assert app.state.db.get_chapter(book["id"], seeded["chapterId"]) is not None


def test_replace_drops_generated_caches(client, app):
    """讲解 / 计划 / 知识点 / 自测是按旧段落生成的，替换后必须作废。"""
    book = _upload(client)
    chapter_id = book["chapters"][0]["id"]
    client.get(f"/api/books/{book['id']}/chapters/{chapter_id}")  # 生成讲解
    client.get(f"/api/books/{book['id']}/knowledge")  # 生成知识点
    client.get(f"/api/books/{book['id']}/chapters/{chapter_id}/quiz")  # 生成自测

    assert app.state.db.get_explanation(book["id"], chapter_id) is not None
    assert app.state.db.get_concepts(book["id"], chapter_id) is not None

    _replace(client, book["id"])

    assert app.state.db.get_explanation(book["id"], chapter_id) is None
    assert app.state.db.get_concepts(book["id"], chapter_id) is None
    assert app.state.db.get_quiz(book["id"], chapter_id) is None
    assert app.state.db.get_plan(book["id"]) is not None  # 重读元信息时又生成了一份


def test_replace_keeps_note_anchor_when_it_still_exists(client, app):
    """重传一本没改过的书，锚点一个都不该动（文本匹配失手也不该把锚点抹掉）。"""
    book = _upload(client)
    seeded = _seed_learning(client, app, book)

    res = _replace(client, book["id"], data=FIRST)

    assert res.json()["replace"]["notesUnanchored"] == 0
    notes = client.get(f"/api/books/{book['id']}/notes").json()
    assert notes[0]["anchorId"] == seeded["anchorId"]


def test_replace_reanchors_note_by_text_when_paragraph_ids_shift(client, app):
    """原文还在、只是段落序号变了：按文本把笔记接到新锚点上。"""
    book = _upload(client)
    chapter_id = book["chapters"][0]["id"]
    anchors = app.state.db.anchors_of(book["id"], chapter_id)
    target = next(a for a in anchors if "函数是描述对应关系" in a["text"])
    created = client.post(
        "/api/notes",
        json={
            "bookId": book["id"],
            "chapterId": chapter_id,
            "anchorId": target["id"],
            "quotedText": "函数是描述对应关系的工具。",
            "body": "这句也要背。",
        },
    ).json()
    # 模拟「上一条记录停在旧解析的序号上」：原锚点在这版里不存在了
    app.state.db.reanchor([(created["id"], f"{book['id']}-s1-999")], [])

    res = _replace(client, book["id"], data=SHIFTED)

    assert res.json()["replace"]["notesReanchored"] == 1
    notes = client.get(f"/api/books/{book['id']}/notes").json()
    fresh = app.state.db.anchors_of(book["id"], chapter_id)
    assert notes[0]["anchorId"] in {a["id"] for a in fresh}
    moved = next(a for a in fresh if a["id"] == notes[0]["anchorId"])
    assert "函数是描述对应关系" in moved["text"], "重挂到的段落必须是当初引用的那一段"


def test_replace_keeps_note_body_when_text_is_gone(client, app):
    """原文整段被删掉时：笔记正文留着（用户写的东西不能丢），只是跳不回原文。"""
    book = _upload(client)
    chapter_id = book["chapters"][0]["id"]
    replacement = _docx([("第1章 函数与极限", ["完全换掉的一段正文。"])])
    # 直接写库模拟一条历史记录：它的锚点与引用原文在新版本里都不存在了
    app.state.db.add_note(
        {
            "id": "note-legacy",
            "book_id": book["id"],
            "chapter_id": chapter_id,
            "anchor_id": f"{book['id']}-s1-999",
            "quoted_text": "这段原文在新版本里被删掉了，找不回来。",
            "body": "我当时写下的想法。",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )

    res = _replace(client, book["id"], data=replacement)

    assert res.json()["replace"]["notesUnanchored"] == 1
    notes = client.get(f"/api/books/{book['id']}/notes").json()
    kept = next(n for n in notes if n["id"] == "note-legacy")
    assert kept["body"] == "我当时写下的想法。"
    assert kept["anchorId"] == ""


def test_replace_removes_stale_assets(client, app):
    """旧解析抽出的插图要被清掉，否则一本书换几次会越换越胖。"""
    assets_dir = app.state.settings.assets_dir
    assets_dir.mkdir(parents=True, exist_ok=True)
    stale = assets_dir / f"{'x' * 8}-p1-0.png"
    stale.write_bytes(b"old")

    book = _upload(client)
    # 手工放一个属于这本书的旧插图
    old = assets_dir / f"{book['id']}-p1-0.png"
    old.write_bytes(b"old-image")

    _replace(client, book["id"])

    assert not old.exists(), "属于这本书的旧插图没被清掉"
    assert stale.exists(), "别的书的文件不该被误删"


def test_replace_swaps_source_file_and_keeps_it_downloadable(client, app):
    book = _upload(client)
    _replace(client, book["id"], data=SECOND)

    res = client.get(f"/api/books/{book['id']}/source")
    assert res.status_code == 200
    assert res.content == SECOND, "下载到的必须替换后的那份新文件"


def test_replace_changes_format_and_drops_the_old_file(client, app):
    """PDF 换成 Word：旧扩展名那份原文件要删掉，别留着一个没人指向的副本。"""
    book = _upload(client)  # docx
    old_name = app.state.db.get_book(book["id"])["source_name"]
    assert old_name.endswith(".docx")

    res = client.post(
        f"/api/books/{book['id']}/replace",
        files={"file": ("教材.pdf", _pdf_bytes(), "application/pdf")},
    )

    assert res.status_code == 200, res.text
    assert res.json()["sourceFormat"] == "pdf"
    assert not (app.state.settings.sources_dir / old_name).exists()
    assert (app.state.settings.sources_dir / f"{book['id']}.pdf").is_file()


def test_replace_rejects_scanned_pdf(client):
    """扫描件替换返回 422 并给出下一步（先删除再上传），而不是一个跑不完的任务。"""
    book = _upload(client)

    res = client.post(
        f"/api/books/{book['id']}/replace",
        files={"file": ("扫描件.pdf", _scanned_pdf_bytes(), "application/pdf")},
    )

    assert res.status_code == 422
    assert REPLACE_SCANNED_MESSAGE in res.json()["detail"]


def test_replace_unknown_book_is_404(client):
    res = client.post(
        "/api/books/nope/replace",
        files={"file": ("教材.docx", FIRST, DOCX_TYPE)},
    )
    assert res.status_code == 404


def test_replace_rejects_unsupported_format(client):
    book = _upload(client)
    res = client.post(
        f"/api/books/{book['id']}/replace",
        files={"file": ("图.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert res.status_code == 422
    assert "docx" in res.json()["detail"]


def test_replace_rejects_empty_and_oversized_files(client):
    book = _upload(client)
    empty = client.post(
        f"/api/books/{book['id']}/replace",
        files={"file": ("空.docx", b"", DOCX_TYPE)},
    )
    assert empty.status_code == 400

    from app.services.ingest import MAX_UPLOAD_BYTES

    huge = client.post(
        f"/api/books/{book['id']}/replace",
        files={"file": ("大.docx", b"x" * (MAX_UPLOAD_BYTES + 1), DOCX_TYPE)},
    )
    assert huge.status_code == 413


def test_failed_replace_leaves_the_old_book_intact(client, app):
    """新文件解析不了时：旧教材的章节、原文件、记录全都不动。"""
    book = _upload(client)
    seeded = _seed_learning(client, app, book)
    before = app.state.db.get_book(book["id"])
    chapters_before = [c["title"] for c in app.state.db.chapters_of(book["id"])]

    res = client.post(
        f"/api/books/{book['id']}/replace",
        files={"file": ("坏文件.docx", b"this is not a docx at all", DOCX_TYPE)},
    )

    assert res.status_code == 422
    assert [c["title"] for c in app.state.db.chapters_of(book["id"])] == chapters_before
    assert app.state.db.get_book(book["id"])["source_name"] == before["source_name"]
    assert _counts(client, book["id"], seeded["chapterId"]) == {"threads": 1, "notes": 1}
    assert not (app.state.settings.data_dir / ".replace_tmp" / book["id"]).exists()


def test_replace_clears_search_cache(client, app):
    """段落换过了，旧检索缓存必须失效，否则问答还会命中上一版的原文。"""
    book = _upload(client)
    client.post(
        "/api/ask",
        json={
            "bookId": book["id"],
            "chapterId": book["chapters"][0]["id"],
            "question": "极限是什么？",
        },
    )
    invalidated = []
    app.state.retrieval.invalidate_book = lambda book_id: invalidated.append(book_id)

    _replace(client, book["id"])

    assert invalidated == [book["id"]]


def _pdf_bytes() -> bytes:
    """一小份可用的文本型 PDF（用 PyMuPDF 现造，避免依赖示例教材）。"""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Chapter 1 Functions and Limits", fontsize=16)
    page.insert_text((72, 140), "A limit describes an infinite approach process.", fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def _scanned_pdf_bytes() -> bytes:
    """没有文本层的 PDF：`probe_pdf` 判定为扫描件（只画一条线，不写字）。"""
    import pymupdf

    doc = pymupdf.open()
    for _ in range(3):
        page = doc.new_page()
        page.draw_line((10, 10), (200, 200))
    data = doc.tobytes()
    doc.close()
    return data
