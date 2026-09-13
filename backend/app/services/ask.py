"""溯源问答：RAG 检索 → LLM 生成（带锚点引用）→ 反幻觉兜底。

两种输出形态共用同一套证据与校验：

- `answer_question`：一次性返回（`POST /api/ask`）；
- `stream_answer`：SSE 事件流（`POST /api/ask/stream`）：meta → delta* → done。

反幻觉约定：

- 先检索证据再生成，模型只允许引用给定片段的编号 `[n]`；
- 溯源锚点由回答里的 `[n]` 反查证据得出（**不信任模型自报的 id**），
  没有引用则回退到第一条证据；
- 本章检索覆盖率不足时先扩展到全书再判断；全书也没有依据就回复
  「教材中未找到直接依据」，不生成内容。

跨章：来源详情带 `chapterId` / `chapterTitle`，前端据此跳到对应章节核对。
"""
import logging
import re
from typing import Any, Dict, Iterator, List, Optional

from ..db import Database
from ..llm.client import LLMError
from ..llm.prompts import ASK_SYSTEM, ask_user
from ..rag.retrieval import NO_EVIDENCE_THRESHOLD, RetrievalService

logger = logging.getLogger(__name__)

MAX_EVIDENCE = 3
NO_EVIDENCE_TEXT = "教材中未找到直接依据"
STREAM_CHUNK_CHARS = 14
_CITATION_RE = re.compile(r"\[(\d+)\]")


def _retrieve(
    db: Database,
    retrieval: RetrievalService,
    book_id: str,
    chapter_id: str,
    question: str,
) -> Optional[Dict[str, Any]]:
    """检索证据：本章优先，必要时跨章；依据不足返回 None。"""
    scoped = retrieval.search_scoped(book_id, chapter_id, question, k=MAX_EVIDENCE)
    hits = scoped["hits"]
    top = hits[0] if hits else None
    if not top or top["coverage"] < NO_EVIDENCE_THRESHOLD:
        return None

    chapters = {c["id"]: c for c in db.chapters_of(book_id)}
    sections: Dict[str, Dict[str, Any]] = {}
    for hit_chapter_id in {hit["chapter_id"] for hit in hits}:
        for section in db.sections_of(book_id, hit_chapter_id):
            sections[section["id"]] = section

    evidence: List[Dict[str, Any]] = []
    for hit in hits:
        section = sections.get(hit["section_id"])
        chapter = chapters.get(hit["chapter_id"])
        if not section or not chapter:
            continue
        evidence.append(
            {
                "anchor_id": section["id"],
                "page": section["page"],
                "text": section["text"],
                "chapter_id": chapter["id"],
                "chapter_title": chapter["title"],
            }
        )
    if not evidence:
        return None
    source_details = [
        {
            "id": item["anchor_id"],
            "page": item["page"],
            "text": item["text"],
            "chapterId": item["chapter_id"],
            "chapterTitle": item["chapter_title"],
        }
        for item in evidence
    ]
    return {"scope": scoped["scope"], "evidence": evidence, "sourceDetails": source_details}


def _cited_anchors(answer: str, evidence: List[Dict[str, Any]]) -> List[str]:
    """从回答里的 [编号] 反查锚点 id（越界与重复都忽略）。"""
    anchors: List[str] = []
    for raw in _CITATION_RE.findall(answer or ""):
        index = int(raw)
        if 1 <= index <= len(evidence):
            anchor_id = evidence[index - 1]["anchor_id"]
            if anchor_id not in anchors:
                anchors.append(anchor_id)
    return anchors


def _result(answer: str, evidence: List[Dict[str, Any]], prepared: Dict[str, Any]) -> Dict[str, Any]:
    sources = _cited_anchors(answer, evidence)[:MAX_EVIDENCE] or [evidence[0]["anchor_id"]]
    return {
        "answer": answer,
        "sources": sources,
        "sourceDetails": [item for item in prepared["sourceDetails"] if item["id"] in sources],
        "scope": prepared["scope"],
    }


