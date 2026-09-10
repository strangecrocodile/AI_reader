"""思维导图预览生成（现成方案：markmap，Markdown → 交互式思维导图）。

输入：graph.json（或 concepts.json）+ 可选 manifest.json（取章节标题）。
输出：
  1) mindmap.md    —— 层级 Markdown 大纲（任何思维导图工具/在线 REPL 可直接用）；
  2) mindmap.html  —— 内嵌大纲 + markmap（CDN ESM），经本地 http 打开即为思维导图。

大纲结构（自动、确定性）：
    # 书名
    ## 章节（依赖最少的概念排前）
    ### 概念名 — 定义摘要（锚点 N 处）
    ## 未入库前置（提示待补章节）

说明：要“更聪明”的层级可由 DeepSeek 直接生成 Markdown 大纲，本工具先给确定版。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>概念思维导图 · kb-agent</title>
<style>
  html, body { margin: 0; height: 100%; overflow: hidden; font-family: sans-serif; }
  #mm { width: 100vw; height: 100vh; display: block; }
</style>
</head>
<body>
<svg id="mm"></svg>
<script type="text/template" id="src">__MD__</script>
<script type="module">
  import { Transformer } from 'https://esm.sh/markmap-lib@0.18.10';
  import { Markmap } from 'https://esm.sh/markmap-view@0.18.10';
  const md = document.getElementById('src').textContent;
  const { root } = new Transformer().transform(md);
  Markmap.create('#mm', { autoFit: true }, root);
</script>
</body>
</html>
"""


def _short(text: str, n: int = 90) -> str:
    t = " ".join(str(text).split())
    return t if len(t) <= n else t[: n - 1] + "…"


def build_outline(items: list[dict], chapter_titles: dict[str, str] | None = None, unresolved: list[str] | None = None) -> str:
    """概念列表 → 层级 Markdown。章节顺序按概念 id 前缀出现顺序。"""
    chapter_titles = chapter_titles or {}
    by_chapter: dict[str, list[dict]] = {}
    for c in items:
        cid = str(c.get("id", ""))
        chapter = cid.split("-kp")[0] if "-kp" in cid else "general"
        by_chapter.setdefault(chapter, []).append(c)

    lines = ["# 概念思维导图"]
    for chapter in sorted(by_chapter, key=_ch_key):
        title = chapter_titles.get(chapter) or f"章节 {chapter}"
        lines.append(f"## {_short(title, 40)}（{chapter}）")
        items_ch = sorted(by_chapter[chapter], key=lambda c: (len(c.get("prerequisites", []) or []), _short(c.get("concept", ""))))
        for c in items_ch:
            name = _short(c.get("concept", ""), 40)
            anchors = len(c.get("anchors", []) or [])
            lines.append(f"### {name}")
            if c.get("definition"):
                lines.append(f"- {_short(c['definition'])}")
            if anchors:
                lines.append(f"- 教材依据：{anchors} 处")
            prereq = c.get("prerequisites", []) or []
            if prereq:
                lines.append(f"- 前置：{', '.join(_short(p, 24) for p in prereq[:5])}")
    if unresolved:
        lines.append("## 未入库前置（待补章节）")
        lines.extend(f"- {_short(u, 40)}" for u in sorted(unresolved))
    return "\n".join(lines)


def _ch_key(ch: str) -> tuple:
    m = "".join(x for x in ch if x.isdigit())
    return (int(m) if m else 0, ch)


def build_html(markdown: str) -> str:
    safe = markdown.replace("</", "<\\/")  # 防止提前闭合 script
    return _HTML.replace("__MD__", safe)


def main(argv: list[str]) -> int:  # pragma: no cover
    if len(argv) < 2:
        print("用法：python make_mindmap_preview.py <concepts.json> [目录]")
        return 1
    base = Path(argv[1]).resolve()
    data_dir = (Path(argv[2]) if len(argv) > 2 else base.parent).resolve()
    concepts = json.loads(base.read_text(encoding="utf-8")).get("concepts", [])
    titles, unresolved = {}, []
    mf = data_dir / "manifest.json"
    if mf.exists():
        m = json.loads(mf.read_text(encoding="utf-8"))
        titles = {ch["id"]: ch["title"] for ch in m.get("chapters", [])}
    gf = data_dir / "graph.json"
    if gf.exists():
        unresolved = json.loads(gf.read_text(encoding="utf-8")).get("unresolved", [])
    outline = build_outline(concepts, titles, unresolved)
    (data_dir / "mindmap.md").write_text(outline, encoding="utf-8")
    (data_dir / "mindmap.html").write_text(build_html(outline), encoding="utf-8")
    print(f"已生成 {data_dir/'mindmap.md'} 与 {data_dir/'mindmap.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
