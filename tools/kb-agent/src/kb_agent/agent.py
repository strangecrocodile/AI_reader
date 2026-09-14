"""入库 Agent 编排（P3）。

把 P0–P2 串成一个流程：给定整本 .docx，Agent 依次执行
“字数分析 → 拆书 → 建库”，并提供检索问答（ask）。

- 工具用 LangChain `@tool` 声明（langchain-core 已安装），
  将来可无缝换成由 LLM 驱动的 Agent（如 LangGraph create_react_agent），
  让模型决定调用顺序与参数；
- 当前在“无模型/离线”环境按确定性流程执行，保证可演示、可测试；
- 若外部提供 llm 回调（如 OpenAI 兼容客户端），ask 会用检索到的原文
  生成回答；否则返回“检索命中原文 + 锚点”，同样可用于验证 RAG 链路。

用法：
    python -m kb_agent.agent 整本书.docx --workdir data/out [--book-id b1]
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

try:
    from langchain_core.tools import tool
except Exception:  # pragma: no cover

    def tool(*args, **kwargs):  # 无 langchain 时降级为普通函数包装
        def deco(fn):
            return fn

        return deco

from .build_kb import DEFAULT_TARGET, VectorKB, build_knowledge_base
from .embeddings import make_embedder
from .llm_chat import build_chat_llm
from .parse import read_paragraphs
from .split import SPLIT_CHAR_LIMIT, split_book
from .textstats import count_text, total_of


@dataclass
class AgentResult:
    """一次 run 的汇总结果。"""

    book_title: str = ""
    analyze: dict = field(default_factory=dict)
    split: dict = field(default_factory=dict)
    build: dict = field(default_factory=dict)
    manifest_path: str = ""
    kb_path: str = ""


def _invoke(entry_point, *args, **kwargs):
    """调用函数或 LangChain 工具对象（StructuredTool 需走 .func）。"""
    fn = getattr(entry_point, "func", None)
    if fn is None:
        fn = entry_point
    return fn(*args, **kwargs)


@tool
def analyze_book_text(docx_path: str) -> dict:
    """统计整本书的字数：全书去空白字符/中文字数/英文词数/段落数。"""
    rows = read_paragraphs(docx_path)
    counts = total_of(count_text(r.text) for r in rows)
    counts["paragraphs"] = len(rows)
    return counts


@tool
def split_into_chapters(docx_path: str, workdir: str, book_id: str, char_limit: int) -> dict:
    """按章节拆书：一章一份 .docx，超 char_limit 字符再切份；返回 manifest。"""
    report = split_book(docx_path, Path(workdir) / "chapters", book_id=book_id, limit=char_limit)
    return {
        "chapters": [
            {"id": c["id"], "title": c["title"], "counts": c["counts"], "files": [p["file"] for p in c["parts"]]}
            for c in report["chapters"]
        ],
        "manifest": report["manifest_path"],
    }


@tool
def build_rag_knowledge_base(manifest_path: str, kb_path: str) -> dict:
    """基于 manifest 构建 RAG 知识库（切块→向量化→存盘），返回统计。"""
    return build_knowledge_base(manifest_path, kb_path)


class KBAgent:
    """教材入库 Agent：run 执行完整流水线，ask 做检索问答。"""

    def __init__(self, book_id: str = "b1", char_limit: int = SPLIT_CHAR_LIMIT, target: int = DEFAULT_TARGET, llm=None, embedder=None):
        self.book_id = book_id
        self.char_limit = char_limit
        self.target = target
        # 问答 LLM：显式传入优先；否则按 .env 配置自动启用（未配 key 时为 None）
        self.llm = llm if llm is not None else build_chat_llm()
        # 向量嵌入：默认按环境自动选择（真实 embedding → 哈希回退）
        self.embedder = embedder if embedder is not None else make_embedder()
        self._kb: VectorKB | None = None
        self.result: AgentResult | None = None
        # LangSmith 追踪（可选）：配了 LANGCHAIN_API_KEY 才包装 run/ask/llm
        from .langsmith_trace import enable_langsmith, wrap

        self.tracing = enable_langsmith()
        if self.tracing:
            self.run = wrap("KBAgent.run", "chain")(self.run)
            self.ask = wrap("KBAgent.ask", "chain")(self.ask)
            if self.llm is not None and not getattr(self.llm, "_kb_traced", False):
                self.llm = wrap("ChatLLM.ask", "llm")(self.llm)
                self.llm._kb_traced = True  # type: ignore[attr-defined]

    # ------------------------------------------------------------- 流程
    def run(self, docx_path: str | Path, workdir: str | Path) -> AgentResult:
        docx_path = Path(docx_path)
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        res = AgentResult()

        # ① 分析
        analyze = _invoke(analyze_book_text, str(docx_path))
        res.analyze = analyze

        # ② 拆书
        split_info = _invoke(split_into_chapters, str(docx_path), str(workdir), self.book_id, self.char_limit)
        res.split = split_info
        manifest_path = Path(split_info["manifest"])
        res.manifest_path = str(manifest_path)

        # 书名（取 manifest）
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        res.book_title = manifest["book"]["title"]

        # ③ 建库（直调以使用与查询一致的 embedder；@tool 版本供未来 LLM Agent 使用）
        kb_path = workdir / "kb" / "kb.json"
        res.build = build_knowledge_base(str(manifest_path), str(kb_path), target=self.target, embedder=self.embedder)
        res.kb_path = str(kb_path)

        self._kb = VectorKB.load(kb_path, embedder=self.embedder)
        self.result = res
        return res

    # ------------------------------------------------------------- 问答
    def ask(self, query: str, k: int = 3) -> dict:
        """检索问答（BM25+向量 RRF 混合）：返回命中的原文块与锚点；有 llm 时附加生成式回答。"""
        if self._kb is None:
            raise RuntimeError("请先 run() 建库后再 ask()")
        hits = self._kb.search_hybrid(query, k=k)
        contexts = [{"text": h["text"], "anchors": h["anchors"], "chapter_id": h["chapter_id"]} for h in hits]
        answer = None
        if self.llm is not None:
            answer = self.llm(query, contexts)
        return {
            "query": query,
            "answer": answer,  # None = 无模型模式，answer 由前端/调用方决定
            "hits": hits,
            "sources": [a for h in hits for a in h["anchors"]][:10],
            "found": bool(hits),
        }

    # ------------------------------------------------------------- 摘要
    def summarize(self) -> str:
        r = self.result
        if r is None:
            return "（尚未执行 run）"
        lines = [
            f"书名：《{r.book_title}》",
            f"字数分析：去空白字符 {r.analyze.get('chars_no_ws')} / 中文字 {r.analyze.get('cjk')} / 段落 {r.analyze.get('paragraphs')}",
            f"拆书：{len(r.split['chapters'])} 章 → {sum(len(c['files']) for c in r.split['chapters'])} 份 docx",
            f"知识库：{r.build['chunks']} 块 / {r.build['characters']} 字符",
            f"产物：manifest={r.manifest_path}  kb={r.kb_path}",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------- V2：知识点抽取
    def extract_concepts(self, out_dir: str | Path | None = None) -> dict:
        """在已拆好的 manifest 上做知识点抽取（LLM 优先，规则兜底）。"""
        if self.result is None or not self.result.manifest_path:
            raise RuntimeError("请先 run() 建库后再 extract_concepts()")
        from .extract import extract_from_manifest

        out_dir = Path(out_dir) if out_dir else Path(self.result.manifest_path).parent
        out_path = out_dir / "concepts.json"
        # 单独构造一个未包装的 ChatLLM 用于结构化抽取（不受问答提示词影响）
        from .llm_chat import build_chat_llm

        llm = build_chat_llm()
        res = extract_from_manifest(self.result.manifest_path, out_path=out_path, llm=llm)
        self.concepts = res
        return res

    # ------------------------------------------------------------- V2.5：概念图谱
    def build_graph(self, out_dir: str | Path | None = None) -> dict:
        """基于 concepts.json 生成概念关系图谱数据（graph.json）。"""
        from .graph import build_concept_graph

        base = Path(out_dir) if out_dir else (Path(self.result.manifest_path).parent if self.result else Path("."))
        concepts_path = base / "concepts.json"
        if not concepts_path.exists():
            self.extract_concepts(base)
        g = build_concept_graph(concepts_path, out_path=base / "graph.json")
        self.graph = g
        return g

    # ------------------------------------------------------------- P4：讲义生成
    def build_lessons(self, out_dir: str | Path | None = None) -> dict:
        """为所有章节生成讲义 JSON（前端契约：knowledgePoints 带锚点回链）。"""
        from .lesson import build_all_lessons

        base = Path(out_dir) if out_dir else (Path(self.result.manifest_path).parent if self.result else Path("."))
        concepts_path = base / "concepts.json"
        if not concepts_path.exists():
            self.extract_concepts(base)
        idx = build_all_lessons(Path(self.result.manifest_path), concepts_path, base / "lessons")
        self.lessons = idx
        return idx


def main() -> None:  # pragma: no cover
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="教材入库 Agent（P0–P4：拆书/建库/问答/知识点/图谱/讲义）")
    parser.add_argument("book", help="整本书路径（.docx / .txt / .md）")
    parser.add_argument("--workdir", default="data/out", help="输出目录（默认 data/out）")
    parser.add_argument("--book-id", default="b1")
    parser.add_argument("--char-limit", type=int, default=SPLIT_CHAR_LIMIT)
    parser.add_argument("--query", default="", help="建库后执行一条检索问答")
    parser.add_argument("--extract", action="store_true", help="建库后执行 V2 知识点抽取（LLM 优先，规则兜底）")
    parser.add_argument("--graph", action="store_true", help="建库后生成概念关系图谱数据 graph.json")
    parser.add_argument("--lessons", action="store_true", help="生成各章讲义 JSON（前端契约，含锚点回链）")
    args = parser.parse_args()

    agent = KBAgent(book_id=args.book_id, char_limit=args.char_limit)
    agent.run(args.book, args.workdir)
    print(agent.summarize())
    if args.query:
        print("\n[问答]", args.query)
        res = agent.ask(args.query)
        for h in res["hits"]:
            print(f"  [{h['score']}] (章 {h['chapter_id']}) {h['text'][:60]}…  锚点: {h['anchors'][:3]}")
    if args.extract or args.graph or args.lessons:
        ex = agent.extract_concepts()
        print(f"\n[知识点抽取] methods={ex['methods']} chapters={ex['chapters']} concepts={len(ex['concepts'])}")
        print(f"产物：{ex.get('out_path')}")
    if args.graph:
        g = agent.build_graph()
        print(f"[概念图谱] {g['meta']}")
        print(f"产物：{g.get('out_path')}")
    if args.lessons:
        idx = agent.build_lessons()
        total = sum(c["knowledgePoints"] for c in idx["chapters"])
        print(f"[讲义生成] {len(idx['chapters'])} 章 / {total} 知识点")
        for c in idx["chapters"]:
            print(f"  {c['id']}《{c['title'][:20]}》{c['knowledgePoints']} 个（契约错误 {c['errors']}）")


if __name__ == "__main__":
    main()
