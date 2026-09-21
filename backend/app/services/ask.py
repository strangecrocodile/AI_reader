"""溯源问答：RAG 检索 → LLM 生成（带锚点引用）→ 反幻觉兜底。

两种输出形态共用同一套证据与校验：

- `answer_question`：一次性返回（`POST /api/ask`）；
- `stream_answer`：SSE 事件流（`POST /api/ask/stream`）：meta → delta* → done。

划词追问（带 `selected_text` / `anchor_id`）另有一条：用户选中的那段原文按锚点
直取、作为第一条证据，且不受依据判定约束——用户是**指着它**提问的。检索词也
换成「选中原文 + 问题」，否则「这段话在讲什么」这类问题根本没有可检索的查询词。

反幻觉约定：

- 先检索证据再生成，模型只允许引用给定片段的编号 `[n]`；
- 溯源锚点由回答里的 `[n]` 反查证据得出（**不信任模型自报的 id**），
  没有引用则回退到第一条证据；
- 证据来自**全书检索**（本章命中加权），题面之外的章节也能进证据——教材常把总述
  与定义放在靠前的总论章、把例题放在具体章节，只看本章就凑不出「提炼」所需的材料；
- 命中词里**一个「教材反复在讲的概念」都没有、且问句也没被哪段原样回答**时，
  才回复「教材中未找到直接依据」，不生成内容。两条通道的判定见 `_has_evidence`：
  它不看命中占问句的比例，所以**问得详细不会被拒答**（旧口径只看覆盖率，
  长问句会被摊薄，见 `bm25.coverage`）。

拒答不是死路：`noEvidence` 为真时同时给出 `hint`（换个问法 / 划词提问）与
`closest`（教材里最接近的几条段落，带章节与页码，可点开核对）。`closest` **不是依据**，
不进 `sources`，避免把「没答上来」和「出处是这里」混为一谈。

跨章：来源详情带 `chapterId` / `chapterTitle`，前端据此跳到对应章节核对。
"""
import logging
import re
from typing import Any, Dict, Iterator, List, Optional

from ..db import Database
from ..llm.client import LLMError
from ..llm.prompts import ASK_SYSTEM, ask_user
from ..rag.retrieval import RetrievalService
from . import threads as thread_service

logger = logging.getLogger(__name__)

#: 送进模型的证据条数上限。要求是「从全书相关内容里提炼」，3 条（实测约 480 字）
#: 太窄：一本扫描教材里「聚类分析」的三个相关段落只覆盖到第 6 章的例子，讲得最准的
#: 那个定义在第 2 章，取 3 时它根本进不了证据。实测全书 top-10 合计约 1600 字，且条条
#: 都还是教材原文，排到第 12 名才开始出现明显无关的段落——10 是「材料够用」与
#: 「别把噪声塞进上下文」之间的位置。
MAX_EVIDENCE = 10
NO_EVIDENCE_TEXT = "教材中未找到直接依据"
#: 拒答时给用户的下一步。拒答不该是死路——用户要么是问偏了，要么该换划词这条路。
NO_EVIDENCE_HINT = (
    "可以换个问法：点出教材里的具体概念（例如「导数的定义」）；"
    "或者直接选中相关原文再提问——划词追问不受依据判定限制。"
)
#: 拒答时附带展示的「教材里最接近的段落」条数。给多了像在硬凑依据，给少了没法让人判断。
CLOSEST_LIMIT = 3
#: 判定依据的**第二条**通道：top1 的朴素覆盖率 ≥ 该值，说明问句几乎被这段原样回答了。
#: 覆盖率单独用是错的（分母是问句词数，长问句会被摊薄，见 `bm25.coverage`），
#: 但它能救「复现词」救不了的场景：语料很小、或某个概念全书只在一处出现时，
#: 所有词的 df 都是 1，复现词必然为空——那时问句与段落的**高度重合**才是依据。
#: 实测：单段教材里「为什么列表是可变的？」覆盖率 1.0；题外问句最高只有 0.167。
VERBATIM_COVERAGE = 0.22
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


def _has_evidence(hit: Optional[Dict[str, Any]]) -> bool:
    """这个命中能不能当依据——**两条通道满足其一即可**：

    1. **复现词**：命中的词是教材反复在讲的概念（`bm25.recurring_matches`）。
       与问句长短无关，救的是长问句——「导数在实际问题中有什么用处」里教材
       不会原样重复这句话，但「导数」是它在反复讲的概念。
    2. **覆盖率达标**：问句几乎被这段原样回答了（`VERBATIM_COVERAGE`）。
       救的是复现词失效的场景：语料很小，或某个概念全书只出现在一处，
       此时所有词的 df 都是 1，复现词必然为空，而问句与段落的**重合度**才是依据。

    单独用任何一条都会误拒：只用 1，单段教材上无解；只用 2，长问句被摊薄
    （这正是「问得越认真越容易被拒答」的根因）。所以是并集，不是二选一。
    """
    if not hit:
        return False
    return bool(hit["recurring_terms"]) or hit["coverage"] >= VERBATIM_COVERAGE


