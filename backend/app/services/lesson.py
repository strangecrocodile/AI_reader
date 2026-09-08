"""备课讲解：按章节生成「AI 讲解 + 知识点大纲」，入库缓存。

- 真模型：提示词约束引用锚点 id，解析 JSON 并校验；失败回退规则生成。
- 无模型（mock）：基于章节结构生成示意性讲解页，保证演示可用。
"""
import json
import logging
from typing import Any, Dict, List

from ..db import Database
from ..llm.client import LLMError, extract_json
from ..llm.prompts import LESSON_SYSTEM, lesson_user

logger = logging.getLogger(__name__)

MAX_POINTS = 3


def get_lesson(db: Database, llm, chapter: Dict, sections: List[Dict], anchors: List[Dict]) -> Dict[str, Any]:
    """获取（或生成并缓存）章节备课数据。"""
    cached = db.get_explanation(chapter["book_id"], chapter["id"])
    if cached:
        return cached["payload"]

    valid_ids = {a["id"] for a in anchors}
    if llm.kind == "cloud":
        try:
            text = llm.chat(
                [{"role": "system", "content": LESSON_SYSTEM}, {"role": "user", "content": lesson_user(chapter["title"], chapter["full_text"], anchors)}],
                temperature=0.3,
                max_tokens=1800,
            )
            payload = extract_json(text)
            payload = _normalize_lesson(payload, valid_ids, anchors)
        except (LLMError, json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("LLM 备课失败，回退规则生成: %s", e)
            payload = heuristic_lesson(chapter, sections, anchors)
    else:
        payload = heuristic_lesson(chapter, sections, anchors)

    db.upsert_explanation(chapter["book_id"], chapter["id"], payload, llm.name)
    return payload


def _normalize_lesson(payload: Dict, valid_ids: set, anchors: List[Dict]) -> Dict:
    """校验/修正：无效 sourceId 回退到最近锚点；确保字段齐全。"""
    fallback = anchors[0]["id"] if anchors else None

    def fix_point(p: Dict, idx: int) -> Dict:
        return {
            "id": str(p.get("id") or f"kp{idx + 1}"),
            "kind": "card",
            "title": str(p.get("title") or f"知识点 {idx + 1}")[:40],
            "body": str(p.get("body") or "")[:500],
            "sourceId": p.get("sourceId") if p.get("sourceId") in valid_ids else fallback,
            "sourceLabel": "定位教材：原文",
        }

    points = [fix_point(p, i) for i, p in enumerate((payload.get("points") or [])[:MAX_POINTS]) if p]
    outline = [
        {
            "index": f"{i + 1:02d}",
            "title": str(o.get("title") or f"大纲 {i + 1}")[:40],
            "summary": str(o.get("summary") or "")[:120],
            "sourceId": o.get("sourceId") if o.get("sourceId") in valid_ids else fallback,
        }
        for i, o in enumerate((payload.get("outline") or [])[:MAX_POINTS])
    ]
    if not points and anchors:
        points = [
            {
                "id": "kp1",
                "kind": "card",
                "title": "本章要点",
                "body": f"结合教材第 {anchors[0]['page']} 页原文学习。",
                "sourceId": anchors[0]["id"],
                "sourceLabel": "定位教材：原文",
            }
        ]
    return {
        "overview": str(payload.get("overview") or "")[:300],
        "points": points,
        "outline": outline,
    }


def heuristic_lesson(chapter: Dict, sections: List[Dict], anchors: List[Dict]) -> Dict:
    """规则生成：以教材原文段落为骨架，标注锚点。"""
    anchor_by_section = {a["section_id"]: a["id"] for a in anchors}
    secs = [s for s in sections if s.get("kind") != "heading"]
    points = []
    outline = []
    for i, sec in enumerate(secs[:MAX_POINTS]):
        sid = anchor_by_section.get(sec["id"])
        if not sid:
            continue
        excerpt = sec["text"].strip()
        title = excerpt[:14] or f"段落 {i + 1}"
        points.append(
            {
                "id": f"kp{i + 1}",
                "kind": "card",
                "title": title,
                "body": f"教材第 {sec['page']} 页原文：{excerpt[:80]}{'…' if len(excerpt) > 80 else ''}。建议先理解这段表述，再继续后面的内容。",
                "sourceId": sid,
                "sourceLabel": "定位教材：原文",
            }
        )
        outline.append(
            {
                "index": f"{i + 1:02d}",
                "title": title,
                "summary": excerpt[:22],
                "sourceId": sid,
            }
        )
    return {
        "overview": f"本章「{chapter['title']}」共 {len(secs)} 个知识点段落，从第 {secs[0]['page'] if secs else 1} 页开始学习。",
        "points": points,
        "outline": outline,
    }
