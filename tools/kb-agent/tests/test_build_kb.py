"""build_kb 模块测试：切块不丢字、向量检索可命中、JSON 持久化可往返。"""
import json
from pathlib import Path

from make_sample_book import build_sample_book
from kb_agent.build_kb import (
    VectorKB,
    build_knowledge_base,
    chunk_paragraphs,
    load_manifest_paragraph_rows,
)
from kb_agent.split import split_book


def _prepared(tmp_path: Path) -> Path:
    """生成样例书并完成 P1 拆书，返回 manifest 路径。"""
    book = build_sample_book(tmp_path / "sample.docx")
    out = tmp_path / "chapters"
    report = split_book(book, out, book_id="b1", limit=100_000)
    return Path(report["manifest_path"])


class TestChunking:
    def test_no_text_loss(self, tmp_path: Path):
        manifest = _prepared(tmp_path)
        rows = load_manifest_paragraph_rows(manifest)
        chunks = chunk_paragraphs(rows)
        assert len(chunks) >= 2

        src_text = "".join(r["text"] for r in rows)
        chunk_text = "".join(c.text for c in chunks)
        assert chunk_text == src_text  # 不丢字、不重复

        # 所有锚点都至少出现一次
        src_anchors = {r["anchor"] for r in rows}
        chunk_anchors = {a for c in chunks for a in c.anchors}
        assert chunk_anchors == src_anchors

    def test_chunk_stays_within_target_mostly(self, tmp_path: Path):
        manifest = _prepared(tmp_path)
        rows = load_manifest_paragraph_rows(manifest)
        chunks = chunk_paragraphs(rows, target=200)
        # 样例段落普遍 < 200 字，按目标合并后不应有灾难性大块
        assert all(len(c.text) <= 400 for c in chunks)
        assert len(chunks) > 3


class TestVectorKB:
    def test_embedding_similarity(self):
        kb = VectorKB()
        a = kb.embedder.embed("导数的定义是极限")
        b = kb.embedder.embed("导数的定义是极限")
        c = kb.embedder.embed("苹果香蕉西瓜")
        same = sum(x * y for x, y in zip(a, b))
        diff = sum(x * y for x, y in zip(a, c))
        assert same > 0.99
        assert same > diff

    def test_build_search_and_roundtrip(self, tmp_path: Path):
        manifest = _prepared(tmp_path)
        kb_path = tmp_path / "kb" / "kb.json"
        stats = build_knowledge_base(manifest, kb_path)
        assert stats["paragraphs"] > 0
        assert stats["chunks"] > 0
        assert Path(kb_path).exists()

        # 检索“导数”应命中第二章相关块并带回锚点
        kb = VectorKB.load(kb_path)
        hits = kb.search("导数的定义是什么", k=3)
        assert hits, "检索应返回结果"
        assert any("导数" in h["text"] for h in hits)
        assert any(h["anchors"] for h in hits)

        # 再验一次持久化内容可解析
        raw = json.loads(Path(kb_path).read_text(encoding="utf-8"))
        assert len(raw["chunks"]) == stats["chunks"]
