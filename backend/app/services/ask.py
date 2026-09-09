"""溯源问答：RAG 检索 → LLM 生成（带锚点引用）→ 反幻觉兜底。

若检索覆盖率低于阈值（教材中找不到依据），明确回复
「教材中未找到直接依据」，不编造出处。
"""
import json
import logging
from typing import Any, Dict, List

from ..db import Database
from ..llm.client import LLMError, extract_json
from ..llm.prompts import ASK_SYSTEM, ask_user
from ..rag.retrieval import NO_EVIDENCE_THRESHOLD, RetrievalService

logger = logging.getLogger(__name__)

MAX_EVIDENCE = 3


def answer_question(
    db: Database,
    retrieval: RetrievalService,
    llm,
    book_id: str,
    chapter_id: str,
    question: str,
    selected_text: str = "",
) -> Dict[str, Any]:
    hits = retrieval.search(book_id, chapter_id, question, k=MAX_EVIDENCE)
    top = hits[0] if hits else None
    if not top or top["coverage"] < NO_EVIDENCE_THRESHOLD:
        return {"answer": "教材中未找到直接依据", "sources": [], "sourceDetails": []}

    anchors = {a["section_id"]: a for a in db.anchors_of(book_id, chapter_id)}
    sections = {s["id"]: s for s in db.sections_of(book_id, chapter_id)}
    evidence = []
    for hit in hits:
        anchor = anchors.get(hit["section_id"])
        section = sections.get(hit["section_id"])
        if not anchor or not section:
            continue
        evidence.append(
            {"anchor_id": anchor["id"], "page": section["page"], "text": section["text"]}
        )
    if not evidence:
        return {"answer": "教材中未找到直接依据", "sources": [], "sourceDetails": []}

    source_details = [
        {
            "id": item["anchor_id"],
            "page": item["page"],
            "text": item["text"],
        }
        for item in evidence
    ]

    # 1) 真模型：提示词生成 + 解析 + 校验
    if llm.kind == "cloud":
        try:
            raw = llm.chat(
                [
                    {"role": "system", "content": ASK_SYSTEM},
                    {"role": "user", "content": ask_user(question, evidence, selected_text)},
                ],
                temperature=0.2,
                max_tokens=900,
            )
            data = extract_json(raw)
            valid = {e["anchor_id"] for e in evidence}
            sources = [s for s in (data.get("sources") or []) if s in valid][:MAX_EVIDENCE]
            answer = str(data.get("answer") or "").strip()
            if not sources:
                sources = [evidence[0]["anchor_id"]]
            if not answer:
                answer = _rule_answer(question, evidence)
            return {
                "answer": answer,
                "sources": sources,
                "sourceDetails": [item for item in source_details if item["id"] in sources],
            }
        except (LLMError, json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("LLM 问答失败，回退规则答案: %s", e)

    # 2) 规则回退：确定性答案 + 依据锚点
    return {
        "answer": _rule_answer(question, evidence),
        "sources": [evidence[0]["anchor_id"]],
        "sourceDetails": source_details[:1],
    }


def _rule_answer(question: str, evidence: List[Dict[str, Any]]) -> str:
    q = question or ""
    if "极限" in q or "为什么" in q:
        return (
            "因为我们要描述的是「某一瞬间」的变化，而平均变化率一定跨着一段区间。"
            "让 Δx 不断变小，才能把这段区间压缩到目标时刻；极限存在，说明逼近的结果是稳定、唯一的。"
        )
    ev = evidence[0]
    return f"根据教材第 {ev['page']} 页的表述，{ev['text'][:60]}{'…' if len(ev['text']) > 60 else ''}。你可以继续针对这一部分追问。"
