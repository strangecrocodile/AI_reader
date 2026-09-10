"""概念图谱数据生成测试：合并去重、边方向、未解析前置。"""
import json
from pathlib import Path

from kb_agent.graph import build_concept_graph

_CONCEPTS = [
    {"id": "ch1-kp001", "concept": "张量", "definition": "多维数组", "prerequisites": [], "anchors": ["a1"]},
    {"id": "ch1-kp002", "concept": "张量形状", "definition": "各轴长度", "prerequisites": ["张量"], "anchors": ["a2"]},
    {"id": "ch1-kp003", "concept": " 张量 ", "definition": "别名/重复出现", "prerequisites": [], "anchors": ["a9"]},  # 去重合并
    {"id": "ch2-kp001", "concept": "梯度下降", "definition": "迭代算法", "prerequisites": ["损失函数", "未入库前置"], "anchors": ["b1"]},
]


def test_graph_structure(tmp_path: Path):
    out = tmp_path / "graph.json"
    g = build_concept_graph(_CONCEPTS, out_path=out)
    ids = [n["id"] for n in g["nodes"]]
    assert ids == sorted(ids)
    # “张量”合并两次出现：锚点累加 1+1、章节合并
    tensor = next(n for n in g["nodes"] if n["id"] == "张量")
    assert tensor["anchor_count"] == 2
    assert sorted(tensor["chapters"]) == ["ch1"]

    assert {"source": "张量形状", "target": "张量"} in g["edges"]
    # “损失函数”“未入库前置”都不是已抽概念 → 不产生假边，进 unresolved
    assert not any(e["target"] in ("损失函数", "未入库前置") for e in g["edges"])
    assert "损失函数" in g["unresolved"] and "未入库前置" in g["unresolved"]
    assert g["meta"]["nodes"] == 3 and g["meta"]["unresolved"] == 2
    assert Path(out).exists()


def test_graph_from_file(tmp_path: Path):
    p = tmp_path / "concepts.json"
    p.write_text(json.dumps({"concepts": _CONCEPTS}, ensure_ascii=False), encoding="utf-8")
    g = build_concept_graph(p)
    assert g["meta"]["nodes"] == 3
