"""知识页聚合服务：把章节知识点整理成跨章概念图谱。

数据链路（契约与 tools/kb-agent 的 V2 概念层对齐）：

    章节原文锚点 ──► concepts.extract_concepts（LLM 抽取 / 规则回退，带缓存）
                 ──► concepts.build_concept_graph（跨章合并 + 前置关系 + 未解析前置）
                 ──► /api/books/{id}/knowledge

返回结构中 `title/summary/chapterId/chapterTitle/sourceId/status/mastery` 为原有的
兼容字段，`definition/chapters/anchorCount/prerequisites/unresolved` 为 v2 新增字段，
前端据此把「章节内学习顺序」升级为带前置依赖的语义图谱。
"""
from typing import Any, Dict, List

from ..db import Database
from . import concepts as concept_service


def get_knowledge(db: Database, llm, book: Dict[str, Any]) -> Dict[str, Any]:
    """聚合一本教材的知识点图谱。"""
    chapter_blocks: List[Dict[str, Any]] = []
    for chapter in db.chapters_of(book["id"]):
        sections = db.sections_of(book["id"], chapter["id"])
        anchors = db.anchors_of(book["id"], chapter["id"])
        payload = concept_service.extract_concepts(db, llm, chapter, sections, anchors)
        chapter_blocks.append(
            {
                "chapter_id": chapter["id"],
                "chapter_title": chapter["title"],
                "method": payload.get("method", "rule"),
                "concepts": payload.get("concepts", []),
            }
        )

    graph = concept_service.build_concept_graph(
        chapter_blocks, db.progress_of_book(book["id"])
    )
    return {
        "bookId": book["id"],
        "bookTitle": book["title"],
        "concepts": graph["concepts"],
        "relations": graph["relations"],
        "unresolved": graph["unresolved"],
        "methods": graph["methods"],
        "stats": graph["stats"],
    }
