"""SQLite 存储层：教材、章节、段落（锚点）、备课讲解、学习路径和学习进度。"""
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
  content_warning TEXT DEFAULT '',
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
CREATE TABLE IF NOT EXISTS chapter_progress (
  book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'planned',
  mastery REAL NOT NULL DEFAULT 0,
  last_seen TEXT NOT NULL,
  PRIMARY KEY (book_id, chapter_id)
);
CREATE TABLE IF NOT EXISTS concepts (
  book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
  payload TEXT NOT NULL,
  model TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (book_id, chapter_id)
);
CREATE TABLE IF NOT EXISTS learning_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  anchor_id TEXT NOT NULL DEFAULT '',
  detail TEXT NOT NULL DEFAULT '',
  value REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS threads (
  id TEXT PRIMARY KEY,
  book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
  anchor_id TEXT NOT NULL DEFAULT '',
  selected_text TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS thread_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  text TEXT NOT NULL,
  sources TEXT NOT NULL DEFAULT '[]',
  detail TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chapters_book ON chapters(book_id);
CREATE INDEX IF NOT EXISTS idx_sections_chapter ON sections(book_id, chapter_id);
CREATE INDEX IF NOT EXISTS idx_progress_book ON chapter_progress(book_id);
CREATE INDEX IF NOT EXISTS idx_events_chapter ON learning_events(book_id, chapter_id);
CREATE INDEX IF NOT EXISTS idx_threads_chapter ON threads(book_id, chapter_id);
CREATE INDEX IF NOT EXISTS idx_thread_messages ON thread_messages(thread_id);
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

    #: 建表后补加的列。`CREATE TABLE IF NOT EXISTS` 不会给**已存在**的表加列，
    #: 而开发机与演示机上的库都是早就建好的，所以必须显式补一次，
    #: 否则升级后老库一插就报 `no such column`。
    _ADDED_COLUMNS = (("books", "content_warning", "TEXT DEFAULT ''"),)

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            for table, column, decl in self._ADDED_COLUMNS:
                existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
                if column not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    def backfill_content_warning(self, warning_of) -> int:
        """给升级前入库、还没写过提示的教材补一次；返回补了几本。

        这些书的问题就摆在数据里（正文只有几百字），但上传时还没有这个字段，
        不回填的话用户永远看不到提示——而它们恰恰最需要提醒：教材本身就读不全，
        重新上传同一份文件也不会有别的结果。

        只做**字数**这一项：当初「跳过了几个表格」之类的结构信息没记下来，编不出来。
        `warning_of(chars)` 由调用方（services.ingest）给文案，阈值口径只留一处，
        存储层不掺业务判断——返回空串就表示这本不用标记。
        """
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT b.id, COALESCE(SUM(LENGTH(s.text)), 0) AS chars FROM books b "
                "LEFT JOIN sections s ON s.book_id = b.id AND s.kind != 'heading' "
                "WHERE COALESCE(b.content_warning, '') = '' "
                "GROUP BY b.id"
            ).fetchall()
            updated = 0
            for row in rows:
                text = warning_of(row["chars"])
                if not text:
                    continue
                conn.execute(
                    "UPDATE books SET content_warning=? WHERE id=?", (text, row["id"])
                )
                updated += 1
            return updated

    # ---------- 教材 ----------
    def add_book(self, book: Dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO books(id,title,author,note,progress_pct,content_warning,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (book["id"], book["title"], book.get("author", ""), book.get("note", ""),
                 book.get("progress_pct", 0.0), book.get("content_warning", ""),
                 book.get("created_at", "")),
            )

    def add_book_bundle(
        self,
        book: Dict[str, Any],
        chapters: List[Dict[str, Any]],
        sections: List[Dict[str, Any]],
        anchors: List[Dict[str, Any]],
    ) -> None:
        """在一个事务中写入教材及其章节、段落、锚点。"""
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO books(id,title,author,note,progress_pct,content_warning,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    book["id"],
                    book["title"],
                    book.get("author", ""),
                    book.get("note", ""),
                    book.get("progress_pct", 0.0),
                    book.get("content_warning", ""),
                    book.get("created_at", ""),
                ),
            )
            for c in chapters:
                conn.execute(
                    "INSERT INTO chapters(id,book_id,num,title,page_start,page_end,full_text) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (c["id"], c["book_id"], c["num"], c["title"], c["page_start"], c["page_end"], c["full_text"]),
                )
            for s in sections:
                conn.execute(
                    "INSERT INTO sections(id,book_id,chapter_id,seq,text,page,kind) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (s["id"], s["book_id"], s["chapter_id"], s["seq"], s["text"], s["page"], s["kind"]),
                )
            for a in anchors:
                conn.execute(
                    "INSERT INTO anchors(id,book_id,chapter_id,section_id,text,page) "
                    "VALUES(?,?,?,?,?,?)",
                    (a["id"], a["book_id"], a["chapter_id"], a["section_id"], a["text"], a["page"]),
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

    # ---------- 学习进度 ----------
    def upsert_chapter_progress(
        self, book_id: str, chapter_id: str, status: str, mastery: float
    ) -> Dict[str, Any]:
        mastery = max(0.0, min(100.0, float(mastery)))
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO chapter_progress(book_id,chapter_id,status,mastery,last_seen) "
                "VALUES(?,?,?,?,?) "
                "ON CONFLICT(book_id,chapter_id) DO UPDATE SET "
                "status=CASE WHEN chapter_progress.status='learned' "
                "OR excluded.status='learned' THEN 'learned' ELSE excluded.status END, "
                "mastery=MAX(chapter_progress.mastery, excluded.mastery), "
                "last_seen=excluded.last_seen",
                (book_id, chapter_id, status, mastery, _now()),
            )
            row = conn.execute(
                "SELECT * FROM chapter_progress WHERE book_id=? AND chapter_id=?",
                (book_id, chapter_id),
            ).fetchone()
            return dict(row)

    def progress_of_book(self, book_id: str) -> Dict[str, Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chapter_progress WHERE book_id=?", (book_id,)
            ).fetchall()
            return {row["chapter_id"]: dict(row) for row in rows}

    def update_book_progress_from_chapters(self, book_id: str) -> None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT AVG(COALESCE(p.mastery, 0)) AS average_mastery "
                "FROM chapters c LEFT JOIN chapter_progress p "
                "ON p.book_id=c.book_id AND p.chapter_id=c.id "
                "WHERE c.book_id=?",
                (book_id,),
            ).fetchone()
            if row and row["average_mastery"] is not None:
                conn.execute(
                    "UPDATE books SET progress_pct=? WHERE id=?",
                    (row["average_mastery"], book_id),
                )

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
        """本章锚点，**按段落先后顺序**返回。

        必须按 sections.seq 排，不能按 section_id 排：id 形如 `{book}-s1-10`，
        字典序下 `-s1-10` 会插到 `-s1-2` 前面，段落一旦满 10 段顺序就整体错乱，
        进而打乱讲义、知识点抽取和「学习顺序」边（与 sections_of 保持一致）。
        """
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT a.* FROM anchors a "
                "LEFT JOIN sections s ON s.id = a.section_id "
                "WHERE a.book_id=? AND a.chapter_id=? "
                "ORDER BY COALESCE(s.seq, 9223372036854775807), a.section_id",
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

    # ---------- 追问线程 ----------
    def add_thread(self, thread: Dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO threads(id,book_id,chapter_id,anchor_id,selected_text,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    thread["id"],
                    thread["book_id"],
                    thread["chapter_id"],
                    thread.get("anchor_id", ""),
                    thread.get("selected_text", ""),
                    thread["created_at"],
                    thread.get("updated_at", thread["created_at"]),
                ),
            )

    def get_thread(self, thread_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM threads WHERE id=?", (thread_id,)).fetchone()
            return dict(row) if row else None

    def threads_of_chapter(self, book_id: str, chapter_id: str) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM threads WHERE book_id=? AND chapter_id=? ORDER BY updated_at DESC, rowid DESC",
                (book_id, chapter_id),
            ).fetchall()
            return [dict(r) for r in rows]

    def touch_thread(self, thread_id: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE threads SET updated_at=? WHERE id=?", (_now(), thread_id))

    def delete_thread(self, thread_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM threads WHERE id=?", (thread_id,))

    def add_thread_message(
        self,
        thread_id: str,
        role: str,
        text: str,
        sources: Optional[List[str]] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO thread_messages(thread_id,role,text,sources,detail,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (
                    thread_id,
                    role,
                    text,
                    json.dumps(sources or [], ensure_ascii=False),
                    json.dumps(detail or {}, ensure_ascii=False),
                    _now(),
                ),
            )
            row = conn.execute(
                "SELECT * FROM thread_messages WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
            return dict(row)

    def thread_messages(self, thread_id: str) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM thread_messages WHERE thread_id=? ORDER BY id", (thread_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ---------- 学习事件（掌握度依据） ----------
    def add_learning_event(
        self,
        book_id: str,
        chapter_id: str,
        kind: str,
        anchor_id: str = "",
        detail: str = "",
        value: float = 0.0,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO learning_events(book_id,chapter_id,kind,anchor_id,detail,value,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (book_id, chapter_id, kind, anchor_id, detail, value, _now()),
            )

    def learning_events_of(self, book_id: str, chapter_id: str) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM learning_events WHERE book_id=? AND chapter_id=? ORDER BY id",
                (book_id, chapter_id),
            ).fetchall()
            return [dict(r) for r in rows]

    # ---------- 知识点抽取（缓存） ----------
    def upsert_concepts(self, book_id: str, chapter_id: str, payload: Dict[str, Any], model: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO concepts(book_id,chapter_id,payload,model,created_at) "
                "VALUES(?,?,?,?,?)",
                (book_id, chapter_id, json.dumps(payload, ensure_ascii=False), model, _now()),
            )

    def get_concepts(self, book_id: str, chapter_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload,model FROM concepts WHERE book_id=? AND chapter_id=?",
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
    """UTC 时间戳（微秒精度：线程「最近追问」排序需要秒内可区分）。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="microseconds")
