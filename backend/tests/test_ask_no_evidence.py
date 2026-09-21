"""拒答（无依据）必须是一条有出口的结果，而不是死路。

背景——用户看到的旧行为只有一句「教材中未找到直接依据」，且：

- 非流式接口**不带** `noEvidence`（流式带），客户端只能靠比对回答文本判断是不是拒答；
- `scope` 被硬编码成 `chapter`，可检索扫的是整本书——前端那句「依据取自全书」的提示
  因此永远显示不出来；
- 没有任何下一步：不说教材里最接近的是什么、也不提示换个问法。

本文件把新的契约钉住：`noEvidence` 恒存在、`closest` 与 `sources` 严格分开、
拒答信息在线程里也能回看。判定口径本身由 `test_bm25.py` / `test_api.py` 盯。
"""
import json

import pytest

REJECTED = "教材中未找到直接依据"
#: 教材里查不到的题外问法，但它确实会撞上一个「只出现一处」的巧合词（`有多`），
#: 所以检索有命中、`closest` 不该是空的——这正是「拒答≠教材里什么都没有」的场景。
OFF_TOPIC_WITH_WEAK_HIT = "今天晚上的月亮有多圆？"
#: 连一个词都撞不上的题外问法
OFF_TOPIC_WITHOUT_HIT = "红烧肉怎么做才好吃？"


