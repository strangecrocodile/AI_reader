"""SQLite 存储层：教材、章节、段落（锚点）、备课讲解、学习路径。"""
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  author TEXT DEFAULT '',
  note TEXT DEFAULT '',
  progress_pct REAL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chapters (
  id TEXT PRIMARY KEY,
  book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  num INTEGER NOT NULL,
  title TEXT NOT NULL,
  page_start INTEGER NOT NULL,
  page_end INTEGER NOT NULL,
  full_text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sections (
  id TEXT PRIMARY KEY,
  book_id TEXT NOT NULL,
  chapter_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  text TEXT NOT NULL,
  page INTEGER NOT NULL,
  kind TEXT DEFAULT 'p'
);
CREATE TABLE IF NOT EXISTS anchors (
  id TEXT PRIMARY KEY,
  book_id TEXT NOT NULL,
  chapter_id TEXT NOT NULL,
  section_id TEXT NOT NULL,
  text TEXT NOT NULL,
  page INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS explanations (
  book_id TEXT NOT NULL,
  chapter_id TEXT NOT NULL,
  payload TEXT NOT NULL,
  model TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (book_id, chapter_id)
);
CREATE TABLE IF NOT EXISTS plans (
  book_id TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  model TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chapters_book ON chapters(book_id);
CREATE INDEX IF NOT EXISTS idx_sections_chapter ON sections(book_id, chapter_id);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    # ---------- 教材 ----------
    def add_book(self, book: Dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO books(id,title,author,note,progress_pct,created_at) VALUES(?,?,?,?,?,?)",
                (book["id"], book["title"], book.get("author", ""), book.get("note", ""),
                 book.get("progress_pct", 0.0), book.get("created_at", "")),
            )

    def list_books(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM books ORDER BY created_at").fetchall()
            return [dict(r) for r in rows]

    def get_book(self, book_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
            return dict(row) if row else None

    def delete_book(self, book_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM books WHERE id=?", (book_id,))

    def set_progress(self, book_id: str, pct: float) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE books SET progress_pct=? WHERE id=?", (pct, book_id))

    # ---------- 章节 ----------
    def add_chapters(self, chapters: List[Dict[str, Any]]) -> None:
        with self.connect() as conn:
            for c in chapters:
                conn.execute(
                    "INSERT OR REPLACE INTO chapters(id,book_id,num,title,page_start,page_end,full_text) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (c["id"], c["book_id"], c["num"], c["title"], c["page_start"], c["page_end"], c["full_text"]),
                )

    def chapters_of(self, book_id: str) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chapters WHERE book_id=? ORDER BY num", (book_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_chapter(self, book_id: str, chapter_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM chapters WHERE book_id=? AND id=?", (book_id, chapter_id)
            ).fetchone()
            return dict(row) if row else None

    # ---------- 段落 ----------
    def add_sections(self, sections: List[Dict[str, Any]]) -> None:
        with self.connect() as conn:
            for s in sections:
                conn.execute(
                    "INSERT OR REPLACE INTO sections(id,book_id,chapter_id,seq,text,page,kind) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (s["id"], s["book_id"], s["chapter_id"], s["seq"], s["text"], s["page"], s["kind"]),
                )

    def sections_of(self, book_id: str, chapter_id: str) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sections WHERE book_id=? AND chapter_id=? ORDER BY seq",
                (book_id, chapter_id),
            ).fetchall()
            return [dict(r) for r in rows]

    # ---------- 锚点 ----------
    def add_anchors(self, anchors: List[Dict[str, Any]]) -> None:
        with self.connect() as conn:
            for a in anchors:
                conn.execute(
                    "INSERT OR REPLACE INTO anchors(id,book_id,chapter_id,section_id,text,page) "
                    "VALUES(?,?,?,?,?,?)",
                    (a["id"], a["book_id"], a["chapter_id"], a["section_id"], a["text"], a["page"]),
                )

    def get_anchor(self, anchor_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM anchors WHERE id=?", (anchor_id,)).fetchone()
            return dict(row) if row else None

    def anchors_of(self, book_id: str, chapter_id: str) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM anchors WHERE book_id=? AND chapter_id=? ORDER BY section_id",
                (book_id, chapter_id),
            ).fetchall()
            return [dict(r) for r in rows]

    # ---------- 备课讲解（缓存） ----------
    def upsert_explanation(self, book_id: str, chapter_id: str, payload: Dict[str, Any], model: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO explanations(book_id,chapter_id,payload,model,created_at) "
                "VALUES(?,?,?,?,?)",
                (book_id, chapter_id, json.dumps(payload, ensure_ascii=False), model, _now()),
            )

    def get_explanation(self, book_id: str, chapter_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload,model FROM explanations WHERE book_id=? AND chapter_id=?",
                (book_id, chapter_id),
            ).fetchone()
            return {"payload": json.loads(row["payload"]), "model": row["model"]} if row else None

    # ---------- 学习路径 ----------
    def upsert_plan(self, book_id: str, payload: Dict[str, Any], model: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO plans(book_id,payload,model,created_at) VALUES(?,?,?,?)",
                (book_id, json.dumps(payload, ensure_ascii=False), model, _now()),
            )

    def get_plan(self, book_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload,model FROM plans WHERE book_id=?", (book_id,)
            ).fetchone()
            return {"payload": json.loads(row["payload"]), "model": row["model"]} if row else None


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
