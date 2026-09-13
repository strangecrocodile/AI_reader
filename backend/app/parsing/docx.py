"""Word（.docx）解析：按 Word 大纲层级识别章与节，产出统一的 ParsedBook。

- 用 Word 原生标题样式（Heading 1..9）判定层级，比正则猜标题可靠；
- Title/Subtitle 样式视为书名，不进正文；
- 比「章」更深的标题（通常是节）作为章内小节，kind='heading'，不参与问答检索；
- 没有标题样式时退回文本模式（第X章 / Chapter N / 附录A，见 base.build_blocks）；
- Word 没有物理页码，段落页号为按字数的**虚拟页码**（见 base 模块说明）。

说明：仅读取正文段落（`doc.paragraphs`），表格内容暂不解析。
"""
import io
import re
from typing import List, Tuple

from docx import Document

from .base import ParsedBook, assemble_book, build_blocks

_HEADING_RE = re.compile(r"^Heading\s+(\d+)$", re.IGNORECASE)
#: 视为书名的 Word 样式
_TITLE_STYLES = ("title", "subtitle")


def _level_of(style_name: str) -> int:
    """Word 样式名 → 层级：Heading N = N，其余（含 Title）= 0。"""
    match = _HEADING_RE.match((style_name or "").strip())
    return min(int(match.group(1)), 9) if match else 0


def read_rows(data: bytes) -> List[Tuple[str, int, str]]:
    """读出 [(段落文本, 层级, 样式名)]，跳过空段。"""
    document = Document(io.BytesIO(data))
    rows: List[Tuple[str, int, str]] = []
    for paragraph in document.paragraphs:
        text = (paragraph.text or "").strip()
        if not text:
            continue
        style = paragraph.style.name if paragraph.style is not None else "Normal"
        rows.append((text, _level_of(style), style))
    return rows


def parse_docx_bytes(data: bytes, default_title: str = "未命名教材") -> ParsedBook:
    rows = read_rows(data)

    title = ""
    body: List[Tuple[str, int]] = []
    for text, level, style in rows:
        if style.lower() in _TITLE_STYLES:
            title = title or text  # 书名只取第一次出现的 Title/Subtitle
            continue
        body.append((text, level))

    return assemble_book(title, build_blocks(body), default_title)
