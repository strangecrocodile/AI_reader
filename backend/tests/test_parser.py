"""PDF 解析单元测试（使用原创示例教材）。"""
import pytest

from app.parsing.pdf import (
    _pick_chapter_level,
    _repeated_margin_lines,
    _split_paragraphs,
    parse_pdf_stream,
)


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


# ---------- 多级书签：章节层级选择 ----------


def test_pick_chapter_level_skips_part_level():
    """第 1 层是「部分」时，应选第 2 层的「章」。

    回归用例：某教材第 1 层只有 5 个「部分」，真正的 20 章在第 2 层；
    旧实现写死 level == 1，于是整本书被拆成 5 个巨型「部分」。
    """
    toc = [
        (1, "目录", 7),
        (1, "第一部分 机器学习基础", 16),
        (1, "第二部分 基础模型", 92),
        (1, "第三部分 进阶模型", 267),
        (2, "第1章  绪论", 17),
        (2, "第2章  机器学习概述", 37),
        (2, "第3章  线性模型", 68),
        (3, "1.1 人工智能", 18),
    ]
    assert _pick_chapter_level(toc) == 2


def test_pick_chapter_level_keeps_shallowest_when_chapters_there():
    """章就在第 1 层时，不应被更深的层抢走。"""
    toc = [
        (1, "第1章 函数", 1),
        (1, "第2章 极限", 10),
        (1, "第3章 导数", 20),
        (2, "1.1 小节", 1),
    ]
    assert _pick_chapter_level(toc) == 1


def test_pick_chapter_level_falls_back_without_chapter_titles():
    """标题不合章模式时，退回最浅层（保持旧行为）。"""
    toc = [(1, "函数", 1), (1, "极限", 10), (1, "导数", 20)]
    assert _pick_chapter_level(toc) == 1


def test_parse_pdf_uses_chapter_toc_level():
    """端到端：书签为「部分(1) → 章(2)」时，应识别出章而不是部分。"""
    book = parse_pdf_stream(_part_toc_pdf(), "toc-demo")
    titles = [c.title.strip() for c in book.chapters]
    assert len(book.chapters) == 4
    assert all("Chapter" in t for t in titles)
    assert not any("Part" in t for t in titles)


def _part_toc_pdf() -> bytes:
    """构造一份「部分 → 章」两级书签的 PDF。"""
    import pymupdf as fitz

    doc = fitz.open()
    for i in range(4):
        page = doc.new_page()
        page.insert_text((72, 72), f"Body text of page {i + 1}.", fontsize=11)
    doc.set_toc(
        [
            [1, "Part 1 Basics", 1],
            [2, "Chapter 1 Intro", 1],
            [2, "Chapter 2 Method", 2],
            [2, "Chapter 3 Advanced", 3],
            [2, "Chapter 4 Summary", 4],
            [3, "1.1 Section", 1],
        ]
    )
    data = doc.tobytes()
    doc.close()
    return data


# ---------- 页眉 / 页脚 / 目录行剔除 ----------


def test_repeated_margin_lines_detects_running_header():
    """跨页重复出现的页眉与页脚 URL 应被识别出来。"""
    pages = [f"页眉\n正文第{i}页的内容。\nhttps://example.com/" for i in range(1, 11)]
    skip = _repeated_margin_lines(pages)
    assert "页眉" in skip
    assert "https://example.com/" in skip


def test_repeated_margin_lines_ignores_body_text():
    """正文每页都不同，不应被误判为页眉。"""
    pages = [f"页眉\n正文第{i}页的内容。\n脚注{i}" for i in range(1, 11)]
    skip = _repeated_margin_lines(pages)
    assert skip == {"页眉"}


def test_split_paragraphs_drops_margin_and_toc_lines():
    text = (
        "人工智能. . . . . . . . . . . . . . . . 3\n"
        "正文第一句应当保留。\n"
        "页眉\n"
        "https://example.com/\n"
    )
    paras = _split_paragraphs(text, skip_lines={"页眉", "https://example.com/"})
    assert paras == ["正文第一句应当保留。"]


def test_split_paragraphs_strips_trailing_footer_url():
    """页脚 URL 粘在正文尾部时应被剥离。"""
    assert _split_paragraphs("原文到此处结束https://nndl.github.io/") == ["原文到此处结束"]


def test_split_paragraphs_handles_fullwidth_full_stop():
    """回归：教材用「．」(U+FF0E) 作句号时也要能断段。

    只认「。」会让整页文字黏成一段（实测某教材中位段长一度涨到 588 字）。
    """
    paras = _split_paragraphs("第一句话到这里结束了．\n第二句话开始了．")
    assert len(paras) == 2


def test_split_paragraphs_rejoins_sentence_broken_by_header():
    """被页眉打断的句子应重新接上，而不是切成两段碎片。"""
    paras = _split_paragraphs("前半句还没有结束\n页眉\n后半句继续。", skip_lines={"页眉"})
    assert paras == ["前半句还没有结束后半句继续。"]
