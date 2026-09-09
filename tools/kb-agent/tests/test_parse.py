"""parse 模块测试：docx → ParaRow 的段落/样式/标题读取。"""
from pathlib import Path

from make_sample_book import build_sample_book
from kb_agent.parse import read_paragraphs


def test_read_sample_paragraphs(tmp_path: Path):
    book = build_sample_book(tmp_path / "sample.docx")
    rows = read_paragraphs(book)

    # 样例书：1 个 Title + 2 个 Heading1 + 2 章正文 4+5 段
    titles = [r for r in rows if r.style.lower() == "title"]
    assert len(titles) == 1
    assert titles[0].text == "微积分简明讲义（样例）"

    headings = [r for r in rows if r.is_heading]
    assert [r.text for r in headings] == ["第一章 函数与极限", "第二章 导数与微分"]

    body = [r for r in rows if not r.is_heading and r.style.lower() != "title"]
    assert len(body) == 10  # 作者行 1 + 第一章 4 + 第二章 5 段正文
    assert all(r.level == 0 for r in body)


def test_read_empty_docx(tmp_path: Path):
    from docx import Document

    p = tmp_path / "empty.docx"
    Document().save(p)
    assert read_paragraphs(p) == []
