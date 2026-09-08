"""PDF 解析单元测试（使用原创示例教材）。"""
import pytest

from app.parsing.pdf import parse_pdf_stream


def test_parse_structure(demo_pdf_bytes):
    book = parse_pdf_stream(demo_pdf_bytes, "demo")
    assert "微积分" in book.title
    assert len(book.chapters) >= 2
    assert "第1章" in book.chapters[0].title.replace(" ", "")
    assert "第2章" in book.chapters[1].title.replace(" ", "")
    for ch in book.chapters:
        assert ch.sections, "章节应有段落"
        assert ch.page_start <= ch.page_end
        assert ch.full_text.strip()
        # 章节标题不应残留在首个段落
        assert not ch.sections[0].text.startswith(ch.title[:4])


def test_sections_have_anchors(demo_pdf_bytes):
    book = parse_pdf_stream(demo_pdf_bytes, "demo")
    ch = book.chapters[1]
    ids = [f"s{ch.num}-{s.seq}" for s in ch.sections]
    assert len(ids) == len(set(ids)), "段落锚点 id 唯一"
    assert all(s.page >= 1 for s in ch.sections)


def test_invalid_pdf_raises():
    with pytest.raises(Exception):
        parse_pdf_stream(b"not a pdf at all", "bad")
