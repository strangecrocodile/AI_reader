"""PDF 解析单元测试（使用原创示例教材）。"""
from typing import Any, Dict, List, Optional

import pytest

from app.parsing.base import runs_payload
from app.parsing.pdf import (
    _pick_chapter_level,
    _repeated_margin_lines,
    _split_styled_paragraphs,
    parse_pdf_stream,
)


def _line(text: str, *, bold: bool = False, size: float = 11.0, dy: float = 0.0) -> Dict[str, Any]:
    """造一个 PDF line：`dy` 是该 span 相对基线的偏移（正数=更靠上）。

    非粗体用 "Regular" 而不是 "Helvetica-Bold"，避免样式断言依赖字体名的细节。
    """
    flags = 16 if bold else 0
    base_y = 100.0
    return {
        "spans": [
            {
                "text": text,
                "font": "Demo-Bold" if bold else "Demo-Regular",
                "size": size,
                "flags": flags,
                "color": 0,
                "origin": (50.0, base_y - dy),
            }
        ]
    }


def _fake_page(blocks: List[List[Dict[str, Any]]]):
    """最小 page 替身：只需要 `get_text("dict")`。

    参数是「块列表」，每块是若干行。基线按块统一计算，所以同一段里的行必须放进
    同一个块——这与 PyMuPDF 的真实结构一致，也让上下标检测有可比对的参照。
    """

    class _Page:
        def get_text(self, kind: str = "text"):
            return {"blocks": [{"type": 0, "lines": lines} for lines in blocks]}

    return _Page()


def _paras(text_or_lines, skip_lines: Optional[set] = None, base=None, blocks=None):
    """按行切段，返回 [(纯文本, 片段 JSON)]。

    传字符串时每行造一个无样式 span——绝大多数用例只关心文本切分，
    只有样式相关的用例才需要自己拼 line。默认全部行放进**同一个块**。
    底层返回的 y 只在插图/表格排版时需要，这里丢掉。
    """
    if blocks is None:
        if isinstance(text_or_lines, str):
            blocks = [[_line(raw) for raw in text_or_lines.splitlines() if raw.strip()]]
        else:
            blocks = [text_or_lines]
    result = []
    for _y, runs, text in _split_styled_paragraphs(
        _fake_page(blocks), skip_lines=skip_lines, base=base
    ):
        payload = runs_payload(runs) or {"runs": []}
        result.append((text, payload["runs"]))
    return result


def _texts(text_or_lines, skip_lines: Optional[set] = None) -> List[str]:
    return [text for text, _ in _paras(text_or_lines, skip_lines=skip_lines)]


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
    paras = _texts(text, skip_lines={"页眉", "https://example.com/"})
    assert paras == ["正文第一句应当保留。"]


def test_split_paragraphs_strips_trailing_footer_url():
    """页脚 URL 粘在正文尾部时应被剥离。"""
    assert _texts("原文到此处结束https://nndl.github.io/") == ["原文到此处结束"]


def test_split_paragraphs_handles_fullwidth_full_stop():
    """回归：教材用「．」(U+FF0E) 作句号时也要能断段。

    只认「。」会让整页文字黏成一段（实测某教材中位段长一度涨到 588 字）。
    """
    paras = _texts("第一句话到这里结束了．\n第二句话开始了．")
    assert len(paras) == 2


def test_ascii_period_ends_a_sentence_but_not_a_decimal():
    """半角句点要能断段（英文教材），但不能切开数字里的点。"""
    assert len(_texts("First sentence.\nSecond sentence.")) == 2
    # 3.14 与行尾的「3.」都不该被当成句末
    assert len(_texts("圆周率约等于3.14\n它是个无理数。")) == 1
    assert len(_texts("极限值记作3.\n下一句在这里。")) == 1


def test_split_paragraphs_rejoins_sentence_broken_by_header():
    """被页眉打断的句子应重新接上，而不是切成两段碎片。"""
    paras = _texts("前半句还没有结束\n页眉\n后半句继续。", skip_lines={"页眉"})
    assert paras == ["前半句还没有结束后半句继续。"]


# ---------- 行内版式（content.runs） ----------


def test_styled_paragraph_keeps_text_and_styles_in_sync():
    """片段拼起来必须等于纯文本——这是渲染与锚点定位的共同前提。"""
    lines = [
        _line("比值 "),
        _line("Δy / Δx", dy=3.0, size=7.0),   # 字号更小且基线偏上 → 上标
        _line(" 的极限存在，称为"),
        _line("导数", bold=True),
        _line("。"),
    ]
    paras = _paras(lines)
    text, runs = paras[0]

    assert text == "比值 Δy / Δx 的极限存在，称为导数。"
    assert "".join(r["text"] for r in runs) == text
    assert any("sup" in r["style"] for r in runs)
    assert any("b" in r["style"] for r in runs)


def test_bold_detected_from_flags_and_from_font_name():
    """粗体判定要同时认 flags 与字体名——不同生成器给的信息不一样。"""
    by_flags = _paras([_line("导数", bold=True)])[0][1]
    assert any("b" in r["style"] for r in by_flags)

    # 只给字体名、不给 flags 的情况（字体名带 Bold 就够）
    named = _line("导数")
    named["spans"][0]["font"] = "SourceHanSerifCN-Bold"
    assert any("b" in r["style"] for r in _paras([named])[0][1])


def test_subscript_baseline_detected():
    """基线偏下 → 下标（PDF 没有直接的上下标标记，只能看基线）。

    下标与正文放在**同一行**：独占一行的裸数字会被页码行过滤规则当成页脚丢掉，
    那是为页码设计的既有行为，不该被这个用例当成缺陷。
    """
    line = {
        "spans": [
            {"text": "x", "font": "Demo-Regular", "size": 11.0, "flags": 0, "origin": (50.0, 100.0)},
            {"text": "0", "font": "Demo-Regular", "size": 7.0, "flags": 0, "origin": (57.0, 103.0)},
            {"text": " 处的导数。", "font": "Demo-Regular", "size": 11.0, "flags": 0, "origin": (60.0, 100.0)},
        ]
    }
    runs = _paras([line])[0][1]

    assert [r["style"] for r in runs if r["text"] == "0"] == [["sub"]]


def test_large_and_small_sizes_map_to_style_tokens():
    """相对正文基准字号的大小档位。"""
    from app.parsing.pdf import _Base

    base = _Base(body_size=10.0)
    lines = [_line("标题", size=13.0), _line("注释", size=7.0), _line("正文", size=10.0)]
    runs = _paras(lines, base=base)[0][1]
    styles = {r["text"]: r["style"] for r in runs}

    assert "lg" in styles["标题"]
    assert "sm" in styles["注释"]
    assert styles["正文"] == []


def test_adjacent_same_style_runs_are_merged():
    """相邻同样式必须合并，否则一个普通段落会碎成几十个 span。"""
    lines = [_line("导", bold=True), _line("数", bold=True), _line("定义", bold=True)]
    runs = _paras(lines)[0][1]

    assert runs == [{"text": "导数定义", "style": ["b"]}]


def test_parse_pdf_content_matches_text(demo_pdf_bytes):
    """端到端：每个段落的片段拼起来都要等于它的纯文本。"""
    book = parse_pdf_stream(demo_pdf_bytes, "demo")
    checked = 0
    for chapter in book.chapters:
        for section in chapter.sections:
            runs = (section.content or {}).get("runs")
            if not runs:
                continue
            assert "".join(r["text"] for r in runs) == section.text
            checked += 1
    assert checked, "示例 PDF 应当至少解析出一个带版式信息的段落"
