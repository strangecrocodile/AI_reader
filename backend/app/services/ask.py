"""溯源问答：RAG 检索 → LLM 生成（带锚点引用）→ 反幻觉兜底。

两种输出形态共用同一套证据与校验：

- `answer_question`：一次性返回（`POST /api/ask`）；
- `stream_answer`：SSE 事件流（`POST /api/ask/stream`）：meta → delta* → done。

划词追问（带 `selected_text` / `anchor_id`）另有一条：用户选中的那段原文按锚点
直取、作为第一条证据，且不受覆盖率门槛约束——用户是**指着它**提问的。检索词也
换成「选中原文 + 问题」，否则「这段话在讲什么」这类问题根本没有可检索的查询词。

反幻觉约定：

- 先检索证据再生成，模型只允许引用给定片段的编号 `[n]`；
- 溯源锚点由回答里的 `[n]` 反查证据得出（**不信任模型自报的 id**），
  没有引用则回退到第一条证据；
- 证据来自**全书检索**（本章命中加权），题面之外的章节也能进证据——教材常把总述
  与定义放在靠前的总论章、把例题放在具体章节，只看本章就凑不出「提炼」所需的材料；
  全书覆盖率达标的段落一个都没有时，才回复「教材中未找到直接依据」，不生成内容。

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

#: 送进模型的证据条数上限。要求是「从全书相关内容里提炼」，3 条（实测约 480 字）
#: 太窄：一本扫描教材里「聚类分析」的三个相关段落只覆盖到第 6 章的例子，讲得最准的
#: 那个定义在第 2 章，取 3 时它根本进不了证据。实测全书 top-10 合计约 1600 字，且条条
#: 都还是教材原文，排到第 12 名才开始出现明显无关的段落——10 是「材料够用」与
#: 「别把噪声塞进上下文」之间的位置。
MAX_EVIDENCE = 10
NO_EVIDENCE_TEXT = "教材中未找到直接依据"
STREAM_CHUNK_CHARS = 14
#: 兜底答案里每条原文摘录的字数上限
EXCERPT_CHARS = 120
#: 兜底答案的开场说明：讲清「为什么只有原文」，避免被误读成模型的回答
FALLBACK_NOTICE = "（未接入大模型，这里直接给出教材中与你的问题最相关的原文，可对照核对。）"
#: 配了模型、但这次一个正文字都没吐出来时的说明。
#: 不能沿用上面那句——模型明明连着，「未接入大模型」是句假话，会把排查引到错误方向。
MODEL_EMPTY_NOTICE = "（模型这次没有返回内容，先给出教材中与你的问题最相关的原文，可对照核对。）"
#: 问答的生成上限。**这个值要和推理开销一起看**：DeepSeek 的推理模型把
#: `reasoning_content` 和正文算在同一个 `max_tokens` 里，实测「这一段为什么成立」
#: 这类问题会先烧掉 1232~1346 字推理，取 900 时正文为 0、`finish_reason=length`，
#: 回答被静默判成「模型没回答」而回退兜底。4000 下同一批问题全部正常出正文。
#: （同项目其它生成任务用的是 1200~2000，这个取最大是给推理留余量。）
ASK_MAX_TOKENS = 4000
_CITATION_RE = re.compile(r"\[(\d+)\]")


def _pinned_evidence(
    db: Database, anchor_id: str, chapters: Dict[str, Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """划词选中的那一段原文，按锚点直接取出。

    划词追问的上下文就是这段原文——用户是**指着它**提问的，不该再让 BM25 去猜
    该不该用它。锚点表里本来就存了原文和页码，按 id 取即可，零猜测。

    取不到（老线程、脏 id、锚点已被重新导入清掉）返回 None，退回纯检索的老路。

    注：`anchors.id` 与 `sections.id` 同值（见 `db.add_anchors`），所以这里给出的
    `anchor_id` 与检索命中给出的锚点是同一套 id，前端回跳原文用的是同一个键。
    """
    if not anchor_id:
        return None
    anchor = db.get_anchor(anchor_id)
    if not anchor:
        return None
    chapter = chapters.get(anchor.get("chapter_id") or "")
    if not chapter:
        return None
    return {
        "anchor_id": anchor["id"],
        "page": anchor["page"],
        "text": anchor["text"],
        "chapter_id": chapter["id"],
        "chapter_title": chapter["title"],
        "selected": True,
    }


def _retrieve(
    db: Database,
    retrieval: RetrievalService,
    book_id: str,
    chapter_id: str,
    question: str,
    selected_text: str = "",
    anchor_id: str = "",
) -> Optional[Dict[str, Any]]:
    """检索全书证据（本章加权）；依据不足返回 None。

    范围是**整本教材**，不是「本章优先、本章不够才扩展」——回答要的是从全书相关内容
    里提炼，而教材把总述/定义与例题分放在不同章节是常态，先查本章会在本章命中的那一刻
    就错过定义（见 `RetrievalService.search_book`）。本章命中加权只影响排序，不排除其它章节。

    划词追问（带 `selected_text` / `anchor_id`）在这条规则之上多两条：

    1. 选中的那段原文直接作为第一条证据，且**不参与覆盖率判定**——用户已经明确
       指着它问，再判一次「有没有依据」是本末倒置；
    2. 检索词换成「选中原文 + 问题」。否则「这段话在讲什么」「这段为什么成立」这类
       问题的查询词在教材里几乎不存在，检索覆盖率低于阈值，模型连被调用的机会
       都没有——这是「划词提问总是无法回答」的主要原因之一。
    """
    chapters = {c["id"]: c for c in db.chapters_of(book_id)}
    pinned = _pinned_evidence(db, anchor_id, chapters)

    query = f"{selected_text} {question}".strip() if selected_text else question
    scoped = retrieval.search_book(book_id, chapter_id, query, k=MAX_EVIDENCE)
    hits = scoped["hits"]
    top = hits[0] if hits else None
    if pinned is None and (not top or top["coverage"] < NO_EVIDENCE_THRESHOLD):
        return None

    sections: Dict[str, Dict[str, Any]] = {}
    for hit_chapter_id in {hit["chapter_id"] for hit in hits}:
        for section in db.sections_of(book_id, hit_chapter_id):
            sections[section["id"]] = section

    evidence: List[Dict[str, Any]] = [pinned] if pinned else []
    for hit in hits:
        if len(evidence) >= MAX_EVIDENCE:
            break
        if any(item["anchor_id"] == hit["section_id"] for item in evidence):
            continue  # 选中的那段自己又被检索命中，别占两格
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
    anchor_id: str = "",
) -> Dict[str, Any]:
    """一次性问答（非流式）。带 thread 时把这一问一答写进追问线程。"""
    prepared = _retrieve(db, retrieval, book_id, chapter_id, question, selected_text, anchor_id)
    if prepared is None:
        result = {"answer": NO_EVIDENCE_TEXT, "sources": [], "sourceDetails": [], "scope": "chapter"}
        _persist_exchange(db, thread, question, result)
        return {**result, "threadId": thread["id"] if thread else None}

    evidence = prepared["evidence"]
    result: Optional[Dict[str, Any]] = None
    if llm.kind == "cloud":
        try:
            answer = (
                llm.chat(
                    _messages(question, evidence, selected_text),
                    temperature=0.2,
                    max_tokens=ASK_MAX_TOKENS,
                )
                or ""
            ).strip()
            if answer:
                result = _result(answer, evidence, prepared)
        except (LLMError, KeyError, TypeError) as e:
            logger.warning("LLM 问答失败，回退规则答案: %s", e)

    if result is None:
        result = _result(_rule_answer(evidence, _fallback_notice(llm)), evidence, prepared)
    _persist_exchange(db, thread, question, result)
    return {**result, "threadId": thread["id"] if thread else None}


def _fallback_notice(llm) -> str:
    """兜底文案要分清「没接模型」还是「接了但这次没吐正文」。

    两者都会走到规则兜底，但原因完全不同：前者是预期行为，后者说明模型侧出了问题
    （超时、被 max_tokens 截断、服务异常）。混用一句话会让后者看起来像「本来就没配」，
    排查时直接被带偏。"""
    return FALLBACK_NOTICE if llm.kind != "cloud" else MODEL_EMPTY_NOTICE


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
    anchor_id: str = "",
) -> Iterator[Dict[str, Any]]:
    """流式问答：产出 {event: meta|delta|done} 事件。

    - `meta`：检索范围与证据（前端可先提示「正在依据 N 段原文回答」）；
    - `delta`：回答片段，逐块追加；
    - `done`：完整回答 + 溯源锚点（由 [n] 反查，不信任模型自报）。

    带 `thread` 时：问题在生成前先落库（流断了也不丢），回答在收尾时落库。
    """
    if thread is not None:
        thread_service.append_message(db, thread["id"], "user", question)

    prepared = _retrieve(db, retrieval, book_id, chapter_id, question, selected_text, anchor_id)
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
            for chunk in llm.chat_stream(
                _messages(question, evidence, selected_text),
                temperature=0.2,
                max_tokens=ASK_MAX_TOKENS,
            ):
                if not chunk:
                    continue
                chunks.append(chunk)
                yield {"event": "delta", "text": chunk}
        except (LLMError, KeyError, TypeError) as e:
            logger.warning("LLM 流式问答失败，回退规则答案: %s", e)
            chunks = []

    if not chunks:
        answer = _rule_answer(evidence, _fallback_notice(llm))
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


def _rule_answer(evidence: List[Dict[str, Any]], notice: str = FALLBACK_NOTICE) -> str:
    """无模型 / 模型调用失败时的兜底：不生成内容，只列教材原文。

    关键约束：兜底答案也必须**可溯源**——每条摘录带 `[n]` 编号，由 `_result` 反查
    出锚点，前端据此回跳原文。绝不返回与教材无关的通用讲解：那会直接违背
    「回答以教材为边界」这条产品边界（详见 docs/产品设计文档.md 第 4.4 节）。

    `notice` 由调用方按失败原因给（见 `_fallback_notice`），别在这里替它猜。
    """
    lines = [notice]
    for index, item in enumerate(evidence, start=1):
        chapter = f"《{item['chapter_title']}》" if item.get("chapter_title") else ""
        excerpt = (item.get("text") or "").strip()
        if len(excerpt) > EXCERPT_CHARS:
            excerpt = excerpt[:EXCERPT_CHARS] + "…"
        lines.append(f"[{index}] {chapter}第 {item['page']} 页：{excerpt}")
    return "\n".join(lines)
