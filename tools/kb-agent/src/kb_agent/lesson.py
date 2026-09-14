"""讲义生成（P4）：原文 + 知识点 → 前端契约的讲义 JSON。

为什么这样设计：AI_reader 前端 `SegmentText.jsx` 认识两种东西——
普通文本片段与「教材源码锚点片段」（{t:'src', id, v}，可点击回到原文高亮）。
因此讲义里的每个知识点都带锚点片段，前端天然就能「讲解 ↔ 原文」联动。

输出结构（与 frontend/src/data/books.js 的演示数据结构对齐）：
{
  "chapterId": "ch1",
  "heading": "数据操作",
  "intro": "…",
  "paragraphs": [{"anchor": "d2l-ch1-p001", "text": "…"}],
  "knowledgePoints": [
    {"id": "ch1-kp001", "kind": "card", "title": "张量",
     "body": [{"t":"text","v":"…定义…"}, {"t":"src","id":"d2l-ch1-p003","v":"…原文片段…","kind":"definition"}],
     "sourceId": "d2l-ch1-p003", "sourceLabel": "定位教材：张量 原文",
     "prerequisites": ["…"]}
  ],
  "outline": [{"index":"01","title":"张量","summary":"…","sourceId":"…"}]
}

知识点顺序：按前置依赖拓扑排序（前置先讲）；无法解析的前置按原顺序兜底（保证不丢、不死循环）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_QUOTE_LEN = 28

_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_MARKS_RE = re.compile(r"[*`_]{1,3}")


def _strip_md(text: str) -> str:
    """去掉 Markdown 装饰（粗体/斜体/行内代码/链接/方括号强调），保留公式本体。"""
    t = _MD_LINK_RE.sub(r"\1", str(text))
    t = _MD_MARKS_RE.sub("", t)
    t = t.replace("[", "").replace("]", "")
    return " ".join(t.split())


def _chapter_of(concept_id: str) -> str:
    return str(concept_id).split("-kp")[0]


def topo_order(concepts: list[dict]) -> list[dict]:
    """按 prerequisites 拓扑排序（稳定、可处理环与未知前置）。"""
    by_name = {str(c.get("concept", "")).strip(): c for c in concepts if str(c.get("concept", "")).strip()}
    emitted: list[dict] = []
    done: set[str] = set()
    pending = list(concepts)

    while pending:
        progressed = False
        for c in list(pending):
            name = str(c.get("concept", "")).strip()
            prereqs = [str(p).strip() for p in c.get("prerequisites", []) or []]
            # 前置要么已讲过，要么不在本批里（外部概念，不阻塞）
            if all(p in done or p not in by_name for p in prereqs):
                emitted.append(c)
                done.add(name)
                pending.remove(c)
                progressed = True
        if not progressed:  # 有环：按原顺序收尾，避免死循环
            emitted.extend(pending)
            break
    return emitted


def _src_segment(anchor: str, text: str, kind: str = "plain") -> dict:
    quote = _strip_md(text)[:_QUOTE_LEN]
    return {"t": "src", "id": anchor, "v": quote, "kind": kind}


def build_lesson(
    manifest: dict,
    chapter_id: str,
    concepts: list[dict] | None = None,
    include_paragraphs: int = 40,
) -> dict:
    """由 manifest + 概念列表组装某一章的讲义 JSON。"""
    chapter = next((c for c in manifest.get("chapters", []) if c["id"] == chapter_id), None)
    if chapter is None:
        raise KeyError(f"manifest 中不存在章节 {chapter_id}")

    paragraphs: list[dict] = []
    for part in chapter.get("parts", []):
        for p in part.get("paragraphs", []):
            paragraphs.append({"anchor": p["anchor"], "text": p["text"]})

    concept_items = [c for c in (concepts or []) if _chapter_of(c.get("id", "")) == chapter_id]
    ordered = topo_order(concept_items)

    knowledge_points: list[dict] = []
    outline: list[dict] = []
    for i, c in enumerate(ordered, start=1):
        anchors = [a for a in (c.get("anchors") or []) if any(p["anchor"] == a for p in paragraphs)]
        anchor = anchors[0] if anchors else ""
        quote_source = next((p["text"] for p in paragraphs if p["anchor"] == anchor), "")
        body: list[dict] = []
        if c.get("definition"):
            body.append({"t": "text", "v": _strip_md(c["definition"])})
        if c.get("example"):
            body.append({"t": "text", "v": f"例：{_strip_md(c['example'])}"})
        if anchor:
            body.append(_src_segment(anchor, quote_source or str(c.get("definition", "")), "definition"))
        knowledge_points.append(
            {
                "id": c.get("id") or f"{chapter_id}-kp{i:03d}",
                "kind": "card",
                "title": str(c.get("concept", "")).strip(),
                "body": body,
                "sourceId": anchor,
                "sourceLabel": f"定位教材：{str(c.get('concept', '')).strip()} 原文" if anchor else "",
                "prerequisites": [str(p) for p in c.get("prerequisites", []) or []],
            }
        )
        outline.append(
            {
                "index": f"{i:02d}",
                "title": str(c.get("concept", "")).strip(),
                "summary": _strip_md(c.get("definition", ""))[:40],
                "sourceId": anchor,
            }
        )

    title = chapter.get("title", chapter_id)
    intro = f"{title} · 本章 {len(paragraphs)} 段原文，{len(knowledge_points)} 个知识点（按前置依赖排序）。"
    return {
        "chapterId": chapter_id,
        "heading": title,
        "intro": intro,
        "paragraphs": paragraphs[:include_paragraphs],
        "knowledgePoints": knowledge_points,
        "outline": outline,
    }


def validate_lesson(payload: dict, valid_anchors: set[str]) -> list[str]:
    """校验讲义是否满足前端契约（返回问题列表，空列表=通过）。"""
    errors: list[str] = []
    for key in ("chapterId", "heading", "intro", "paragraphs", "knowledgePoints", "outline"):
        if key not in payload:
            errors.append(f"缺少字段 {key}")
    for kp in payload.get("knowledgePoints", []):
        for key in ("id", "kind", "title", "body", "sourceId"):
            if key not in kp:
                errors.append(f"知识点缺少字段 {key}: {kp.get('id')}")
        if kp.get("sourceId") and kp["sourceId"] not in valid_anchors:
            errors.append(f"知识点锚点不存在：{kp['sourceId']}")
        for seg in kp.get("body", []):
            if seg.get("t") == "src" and seg.get("id") not in valid_anchors:
                errors.append(f"正文片段锚点不存在：{seg.get('id')}")
    for i, item in enumerate(payload.get("outline", []), start=1):
        if item.get("index") != f"{i:02d}":
            errors.append(f"大纲序号不连续：{item.get('index')}")
        if item.get("sourceId") and item["sourceId"] not in valid_anchors:
            errors.append(f"大纲锚点不存在：{item['sourceId']}")
    return errors


def collect_anchors(manifest: dict) -> set[str]:
    return {p["anchor"] for ch in manifest.get("chapters", []) for part in ch.get("parts", []) for p in part.get("paragraphs", [])}


def build_all_lessons(manifest_path: str | Path, concepts_path: str | Path | None = None, out_dir: str | Path | None = None) -> dict:
    """为所有章节生成讲义 JSON，写 lessons/<chapter>.json + lessons/index.json。"""
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    concepts: list[dict] = []
    if concepts_path and Path(concepts_path).exists():
        data = json.loads(Path(concepts_path).read_text(encoding="utf-8"))
        concepts = data.get("concepts", data) if isinstance(data, dict) else data

    out_dir = Path(out_dir) if out_dir else manifest_path.parent / "lessons"
    out_dir.mkdir(parents=True, exist_ok=True)
    anchors = collect_anchors(manifest)

    index = {"book": manifest.get("book", {}).get("title", ""), "chapters": []}
    for ch in manifest.get("chapters", []):
        payload = build_lesson(manifest, ch["id"], concepts)
        errors = validate_lesson(payload, anchors)
        (out_dir / f"{ch['id']}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        index["chapters"].append(
            {
                "id": ch["id"],
                "title": payload["heading"],
                "knowledgePoints": len(payload["knowledgePoints"]),
                "errors": len(errors),
            }
        )
    (out_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index