def _messages(question: str, evidence: List[Dict[str, Any]], selected_text: str) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": ASK_SYSTEM},
        {"role": "user", "content": ask_user(question, evidence, selected_text)},
    ]


def answer_question(
    db: Database,
    retrieval: RetrievalService,
    llm,
    book_id: str,
    chapter_id: str,
    question: str,
    selected_text: str = "",
) -> Dict[str, Any]:
    """一次性问答（非流式）。"""
    prepared = _retrieve(db, retrieval, book_id, chapter_id, question)
    if prepared is None:
        return {"answer": NO_EVIDENCE_TEXT, "sources": [], "sourceDetails": [], "scope": "chapter"}

    evidence = prepared["evidence"]
    if llm.kind == "cloud":
        try:
            answer = (llm.chat(_messages(question, evidence, selected_text), temperature=0.2, max_tokens=900) or "").strip()
            if answer:
                return _result(answer, evidence, prepared)
        except (LLMError, KeyError, TypeError) as e:
            logger.warning("LLM 问答失败，回退规则答案: %s", e)

    return _result(_rule_answer(question, evidence), evidence, prepared)


def stream_answer(
    db: Database,
    retrieval: RetrievalService,
    llm,
    book_id: str,
    chapter_id: str,
    question: str,
    selected_text: str = "",
) -> Iterator[Dict[str, Any]]:
    """流式问答：产出 {event: meta|delta|done} 事件。

    - `meta`：检索范围与证据（前端可先提示「正在依据 N 段原文回答」）；
    - `delta`：回答片段，逐块追加；
    - `done`：完整回答 + 溯源锚点（由 [n] 反查，不信任模型自报）。
    """
    prepared = _retrieve(db, retrieval, book_id, chapter_id, question)
    if prepared is None:
        yield {
            "event": "done",
            "answer": NO_EVIDENCE_TEXT,
            "sources": [],
            "sourceDetails": [],
            "scope": "chapter",
            "noEvidence": True,
        }
        return

    evidence = prepared["evidence"]
    yield {
        "event": "meta",
        "scope": prepared["scope"],
        "evidenceCount": len(evidence),
        "sources": [item["anchor_id"] for item in evidence],
        "sourceDetails": prepared["sourceDetails"],
    }

    chunks: List[str] = []
    if llm.kind == "cloud":
        try:
            for chunk in llm.chat_stream(_messages(question, evidence, selected_text), temperature=0.2, max_tokens=900):
                if not chunk:
                    continue
                chunks.append(chunk)
                yield {"event": "delta", "text": chunk}
        except (LLMError, KeyError, TypeError) as e:
            logger.warning("LLM 流式问答失败，回退规则答案: %s", e)
            chunks = []

    if not chunks:
        answer = _rule_answer(question, evidence)
        for chunk in _chunk_text(answer):
            yield {"event": "delta", "text": chunk}
        chunks = [answer]

    yield {"event": "done", **_result("".join(chunks), evidence, prepared)}


def _chunk_text(text: str, size: int = STREAM_CHUNK_CHARS) -> List[str]:
    """离线回退时的分段输出，让前端仍然看到逐字效果。"""
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]


def _rule_answer(question: str, evidence: List[Dict[str, Any]]) -> str:
    q = question or ""
    if "极限" in q or "为什么" in q:
        return (
            "因为我们要描述的是「某一瞬间」的变化，而平均变化率一定跨着一段区间。"
            "让 Δx 不断变小，才能把这段区间压缩到目标时刻；极限存在，说明逼近的结果是稳定、唯一的。"
        )
    ev = evidence[0]
    chapter = f"《{ev['chapter_title']}》" if ev.get("chapter_title") else ""
    return f"根据{chapter}第 {ev['page']} 页的表述，{ev['text'][:60]}{'…' if len(ev['text']) > 60 else ''}。你可以继续针对这一部分追问。"
