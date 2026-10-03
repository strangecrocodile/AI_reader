"""阅读工具：翻译与总结。两者都产出与「问答」同一形状的流式事件。

## 为什么单独一个模块，而不是塞进 ask.py

问答的核心是**检索 + 溯源**：先去全书找证据，再判「有没有依据」，最后把 [n] 反查成锚点。
翻译与总结不需要检索——作用对象是**用户眼前的那段东西**（选中的原文、当前页、本章），
依据是给定的，不靠检索找。硬塞进 ask 会让那条已经被四个坑打磨过的链路多出两条分支。

## 两者的依据从哪来

- **翻译**：目标就是原文本身，逐段译回去，锚点天然一一对应（每段一条）；
- **总结**：把段落**编号**喂给模型，要求它在每条要点末尾写 `[编号]`，我们再按编号反查锚点
  ——与问答同一套「不信任模型自报 id」的口径：模型只许报编号，锚点由我们查表得出。

## 无模型时怎么办（这条不能含糊）

- 总结：退化成**规则摘要**（每段取首句），并明确标注这是规则结果，不是模型写的；
- 翻译：**不翻译**。没有模型就译不出来，编一段「看着像译文」的中文是最坏的结果——
  用户会以为那是原文的意思。如实说「未接入大模型，无法翻译」并把原文列出来对照。
"""
import logging
import re
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ..db import Database
from ..llm.client import LLMError
from ..llm.prompts import (
    SUMMARY_MERGE_SYSTEM,
    SUMMARY_SYSTEM,
    TRANSLATE_SYSTEM,
    summary_merge_user,
    summary_user,
    translate_user,
)

logger = logging.getLogger(__name__)

#: 中日韩统一表意文字：判断「这段原文是中文还是外文」只要这一条
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

TOOL_TRANSLATE = "translate"
TOOL_SUMMARY = "summary"

#: 一次送进模型的段落数上限（章翻译 / 章总结都按这个切块）
CHUNK_PARAGRAPHS = 8
#: 单块文本的字符预算，与 lesson.py 的口径一致
CHUNK_CHARS = 4000
#: 一段翻译最多送给模型的字符数（选中的原文可能很长）
MAX_TRANSLATE_CHARS = 3000
#: 章总结最多处理多少块，避免一本 175 页的章把模型调用打成几十次
MAX_SUMMARY_CHUNKS = 12
#: 总结/翻译的 token 预算：推理模型会把 reasoning 算进同一个额度（见 ask.ASK_MAX_TOKENS）
TOOL_MAX_TOKENS = 2000
TRANSLATE_MAX_TOKENS = 3000

FALLBACK_NOTICE = "（未接入大模型，无法翻译。下面是原文，请自行对照阅读。）"
MODEL_EMPTY_NOTICE = "（模型这次没有返回内容。下面是原文，请自行对照阅读。）"
RULE_SUMMARY_NOTICE = "（未接入大模型，以下是按段落首句抽取的规则摘要，不是模型写的总结。）"
SUMMARY_TRUNCATED_NOTICE = "（本章较长，总结基于前 {chunks} 块、共 {paragraphs} 段；后半章未纳入。）"


def resolve_target_language(text: str, requested: str = "") -> str:
    """译文语言：显式指定优先；否则「译成读者更可能看不懂的那一边」。

    中文教材译成英文、外文教材译成中文——用户点「翻译」想要的几乎总是这个方向，
    让他每次先选一遍语言是多余的一步。
    """
    if requested in ("zh", "en"):
        return requested
    sample = (text or "")[:400]
    cjk = len(_CJK_RE.findall(sample))
    return "en" if cjk >= max(4, len(sample) * 0.3) else "zh"


def paragraphs_of(sections: List[Dict[str, Any]], page: Optional[int] = None) -> List[Dict[str, Any]]:
    """可翻译/可总结的正文段落（标题、空段不算）。

    `page` 给出时只取那一页的段落——「翻译本页」是阅读时最常用的粒度：
    一整章几百段，逐段译完既慢又贵，而且没人会一口气读完。
    """
    out = []
    for s in sections:
        if s.get("kind") == "heading":
            continue
        text = (s.get("text") or "").strip()
        if not text:
            continue
        if page is not None and int(s.get("page") or 0) != int(page):
            continue
        out.append(s)
    return out


