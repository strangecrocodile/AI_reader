"""富文本（行内版式）解析：Word 与 PDF 都要产出可渲染的片段，且不破坏纯文本。

核心不变量：**片段拼起来必须等于 `section.text`**。检索、锚点、划词定位全都建立在
`text` 上，片段只是额外的渲染信息；两者一旦不一致，就会出现「渲染出来的字和
能选中的字不是同一批」这种极难排查的问题。所以这里既测样式识别，也测不变量。

覆盖：
- Word：粗体 / 斜体 / 上下标 / 字号档位识别；
- Word：`paragraph.runs` 读不全时（超链接、域代码）退回纯文本，绝不丢字；
- Word：无格式正文不产出多余片段（content 为 None，渲染走回退路径）；
- base：片段合并、空白片段丢弃、样式 token 白名单。
"""
import io

from docx import Document
from docx.shared import Pt

from app.parsing.base import STYLE_TOKENS, make_run, merge_runs, runs_payload, text_of_runs
from app.parsing.docx import parse_docx_bytes, styled_runs_of


def _styled_paragraph(*runs):
    """用 python-docx 组装一个带格式的段落并保存为 bytes。

    格式用 `{属性名: 值}` 给出，属性名是 `run.font` 上的名字（bold / italic /
    superscript / subscript / size），而不是点号路径——`setattr(r, "font.bold", True)`
    会设出一个名为 "font.bold" 的新属性，什么格式都不会写进文档。
    """
    document = Document()
    document.add_heading("第1章 富文本测试", level=1)
    paragraph = document.add_paragraph()
    for text, attrs in runs:
        run = paragraph.add_run(text)
        for name, value in attrs.items():
            setattr(run.font, name, value)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _sections(data: bytes):
    book = parse_docx_bytes(data)
    return [s for chapter in book.chapters for s in chapter.sections if s.kind == "p"]


def test_docx_bold_and_italic_become_style_tokens():
    data = _styled_paragraph(
        ("普通", {}), ("加粗", {"bold": True}), ("斜体", {"italic": True}), ("，结束。", {})
    )
    section = _sections(data)[0]
    styles = {run["text"]: run["style"] for run in section.content["runs"]}

    assert section.text == "普通加粗斜体，结束。"
    assert "b" in styles["加粗"]
    assert "i" in styles["斜体"]
    assert styles["普通"] == []


def test_docx_superscript_and_subscript_detected():
    data = _styled_paragraph(
        ("x", {}),
        ("2", {"superscript": True}),
        (" 与 a", {}),
        ("n", {"subscript": True}),
        (" 都是常见写法。", {}),
    )
    section = _sections(data)[0]
    styles = {run["text"]: run["style"] for run in section.content["runs"]}

    assert "sup" in styles["2"]
    assert "sub" in styles["n"]


def test_docx_larger_font_marks_large_token():
    """比正文中位数大的字号 → lg（用于还原小节标题的视觉层级）。"""
    data = _styled_paragraph(
        ("正文一句话。", {"size": Pt(10)}), ("大一号的字。", {"size": Pt(16)})
    )
    section = _sections(data)[0]
    styles = {run["text"]: run["style"] for run in section.content["runs"]}

    # 正文基准字号取**众数**：这里 10pt 与 16pt 各一次，并列时取较小者
    assert "lg" in styles["大一号的字。"]
    assert styles["正文一句话。"] == []


def test_docx_plain_paragraph_has_no_content():
    """没有任何行内格式时 content 为 None，渲染层走纯文本回退路径。"""
    data = _styled_paragraph(("这是一段完全普通的正文。", {}))
    section = _sections(data)[0]

    assert section.content is None
    assert section.text == "这是一段完全普通的正文。"


def test_docx_runs_text_always_matches_section_text():
    """不变量：所有片段的文本拼起来等于段落纯文本。"""
    data = _styled_paragraph(
        ("设 ", {}), ("f(x)", {"bold": True}), (" 在点 ", {}), ("x", {}),
        ("0", {"subscript": True}), (" 处可导，则 ", {}), ("f′(x", {"italic": True}),
        ("0", {"subscript": True}), (") 存在。", {"italic": True}),
    )
    section = _sections(data)[0]
    runs = section.content["runs"]

    assert text_of_runs(runs) == section.text
    assert section.text == "设 f(x) 在点 x0 处可导，则 f′(x0) 存在。"


def test_docx_falls_back_to_plain_text_when_runs_are_incomplete():
    """`paragraph.runs` 读不到超链接等节点时，宁可整段退回纯文本，也不能丢字。"""
    document = Document()
    paragraph = document.add_paragraph("前言")
    paragraph.add_run("中间")
    # 超链接里的文字不在 paragraph.runs 里，但 paragraph.text 有
    hyperlink_text_expected = paragraph.text

    class _Paragraph:
        runs = paragraph.runs
        text = hyperlink_text_expected + "（链接文字）"

    runs, plain = styled_runs_of(_Paragraph(), body_size=None)

    assert runs == []
    assert plain == hyperlink_text_expected + "（链接文字）"


# ---------- base 层的片段工具 ----------


def test_make_run_drops_blank_and_filters_unknown_tokens():
    assert make_run("   ") is None
    assert make_run("") is None
    assert make_run("字", "b", "不存在的样式").style == ("b",)
    # 重复 token 只留一个
    assert make_run("字", "b", "b").style == ("b",)


def test_merge_runs_joins_only_adjacent_same_style():
    merged = merge_runs(
        [make_run("a", "b"), make_run("b", "b"), make_run("c"), make_run("d", "b")]
    )

    assert [(r.text, r.style) for r in merged] == [("ab", ("b",)), ("c", ()), ("d", ("b",))]


def test_runs_payload_is_none_without_any_valid_run():
    assert runs_payload([None, make_run("  ")]) is None


def test_style_tokens_are_a_small_whitelist():
    """样式 token 必须是一份白名单：透传字体名会让前端加载不可控的字体。"""
    assert set(STYLE_TOKENS) == {"b", "i", "sup", "sub", "lg", "sm"}
