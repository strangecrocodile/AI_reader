"""教材入库：PDF → 解析 → SQLite（教材/章节/段落/锚点）。"""
import uuid
from typing import Dict, List

from ..db import Database
from ..parsing.pdf import parse_pdf_stream


def ingest_pdf_bytes(db: Database, file_bytes: bytes, default_title: str = "未命名教材") -> Dict:
    """解析并入库，返回教材元信息（含章节）。已存在的同名教材会先移除旧数据。"""
    parsed = parse_pdf_stream(file_bytes, default_title)
    if not parsed.chapters:
        raise ValueError("未能从 PDF 中识别出章节内容")

    book_id = uuid.uuid4().hex[:8]
    book_row = {
        "id": book_id,
        "title": parsed.title or default_title,
        "author": "",
        "note": "教材导入时间见数据库",
        "progress_pct": 0.0,
        "created_at": _now(),
    }

    chapter_rows = []
    section_rows = []
    anchor_rows = []
    for ch in parsed.chapters:
        cid = f"{book_id}-ch{ch.num}"
        chapter_rows.append(
            {
                "id": cid,
                "book_id": book_id,
                "num": ch.num,
                "title": ch.title,
                "page_start": ch.page_start,
                "page_end": ch.page_end,
                "full_text": ch.full_text,
            }
        )
        for sec in ch.sections:
            sid = f"{book_id}-s{ch.num}-{sec.seq}"
            section_rows.append(
                {
                    "id": sid,
                    "book_id": book_id,
                    "chapter_id": cid,
                    "seq": sec.seq,
                    "text": sec.text,
                    "page": sec.page,
                    "kind": sec.kind,
                }
            )
            anchor_rows.append(
                {
                    "id": sid,
                    "book_id": book_id,
                    "chapter_id": cid,
                    "section_id": sid,
                    "text": sec.text,
                    "page": sec.page,
                }
            )

    db.add_book_bundle(book_row, chapter_rows, section_rows, anchor_rows)
    return {"id": book_id, "title": parsed.title, "chapters": chapter_rows}


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
