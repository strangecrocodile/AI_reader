"""追问线程：围绕一段教材原文的持续问答。

- 线程绑定 `(book, chapter, 锚点, 选中原文)`：同一个气泡里的追问都落在同一条线上；
- 消息持久化（问题 + 回答 + 溯源信息），刷新页面或切回章节仍能回看；
- 气泡位置 / 拖拽状态由前端管理，后端不存 UI 坐标
  （见 `docs/下一阶段开发文档.md` 第 4 节「UI 坐标、浮层位置、拖拽状态由前端管理」）。
"""
import json
import uuid
from typing import Any, Dict, List, Optional

from ..db import Database

MAX_SELECTED_CHARS = 1000
TITLE_CHARS = 24


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def create_thread(
    db: Database,
    book_id: str,
    chapter_id: str,
    anchor_id: str = "",
    selected_text: str = "",
) -> Dict[str, Any]:
    """新建一条追问线程（选中原文时创建）。"""
    thread_id = f"th-{uuid.uuid4().hex[:10]}"
    now = _now()
    db.add_thread(
        {
            "id": thread_id,
            "book_id": book_id,
            "chapter_id": chapter_id,
            "anchor_id": anchor_id or "",
            "selected_text": (selected_text or "").strip()[:MAX_SELECTED_CHARS],
            "created_at": now,
            "updated_at": now,
        }
    )
    return serialize(db.get_thread(thread_id), [])


def get_thread(db: Database, thread_id: str) -> Optional[Dict[str, Any]]:
    row = db.get_thread(thread_id)
    if not row:
        return None
    return serialize(row, db.thread_messages(thread_id))


def list_threads(db: Database, book_id: str, chapter_id: str) -> List[Dict[str, Any]]:
    return [serialize(row, db.thread_messages(row["id"])) for row in db.threads_of_chapter(book_id, chapter_id)]


def delete_thread(db: Database, thread_id: str) -> bool:
    if not db.get_thread(thread_id):
        return False
    db.delete_thread(thread_id)
    return True


def append_message(
    db: Database,
    thread_id: str,
    role: str,
    text: str,
    sources: Optional[List[str]] = None,
    source_details: Optional[List[Dict[str, Any]]] = None,
    scope: str = "",
) -> Dict[str, Any]:
    """追加一条消息；`detail` 里存溯源信息（依据锚点与检索范围）。"""
    row = db.add_thread_message(
        thread_id,
        role,
        text or "",
        sources=sources or [],
        detail={"sourceDetails": source_details or [], "scope": scope},
    )
    db.touch_thread(thread_id)
    return _serialize_message(row)


def append_exchange(db: Database, thread_id: str, question: str, result: Dict[str, Any]) -> None:
    """把一次问答（问题 + 回答）写进线程。"""
    append_message(db, thread_id, "user", question)
    append_message(
        db,
        thread_id,
        "assistant",
        result.get("answer", ""),
        sources=result.get("sources"),
        source_details=result.get("sourceDetails"),
        scope=result.get("scope", ""),
    )


def serialize(row: Optional[Dict[str, Any]], messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    if row is None:
        return {}
    parsed = [_serialize_message(message) for message in messages]
    return {
        "id": row["id"],
        "bookId": row["book_id"],
        "chapterId": row["chapter_id"],
        "anchorId": row["anchor_id"],
        "selectedText": row["selected_text"],
        "title": _title(row, parsed),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "messages": parsed,
    }


def _serialize_message(row: Dict[str, Any]) -> Dict[str, Any]:
    try:
        sources = json.loads(row.get("sources") or "[]")
    except (TypeError, ValueError):
        sources = []
    try:
        detail = json.loads(row.get("detail") or "{}")
    except (TypeError, ValueError):
        detail = {}
    return {
        "id": row.get("id"),
        "role": row.get("role", "user"),
        "text": row.get("text", ""),
        "sources": sources,
        "sourceDetails": detail.get("sourceDetails", []),
        "scope": detail.get("scope", ""),
        "createdAt": row.get("created_at", ""),
    }


def _title(row: Dict[str, Any], messages: List[Dict[str, Any]]) -> str:
    if row.get("selected_text"):
        return _clip(row["selected_text"])
    first_question = next((m["text"] for m in messages if m["role"] == "user"), "")
    return _clip(first_question) or "追问线程"


def _clip(text: str) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= TITLE_CHARS else text[:TITLE_CHARS] + "…"
