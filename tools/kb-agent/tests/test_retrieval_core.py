"""核心检索升级测试：BM25、RRF 混合、embedding 工厂回退策略。"""
from pathlib import Path

import pytest

from make_sample_book import build_sample_book
from kb_agent.build_kb import BM25Index, HashEmbedder, VectorKB, build_knowledge_base, chunk_paragraphs, load_manifest_paragraph_rows
from kb_agent.embeddings import OpenAICompatEmbedder, make_embedder
from kb_agent.split import split_book


class TestBM25:
    def test_rare_keyword_ranks_correct_doc(self):
        docs = [
            "极限与函数是微积分的基础概念。",
            "苹果是一种常见的水果，富含维生素。",
            "导数的几何意义是曲线在该点的切线斜率。",
        ]
        bm = BM25Index(docs)
        hits = bm.search("切线斜率", k=2)
        assert hits and hits[0]["index"] == 2

    def test_empty_corpus_and_no_match(self):
        assert BM25Index([]).search("任意词") == []
        bm = BM25Index(["苹果"])
        assert bm.search("不存在的词xyz") == []


class TestHybrid:
    def _prepared(self, tmp_path: Path) -> tuple[Path, VectorKB]:
        book = build_sample_book(tmp_path / "sample.docx")
        manifest = Path(split_book(book, tmp_path / "chapters", book_id="b1", limit=100_000)["manifest_path"])
        rows = load_manifest_paragraph_rows(manifest)
        kb = VectorKB.build(chunk_paragraphs(rows))
        return manifest, kb

    def test_hybrid_returns_merged_with_method_and_index(self, tmp_path: Path):
        _, kb = self._prepared(tmp_path)
        hits = kb.search_hybrid("什么是导数？", k=3)
        assert hits
        for h in hits:
            assert h["method"] == "hybrid"
            assert "index" in h and isinstance(h["index"], int)
            assert h["score"] > 0
        # 命中第二章（导数），并带回锚点
        assert any(a.startswith("b1-ch2-p") for h in hits for a in h["anchors"])

    def test_hybrid_deterministic(self, tmp_path: Path):
        _, kb = self._prepared(tmp_path)
        a = [h["index"] for h in kb.search_hybrid("导数的定义", k=2)]
        b = [h["index"] for h in kb.search_hybrid("导数的定义", k=2)]
        assert a == b


class TestEmbedderFactory:
    def test_default_returns_hash(self, monkeypatch):
        for k in ("EMBED_BASE_URL", "EMBED_API_KEY", "EMBED_MODEL"):
            monkeypatch.delenv(k, raising=False)
        assert isinstance(make_embedder(), HashEmbedder)

    def test_api_embedder_used_when_configured(self, monkeypatch):
        monkeypatch.setenv("EMBED_BASE_URL", "https://example.test/v1")
        monkeypatch.setenv("EMBED_API_KEY", "sk-test")
        monkeypatch.setenv("EMBED_MODEL", "bge-m3")

        def fake_urlopen(req, timeout=15):
            payload = {"data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}], "model": "bge-m3"}
            return _BytesResp(payload)

        monkeypatch.setattr("kb_agent.embeddings.urlopen", fake_urlopen)
        emb = make_embedder()
        assert isinstance(emb, OpenAICompatEmbedder)
        assert emb.embed("探测") == [0.1, 0.2, 0.3]

    def test_api_failure_falls_back_to_hash(self, monkeypatch):
        monkeypatch.setenv("EMBED_BASE_URL", "https://example.test/v1")
        monkeypatch.setenv("EMBED_API_KEY", "sk-test")
        monkeypatch.setenv("EMBED_MODEL", "bge-m3")

        def boom(req, timeout=15):
            raise __import__("urllib.error", fromlist=["URLError"]).URLError("网络不可达")

        monkeypatch.setattr("kb_agent.embeddings.urlopen", boom)
        assert isinstance(make_embedder(), HashEmbedder)


class _BytesResp:
    """给 urlopen 假返回用的简易响应对象（含 json 读取）。"""

    def __init__(self, payload: dict):
        import io
        import json

        self._buf = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._buf.read()
