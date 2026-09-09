"""知识页聚合服务：把章节讲义转换成可浏览的知识点与关系图谱。"""
from typing import Any, Dict, List

from ..db import Database
from .lesson import get_lesson


def get_knowledge(db: Database, llm, book: Dict[str, Any]) -> Dict[str, Any]:
    """聚合一本教材的知识点。

    MVP 阶段先复用章节讲义缓存，不额外引入图数据库：
    - 每个讲义 point 变成一个知识点节点；
    - 同一章节内按教材顺序连接为“学习路径”关系；
    - 节点保留 chapter/source 信息，前端可以回到原文。
    """
    concepts: List[Dict[str, Any]] = []
    relations: List[Dict[str, Any]] = []
    chapters = db.chapters_of(book["id"])
    progress_by_chapter = db.progress_of_book(book["id"])

    for chapter in chapters:
        sections = db.sections_of(book["id"], chapter["id"])
        anchors = db.anchors_of(book["id"], chapter["id"])
        lesson = get_lesson(db, llm, chapter, sections, anchors)
        chapter_concepts = []

        for point_index, point in enumerate(lesson.get("points", [])):
            concept_id = f"{chapter['id']}:{point['id']}"
            source_id = point.get("sourceId")
            progress = progress_by_chapter.get(chapter["id"])
            status = progress["status"] if progress else "planned"
            mastery = progress["mastery"] if progress else 0
            concept = {
                "id": concept_id,
                "title": point.get("title", f"知识点 {point_index + 1}"),
                "summary": _plain_text(point.get("body", "")),
                "chapterId": chapter["id"],
                "chapterTitle": chapter["title"],
                "sourceId": source_id,
                "sourceLabel": point.get("sourceLabel", "定位教材：原文"),
                "status": status,
                "mastery": mastery,
            }
            concepts.append(concept)
            chapter_concepts.append(concept)

        for previous, current in zip(chapter_concepts, chapter_concepts[1:]):
            relations.append(
                {
                    "id": f"{previous['id']}->{current['id']}",
                    "source": previous["id"],
                    "target": current["id"],
                    "type": "sequence",
                    "label": "学习顺序",
                }
            )

    return {
        "bookId": book["id"],
        "bookTitle": book["title"],
        "concepts": concepts,
        "relations": relations,
        "stats": {
            "conceptCount": len(concepts),
            "learnedCount": sum(c["status"] != "planned" for c in concepts),
            "relationCount": len(relations),
        },
    }


def _plain_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            item.get("v", "") if isinstance(item, dict) else str(item)
            for item in value
        )
    return str(value or "")