def _upload(client, data):
    resp = client.post("/api/books", files={"file": ("demo.pdf", data, "application/pdf")})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _ask(client, book, chapter_id, question, **extra):
    resp = client.post(
        "/api/ask",
        json={"question": question, "bookId": book["id"], "chapterId": chapter_id, **extra},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ask_stream(client, book, chapter_id, question, **extra):
    resp = client.post(
        "/api/ask/stream",
        json={"question": question, "bookId": book["id"], "chapterId": chapter_id, **extra},
    )
    assert resp.status_code == 200, resp.text
    frames = []
    for block in resp.text.strip().split("\n\n"):
        lines = [line for line in block.splitlines() if line.strip()]
        if len(lines) >= 2:
            frames.append((lines[0].split(":", 1)[1].strip(), json.loads(lines[1].split(":", 1)[1])))
    return frames


def _done(frames):
    return next(payload for event, payload in frames if event == "done")


def test_refusal_carries_a_way_out(client, demo_pdf_bytes):
    """拒答要给出「教材里最接近的段落」和「下一步怎么办」。"""
    book = _upload(client, demo_pdf_bytes)
    chapter = book["chapters"][0]

    data = _ask(client, book, chapter["id"], OFF_TOPIC_WITH_WEAK_HIT)

    assert data["answer"] == REJECTED
    assert data["noEvidence"] is True
    assert data["hint"], "拒答必须给出下一步，否则用户无路可走"
    assert data["closest"], "检索有命中，就该把最接近的段落摆出来"

    for item in data["closest"]:
        assert set(item) == {"id", "page", "text", "chapterId", "chapterTitle"}
        assert item["text"] and item["page"] > 0

    assert len(data["closest"]) <= 3, "给多了像在硬凑依据"


def test_closest_is_not_confused_with_sources(client, demo_pdf_bytes):
    """`closest` 不是依据：绝不进 `sources`。

    这是溯源可信度的边界——把「没答上来」和「出处就是这里」混为一谈，
    就等于把一段没被采信过的原文伪装成回答的依据。
    """
    book = _upload(client, demo_pdf_bytes)
    data = _ask(client, book, book["chapters"][0]["id"], OFF_TOPIC_WITH_WEAK_HIT)

    assert data["sources"] == []
    assert data["sourceDetails"] == []
    assert data["closest"], "前提：确实有最接近的段落可给"


def test_refusal_without_any_hit_has_empty_closest(client, demo_pdf_bytes):
    """连一个词都撞不上时，`closest` 是空列表——不编造「最接近的段落」。"""
    book = _upload(client, demo_pdf_bytes)
    data = _ask(client, book, book["chapters"][0]["id"], OFF_TOPIC_WITHOUT_HIT)

    assert data["answer"] == REJECTED
    assert data["noEvidence"] is True
    assert data["closest"] == []


def test_refusal_scope_is_not_hardcoded_to_chapter(client, demo_pdf_bytes):
    """拒答也要如实报检索范围。

    旧实现把 `scope` 硬编码成 `chapter`，可实际扫的是整本书；前端因此认为
    「没有跨章」，连「依据取自全书」这类提示都显示不出来。
    """
    book = _upload(client, demo_pdf_bytes)
    # 在第 1 章里问，命中的却来自第 2 章（`有多` 出现在导数那一章）
    data = _ask(client, book, book["chapters"][0]["id"], OFF_TOPIC_WITH_WEAK_HIT)

    chapter_ids = {item["chapterId"] for item in data["closest"]}
    if chapter_ids - {book["chapters"][0]["id"]}:
        assert data["scope"] == "book", "命中跨了章，scope 就该报 book"
    else:
        pytest.skip("该问法在这本教材上没有跨章命中，无法验证 scope")


def test_stream_refusal_matches_the_non_stream_contract(client, demo_pdf_bytes):
    """两个接口的拒答契约必须一致（旧实现只有流式带 `noEvidence`）。"""
    book = _upload(client, demo_pdf_bytes)
    chapter = book["chapters"][1]

    plain = _ask(client, book, chapter["id"], OFF_TOPIC_WITH_WEAK_HIT)
    done = _done(_ask_stream(client, book, chapter["id"], OFF_TOPIC_WITH_WEAK_HIT))

    for key in ("answer", "noEvidence", "scope", "hint"):
        assert done[key] == plain[key], f"`{key}` 在两个接口上不一致"
    assert [item["id"] for item in done["closest"]] == [item["id"] for item in plain["closest"]]


def test_successful_answer_always_carries_noevidence_false(client, demo_pdf_bytes):
    """成功回答同样带 `noEvidence: False`——契约恒定，客户端不必靠文本比对猜。"""
    book = _upload(client, demo_pdf_bytes)
    chapter = book["chapters"][1]

    plain = _ask(client, book, chapter["id"], "导数的定义是什么？")
    assert plain["noEvidence"] is False
    assert "closest" not in plain, "有依据时不该带 `closest`"

    done = _done(_ask_stream(client, book, chapter["id"], "导数的定义是什么？"))
    assert done["noEvidence"] is False


def test_verbatim_match_is_evidence_even_in_a_tiny_corpus(client):
    """「复现词」在小语料上必然失效，所以要靠第二条通道救回来。

    只有一段的教材里，每个词的 df 都是 1 → 复现词恒为空。这不是退化场景而已：
    「某个概念全书只在一处出现」同样如此。那时能当依据的是**问句与段落的高度重合**
    ——所以判定是「复现词 **或** 覆盖率达标」的并集，缺任何一条都会误拒。
    """
    raw = (
        "第1章 列表与可变对象\n"
        "为什么列表是可变的？列表之所以被称为可变对象，是因为它支持原地修改。\n"
    ).encode("utf-8")
    book = client.post("/api/books", files={"file": ("Python编程.txt", raw, "text/plain")}).json()

    data = _ask(client, book, book["chapters"][0]["id"], "为什么列表是可变的？")

    assert data["noEvidence"] is False, "单段教材上问它自己讲的内容，不该被判成没依据"
    assert data["sources"], "有依据就要给溯源锚点"


def test_thread_keeps_the_way_out_after_reload(client, demo_pdf_bytes):
    """线程重新打开时，拒答的出口不能丢——否则回看历史又变成死路。"""
    book = _upload(client, demo_pdf_bytes)
    chapter = book["chapters"][0]

    thread = client.post(
        "/api/threads",
        json={"bookId": book["id"], "chapterId": chapter["id"]},
    ).json()
    _ask(client, book, chapter["id"], OFF_TOPIC_WITH_WEAK_HIT, threadId=thread["id"])

    reloaded = client.get(f"/api/threads/{thread['id']}").json()
    answer = reloaded["messages"][-1]

    assert answer["role"] == "assistant"
    assert answer["noEvidence"] is True
    assert answer["hint"]
    assert answer["closest"], "落库后仍要能回看最接近的段落"
    assert answer["sources"] == []
