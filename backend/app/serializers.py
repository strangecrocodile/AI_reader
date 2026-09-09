"""序列化：把数据库行转换为与前端 services/api.js 约定一致的结构。"""
from typing import Any, Dict, List, Optional

from .db import Database
from .services import lesson, plan as plan_service


def book_meta(db: Database, llm, book: Dict) -> Dict[str, Any]:
    chapters = db.chapters_of(book["id"])
    progress_by_chapter = db.progress_of_book(book["id"])
    plan = plan_service.get_plan(db, llm, book, chapters)
    pct = round(book.get("progress_pct", 0) or 0)
    return {
        "id": book["id"],
        "title": book["title"],
        "author": book.get("author", "") or "来源：用户导入",
        "edition": "",
        "note": book.get("note", ""),
        "progressText": f"{pct}% 已完成",
        "tag": book["title"][:8],
        "cover": {
            "series": "AI LECTURER · IMPORTED TEXTBOOK",
            "lines": [book["title"], "注：演示数据"],
            "formula": ["f′(x₀) = lim Δx→0 …", "∫ f(x) dx"],
            "footer": f"第 {len(chapters)} 章已识别",
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
    head = items[0]
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
            paragraphs.append({"type": "formula", "parts": [s["text"]]})
        else:
            paragraphs.append(
                {
                    "type": "p",
                    "segs": [
                        {
                            "t": "src",
                            "id": s["id"],
                            "v": s["text"],
                            "kind": "definition" if s["seq"] == 1 else "plain",
                        }
                    ],
                }
            )

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
        "heading": chapter["title"],
        "intro": f"第 {chapter['num']} 章 · {chapter['title']}　/　第 {chapter['page_start']} 页",
        "paragraphs": paragraphs,
        "knowledgePoints": points,
        "outline": outline,
    }
