"""章节识别 + 拆书（P1）。

输入：整本书 .docx 的 ParaRow 列表。
输出：
  1. 按“章节”组织的结构（每章含段落与统计）；
  2. 章节 .docx 文件：一章一份，章节过大（默认 >10000 字符）按段落边界切成多份；
  3. manifest.json：全书的锚点清单（段落 id 稳定、全局唯一）。

章节识别策略（按优先级）：
  1. Word 原生标题样式 Heading 1..9；
  2. 无标题样式时，匹配常见文本模式（第X章 / Chapter X / X. 小节）；
  3. 完全识别不到时，整本视为单章。

段落切分说明：优先在段落边界切分；若单个段落本身超过上限，
则把该段文字按字符切成多段（保证大段内容也能落盘，不丢字）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document

from .parse import ParaRow, read_paragraphs
from .textstats import count_text, total_of

#: 单份章节 .docx 的字符上限（去空白总字符），可传参覆盖
SPLIT_CHAR_LIMIT = 10_000

#: 常见章标题文本模式（识别不到标题样式时的兜底）
_CHAPTER_TEXT_RE = re.compile(
    r"^\s*(?:第\s*[0-9一二三四五六七八九十百千万]+\s*[章节篇部卷].*|"
    r"[0-9]+(?:\.[0-9]+)*\s+[^\s，。；：]{1,30}|"
    r"chapter\s+[0-9]+(?:\s*[:：\-–]\s*.*)?)\s*$",
    re.IGNORECASE,
)


@dataclass
class Chapter:
    """一个章节：id、标题、段落（ParaRow）、字数统计。"""

    id: str
    title: str
    paragraphs: list[ParaRow] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return total_of(count_text(p.text) for p in self.paragraphs)


def detect_chapters(rows: list[ParaRow]) -> list[Chapter]:
    """按标题样式/文本模式把段落流切成章节列表。

    规则：
    - Title（书名）行不算章节，只用来兜底命名；
    - 首个章标题之前出现的正文视作“前言”，并入第一章（保持内容不丢）；
    - 完全识别不到章节时，整本视为单章。
    """
    if not rows:
        return []

    def _starts_chapter(row: ParaRow) -> bool:
        if row.level >= 1:  # Heading 1..9 一律视为章标题
            return True
        return bool(_CHAPTER_TEXT_RE.match(row.text))

    title_row = next((r for r in rows if r.style.lower() == "title"), None)
    body_rows = [r for r in rows if r is not title_row]

    chapters: list[Chapter] = []
    front: list[ParaRow] = []

    for row in body_rows:
        if _starts_chapter(row):
            if chapters:
                chapters.append(Chapter(id=f"ch{len(chapters) + 1}", title=row.text, paragraphs=[row]))
            else:
                # 第一章：章标题在前，前言（若有）跟在标题后，随后是正文
                chapters.append(Chapter(id="ch1", title=row.text, paragraphs=[row] + front))
        else:
            if chapters:
                chapters[-1].paragraphs.append(row)
            else:
                front.append(row)

    if not chapters:
        title = title_row.text if title_row else "全书（未识别章节）"
        chapters.append(Chapter(id="ch1", title=title, paragraphs=body_rows))

    return [c for c in chapters if c.paragraphs]


def _split_long_text(text: str, limit: int) -> list[str]:
    """单个超大段落按字符切成多段（不含空白时可能仍超限，按可视字符处理）。"""
    if len(text) <= limit:
        return [text]
    return [text[i : i + limit] for i in range(0, len(text), limit)]


def split_chapter(chapter: Chapter, limit: int) -> list[list[ParaRow]]:
    """把一个章节切成若干“份”，每份是不超过 limit 字符的段落组。"""
    parts: list[list[ParaRow]] = [[]]
    current_chars = 0
    seq = 0  # 用于大段二次切分时造出编号段落

    for para in chapter.paragraphs:
        if len(para.text) > limit:
            # 单段超限：先收尾当前份（若有内容），再按字符切段
            if parts[-1]:
                parts.append([])
            for seg in _split_long_text(para.text, limit):
                seq += 1
                fake = ParaRow(text=seg, style=para.style, level=0, index=para.index * 1000 + seq)
                if current_chars + len(seg) > limit and parts[-1]:
                    parts.append([])
                    current_chars = 0
                parts[-1].append(fake)
                current_chars += len(seg)
            continue

        if parts[-1] and current_chars + len(para.text) > limit:
            parts.append([])
            current_chars = 0
        parts[-1].append(para)
        current_chars += len(para.text)

    return [p for p in parts if p]


def write_chapter_docx(chapter: Chapter, part_rows: list[ParaRow], book_title: str, out_path: Path) -> None:
    """把章节的一部分写成一份独立 .docx（页眉元信息 + 标题 + 正文）。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    counts = total_of(count_text(p.text) for p in part_rows)

    doc = Document()
    doc.add_heading(f"{book_title} · {chapter.title}", level=0)
    meta = (
        f"章节编号：{chapter.id}　|　本份字符数（去空白）：{counts['chars_no_ws']}　|　"
        f"中文字数：{counts['cjk']}　|　段落数：{len(part_rows)}"
    )
    doc.add_paragraph(meta)
    for para in part_rows:
        if para.is_heading and para.level <= 2:
            doc.add_heading(para.text, level=para.level)
        else:
            doc.add_paragraph(para.text)
    doc.save(out_path)


