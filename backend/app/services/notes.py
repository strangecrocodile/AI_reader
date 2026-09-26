"""笔记：把「我读到这里想到了什么」留在原文上。

## 为什么绑锚点而不是绑页码

笔记绑的是**段落锚点**（`anchor_id`），和溯源问答用的是同一套坐标。页码会随版本、
随解析方式变化，锚点不会——所以「回到这条笔记对应的原文」永远跳得准，
而笔记也就自然跟着原文一起被删除、一起被重建。

同时存一份 `quoted_text`（写下笔记时选中的那段原文）：锚点失效时（比如教材被重传、
段落重新切分），笔记至少还能显示「当时记的是这一句」，而不是变成一条无主的字符串。
"""
import logging
import uuid
from typing import Any, Dict, List, Optional

from ..db import Database

logger = logging.getLogger(__name__)

#: 笔记正文上限。够写一段心得，又不至于让一条笔记变成一篇论文。
MAX_BODY_CHARS = 4000
#: 引文上限：只作为「当时记的是哪一句」的线索，不需要存整段。
MAX_QUOTE_CHARS = 500


class NoteError(ValueError):
    """笔记本身的校验问题（空正文、引用位置不属于这本书等）。"""


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def to_frontend(note: Dict[str, Any]) -> Dict[str, Any]:
    """数据库行 → 前端结构（camelCase，与 serializers 同一约定）。"""
    return {
        "id": note["id"],
        "bookId": note["book_id"],
        "chapterId": note["chapter_id"],
        "anchorId": note.get("anchor_id", "") or "",
        "quotedText": note.get("quoted_text", "") or "",
        "body": note.get("body", "") or "",
        "createdAt": note.get("created_at", ""),
        "updatedAt": note.get("updated_at", ""),
    }


def create_note(
    db: Database,
    book_id: str,
    chapter_id: str,
    anchor_id: str,
    quoted_text: str,
    body: str,
) -> Dict[str, Any]:
    """新建一条笔记。正文为空直接拒绝——空笔记没有意义，只会变成列表里的噪音。"""
    text = (body or "").strip()
    if not text:
        raise NoteError("笔记内容不能为空")
    if len(text) > MAX_BODY_CHARS:
        raise NoteError(f"笔记内容过长（上限 {MAX_BODY_CHARS} 字）")

    anchor = (anchor_id or "").strip()
    if anchor and anchor not in _anchor_ids(db, book_id, chapter_id):
        # 乱报锚点会让「回到原文」跳到一个不存在的位置。宁可拒绝，也不收下一条坏笔记。
        raise NoteError("这段原文不属于本章，无法记录笔记")

    note_id = uuid.uuid4().hex[:12]
    created = _now()
    note = {
        "id": note_id,
        "book_id": book_id,
        "chapter_id": chapter_id,
        "anchor_id": anchor,
        "quoted_text": (quoted_text or "").strip()[:MAX_QUOTE_CHARS],
        "body": text,
        "created_at": created,
        "updated_at": created,
    }
    db.add_note(note)
    return to_frontend(note)


def list_notes(db: Database, book_id: str, chapter_id: str) -> List[Dict[str, Any]]:
    return [to_frontend(note) for note in db.notes_of_chapter(book_id, chapter_id)]


def list_book_notes(db: Database, book_id: str) -> List[Dict[str, Any]]:
    """整本书的笔记，并补上章节标题——跨章列出来时得知道每条属于哪一章。"""
    chapters = {c["id"]: c.get("title", "") for c in db.chapters_of(book_id)}
    return [
        {**to_frontend(note), "chapterTitle": chapters.get(note["chapter_id"], "")}
        for note in db.notes_of_book(book_id)
    ]


def update_note(db: Database, note_id: str, body: str) -> Optional[Dict[str, Any]]:
    text = (body or "").strip()
    if not text:
        raise NoteError("笔记内容不能为空")
    if len(text) > MAX_BODY_CHARS:
        raise NoteError(f"笔记内容过长（上限 {MAX_BODY_CHARS} 字）")
    updated = db.update_note(note_id, text)
    return to_frontend(updated) if updated else None


def delete_note(db: Database, note_id: str) -> bool:
    if not db.get_note(note_id):
        return False
    db.delete_note(note_id)
    return True


def _anchor_ids(db: Database, book_id: str, chapter_id: str) -> set:
    return {section["id"] for section in db.sections_of(book_id, chapter_id)}
