"""思维导图大纲/HTML 生成测试。"""
from pathlib import Path

from kb_agent.graph import build_concept_graph
from make_mindmap_preview import build_html, build_outline

_CONCEPTS = [
    {"id": "ch1-kp001", "concept": "张量", "definition": "多维数组", "prerequisites": [], "anchors": ["a1"]},
    {"id": "ch1-kp002", "concept": "张量形状", "definition": "各轴长度", "prerequisites": ["张量"], "anchors": ["a2"]},
    {"id": "ch2-kp001", "concept": "梯度下降", "definition": "迭代算法", "prerequisites": ["损失函数"], "anchors": ["b1"]},
]


def _graph() -> dict:
    return build_concept_graph(_CONCEPTS)


def test_outline_structure():
    titles = {"ch1": "数据操作", "ch2": "优化"}
    md = build_outline(_CONCEPTS, titles, unresolved=["损失函数", "GPU"])
    assert md.startswith("# 概念思维导图")
    assert "## 数据操作（ch1）" in md
    assert "### 张量" in md
    # 依赖少的排前：张量 应在 张量形状 之前
    assert md.index("### 张量\n") < md.index("### 张量形状")
    assert "未入库前置" in md and "损失函数" in md and "GPU" in md
    assert "教材依据" in md


def test_html_embeds_markdown_safely():
    md = build_outline(_CONCEPTS, {"ch1": "数据操作"}, unresolved=["损失函数"])
    html = build_html(md)
    assert "markmap-lib" in html
    assert "张量形状" in html
    assert "</script>" in html  # 结尾闭合正常
