"""划词追问：用户选中的那段原文必须参与检索，并成为第一条证据。

背景——「划词提问总是无法回答」是两件事叠在一起：

1. `_retrieve` 只拿 `question` 去检索，选中的原文根本没进检索。像「这段话在讲什么」
   这类问题的查询词在教材里几乎不存在，本章与全书两次检索的覆盖率都低于 0.22，
   模型连被调用的机会都没有，直接回「教材中未找到直接依据」；
2. 即便进了模型，命中的也常常是别的段落（例题而不是定义），模型照提示词里
   「片段不足以回答就回复『教材中未找到直接依据』」的规则直接拒绝。

本文件盯住第 1 条（第 2 条由 `test_ask_prompt.py` 盯）。测试用的是 MockLLM：
它不做推理，直接走 `_rule_answer` 兜底，所以断言恰好落在「证据是什么」上，
不受模型发挥影响。
"""
import json

import pytest

from app.llm.prompts import ask_user

#: 一个查不到任何教材段落的问法——这正是划词的典型问法（指着一段话问它讲什么）
BLIND_QUESTION = "这段话在讲什么"


def _upload(client, data):
    resp = client.post("/api/books", files={"file": ("demo.pdf", data, "application/pdf")})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_thread(client, book, chapter_id, **extra):
    resp = client.post(
        "/api/threads",
        json={"bookId": book["id"], "chapterId": chapter_id, **extra},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _sse_frames(body: str):
    frames = []
    for block in body.strip().split("\n\n"):
        lines = [line for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        frames.append((lines[0].split(":", 1)[1].strip(), json.loads(lines[1].split(":", 1)[1].strip())))
    return frames


def _first_anchor(app, book_id, chapter_id):
    anchors = app.state.db.anchors_of(book_id, chapter_id)
    assert anchors, "示例教材应当有锚点"
    return anchors[0]


def _ask_plain(client, book, chapter_id, question):
    resp = client.post(
        "/api/ask",
        json={"question": question, "bookId": book["id"], "chapterId": chapter_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_blind_question_really_has_no_evidence(client, demo_pdf_bytes):
    """对照组：不带划词时，BLIND_QUESTION 确实检索不到依据。

    这条是下面几条测试的「前提自检」——如果哪天示例教材或阈值变了、使这个问法
    本来就能命中，下面那些断言会变得毫无意义却照样通过。
    """
    book = _upload(client, demo_pdf_bytes)
    assert _ask_plain(client, book, book["chapters"][0]["id"], BLIND_QUESTION)["answer"] == (
        "教材中未找到直接依据"
    )


def test_selected_paragraph_becomes_first_evidence(client, app, demo_pdf_bytes):
    """划词后，选中的那段按锚点直取，排在证据第一位（不再只拿问题去检索）。"""
    book = _upload(client, demo_pdf_bytes)
    chapter = book["chapters"][0]
    anchor = _first_anchor(app, book["id"], chapter["id"])

    thread = _create_thread(
        client, book, chapter["id"], anchorId=anchor["id"], selectedText=anchor["text"]
    )
    data = _ask_plain(client, book, chapter["id"], BLIND_QUESTION)
    assert data["answer"] == "教材中未找到直接依据"  # 前提仍然成立

    resp = client.post(
        "/api/ask",
        json={
            "question": BLIND_QUESTION,
            "bookId": book["id"],
            "chapterId": chapter["id"],
            "threadId": thread["id"],
            "selectedText": anchor["text"],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["answer"] != "教材中未找到直接依据"
    assert data["sources"][0] == anchor["id"]
    assert data["sourceDetails"][0]["id"] == anchor["id"]
    assert data["sourceDetails"][0]["text"] == anchor["text"]


def test_selected_paragraph_is_first_evidence_in_stream(client, app, demo_pdf_bytes):
    """流式路径同样成立——前端划词走的就是 /api/ask/stream。"""
    book = _upload(client, demo_pdf_bytes)
    chapter = book["chapters"][0]
    anchor = _first_anchor(app, book["id"], chapter["id"])
    thread = _create_thread(
        client, book, chapter["id"], anchorId=anchor["id"], selectedText=anchor["text"]
    )

    resp = client.post(
        "/api/ask/stream",
        json={
            "question": BLIND_QUESTION,
            "bookId": book["id"],
            "chapterId": chapter["id"],
            "threadId": thread["id"],
            "selectedText": anchor["text"],
        },
    )
    frames = _sse_frames(resp.text)
    assert frames[0][0] == "meta"
    assert frames[0][1]["sourceDetails"][0]["id"] == anchor["id"]

    done = next(payload for event, payload in frames if event == "done")
    assert done["noEvidence"] is False, "契约恒定：成功回答也带这个字段，值为 False"
    assert done["sources"][0] == anchor["id"]


def test_selected_text_alone_lifts_retrieval(client, app, demo_pdf_bytes):
    """只有 selectedText、拿不到锚点时，检索词也应当是「选中原文 + 问题」。

    前端偶尔会拿不到锚点（选区落在没有 data-source-id 的元素上），这条路不能塌。
    """
    book = _upload(client, demo_pdf_bytes)
    chapter = book["chapters"][0]
    anchor = _first_anchor(app, book["id"], chapter["id"])

    resp = client.post(
        "/api/ask",
        json={
            "question": BLIND_QUESTION,
            "bookId": book["id"],
            "chapterId": chapter["id"],
            "selectedText": anchor["text"],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["answer"] != "教材中未找到直接依据"


def test_unknown_anchor_falls_back_to_plain_retrieval(client, demo_pdf_bytes):
    """锚点取不到（老线程、脏 id、教材重新导入过）不该 500，退回纯检索。"""
    book = _upload(client, demo_pdf_bytes)
    chapter = book["chapters"][0]
    thread = _create_thread(
        client, book, chapter["id"], anchorId="不存在的锚点", selectedText=""
    )

    resp = client.post(
        "/api/ask",
        json={
            "question": "今天晚上的月亮有多圆？",
            "bookId": book["id"],
            "chapterId": chapter["id"],
            "threadId": thread["id"],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["answer"] == "教材中未找到直接依据"


def test_ask_user_keeps_selected_paragraph_whole():
    """选中的原文按原样给全（不参与 400 字截断），并明确标注出来。

    用户点的就是这段，截断它会直接改变问题的含义；检索命中的其它片段才截断。
    """
    selected = "甲" * 600
    other = "乙" * 600
    evidence = [
        {"anchor_id": "a1", "page": 1, "text": selected, "chapter_title": "第1章", "selected": True},
        {"anchor_id": "a2", "page": 2, "text": other, "chapter_title": "第1章"},
    ]

    prompt = ask_user("这段话在讲什么", evidence)

    assert "（用户选中的原文）" in prompt
    assert selected in prompt
    assert other[:400] in prompt
    assert other[:401] not in prompt


@pytest.mark.parametrize("text", ["", None])
def test_ask_user_tolerates_missing_fields(text):
    """脏数据（text 为空/None）不该把提示词拼出个「None」。"""
    evidence = [{"anchor_id": "a1", "page": 1, "text": text, "chapter_title": ""}]
    prompt = ask_user("问题", evidence)
    assert "None" not in prompt
