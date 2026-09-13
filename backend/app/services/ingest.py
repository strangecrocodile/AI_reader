"""教材入库：多格式文件 → 解析 → SQLite（教材/章节/段落/锚点）。

支持 PDF、Word（.docx）与纯文本（.txt/.md）。三种格式解析后产出同一套
章节-段落-锚点模型，因此检索、溯源问答、知识点图谱等下游逻辑完全共用，
不需要按来源格式分叉（页码差异见 `parsing/base.py` 的虚拟页码说明）。
"""
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..db import Database
from ..parsing.docx import parse_docx_bytes
from ..parsing.pdf import parse_pdf_stream
from ..parsing.text import parse_text_bytes

PDF = "pdf"
DOCX = "docx"
TEXT = "text"

#: 格式不支持时给用户看的提示（前端也会用同样的文案做前置校验）
SUPPORTED_MESSAGE = "目前支持 PDF / Word(.docx) / 纯文本(.txt/.md) 教材；.doc 请先另存为 .docx"
_TEXT_SUFFIXES = (".txt", ".md", ".markdown")


def detect_format(filename: str = "", content_type: str = "") -> Optional[str]:
    """按扩展名判断来源格式；扩展名缺失或不可识别时退回 content-type。"""
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".pdf":
        return PDF
    if suffix == ".docx":
        return DOCX
    if suffix in _TEXT_SUFFIXES:
        return TEXT

    content = (content_type or "").lower()
    if content == "application/pdf":
        return PDF
    if "wordprocessingml" in content:
        return DOCX
    if content.startswith("text/"):
        return TEXT
    return None


def parse_bytes(fmt: str, data: bytes, default_title: str = "未命名教材"):
    """按格式解析为 ParsedBook（章节 → 段落，段落为最小锚点粒度）。"""
    if fmt == PDF:
        return parse_pdf_stream(data, default_title)
    if fmt == DOCX:
        return parse_docx_bytes(data, default_title)
    if fmt == TEXT:
        return parse_text_bytes(data, default_title)
    raise ValueError(SUPPORTED_MESSAGE)


def ingest_file_bytes(
    db: Database,
    file_bytes: bytes,
    filename: str = "",
    content_type: str = "",
    default_title: str = "未命名教材",
) -> Dict[str, Any]:
    """解析并入库任意受支持格式，返回教材元信息（含章节）。"""
    fmt = detect_format(filename, content_type)
    if fmt is None:
        raise ValueError(SUPPORTED_MESSAGE)

    parsed = parse_bytes(fmt, file_bytes, default_title)
    if not parsed.chapters:
        raise ValueError("未能从文件中识别出章节内容")

    book_id = uuid.uuid4().hex[:8]
    book_row = {
        "id": book_id,
        "title": parsed.title or default_title,
        "author": "",
        "note": f"来源格式：{fmt}",
        "progress_pct": 0.0,
        "created_at": _now(),
    }

    chapter_rows: List[Dict[str, Any]] = []
    section_rows: List[Dict[str, Any]] = []
    anchor_rows: List[Dict[str, Any]] = []
    for chapter in parsed.chapters:
        chapter_id = f"{book_id}-ch{chapter.num}"
        chapter_rows.append(
            {
                "id": chapter_id,
                "book_id": book_id,
                "num": chapter.num,
                "title": chapter.title,
                "page_start": chapter.page_start,
                "page_end": chapter.page_end,
                "full_text": chapter.full_text,
            }
        )
        for section in chapter.sections:
            section_id = f"{book_id}-s{chapter.num}-{section.seq}"
            section_rows.append(
                {
                    "id": section_id,
                    "book_id": book_id,
                    "chapter_id": chapter_id,
                    "seq": section.seq,
                    "text": section.text,
                    "page": section.page,
                    "kind": section.kind,
                }
            )
            anchor_rows.append(
                {
                    "id": section_id,
                    "book_id": book_id,
                    "chapter_id": chapter_id,
                    "section_id": section_id,
                    "text": section.text,
                    "page": section.page,
                }
            )

    db.add_book_bundle(book_row, chapter_rows, section_rows, anchor_rows)
    return {
        "id": book_id,
        "title": parsed.title,
        "format": fmt,
        "chapters": chapter_rows,
    }


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
