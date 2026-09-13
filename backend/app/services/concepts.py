"""知识点抽取与概念图谱（V2 concept 层）。

契约与 `tools/kb-agent` 的 `extract.py` / `graph.py` 对齐（该组件依赖 LangChain 等
重型依赖、独立虚拟环境，后端这里自研轻量实现，不引入它的依赖）：

    概念：{id, concept, definition, prerequisites[], example, anchors[]}
    - anchors 只能引用本章真实存在的锚点 id，保证可回跳教材原文；
    - 首选 LLM（DeepSeek）结构化抽取；LLM 不可用或输出非法 JSON 时，
      自动回退「规则抽取」（确定性、离线可测），保证流程永远能跑通。

建图（`build_concept_graph`）：
    - 节点 = 概念名跨章合并去重（同名概念的章节、锚点、掌握度累加）；
    - 边 = prerequisites → 「前置」边（source 依赖 target）为主；
          同章相邻概念补「学习顺序」边作为离线兜底（已有前置边则不再补）；
    - unresolved = 前置概念在本教材里找不到，前端可渲染成外部节点。
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from ..db import Database
from ..llm.client import LLMError, extract_json_array
from ..llm.prompts import CONCEPT_SYSTEM, concept_user

logger = logging.getLogger(__name__)

#: 每章最多保留的知识点数（与 kb-agent 的「每章不超过 12 条」一致）
MAX_CONCEPTS_PER_CHAPTER = 12
#: 每章送入 LLM 的正文字符上限，防止超长章节爆上下文
PER_CHAPTER_CHARS = 8000
MAX_NAME_LEN = 16
MAX_TEXT_LEN = 300
MAX_ANCHORS_PER_CONCEPT = 6
MAX_PREREQUISITES = 10
#: 短于该长度的段落不参与规则抽取（不足以承载一个定义）
MIN_PARAGRAPH_LEN = 8

_STRONG_KW = re.compile(
    r"(是指|指的是|称为|叫作|叫做|被称为|就称|定义为|定义是|含义是|的意思是|表示的是)"
)
#: 明显是叙述/过渡句开头的「伪概念名」
_SKIP_STARTS = (
    "首先", "其次", "如果", "我们", "这里", "下面", "因此", "其中", "对于",
    "在", "当", "例如", "另外", "注意", "也就是说", "最后", "然后", "需要", "假设",
)
#: 概念名里常见的填充前缀，规则抽取时剥掉
_FILLER_PREFIXES = ("这个", "一个", "两个", "某个", "其", "该", "所谓")
_SENTENCE_END = "。！？；\n"
#: 截断概念名的标点（不含括号：定义句里常出现 f(x)、x₀ 这类括注）
_NAME_END = "，。、；：,;:!?"
_CJK = re.compile(r"[\u4e00-\u9fff]")
_MULTI_SPACE = re.compile(r"\s{2,}")
_CJK_SPACE = re.compile(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])")

_STATUS_RANK = {"planned": 0, "learning": 1, "learned": 2}


def paragraphs_of(sections: List[Dict], anchors: List[Dict]) -> List[Dict[str, str]]:
    """构造 [{anchor, text}]：只取带锚点的正文段落（跳过标题与公式）。"""
    kinds = {s["id"]: s.get("kind", "p") for s in sections}
    out: List[Dict[str, str]] = []
    for anchor in anchors:
        if kinds.get(anchor["section_id"], "p") in ("heading", "formula"):
            continue
        text = (anchor.get("text") or "").strip()
        if len(text) < MIN_PARAGRAPH_LEN:
            continue
        out.append({"anchor": anchor["id"], "text": text})
    return out


def extract_concepts(
    db: Database,
    llm,
    chapter: Dict[str, Any],
    sections: List[Dict],
    anchors: List[Dict],
) -> Dict[str, Any]:
    """获取（或抽取并缓存）本章知识点，返回 {method, concepts, model}。"""
    cached = db.get_concepts(chapter["book_id"], chapter["id"])
    if cached:
        return cached["payload"]

    paragraphs = paragraphs_of(sections, anchors)
    valid_ids = {a["id"] for a in anchors}
    payload = _llm_extract(llm, chapter, paragraphs, anchors, valid_ids)
    if payload is None:
        payload = {
            "method": "rule",
            "concepts": rule_extract(paragraphs, chapter["id"]),
        }
    payload["model"] = getattr(llm, "name", "")
    db.upsert_concepts(chapter["book_id"], chapter["id"], payload, payload["model"])
    return payload


def _llm_extract(llm, chapter, paragraphs, anchors, valid_ids) -> Optional[Dict[str, Any]]:
    """LLM 结构化抽取；不可用、输出非法或结果为空时返回 None（交由规则回退）。"""
    if getattr(llm, "kind", "mock") != "cloud" or not paragraphs:
        return None
    try:
        raw = llm.chat(
            [
                {"role": "system", "content": CONCEPT_SYSTEM},
                {
                    "role": "user",
                    "content": concept_user(chapter["title"], _material(paragraphs), anchors),
                },
            ],
            temperature=0.2,
            max_tokens=2000,
        )
        concepts = normalize_concepts(extract_json_array(raw), valid_ids, chapter["id"])
    except (LLMError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.warning("LLM 知识点抽取失败，回退规则抽取: %s", e)
        return None
    if not concepts:
        return None
    return {"method": "llm", "concepts": concepts}


def _material(paragraphs: List[Dict[str, str]], limit: int = PER_CHAPTER_CHARS) -> str:
    parts: List[str] = []
    used = 0
    for p in paragraphs:
        line = f"[{p['anchor']}] {p['text']}"
        used += len(line)
        if used > limit:
            break
        parts.append(line)
    return "\n".join(parts)


def normalize_concepts(raw: List[Dict], valid_ids: set, chapter_id: str) -> List[Dict[str, Any]]:
    """清洗 LLM 抽取结果：滤伪概念、只留合法锚点、按名去重、限条数。"""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for item in raw:
        name = clean_name(item.get("concept"))
        definition = str(item.get("definition") or "").strip()[:MAX_TEXT_LEN]
        if not name or not definition:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        anchors = [
            str(a) for a in (item.get("anchors") or []) if str(a) in valid_ids
        ][:MAX_ANCHORS_PER_CONCEPT]

        prerequisites: List[str] = []
        for raw_p in item.get("prerequisites") or []:
            p_name = clean_name(raw_p)
            if not p_name or p_name.lower() == key:
                continue
            if p_name.lower() in {p.lower() for p in prerequisites}:
                continue
            prerequisites.append(p_name)
        out.append(
            {
                "id": f"{chapter_id}-kp{len(out) + 1:03d}",
                "concept": name,
                "definition": definition,
                "prerequisites": prerequisites[:MAX_PREREQUISITES],
                "example": str(item.get("example") or "").strip()[:MAX_TEXT_LEN],
                "anchors": anchors,
            }
        )
        if len(out) >= MAX_CONCEPTS_PER_CHAPTER:
            break
    return out


def clean_name(value: Any) -> str:
    """规整概念名：去空白与书名号引号，过长、像叙述句或碎片的一律丢弃。"""
    name = str(value or "").strip().strip("《》「」\"'“” \t")
    if not 2 <= len(name) <= MAX_NAME_LEN:
        return ""
    if name.startswith(_SKIP_STARTS):
        return ""
    # 中文名至少两个汉字（挡掉「A 为 f」这类切碎的外文片段）；纯外文名按长度判定
    cjk_count = len(_CJK.findall(name))
    if cjk_count == 1 or (cjk_count == 0 and len(name) < 3):
        return ""
    return name


def _tidy(text: str) -> str:
    """压缩 PDF 提取带来的多余空格（中文之间不留空格）。"""
    return _CJK_SPACE.sub("", _MULTI_SPACE.sub(" ", text)).strip()


def rule_extract(paragraphs: List[Dict[str, str]], chapter_id: str) -> List[Dict[str, Any]]:
    """规则回退：用强标记词定位定义句，概念名取标记词附近的名词短语。

    确定性、离线可测；质量低于 LLM 路径，仅用于无 Key / 模型异常时的兜底。
    """
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for p in paragraphs:
        text = p["text"]
        match = _STRONG_KW.search(text)
        if not match:
            continue
        name = _rule_name(text, match)
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append(
            {
                "id": f"{chapter_id}-kp{len(out) + 1:03d}",
                "concept": name,
                "definition": _tidy(_sentence_at(text, match.start())),
                "prerequisites": [],
                "example": "",
                "anchors": [p["anchor"]],
            }
        )
        if len(out) >= MAX_CONCEPTS_PER_CHAPTER:
            break
    return out


def _rule_name(text: str, match: re.Match) -> str:
    """从「……称为 X 的 Y」这类定义句里取概念名（尽量取中心词）。"""
    candidate = _strip_filler(_first_clause(_tidy(text[match.end():])))
    if "的" in candidate:
        tail = _strip_filler(_first_clause(candidate.rsplit("的", 1)[1]))
        if 2 <= len(tail) <= MAX_NAME_LEN:
            candidate = tail
    return clean_name(_strip_filler(candidate))


def _strip_filler(text: str) -> str:
    for prefix in _FILLER_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix):]
    return text


def _first_clause(text: str) -> str:
    for i, ch in enumerate(text):
        if ch in _NAME_END:
            return text[:i].strip()
    return text.strip()


def _sentence_at(text: str, position: int, limit: int = 120) -> str:
    """取包含 position 的整句；句子过长时退化为标记词附近的窗口。"""
    start = position
    while start > 0 and text[start - 1] not in _SENTENCE_END:
        start -= 1
    end = position
    while end < len(text) and text[end] not in _SENTENCE_END:
        end += 1
    sentence = text[start:end + 1].strip()
    if len(sentence) > limit:
        sentence = text[max(0, position - 40): position + limit].strip()
    return sentence[:MAX_TEXT_LEN]


def build_concept_graph(
    chapter_concepts: List[Dict[str, Any]],
    progress_by_chapter: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """把各章概念合并成图谱节点、语义关系与未解析前置。

    chapter_concepts: [{chapter_id, chapter_title, method, concepts:[...]}]
    """
    progress = progress_by_chapter or {}
    nodes: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    methods: set = set()

    for block in chapter_concepts:
        chapter_id = block.get("chapter_id", "")
        chapter_title = block.get("chapter_title", "")
        methods.add(block.get("method", "rule"))
        row = progress.get(chapter_id) or {}
        status = row.get("status", "planned")
        mastery = float(row.get("mastery") or 0)

        for concept in block.get("concepts", []):
            name = concept.get("concept") or ""
            if not name:
                continue
            key = name.lower()
            node = nodes.get(key)
            if node is None:
                anchors = list(concept.get("anchors") or [])
                node = {
                    "id": name,
                    "title": name,
                    "label": name,
                    "definition": concept.get("definition", ""),
                    "summary": concept.get("definition", ""),
                    "example": concept.get("example", ""),
                    "prerequisites": [],
                    "chapterId": chapter_id,
                    "chapterTitle": chapter_title,
                    "sourceId": anchors[0] if anchors else None,
                    "sourceLabel": "定位教材：原文",
                    "chapters": [],
                    "anchors": [],
                    "anchorCount": 0,
                    "method": block.get("method", "rule"),
                    "status": status,
                    "mastery": mastery,
                }
                nodes[key] = node
                order.append(key)

            if chapter_id and chapter_id not in node["chapters"]:
                node["chapters"].append(chapter_id)
            for anchor in concept.get("anchors") or []:
                if anchor not in node["anchors"]:
                    node["anchors"].append(anchor)
            node["anchorCount"] = len(node["anchors"])
            if not node["sourceId"] and concept.get("anchors"):
                node["sourceId"] = concept["anchors"][0]
                node["chapterId"] = chapter_id
                node["chapterTitle"] = chapter_title
            for prerequisite in concept.get("prerequisites") or []:
                if prerequisite.lower() != key and prerequisite not in node["prerequisites"]:
                    node["prerequisites"].append(prerequisite)
            if _STATUS_RANK.get(status, 0) > _STATUS_RANK.get(node["status"], 0):
                node["status"] = status
            node["mastery"] = max(node["mastery"], mastery)
            if block.get("method") == "llm":
                node["method"] = "llm"

    relations: List[Dict[str, Any]] = []
    seen_edges: set = set()
    unresolved: Dict[str, set] = {}

    # 1) 语义边：概念 → 它的前置概念
    for key in order:
        node = nodes[key]
        for prerequisite in node["prerequisites"]:
            p_key = prerequisite.lower()
            if p_key in nodes:
                if (key, p_key) in seen_edges:
                    continue
                seen_edges.add((key, p_key))
                relations.append(
                    {
                        "id": f"{node['id']}->{nodes[p_key]['id']}",
                        "source": node["id"],
                        "target": nodes[p_key]["id"],
                        "type": "prerequisite",
                        "label": "前置",
                    }
                )
            else:
                unresolved.setdefault(prerequisite, set()).add(node["id"])

    # 2) 离线兜底：同章相邻概念补「学习顺序」边（与已有前置边不重复）
    for block in chapter_concepts:
        concepts = [c.get("concept") or "" for c in block.get("concepts", [])]
        for previous, current in zip(concepts, concepts[1:]):
            a, b = previous.lower(), current.lower()
            if not a or not b or a == b:
                continue
            if a not in nodes or b not in nodes:
                continue
            if (a, b) in seen_edges or (b, a) in seen_edges:
                continue
            seen_edges.add((a, b))
            relations.append(
                {
                    "id": f"{nodes[a]['id']}->{nodes[b]['id']}",
                    "source": nodes[a]["id"],
                    "target": nodes[b]["id"],
                    "type": "sequence",
                    "label": "学习顺序",
                }
            )

    unresolved_list = [
        {"name": name, "requiredBy": sorted(required_by)}
        for name, required_by in sorted(unresolved.items())
    ]
    concept_list = [nodes[key] for key in order]
    return {
        "concepts": concept_list,
        "relations": relations,
        "unresolved": unresolved_list,
        "methods": sorted(methods),
        "stats": {
            "conceptCount": len(concept_list),
            "learnedCount": sum(1 for c in concept_list if c["status"] != "planned"),
            "relationCount": len(relations),
            "prerequisiteCount": sum(1 for r in relations if r["type"] == "prerequisite"),
            "unresolvedCount": len(unresolved_list),
        },
    }
