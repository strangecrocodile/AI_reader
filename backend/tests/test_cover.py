"""封面卡片上的每一句都必须对得上这本书。

这是首屏：用户导入教材后第一眼看到的就是它。这里以前对所有教材硬编码
`lines: [title, "注：演示数据"]` 与一行微积分公式（`f′(x₀) = lim Δx→0 …`），
于是上传一本法学期刊，书架上也写着「注：演示数据」并配着导数公式——
用户会以为自己的书没被正确导入，评委则会以为整个产品只有演示数据。

判据分两层：**不许出现假信息**（负向断言），**真实信息要真的在**（正向断言）。
只有负向断言的话，把封面清空也能通过。
"""
import pytest

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

#: 这些字符串曾经被后端无差别盖在所有教材上
FORBIDDEN_COVER_STRINGS = ("注：演示数据", "f′(x₀) = lim Δx→0 …", "∫ f(x) dx")


def _upload(client, name: str, data: bytes, mime: str) -> dict:
    res = client.post("/api/books", files={"file": (name, data, mime)})
    assert res.status_code == 201, res.text
    return res.json()


def _cover_text(book: dict) -> str:
    cover = book["cover"]
    return " ".join([cover["series"], *cover["lines"], *cover["formula"], cover["footer"]])


@pytest.mark.parametrize(
    "filename,mime,fixture_name,expected_format_label",
    [
        ("教材.docx", DOCX_MIME, "demo_docx_bytes", "WORD"),
        ("教材.pdf", "application/pdf", "demo_pdf_bytes", "PDF"),
    ],
)
def test_cover_is_derived_from_the_book_not_hardcoded(
    request, client, filename, mime, fixture_name, expected_format_label
):
    book = _upload(client, filename, request.getfixturevalue(fixture_name), mime)

    text = _cover_text(book)
    for forbidden in FORBIDDEN_COVER_STRINGS:
        assert forbidden not in text, f"封面又出现了写死的假信息：{forbidden!r}"

    # 正向：书名、来源格式、章节数、来源说明都要在场
    assert book["title"] in book["cover"]["lines"]
    assert expected_format_label in book["cover"]["formula"]
    assert f"{len(book['chapters'])} 章" in book["cover"]["formula"]
    assert book["cover"]["footer"] == book["author"]


def test_plain_text_book_gets_text_label(client):
    data = "# 微积分入门\n\n## 第1章 函数\n\n函数是一种对应关系，对每个 x 有唯一的 y。\n".encode()
    book = _upload(client, "教材.md", data, "text/markdown")

    assert "文本" in book["cover"]["formula"]
    assert book["title"] in book["cover"]["lines"]


def test_uploaded_book_without_author_still_reads_as_a_source(client, demo_docx_bytes):
    """上传的教材没有 author 字段，页脚不能是空白——首屏留一个空槽位看不出所以然。"""
    book = _upload(client, "无作者.docx", demo_docx_bytes, DOCX_MIME)

    assert book["author"] == "来源：用户导入"
    assert book["cover"]["footer"] == "来源：用户导入"


def test_books_list_and_detail_agree_on_the_cover(client, demo_docx_bytes):
    """书架列表与详情走同一套序列化；两处封面不一致会让人觉得列表是缓存错的。"""
    book = _upload(client, "一致性.docx", demo_docx_bytes, DOCX_MIME)

    listed = next(b for b in client.get("/api/books").json() if b["id"] == book["id"])
    detail = client.get(f"/api/books/{book['id']}").json()

    assert listed["cover"] == detail["cover"] == book["cover"]