def chunks_of(paragraphs: List[Dict[str, Any]], size: int = CHUNK_PARAGRAPHS,
              budget: int = CHUNK_CHARS) -> List[List[Dict[str, Any]]]:
    """按段落数与字符预算切块。段落本身超预算时独占一块（不切开一段话）。"""
    chunks: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    used = 0
    for para in paragraphs:
        length = len(para.get("text") or "")
        if current and (len(current) >= size or used + length > budget):
            chunks.append(current)
            current, used = [], 0
        current.append(para)
        used += length
    if current:
        chunks.append(current)
    return chunks


def numbered_blocks(paragraphs: List[Dict[str, Any]], anchors: Dict[str, str]) -> Tuple[str, List[Dict[str, Any]]]:
    """段落 → 带编号的文本块 + 编号到锚点的对照表。

    编号从 1 开始，`[n]` 就是模型唯一被允许引用的东西；真实锚点 id 由我们查表补上。
    """
    lines = []
    mapping = []
    for index, para in enumerate(paragraphs, start=1):
        anchor_id = anchors.get(para["id"], "")
        if not anchor_id:
            continue
        mapping.append(
            {
                "index": index,
                "anchor_id": anchor_id,
                "page": para.get("page"),
                "chapter_id": para.get("chapter_id"),
                "text": (para.get("text") or "")[:400],
            }
        )
        body = (para.get("text") or "")[:400]
        lines.append(f"[{index}] {body}")
    return "\n".join(lines), mapping


def cited_anchors(answer: str, mapping: List[Dict[str, Any]], limit: int = 30) -> List[str]:
    """从总结正文里反查 `[n]` 的依据锚点（与问答同一口径：不信模型自报 id）。

    越界与重复都忽略；一条都没引用时退回前三条——**有依据总比没有强**，
    但顺序按段落顺序，不假装是模型选的。
    """
    by_index = {item["index"]: item["anchor_id"] for item in mapping}
    cited: List[str] = []
    for raw in re.findall(r"\[(\d{1,3})\]", answer or ""):
        anchor = by_index.get(int(raw))
        if anchor and anchor not in cited:
            cited.append(anchor)
    if not cited:
        cited = [item["anchor_id"] for item in mapping[:3]]
    return cited[:limit]


def source_details(mapping: List[Dict[str, Any]], chapter_title: str, current_chapter: str) -> List[Dict[str, Any]]:
    """依据的展示信息，形状与问答的 `sourceDetails` 一致（前端复用同一套按钮）。"""
    details = []
    for item in mapping:
        details.append(
            {
                "id": item["anchor_id"],
                "page": item.get("page"),
                "chapterId": item.get("chapter_id") or current_chapter,
                "chapterTitle": chapter_title,
                "text": item.get("text") or "",
                "crossChapter": (item.get("chapter_id") or current_chapter) != current_chapter,
            }
        )
    return details


# ---------------------------------------------------------------- 翻译


def stream_translate(
    db: Database,
    llm,
    book: Dict[str, Any],
    chapter: Dict[str, Any],
    sections: List[Dict[str, Any]],
    anchors: Dict[str, str],
    *,
    selected_text: str = "",
    anchor_id: str = "",
    page: Optional[int] = None,
    target: str = "",
) -> Iterator[Dict[str, Any]]:
    """逐段翻译（选中的原文 / 某一页的全部段落）。产出 meta|delta|done 事件。"""
    if selected_text.strip():
        targets = [
            {
                "id": anchor_id or "",
                "text": selected_text.strip()[:MAX_TRANSLATE_CHARS],
                "page": None,
                "chapter_id": chapter["id"],
            }
        ]
        scope = "selection"
    else:
        body = paragraphs_of(sections)
        # 没给页码时退到本章第一段所在页：总比把整章几百段一起送去翻译强
        if page is None and body:
            page = body[0].get("page")
        page_paragraphs = paragraphs_of(sections, page) if page is not None else body
        targets = [
            {
                "id": para["id"],
                "text": (para.get("text") or "")[:MAX_TRANSLATE_CHARS],
                "page": para.get("page"),
                "chapter_id": para.get("chapter_id") or chapter["id"],
            }
            for para in page_paragraphs
        ]
        scope = "page"

    if not targets:
        yield {
            "event": "done",
            "scope": scope,
            "target": resolve_target_language("", target),
            "translations": [],
            "notice": "这一页没有可翻译的正文段落。" if scope == "page" else "没有选中原文。",
        }
        return

    language = resolve_target_language(" ".join(t["text"] for t in targets), target)
    yield {
        "event": "meta",
        "scope": scope,
        "target": language,
        "page": page,
        "paragraphs": [
            {"anchorId": t["id"], "page": t["page"], "source": t["text"][:400]} for t in targets
        ],
    }

    translations: List[Dict[str, Any]] = []
    notice = ""
    for item in targets:
        text = item["text"]
        translated = ""
        if llm.kind == "cloud":
            try:
                for chunk in llm.chat_stream(
                    [
                        {"role": "system", "content": TRANSLATE_SYSTEM},
                        {
                            "role": "user",
                            "content": translate_user(text, language, context=chapter.get("title") or ""),
                        },
                    ],
                    temperature=0.2,
                    max_tokens=TRANSLATE_MAX_TOKENS,
                ):
                    if not chunk:
                        continue
                    translated += chunk
                    yield {"event": "delta", "anchorId": item["id"], "text": chunk}
            except (LLMError, KeyError, TypeError) as e:
                logger.warning("LLM 翻译失败: %s", e)
                translated = ""
        if not translated:
            notice = FALLBACK_NOTICE if llm.kind != "cloud" else MODEL_EMPTY_NOTICE
        translations.append(
            {"anchorId": item["id"], "page": item["page"], "source": text, "text": translated}
        )

    yield {
        "event": "done",
        "scope": scope,
        "target": language,
        "page": page,
        "translations": translations,
        "notice": notice,
    }