def _closest(
    hits: List[Dict[str, Any]],
    sections: Dict[str, Dict[str, Any]],
    chapters: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """拒答时附带展示的「教材里最接近的段落」。

    拒答不等于教材里什么都没有——更常见的是**有相关段落、但没到能据此作答的程度**
    （或者问题本身问偏了）。把最接近的几条连章节与页码摆出来，用户自己就能判断是该
    换个问法、还是其实想问的是另一件事。

    形状与 `sourceDetails` 一致，前端复用同一套渲染与「跳到原文」。
    但它们**不是依据**：单独一个字段、不进 `sources`，避免把「没答上来」和
    「出处就是这里」混为一谈——溯源的可信度就靠这条边界撑着。
    """
    out: List[Dict[str, Any]] = []
    for hit in hits[:CLOSEST_LIMIT]:
        section = sections.get(hit["section_id"])
        chapter = chapters.get(hit["chapter_id"])
        if not section or not chapter:
            continue
        out.append(
            {
                "id": section["id"],
                "page": section["page"],
                "text": section["text"],
                "chapterId": chapter["id"],
                "chapterTitle": chapter["title"],
            }
        )
    return out


def _retrieve(
    db: Database,
    retrieval: RetrievalService,
    book_id: str,
    chapter_id: str,
    question: str,
    selected_text: str = "",
    anchor_id: str = "",
) -> Dict[str, Any]:
    """检索全书证据（本章加权）；返回带 `noEvidence` 的结果，拒答时附「出口」。

    范围是**整本教材**，不是「本章优先、本章不够才扩展」——回答要的是从全书相关内容
    里提炼，而教材把总述/定义与例题分放在不同章节是常态，先查本章会在本章命中的那一刻
    就错过定义（见 `RetrievalService.search_book`）。本章命中加权只影响排序，不排除其它章节。

    判定看 `_has_evidence(top)`：**复现词**（教材在讲这个概念）**或**覆盖率达标
    （这段几乎原样回答了问题）。旧口径只看「top1 的朴素覆盖率 ≥ 0.22」，它随问句
    变长而下降，**认真提问反被拒答**：实测「导数是什么」0.250 通过，而同一本书的
    「导数在实际问题中有什么用处」0.167 被拒。复现词与前一条通道都不看问句长度，
    这个反例已由
    `tests/test_api.py::test_ask_long_natural_question_about_the_textbooks_own_topic` 钉住。

    划词追问（带 `selected_text` / `anchor_id`）在这条规则之上多两条：

    1. 选中的那段原文直接作为第一条证据，且**不参与依据判定**——用户已经明确
       指着它问，再判一次「有没有依据」是本末倒置；
    2. 检索词换成「选中原文 + 问题」。否则「这段话在讲什么」「这段为什么成立」这类
       问题的查询词在教材里几乎不存在，模型连被调用的机会都没有——这是
       「划词提问总是无法回答」的主要原因之一。

    返回值恒为 dict（不再返回 None）：拒答也是一条要给用户看的结果，而且必须带上
    `closest` 与 `scope`，否则前端只能渲染一句「没找到」，用户无路可走。
    """
    chapters = {c["id"]: c for c in db.chapters_of(book_id)}
    pinned = _pinned_evidence(db, anchor_id, chapters)

    query = f"{selected_text} {question}".strip() if selected_text else question
    scoped = retrieval.search_book(book_id, chapter_id, query, k=MAX_EVIDENCE)
    hits = scoped["hits"]
    top = hits[0] if hits else None

    sections: Dict[str, Dict[str, Any]] = {}
    for hit_chapter_id in {hit["chapter_id"] for hit in hits}:
        for section in db.sections_of(book_id, hit_chapter_id):
            sections[section["id"]] = section

    if pinned is None and not _has_evidence(top):
        return {
            "noEvidence": True,
            "scope": scoped["scope"],
            "closest": _closest(hits, sections, chapters),
        }

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
        return {
            "noEvidence": True,
            "scope": scoped["scope"],
            "closest": _closest(hits, sections, chapters),
        }
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
    return {
        "noEvidence": False,
        "scope": scoped["scope"],
        "evidence": evidence,
        "sourceDetails": source_details,
    }


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
        # 契约恒定：`noEvidence` 在两个接口、成功与拒答两条路上**都存在**，
        # 客户端不必靠比对回答文本来判断是不是拒答（那是最脆的一种判法）。
        "noEvidence": False,
    }


def _no_evidence_result(prepared: Dict[str, Any]) -> Dict[str, Any]:
    """拒答结果：同一条消息里给出「为什么没有」和「下一步怎么办」。

    `scope` 用检索真实反推出的值，不硬编码 `chapter`——全书检索扫的就是整本书，
    谎报范围会让前端连「依据取自全书」这类提示都显示不出来。
    """
    return {
        "answer": NO_EVIDENCE_TEXT,
        "sources": [],
        "sourceDetails": [],
        "scope": prepared["scope"],
        "noEvidence": True,
        "closest": prepared["closest"],
        "hint": NO_EVIDENCE_HINT,
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
    if prepared["noEvidence"]:
        result = _no_evidence_result(prepared)
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
    if prepared["noEvidence"]:
        result = _no_evidence_result(prepared)
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
        # 拒答的「出口」也要落库：线程重新打开时不能只剩下「没找到」这一句。
        no_evidence=bool(result.get("noEvidence")),
        closest=result.get("closest"),
        hint=result.get("hint", ""),
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
