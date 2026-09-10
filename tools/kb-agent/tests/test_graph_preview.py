"""图谱预览 HTML 生成测试。"""
from pathlib import Path

from kb_agent.graph import build_concept_graph
from make_graph_preview import build_preview_html

_CONCEPTS = [
    {"id": "ch1-kp001", "concept": "张量", "definition": "多维数组", "prerequisites": [], "anchors": ["a1"]},
    {"id": "ch1-kp002", "concept": "张量形状", "definition": "各轴长度", "prerequisites": ["张量"], "anchors": ["a2"]},
]


def test_build_preview_html(tmp_path: Path):
    g = build_concept_graph(_CONCEPTS, out_path=tmp_path / "graph.json")
    html = build_preview_html(g)
    assert "<!doctype html>" in html
    assert "cytoscape" in html
    assert "张量形状" in html          # 数据内嵌
    assert '"/" === 无' not in html     # 未解析无特殊字符问题
    assert "</script>" in html          # 标签闭合正常


def test_graph_roundtrip_no_script_break():
    g = {
        "meta": {"nodes": 1, "edges": 0, "unresolved": 0},
        "nodes": [{"id": "x", "label": "a</script>恶意", "chapters": [], "anchor_count": 0, "definition": ""}],
        "edges": [],
        "unresolved": [],
    }
    html = build_preview_html(g)
    # 数据中的 </script 被转义，不会提前闭合脚本
    assert "a<\\/script>" in html