# ---------------------------------------------------------------- 总结


def stream_summarize(
    db: Database,
    llm,
    book: Dict[str, Any],
    chapter: Dict[str, Any],
    sections: List[Dict[str, Any]],
    anchors: Dict[str, str],
    *,
    selected_text: str = "",
    anchor_id: str = "",
) -> Iterator[Dict[str, Any]]:
    """总结本章（分块 → 合并）或选中的原文（一次调用）。"""
    chapter_anchors = {sid: aid for sid, aid in anchors.items()}
    if selected_text.strip():
        paragraphs = [
            {
                "id": anchor_id or "",
                "text": selected_text.strip()[:MAX_TRANSLATE_CHARS],
                "page": None,
                "chapter_id": chapter["id"],
            }
        ]
        scope = "selection"
    else:
        paragraphs = paragraphs_of(sections)
        scope = "chapter"

    if not paragraphs:
        yield {
            "event": "done",
            "scope": scope,
            "summary": "",
            "sources": [],
            "sourceDetails": [],
            "notice": "这一章没有可总结的正文段落。" if scope == "chapter" else "没有选中原文。",
        }
        return

    chunks = chunks_of(paragraphs)
    if scope == "chapter":
        chunks = chunks[:MAX_SUMMARY_CHUNKS]
    used_paragraphs = [p for chunk in chunks for p in chunk]
    numbered, mapping = numbered_blocks(used_paragraphs, chapter_anchors)
    truncated = scope == "chapter" and len(chunks_of(paragraphs)) > len(chunks)

    yield {
        "event": "meta",
        "scope": scope,
        "chunkCount": len(chunks),
        "paragraphCount": len(used_paragraphs),
        "totalParagraphs": len(paragraphs),
        "pages": _pages_of(used_paragraphs),
        "notice": SUMMARY_TRUNCATED_NOTICE.format(chunks=len(chunks), paragraphs=len(used_paragraphs))
        if truncated
        else "",
    }

    if llm.kind != "cloud":
        summary = rule_summary(used_paragraphs)
        for chunk in _chunk_text(summary):
            yield {"event": "delta", "text": chunk}
        yield _summary_result(
            db, book, chapter, scope, summary, mapping, RULE_SUMMARY_NOTICE, "rule"
        )
        return

    partials: List[str] = []
    try:
        for index, chunk in enumerate(chunks, start=1):
            yield {"event": "progress", "chunk": index, "chunkCount": len(chunks)}
            block_text, _ = numbered_blocks(chunk, chapter_anchors)
            if len(chunks) == 1:
                # 只有一块：直接流式输出，用户立刻看到正文（不必等合并那一步）
                buffer = ""
                for piece in llm.chat_stream(
                    [
                        {"role": "system", "content": SUMMARY_SYSTEM},
                        {"role": "user", "content": summary_user(chapter.get("title") or "", block_text)},
                    ],
                    temperature=0.3,
                    max_tokens=TOOL_MAX_TOKENS,
                ):
                    if not piece:
                        continue
                    buffer += piece
                    yield {"event": "delta", "text": piece}
                partials.append(buffer)
                continue
            partials.append(
                llm.chat(
                    [
                        {"role": "system", "content": SUMMARY_SYSTEM},
                        {"role": "user", "content": summary_user(chapter.get("title") or "", block_text, partial=True)},
                    ],
                    temperature=0.3,
                    max_tokens=TOOL_MAX_TOKENS,
                )
            )
    except (LLMError, KeyError, TypeError) as e:
        logger.warning("LLM 总结失败: %s", e)
        partials = []

    if not partials or not "".join(partials).strip():
        summary = rule_summary(used_paragraphs)
        for chunk in _chunk_text(summary):
            yield {"event": "delta", "text": chunk}
        # 模型没吐出东西时给出的规则摘要同样要落库并标明来源（model="rule"），
        # 否则「有没有缓存」和「这是谁写的」两件事在库里都对不上
        yield _summary_result(
            db, book, chapter, scope, summary, mapping, RULE_SUMMARY_NOTICE, "rule"
        )
        return

    if len(partials) == 1:
        summary = partials[0]
    else:
        summary = ""
        for piece in llm.chat_stream(
            [
                {"role": "system", "content": SUMMARY_MERGE_SYSTEM},
                {"role": "user", "content": summary_merge_user(chapter.get("title") or "", partials)},
            ],
            temperature=0.3,
            max_tokens=TOOL_MAX_TOKENS,
        ):
            if not piece:
                continue
            summary += piece
            yield {"event": "delta", "text": piece}
        if not summary.strip():
            summary = "\n".join(partials)

    yield _summary_result(db, book, chapter, scope, summary, mapping, "", llm.name)


