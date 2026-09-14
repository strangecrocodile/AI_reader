"""知识点抽取（V2·concept 层）。

目标：把每一章原文提炼成结构化“知识点”，供讲义排序与知识图谱使用：

    {concept, definition, prerequisites[], example?, anchors[]}

- anchors 只能引用该章内真实存在的段落锚点（可回链教材原文）；
- 首选 LLM（DeepSeek）结构化抽取；LLM 不可用/输出非法 JSON 时，
  自动退回“规则抽取”（确定性、离线可测），保证流程永远能跑通；
- 产物：concepts.json（含 method: llm|rule 标记）。

规则抽取说明（回退方案，质量有限）：
用强标记词（是指/称为/定义为/含义是…）定位“定义句”，
概念名取句子开头一小段，锚点取定义句所在段落。正式质量依赖 LLM 路径。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config_env import ensure_env
from .llm_chat import build_chat_llm

#: 每章送入 LLM 的正文上限（字符），防止超长章节爆上下文
PER_CHAPTER_CHARS = 8000

_STRONG_KW = re.compile(r"(是指|指的是|称为|叫作|被称为|定义为|定义是|含义是|的意思是|表示的是)")
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

_SYSTEM = (
    "你是教材知识点分析器。只依据用户提供的教材段落抽取“真正的知识点”"
    "（定义、概念、算法、方法、重要性质），不要抽取叙述/过渡句、例子细节、代码片段。\n"
    "要求：concept 是简短名词短语（中文≤16字），例如『线性回归』『张量』『自动微分』；"
    "definition 用一句话讲清含义；prerequisites 填该概念依赖的前置概念名数组（没有则空）；"
    "example 是教材中体现它的简短例子，可空；anchors 是依据的段落锚点（可多个）。\n"
    "输出严格 JSON 数组，每章不超过 12 条；不要输出 JSON 以外的文字。"
)

#: 明显是叙述/过渡句开头的“伪概念名”，直接滤掉
_SKIP_STARTS = (
    "首先", "其次", "如果", "我们", "这里", "下面", "因此", "其中", "对于",
    "在", "当", "例如", "另外", "注意", "也就是说", "最后", "然后", "需要", "假设",
)


def _load_chapter_rows(manifest: dict) -> list[dict]:
    """把 manifest 章节展开为 {chapter_id, chapter_title, paragraphs:[{anchor,text}]}。"""
    out = []
    for ch in manifest.get("chapters", []):
        paras = []
        for part in ch.get("parts", []):
            paras.extend(part.get("paragraphs", []))
        out.append({"chapter_id": ch["id"], "chapter_title": ch["title"], "paragraphs": paras})
    return out


def _text_with_anchors(paragraphs: list[dict], limit: int = PER_CHAPTER_CHARS) -> str:
    parts = []
    used = 0
    for p in paragraphs:
        line = f"[{p['anchor']}] {p['text']}"
        used += len(line)
        if used > limit:
            break
        parts.append(line)
    return "\n".join(parts)


def _parse_json_array(raw: str) -> list[dict]:
    """尽力从 LLM 输出中解析 JSON 数组（容错代码围栏/前后杂文）。"""
    text = raw.strip()
    m = _JSON_FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        raise ValueError("找不到 JSON 数组")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("不是数组")
    return [d for d in data if isinstance(d, dict)]


def _normalize_concepts(concepts: list[dict], valid_anchors: set[str], chapter_id: str) -> list[dict]:
    """清洗：滤叙述伪概念、只保留合法锚点、补默认字段、按概念名去重。"""
    out = []
    seen: set[str] = set()
    for c in concepts:
        name = str(c.get("concept") or "").strip()[:40]
        definition = str(c.get("definition") or "").strip()[:500]
        if not name or not definition:
            continue
        if len(name) > 24 or name.startswith(_SKIP_STARTS):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        anchors = [a for a in c.get("anchors", []) if str(a) in valid_anchors][:6]
        prereq = [str(p).strip()[:40] for p in c.get("prerequisites", []) if str(p).strip()][:10]
        out.append(
            {
                "id": f"{chapter_id}-kp{len(out) + 1:03d}",
                "concept": name,
                "definition": definition,
                "prerequisites": prereq,
                "example": str(c.get("example") or "").strip()[:300] or "",
                "anchors": anchors,
            }
        )
    return out


def rule_extract(paragraphs: list[dict]) -> list[dict]:
    """规则回退：用强标记词找“定义句”，锚点取该句所在段落（确定性、可测）。"""
    valid = {p["anchor"] for p in paragraphs}
    concepts: list[dict] = []
    for p in paragraphs:
        m = _STRONG_KW.search(p["text"])
        if not m:
            continue
        seg = p["text"][max(0, m.start() - 40) : m.end() + 160].strip()
        name = p["text"][:14].strip("，。；: ：\t#")
        if not name:
            continue
        concepts.append(
            {
                "concept": name,
                "definition": seg,
                "prerequisites": [],
                "example": "",
                "anchors": [p["anchor"]] if p["anchor"] in valid else [],
            }
        )
    return concepts


def extract_from_manifest(manifest_path: str | Path, out_path: str | Path | None = None, llm=None) -> dict:
    """对每章抽取知识点；llm 缺省时按 .env 自动构建（无 key 走规则）。

    返回 {concepts:[...], chapters, method, out_path}。
    """
    ensure_env()
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    chapter_rows = _load_chapter_rows(manifest)
    if llm is None:
        llm = build_chat_llm()

    all_concepts: list[dict] = []
    methods: set[str] = set()

    for ch in chapter_rows:
        paragraphs = ch["paragraphs"]
        valid = {p["anchor"] for p in paragraphs}
        if not paragraphs:
            continue
        handled = False
        if llm is not None:
            # 材料过长时模型容易返回不可用结果：先全量，再缩小材料重试一次
            for limit in (PER_CHAPTER_CHARS, max(2000, PER_CHAPTER_CHARS // 2)):
                material = _text_with_anchors(paragraphs, limit)
                user = f"请抽取「{ch['chapter_title']}」的知识点。教材段落：\n{material}"
                try:
                    raw = llm.complete([{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}])
                    concepts = _normalize_concepts(_parse_json_array(raw), valid, ch["chapter_id"])
                except Exception:  # noqa: BLE001 —— 该轮输出非法则作废
                    concepts = []
                if concepts:
                    methods.add("llm")
                    all_concepts.extend(concepts)
                    handled = True
                    break
        if handled:
            continue
        methods.add("rule")
        rule = rule_extract(paragraphs)
        for c in rule:
            c["id"] = f"{ch['chapter_id']}-kp{rule.index(c)+1:03d}"
        all_concepts.extend(rule)

    result = {
        "book": manifest.get("book", {}).get("title", ""),
        "chapters": len(chapter_rows),
        "concepts": all_concepts,
        "methods": sorted(methods),
    }
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["out_path"] = str(out_path)
    return result
