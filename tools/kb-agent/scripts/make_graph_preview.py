"""生成“知识图谱预览”HTML（内嵌 graph.json 数据，双击即可打开）。

用法：
    python scripts/make_graph_preview.py <graph.json> [输出.html]
默认输出到与输入同目录的 graph-preview.html。

页面基于 Cytoscape.js（CDN 加载），节点可拖拽/缩放/点击查看详情；
预览仅供演示，正式页面由小组前端实现。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>kb-agent · 概念知识图谱预览</title>
<style>
  html, body { margin: 0; height: 100%; font-family: "Microsoft YaHei", sans-serif; }
  header { padding: 10px 16px; background: #f6f8fa; border-bottom: 1px solid #e1e4e8; }
  header h1 { margin: 0; font-size: 18px; }
  header .stats { color: #57606a; font-size: 13px; margin-top: 4px; }
  #wrap { display: flex; height: calc(100% - 76px); }
  #cy { flex: 1; }
  #side { width: 300px; border-left: 1px solid #e1e4e8; overflow: auto; padding: 12px; font-size: 13px; }
  #side h3 { margin: 6px 0; }
  .kv { color: #57606a; }
  #unresolved { margin-top: 16px; }
</style>
</head>
<body>
<header>
  <h1>概念知识图谱预览（kb-agent 产物）</h1>
  <div class="stats" id="stats">加载中…</div>
</header>
<div id="wrap">
  <div id="cy"></div>
  <div id="side">
    <h3>节点详情</h3>
    <div id="info">点击左侧任意节点查看详情。</div>
    <div id="unresolved"></div>
  </div>
</div>
<script src="https://unpkg.com/cytoscape@3.29.2/dist/cytoscape.min.js"></script>
<script>
const DATA = __DATA__;
const meta = DATA.meta || { nodes: 0, edges: 0, unresolved: 0 };
document.getElementById('stats').textContent =
  `共 ${meta.nodes} 个概念节点 · ${meta.edges} 条前置依赖边 · 未解析前置 ${meta.unresolved} 个`;

const elements = [];
for (const n of DATA.nodes) {
  const size = 20 + Math.min(30, Math.sqrt(n.anchor_count || 1) * 8);
  elements.push({ data: { id: n.id, label: n.label, definition: n.definition || '',
                           chapters: (n.chapters || []).join('、'), anchors: n.anchor_count || 0 }, style: { width: size, height: size } });
}
for (const e of DATA.edges) {
  elements.push({ data: { id: e.source + '>' + e.target, source: e.source, target: e.target, label: '' } });
}

const cy = cytoscape({
  container: document.getElementById('cy'),
  elements,
  layout: { name: 'cose', animate: false, nodeRepulsion: 8000, idealEdgeLength: 90 },
  style: [
    { selector: 'node', style: { 'label': 'data(label)', 'text-valign': 'center', 'text-halign': 'center',
                                 'background-color': '#4c8bf5', 'color': '#fff', 'font-size': 11,
                                 'text-wrap': 'ellipsis', 'text-max-width': 120, 'overlay-opacity': 0 } },
    { selector: 'edge', style: { 'width': 1.5, 'line-color': '#a9b7c6', 'target-arrow-color': '#a9b7c6',
                                  'target-arrow-shape': 'triangle', 'curve-style': 'bezier' } },
    { selector: ':selected', style: { 'background-color': '#e36209' } }
  ],
  wheelSensitivity: 0.2
});

cy.on('tap', 'node', (evt) => {
  const n = evt.target;
  document.getElementById('info').innerHTML =
    `<h3>${n.data('label')}</h3>
     <div class="kv">章节：${n.data('chapters') || '—'}<br>锚点引用数：${n.data('anchors')}</div>
     <p>${n.data('definition') || '（无定义）'}</p>
     <div class="kv">相邻概念：${cy.elements().neighborhood(n).nodes().map(x => x.data('label')).slice(0, 12).join('、') || '—'}</div>`;
});

const un = DATA.unresolved || [];
if (un.length) {
  document.getElementById('unresolved').innerHTML =
    `<h3>未入库前置概念（${un.length}）</h3><div class="kv">${un.join('、')}</div>`;
} else {
  document.getElementById('unresolved').innerHTML = '<h3>未入库前置概念</h3><div class="kv">无</div>';
}
</script>
</body>
</html>
"""


def build_preview_html(graph: dict) -> str:
    """把图谱 dict 渲染成完整 HTML 字符串。"""
    # 防止 JSON 中 '</script' 提前闭合脚本标签
    data = json.dumps(graph, ensure_ascii=False).replace("</", "<\\/")
    return _HTML_TEMPLATE.replace("__DATA__", data)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("用法：python make_graph_preview.py <graph.json> [输出.html]")
        return 1
    src = Path(argv[1])
    out = Path(argv[2]) if len(argv) > 2 else src.with_name("graph-preview.html")
    graph = json.loads(src.read_text(encoding="utf-8"))
    out.write_text(build_preview_html(graph), encoding="utf-8")
    print(f"已生成预览：{out}（双击用浏览器打开）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