def _summary_result(
    db: Database,
    book: Dict[str, Any],
    chapter: Dict[str, Any],
    scope: str,
    summary: str,
    mapping: List[Dict[str, Any]],
    notice: str,
    model: str,
) -> Dict[str, Any]:
    """收尾的统一出口：组装 done 事件，并把**章**总结落库缓存。

    抓在一处是有原因的：规则兜底与模型生成两条路都要缓存，写两遍必然漂移
    （第一版就漏了规则那条，于是无 Key 时每次重开章节都会重算一遍，
    而接口却告诉前端「缓存已就绪」）。选中段落的总结**不缓存**：它只对那一句话
    有意义，存下来会顶掉章总结的位置。
    """
    result = {
        "event": "done",
        "scope": scope,
        "summary": summary,
        "sources": cited_anchors(summary, mapping),
        "sourceDetails": source_details(mapping, chapter.get("title") or "", chapter["id"]),
        "notice": notice,
    }
    if scope == "chapter":
        db.upsert_tool_output(
            book["id"],
            chapter["id"],
            TOOL_SUMMARY,
            {
                "summary": summary,
                "sources": result["sources"],
                "sourceDetails": result["sourceDetails"],
                "model": model,
            },
            model,
        )
    return result


def cached_summary(db: Database, book: Dict[str, Any], chapter: Dict[str, Any]) -> Dict[str, Any]:
    """读回缓存的本章总结；没有就给一个空壳（前端据此决定是否自动生成）。"""
    cached = db.get_tool_output(book["id"], chapter["id"], TOOL_SUMMARY)
    if not cached:
        return {"summary": "", "sources": [], "sourceDetails": [], "cached": False}
    payload = cached["payload"]
    return {
        "summary": payload.get("summary", ""),
        "sources": payload.get("sources", []),
        "sourceDetails": payload.get("sourceDetails", []),
        "cached": True,
    }


def rule_summary(paragraphs: List[Dict[str, Any]], max_points: int = 6) -> str:
    """没有模型时的规则摘要：概述 + 每段首句。

    它当然不如模型写的，但**不是编的**——每一句都出自原文，且界面会标明这是规则结果。
    这比返回一段「看着像总结」的通用文字更诚实。
    """
    sentences: List[str] = []
    for para in paragraphs:
        text = (para.get("text") or "").strip()
        if not text:
            continue
        head = _first_sentence(text)
        if head:
            sentences.append(head)
        if len(sentences) >= max_points:
            break
    if not sentences:
        return ""
    overview = f"本章共 {len(paragraphs)} 段正文，以下按段落顺序列出各段首句。"
    return "\n".join([overview] + [f"- {s}" for s in sentences])


def _first_sentence(text: str, limit: int = 90) -> str:
    for mark in ("。", "！", "？", ".", ";", "；"):
        index = text.find(mark)
        if 0 < index <= limit:
            return text[: index + 1]
    return text[:limit] + ("…" if len(text) > limit else "")


def _pages_of(paragraphs: List[Dict[str, Any]]) -> List[int]:
    pages = sorted({int(p.get("page") or 0) for p in paragraphs if p.get("page")})
    return [p for p in pages if p]


def _chunk_text(text: str, size: int = 14) -> List[str]:
    """把已生成好的文本切片送出（仅用于规则兜底，让前端复用同一套追加逻辑）。"""
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]
