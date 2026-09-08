"""BM25 检索索引单元测试。"""
from app.rag.bm25 import BM25Index, tokenize


def test_tokenize_cjk_bigrams():
    tokens = tokenize("导数的极限")
    assert "导数" in tokens
    assert "极限" in tokens
    assert "数的" in tokens


def test_tokenize_ascii_words():
    tokens = tokenize("y = f(x) and lim")
    for w in ("y", "f", "x", "and", "lim"):
        assert w in tokens


def test_ranking_prefers_relevant_doc():
    docs = {
        "a": "导数就是函数的变化率，定义为增量比值的极限。",
        "b": "春天来了，花园里的花开得很美。",
        "c": "数列的极限存在，则称数列收敛。",
    }
    index = BM25Index(docs)
    hits = index.search("导数是什么", k=2)
    assert hits and hits[0][0] == "a"
    assert hits[0][1] > 0


def test_coverage_no_evidence():
    docs = {"a": "导数就是函数的变化率，定义为增量比值的极限。"}
    index = BM25Index(docs)
    assert index.coverage("导数", "a") == 1.0
    assert index.coverage("今天天气", "a") == 0.0


def test_empty_corpus_safe():
    index = BM25Index({})
    assert index.search("任何问题") == []
