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
from . import threads as thread_service

logger = logging.getLogger(__name__)

MAX_EVIDENCE = 3
NO_EVIDENCE_TEXT = "教材中未找到直接依据"
STREAM_CHUNK_CHARS = 14
#: 兜底答案里每条原文摘录的字数上限
EXCERPT_CHARS = 120
#: 兜底答案的开场说明：讲清「为什么只有原文」，避免被误读成模型的回答
FALLBACK_NOTICE = "（未接入大模型，这里直接给出教材中与你的问题最相关的原文，可对照核对。）"
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
    thread: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """一次性问答（非流式）。带 thread 时把这一问一答写进追问线程。"""
    prepared = _retrieve(db, retrieval, book_id, chapter_id, question)
    if prepared is None:
        result = {"answer": NO_EVIDENCE_TEXT, "sources": [], "sourceDetails": [], "scope": "chapter"}
        _persist_exchange(db, thread, question, result)
        return {**result, "threadId": thread["id"] if thread else None}

    evidence = prepared["evidence"]
    result: Optional[Dict[str, Any]] = None
    if llm.kind == "cloud":
        try:
            answer = (llm.chat(_messages(question, evidence, selected_text), temperature=0.2, max_tokens=900) or "").strip()
            if answer:
                result = _result(answer, evidence, prepared)
        except (LLMError, KeyError, TypeError) as e:
            logger.warning("LLM 问答失败，回退规则答案: %s", e)

    if result is None:
        result = _result(_rule_answer(evidence), evidence, prepared)
    _persist_exchange(db, thread, question, result)
    return {**result, "threadId": thread["id"] if thread else None}


def _persist_exchange(
    db: Database, thread: Optional[Dict[str, Any]], question: str, result: Dict[str, Any]
) -> None:
    """线程模式下记录问答；未启用线程时保持无状态。"""
    if thread is None:
        return
    thread_service.append_exchange(db, thread["id"], question, result)


def stream_answer(
    db: Database,
    retrieval: RetrievalService,
    llm,
    book_id: str,
    chapter_id: str,
    question: str,
    selected_text: str = "",
    thread: Optional[Dict[str, Any]] = None,
) -> Iterator[Dict[str, Any]]:
    """流式问答：产出 {event: meta|delta|done} 事件。

    - `meta`：检索范围与证据（前端可先提示「正在依据 N 段原文回答」）；
    - `delta`：回答片段，逐块追加；
    - `done`：完整回答 + 溯源锚点（由 [n] 反查，不信任模型自报）。

    带 `thread` 时：问题在生成前先落库（流断了也不丢），回答在收尾时落库。
    """
    if thread is not None:
        thread_service.append_message(db, thread["id"], "user", question)

    prepared = _retrieve(db, retrieval, book_id, chapter_id, question)
    if prepared is None:
        result = {
            "answer": NO_EVIDENCE_TEXT,
            "sources": [],
            "sourceDetails": [],
            "scope": "chapter",
            "noEvidence": True,
        }
        _persist_answer(db, thread, result)
        yield {"event": "done", "threadId": thread["id"] if thread else None, **result}
        return

    evidence = prepared["evidence"]
    yield {
        "event": "meta",
        "threadId": thread["id"] if thread else None,
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
        answer = _rule_answer(evidence)
        for chunk in _chunk_text(answer):
            yield {"event": "delta", "text": chunk}
        chunks = [answer]

    result = _result("".join(chunks), evidence, prepared)
    _persist_answer(db, thread, result)
    yield {"event": "done", "threadId": thread["id"] if thread else None, **result}


def _persist_answer(db: Database, thread: Optional[Dict[str, Any]], result: Dict[str, Any]) -> None:
    if thread is None:
        return
    thread_service.append_message(
        db,
        thread["id"],
        "assistant",
        result.get("answer", ""),
        sources=result.get("sources"),
        source_details=result.get("sourceDetails"),
        scope=result.get("scope", ""),
    )


def _chunk_text(text: str, size: int = STREAM_CHUNK_CHARS) -> List[str]:
    """离线回退时的分段输出，让前端仍然看到逐字效果。"""
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]


def _rule_answer(evidence: List[Dict[str, Any]]) -> str:
    """无模型 / 模型调用失败时的兜底：不生成内容，只列教材原文。

    关键约束：兜底答案也必须**可溯源**——每条摘录带 `[n]` 编号，由 `_result` 反查
    出锚点，前端据此回跳原文。绝不返回与教材无关的通用讲解：那会直接违背
    「回答以教材为边界」这条产品边界（详见 docs/产品设计文档.md 第 4.4 节）。
    """
    lines = [FALLBACK_NOTICE]
    for index, item in enumerate(evidence, start=1):
        chapter = f"《{item['chapter_title']}》" if item.get("chapter_title") else ""
        excerpt = (item.get("text") or "").strip()
        if len(excerpt) > EXCERPT_CHARS:
            excerpt = excerpt[:EXCERPT_CHARS] + "…"
        lines.append(f"[{index}] {chapter}第 {item['page']} 页：{excerpt}")
    return "\n".join(lines)
