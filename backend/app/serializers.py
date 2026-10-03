"""序列化：把数据库行转换为与前端 services/api.js 约定一致的结构。"""
from typing import Any, Dict, List, Optional

from .db import Database
from .parsing.base import CHAPTER_TITLE_RE, STYLE_TOKENS
from .services import lesson, plan as plan_service

#: 封面「规格行」用的格式名。封面是纯展示，但**不能展示假信息**：这里以前对所有
#: 教材硬编码「注：演示数据」与一行微积分公式，用户上传一本法学期刊，书架首屏也会
#: 告诉他这是演示数据、还配着导数公式。现在四个槽位全部由这本书自己派生。
_COVER_FORMAT_LABELS = {
    "pdf": "PDF",
    "docx": "WORD",
    "doc": "WORD",
    "text": "文本",
}


def book_meta(db: Database, llm, book: Dict) -> Dict[str, Any]:
    chapters = db.chapters_of(book["id"])
    progress_by_chapter = db.progress_of_book(book["id"])
    plan = plan_service.get_plan(db, llm, book, chapters)
    pct = round(book.get("progress_pct", 0) or 0)
    author = book.get("author", "") or "来源：用户导入"
    source_format = (book.get("source_format") or "").strip().lower()
    return {
        "id": book["id"],
        "title": book["title"],
        "author": author,
        "edition": "",
        "note": book.get("note", ""),
        # 解析受限提示（跳过了表格/文本框/图片、正文过少等）。前端据此提醒用户
        # 「内容可能没被完整读取」；为空串表示解析正常。
        "contentWarning": book.get("content_warning", "") or "",
        # 原文件信息：`hasSource` 为假表示这本没有留存原文件（早于该功能上线时导入），
        # 前端据此把「下载原文件」置灰，而不是给一个必然 404 的链接。
        "hasSource": bool((book.get("source_name") or "").strip()),
        "sourceFormat": book.get("source_format", "") or "",
        # 印刷页码 − PDF 页序。扫描件的页码取自原书页脚，而原版 PDF 阅读面按
        # **PDF 页序**翻页，所以要减掉这个偏移才能跳到对的那一页（见 parsing/ocr_pdf.py）。
        # 文本型 PDF 与 Word/纯文本没有这层换算，恒为 0。
        "pageOffset": int(book.get("page_offset", 0) or 0),
        "progressText": f"{pct}% 已完成",
        "tag": book["title"][:8],
        # 封面：书名用真书名，规格行用来源格式与已识别章节数，页脚用作者/来源。
        # 每一句都对得上这本书（见 _COVER_FORMAT_LABELS 的说明）。
        "cover": {
            "series": "AI LECTURER · IMPORTED TEXTBOOK",
            "lines": [book["title"]],
            "formula": [_COVER_FORMAT_LABELS.get(source_format, "教材"), f"{len(chapters)} 章"],
            "footer": author,
        },
        "plan": _plan_to_frontend(plan),
        "chapters": [
            _chapter_to_frontend(c, i == 0, progress_by_chapter.get(c["id"]))
            for i, c in enumerate(chapters)
        ],
    }


def _plan_to_frontend(plan: Dict) -> Dict[str, Any]:
    items = plan.get("items") or []
    total_min = sum(i.get("duration_minutes", 0) for i in items)
    # 空计划是合法状态（教材一章节都没有时），不能直接取 items[0]——那会让
    # 教材详情接口 500，而不是返回一个「还没有学习单元」的正常响应。
    head = items[0] if items else None
    goal = head.get("goal", "跟随章节顺序完成学习。") if head else "跟随章节顺序完成学习。"
    return {
        "eyebrow": "AI 学习路径",
        "headline": ["规划好路径，", "再翻开教材。"],
        "sub": f"AI 已按教材目录生成 {len(items)} 个学习单元，选择章节开始学习。",
        "goalLabel": "AI 规划 · 学习目标",
        "goal": goal,
        "remaining": f"共 {len(items)} 个学习单元 · 预计 {total_min} 分钟",
    }


