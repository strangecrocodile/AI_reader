"""docx 解析（P0/P1）：把 Word 文档读成统一、有序的“段落行”。

每种段落保留：文本、Word 样式名、是否为标题及标题级别、在文档中的顺序。
后续的章节识别（split.py）与拆书都基于这里输出的 ParaRow 列表工作，
不直接依赖 python-docx 的细节，便于测试与替换。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from docx import Document

_HEADING_RE = re.compile(r"^Heading\s+(\d+)$", re.IGNORECASE)


@dataclass(frozen=True)
class ParaRow:
    """文档中的一个非空段落。level：0=正文，1..9=标题层级。"""

    text: str
    style: str
    level: int
    index: int  # 在文档中的原始顺序（含被跳过的空段）

    @property
    def is_heading(self) -> bool:
        return self.level >= 1


def _level_of(style_name: str | None) -> int:
    """把 Word 样式名换算成层级：Title=0（当作标题但非章节），Heading N=N，其余=正文0。"""
    name = (style_name or "").strip()
    if name.lower() in ("title", "subtitle"):
        return 0
    m = _HEADING_RE.match(name)
    if m:
        return int(m.group(1))
    return 0


def read_paragraphs(path: str | Path) -> list[ParaRow]:
    """读取 .docx 所有段落；.txt/.md 按行读入（自动识别 UTF-8/GB18030 编码）。

    返回按文档顺序排列的 ParaRow 列表（跳过空行/空段）。
    TXT 没有 Word 样式，全部按正文（level=0）处理，章节交给 split.py
    的“文本模式”识别（第X章 / Chapter N 等）。
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".txt", ".md"):
        return _read_text_lines(path)
    doc = Document(str(path))
    rows: list[ParaRow] = []
    for i, para in enumerate(doc.paragraphs):
        text = para.text.strip()
        if not text:
            continue
        style = para.style.name if para.style is not None else "Normal"
        rows.append(ParaRow(text=text, style=style, level=_level_of(style), index=i))
    return rows


def _decode_text_bytes(raw: bytes) -> str:
    """TXT 编码探测：UTF-8(含 BOM) → GB18030（GBK/GB2312 超集）→ 兜底替换。"""
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


def _read_text_lines(path: Path) -> list[ParaRow]:
    raw = path.read_bytes()
    text = _decode_text_bytes(raw)
    rows: list[ParaRow] = []
    in_code = False  # Markdown ``` 代码块内的行不算正文/标题
    for i, line in enumerate(text.splitlines()):
        line = line.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not line:
            continue
        # Markdown 标题（# 数 = 层级）→ 章节识别可走 Heading 路径
        m = _MD_HEADING_RE.match(line)
        if m:
            level = min(len(m.group(1)), 9)
            rows.append(ParaRow(text=m.group(2).strip(), style=f"Heading {level}", level=level, index=i))
            continue
        rows.append(ParaRow(text=line, style="Normal", level=0, index=i))
    return rows
