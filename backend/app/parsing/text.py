"""纯文本 / Markdown 解析：.txt / .md → 统一 ParsedBook。

- Markdown 标题（`#` 数量即层级）与 Word 大纲走同一套章/节判定（见 base.build_blocks）；
- 纯文本按「第X章 / Chapter N / Part N / 附录A」文本模式识别章，
  「第X节 / 1.2 标题」识别为章内小节；
- 代码围栏（```）内的内容按正文保留（技术教材的示例代码不该丢），但不参与标题识别；
- 编码：UTF-8(含 BOM) → GB18030（GBK/GB2312 超集）→ 兜底替换，与 kb-agent 一致。
"""
import re
from typing import List, Tuple

from .base import ParsedBook, assemble_book, build_blocks, chapter_level_of

_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_MAX_MD_LEVEL = 6


def decode_bytes(raw: bytes) -> str:
    """文本编码探测，避免中文 txt 因 GBK 编码读成乱码。"""
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_rows(text: str) -> List[Tuple[str, int]]:
    """读出 [(段落文本, 标题层级)]；Markdown 标题给出层级，其余为 0。"""
    rows: List[Tuple[str, int]] = []
    in_code = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if not stripped:
            continue
        match = None if in_code else _MD_HEADING_RE.match(stripped)
        if match:
            rows.append((match.group(2).strip(), min(len(match.group(1)), _MAX_MD_LEVEL)))
        else:
            rows.append((stripped, 0))
    return rows


def parse_text_bytes(data: bytes, default_title: str = "未命名教材") -> ParsedBook:
    rows = read_rows(decode_bytes(data))

    # 只有一个 Markdown 一级标题、而章在更深层时，这个一级标题就是书名
    title = ""
    chapter_level = chapter_level_of(rows)
    if chapter_level is not None and chapter_level > 1:
        top = [text for text, level in rows if level == 1]
        if top:
            title = top[0].strip()

    return assemble_book(title, build_blocks(rows), default_title)