def _chapter_to_frontend(
    c: Dict, is_first: bool = False, progress: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    status = progress["status"] if progress else ("doing" if is_first else "todo")
    mastery = round(progress["mastery"]) if progress else 0
    return {
        "id": c["id"],
        "num": f"{c['num']:02d}",
        "title": c["title"],
        "status": status,
        "meta": "已完成" if status == "learned" else "正在学习" if status == "learning" else "待学习",
        "progressPct": mastery,
        "isToday": is_first and status != "learned",
    }


def chapter_content(db: Database, llm, book: Dict, chapter: Dict) -> Dict[str, Any]:
    sections = db.sections_of(book["id"], chapter["id"])
    anchors = db.anchors_of(book["id"], chapter["id"])
    explanation = lesson.get_lesson(db, llm, chapter, sections, anchors)

    paragraphs = []
    for s in sections:
        if s["kind"] == "heading":
            continue
        if s["kind"] == "formula":
            para = {"type": "formula", "parts": [s["text"]]}
        elif s["kind"] == "image":
            para = _image_paragraph(s)
        elif s["kind"] == "table":
            para = _table_paragraph(s)
        else:
            para = {"type": "p", "segs": _segs_of(s)}
        # 段落级页码：原版 PDF 阅读面靠它把「PDF 页 ↔ 锚点」对上——划词回填锚点、
        # 依据回跳、按页上报已读都建立在它上面（见前端 utils/anchorPage.js）。
        # 缺页码的脏数据回退到本章起始页，而不是 0：0 会把用户甩到整本书第一页。
        para["page"] = int(s.get("page") or chapter["page_start"] or 0)
        paragraphs.append(para)

    points = []
    for kp in explanation.get("points", []):
        item = {
            "id": kp["id"],
            "kind": kp.get("kind", "card"),
            "title": kp["title"],
            "body": [{"t": "text", "v": kp["body"]}],
        }
        if kp.get("sourceId"):
            item["sourceId"] = kp["sourceId"]
            item["sourceLabel"] = kp.get("sourceLabel", "定位教材：原文")
        points.append(item)

    outline = [
        {
            "index": o.get("index", f"{i + 1:02d}"),
            "title": o["title"],
            "summary": o["summary"],
            "sourceId": o["sourceId"],
        }
        for i, o in enumerate(explanation.get("outline", []))
    ]

    return {
        "bookId": book["id"],
        "chapterId": chapter["id"],
        "page": chapter["page_start"],
        # 章末页：原版阅读面据此知道这一章覆盖 PDF 的哪一段（第 2 章 = 第 16–91 页）。
        "pageEnd": chapter["page_end"],
        "heading": chapter["title"],
        "intro": _chapter_intro(chapter),
        # 阅读面选择所需的来源信息跟着章节内容一起下发：阅读器因此不必依赖
        # 书架列表是否已经加载完（直接打开一个章节链接时也一样能判断）。
        "sourceFormat": book.get("source_format", "") or "",
        "hasSource": bool((book.get("source_name") or "").strip()),
        "pageOffset": int(book.get("page_offset", 0) or 0),
        "paragraphs": paragraphs,
        "knowledgePoints": points,
        "outline": outline,
    }


def _segs_of(section: Dict[str, Any]) -> List[Dict[str, Any]]:
    """段落 → 前端片段数组。

    结构刻意保持「锚点在最内层」：`{t:'src', id, v:'', segs:[...]}`。这样
    `data-source-id` 与锚点定位（跨章跳转、知识点回链）的既有逻辑一行都不用改，
    段落里的粗体/斜体/上下标只是渲染细节。

    没有版式信息时退回原来的「整段一个纯文本片段」，纯文本教材、Markdown 教材
    和升级前入库的老数据都走这条路径。
    """
    runs = (section.get("content") or {}).get("runs")
    if not runs:
        # 没有版式信息：保持和以前完全一样的单片段结构（`v` 直接放正文），
        # 纯文本/Markdown 教材与升级前入库的老数据走这条路径，前端行为不变。
        return [
            {
                "t": "src",
                "id": section["id"],
                "v": section.get("text", ""),
                "kind": "definition" if section.get("seq") == 1 else "plain",
            }
        ]

    inner: List[Dict[str, Any]] = []
    for run in runs:
        text = str(run.get("text", ""))
        if not text:
            continue
        style = [token for token in run.get("style", []) if token in STYLE_TOKENS]
        inner.append({"t": "run", "v": text, "style": style} if style else {"t": "text", "v": text})
    if not inner:
        inner = [{"t": "text", "v": section.get("text", "")}]
    # 有版式时锚点仍在最外层，行内片段作为它的子片段（`v` 留空，避免文本重复渲染）
    return [
        {
            "t": "src",
            "id": section["id"],
            "v": "",
            "kind": "definition" if section.get("seq") == 1 else "plain",
            "segs": inner,
        }
    ]


def _image_paragraph(section: Dict[str, Any]) -> Dict[str, Any]:
    """插图段落。资源经 /assets 静态目录提供，前端按 URL 直接 <img>。"""
    content = section.get("content") or {}
    asset = str(content.get("asset", ""))
    return {
        "type": "image",
        "id": section["id"],
        "src": f"/assets/{asset}" if asset else "",
        "width": content.get("width"),
        "height": content.get("height"),
        "caption": section.get("text", ""),
    }


def _table_paragraph(section: Dict[str, Any]) -> Dict[str, Any]:
    """表格段落。单元格目前是纯文本，按行按列下发。"""
    content = section.get("content") or {}
    rows = [
        [str(cell.get("text", "")) for cell in row]
        for row in (content.get("rows") or [])
    ]
    return {
        "type": "table",
        "id": section["id"],
        "rows": rows,
        "header": bool(content.get("header")),
    }


def _chapter_intro(chapter: Dict[str, Any]) -> str:
    """章节导语：标题自带「第X章」时不再重复加章号。"""
    title = chapter["title"]
    prefix = "" if CHAPTER_TITLE_RE.match(title) else f"第 {chapter['num']} 章 · "
    return f"{prefix}{title}　/　第 {chapter['page_start']} 页"