def split_book(docx_path: str | Path, out_dir: str | Path, book_id: str = "b1", limit: int = SPLIT_CHAR_LIMIT) -> dict:
    """整本 docx → 章节 docx + manifest.json；返回可供打印/测试的完整报告。"""
    docx_path = Path(docx_path)
    out_dir = Path(out_dir)
    rows = read_paragraphs(docx_path)
    chapters = detect_chapters(rows)

    title_row = next((r for r in rows if r.style.lower() == "title"), None)
    book_title = title_row.text if title_row else docx_path.stem

    book_counts = total_of(count_text(p.text) for p in rows)
    chapter_entries: list[dict] = []
    manifest = {
        "book": {
            "id": book_id,
            "title": book_title,
            "source": docx_path.name,
            "counts": book_counts,
        },
        "version": 1,
        "chapters": chapter_entries,
    }

    for ch in chapters:
        parts = split_chapter(ch, limit)
        para_global = 0
        ch_total = total_of(count_text(p.text) for p in ch.paragraphs)
        entries: list[dict] = []
        for idx, part_rows in enumerate(parts, start=1):
            fname = f"{book_id}-{ch.id}.docx" if len(parts) == 1 else f"{book_id}-{ch.id}-part{idx}.docx"
            write_chapter_docx(ch, part_rows, book_title, out_dir / fname)
            part_counts = total_of(count_text(p.text) for p in part_rows)
            paras = []
            for para in part_rows:
                para_global += 1
                anchor = f"{book_id}-{ch.id}-p{para_global:03d}"
                paras.append({"anchor": anchor, "text": para.text})
            entries.append(
                {
                    "file": fname,
                    "counts": part_counts,
                    "paragraphs": paras,
                }
            )
        chapter_entries.append(
            {
                "id": ch.id,
                "title": ch.title,
                "counts": ch_total,
                "parts": entries,
            }
        )

    manifest_path = out_dir.parent / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"manifest": manifest, "manifest_path": str(manifest_path), "chapters": chapter_entries}


def main() -> None:  # pragma: no cover
    import sys

    if len(sys.argv) < 2:
        print("用法：python -m kb_agent.split <整本书.docx> [输出目录] [book_id] [字数上限]")
        sys.exit(1)
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.parent / "chapters"
    book_id = sys.argv[3] if len(sys.argv) > 3 else "b1"
    limit = int(sys.argv[4]) if len(sys.argv) > 4 else SPLIT_CHAR_LIMIT
    report = split_book(src, out, book_id=book_id, limit=limit)
    b = report["manifest"]["book"]
    print(f"书名：《{b['title']}》  全书去空白字符 {b['counts']['chars_no_ws']} / 中文字数 {b['counts']['cjk']}")
    for ch in report["chapters"]:
        print(f"  {ch['id']}《{ch['title']}》：{ch['counts']['chars_no_ws']} 字符 / {len(ch['parts'])} 份")
    print(f"manifest：{report['manifest_path']}")


if __name__ == "__main__":
    main()
