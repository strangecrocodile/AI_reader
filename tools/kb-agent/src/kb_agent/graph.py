"""概念关系图谱数据生成（V2.5，供前端知识图谱页消费）。

输入：V2 抽取的 concepts.json（concepts 列表）。
输出：graph.json
    nodes:   [{id, label, chapters, anchor_count, definition}]
             —— 概念名跨章合并去重（同名概念的章节/锚点累加）；
    edges:   [{source, target}]，语义：source 依赖 target（target 是前置概念）；
    unresolved: [前置概念名] —— 前置在本库找不到（可能来自未入库章节/表述差异），
             前端可渲染为“外部/虚线”节点。
"""
from __future__ import annotations

import json
from pathlib import Path

_STRIP = "《》「」\"'“” \t"


def _clean(name: str) -> str:
    return str(name).strip(_STRIP).strip()


def _chapter_of(concept_id: str) -> str:
    return str(concept_id).split("-kp")[0]


def build_concept_graph(concepts, out_path: str | Path | None = None) -> dict:
    """concepts 可为：concepts.json 路径 / {concepts:[...]} dict / 概念列表。"""
    if isinstance(concepts, (str, Path)):
        data = json.loads(Path(concepts).read_text(encoding="utf-8"))
        items = data.get("concepts", data) if isinstance(data, dict) else data
    elif isinstance(concepts, dict):
        items = concepts.get("concepts", [])
    else:
        items = concepts
    if not isinstance(items, list):
        raise ValueError("concepts 必须是概念列表")

    # 第一遍：按清洗后的概念名建节点（大小写/空白归一匹配）
    node_map: dict[str, dict] = {}
    for c in items:
        name = _clean(c.get("concept", ""))
        if not name:
            continue
        key = name.lower()
        node = node_map.get(key)
        if node is None:
            node = {
                "id": name,
                "label": name,
                "definition": str(c.get("definition", "")).strip()[:300],
                "chapters": set(),
                "anchor_count": 0,
            }
            node_map[key] = node
        chapter = _chapter_of(str(c.get("id", "")))
        if chapter:
            node["chapters"].add(chapter)
        node["anchor_count"] += len(c.get("anchors", []) or [])

    # 第二遍：建边（概念 → 前置概念）并收集未解析前置
    edge_set: set[tuple[str, str]] = set()
    unresolved: set[str] = set()
    for c in items:
        name = _clean(c.get("concept", ""))
        if not name:
            continue
        key = name.lower()
        for raw_p in c.get("prerequisites", []) or []:
            p = _clean(raw_p)
            if not p:
                continue
            pk = p.lower()
            if pk in node_map:
                edge_set.add((node_map[key]["id"], node_map[pk]["id"]))
            else:
                unresolved.add(p)

    nodes = [
        {
            "id": n["id"],
            "label": n["label"],
            "definition": n["definition"],
            "chapters": sorted(n["chapters"]),
            "anchor_count": n["anchor_count"],
        }
        for _, n in sorted(node_map.items())
    ]
    edges = [{"source": s, "target": t} for s, t in sorted(edge_set)]
    unresolved_list = sorted(unresolved)
    result = {
        "meta": {"nodes": len(nodes), "edges": len(edges), "unresolved": len(unresolved_list)},
        "nodes": nodes,
        "edges": edges,
        "unresolved": unresolved_list,
    }
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["out_path"] = str(out_path)
    return result
