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


def test_coverage_falls_with_question_length():
    """记录朴素覆盖率的已知缺陷：**问句越长越容易低于阈值**。

    中文按二元组切分，「导数」是 1 个词而「导数在实际问题中有什么用处」是 12 个，
    同一个讲导数的段落覆盖率从 1.0 掉到 0.167，于是教材里写清楚的
    「导数」会被判成「教材中未找到直接依据」。

    这条测试是**缺陷的看门人**，不是正确行为的断言：一旦换成正确的判据
    （分词或语义判据），它应该被删掉，而不是被改成迁就实现的样子。
    """
    docs = {
        "a": "导数定义为函数在某一点处的瞬时变化率。",
        "b": "春天来了，花园里的花开得很美。",
    }
    index = BM25Index(docs)

    assert index.coverage("导数", "a") == 1.0
    assert index.coverage("导数在实际问题中有什么用处", "a") < 0.22, "缺陷：长问句覆盖率被摊薄"


def test_empty_corpus_safe():
    index = BM25Index({})
    assert index.search("任何问题") == []
