"""学习路径：按教材目录生成学习顺序与目标，入库缓存。"""
import json
import logging
from typing import Any, Dict, List

from ..db import Database
from ..llm.client import LLMError, extract_json
from ..llm.prompts import PLAN_SYSTEM, plan_user

logger = logging.getLogger(__name__)


def get_plan(db: Database, llm, book: Dict, chapters: List[Dict], force: bool = False) -> Dict[str, Any]:
    if not force:
        cached = db.get_plan(book["id"])
        if cached:
            return cached["payload"]

    if llm.kind == "cloud":
        try:
            raw = llm.chat(
                [{"role": "system", "content": PLAN_SYSTEM}, {"role": "user", "content": plan_user(chapters)}],
                temperature=0.2,
                max_tokens=1200,
            )
            items = extract_json(raw).get("items") or []
            payload = {"items": _normalize_items(items, chapters)}
        except (LLMError, json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("LLM 规划失败，回退规则生成: %s", e)
            payload = heuristic_plan(chapters)
    else:
        payload = heuristic_plan(chapters)

    db.upsert_plan(book["id"], payload, llm.name)
    return payload


def heuristic_plan(chapters: List[Dict]) -> Dict[str, Any]:
    items = []
    for ch in chapters:
        char_count = len(ch.get("full_text", ""))
        items.append(
            {
                "chapterId": ch["id"],
                "order": ch["num"],
                "duration_minutes": max(20, min(90, 25 + char_count // 80)),
                "goal": f"理解「{ch['title']}」的核心内容，能复述关键概念。",
                "overview": f"从第 {ch['page_start']} 页开始，共 {ch['page_end'] - ch['page_start'] + 1} 页。",
            }
        )
    return {"items": items}


def _normalize_items(items: List[Dict], chapters: List[Dict]) -> List[Dict]:
    by_id = {c["id"]: c for c in chapters}
    out = []
    for it in items:
        cid = it.get("chapterId")
        if cid not in by_id:
            continue
        out.append(
            {
                "chapterId": cid,
                "order": int(it.get("order") or len(out) + 1),
                "duration_minutes": min(120, max(15, int(it.get("duration_minutes") or 30))),
                "goal": str(it.get("goal") or f"理解「{by_id[cid]['title']}」。")[:120],
                "overview": str(it.get("overview") or "")[:160],
            }
        )
    return out
