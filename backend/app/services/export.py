"""教材导出：把库里的章节/段落渲染成 Markdown。

**按需生成，不落库。** 数据库（books/chapters/sections）是唯一权威，因为溯源问答
依赖它；再存一份 md 副本会静默漂移——仓库里已经有这种先例（`backfill_content_warning`
事后改写 books 行）。纯函数 + 导出端点，成本只有一次字符串拼接。

页码这类只在展示时有意义的信息用 HTML 注释带上（`<!-- page: 12 -->`）：
Markdown 渲染器会忽略它，需要核对页码时又一眼能看到。
"""
from typing import Any, Dict, List

from ..db import Database

#: 与 `parsing/base.py` 的 kind 取值一一对应
_KIND_HEADING = "heading"
_KIND_FORMULA = "formula"


def render_markdown(book: Dict[str, Any], chapters: List[Dict], sections_by_chapter: Dict[str, List[Dict]]) -> str:
    """渲染整本教材为 Markdown。

    - 一级标题是书名，二级是章，三级是章内小节（`kind='heading'`）；
    - 每个段落前带 `<!-- page: N -->`，保留「教材依据 · 第 N 页」的可核对性；
    - 公式段落包在代码块里，避免 `_` `^` `*` 被当成 Markdown 语法吃掉。
    """
    lines: List[str] = [f"# {book.get('title') or '未命名教材'}", ""]
    note = (book.get("note") or "").strip()
    if note:
        lines += [f"> {note}", ""]
    warning = (book.get("content_warning") or "").strip()
    if warning:
        lines += [f"> ⚠️ {warning}", ""]

    for chapter in chapters:
        lines += [f"## {chapter.get('title') or '未命名章节'}", ""]
        for section in sections_by_chapter.get(chapter["id"], []):
            page = section.get("page", 1)
            text = (section.get("text") or "").strip()
            if not text:
                continue
            if section.get("kind") == _KIND_HEADING:
                lines += [f"<!-- page: {page} -->", f"### {text}", ""]
            elif section.get("kind") == _KIND_FORMULA:
                lines += [f"<!-- page: {page} -->", "```", text, "```", ""]
            else:
                # 单换行在 Markdown 里会并成一行，段内换行要转成硬换行
                body = text.replace("\n", "  \n")
                lines += [f"<!-- page: {page} -->", body, ""]
    return "\n".join(lines).rstrip() + "\n"


def export_book_markdown(db: Database, book: Dict[str, Any]) -> str:
    """从库里取数并渲染。调用方负责确认 book 存在。"""
    chapters = db.chapters_of(book["id"])
    sections_by_chapter = {c["id"]: db.sections_of(book["id"], c["id"]) for c in chapters}
    return render_markdown(book, chapters, sections_by_chapter)
