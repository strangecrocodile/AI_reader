"""BM25 检索索引单元测试。"""
from app.rag.bm25 import RECURRING_DF, BM25Index, tokenize


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
    """记录覆盖率**为什么不能**当依据判据：它与问句长度挂钩。

    中文按二元组切分，「导数」是 1 个词而「导数在实际问题中有什么用处」是 12 个，
    同一个讲导数的段落覆盖率从 1.0 掉到 0.167。

    这里保留这条是为了**钉住「别退回按覆盖率判定」**：判据已改成
    `recurring_matches`（与问句长短无关，见下一条）。覆盖率只作展示与排查参考，
    谁把它接回判定，就会重新引入「问得越认真越容易被拒答」。
    """
    docs = {
        "a": "导数定义为函数在某一点处的瞬时变化率。",
        "b": "春天来了，花园里的花开得很美。",
    }
    index = BM25Index(docs)

    assert index.coverage("导数", "a") == 1.0
    assert index.coverage("导数在实际问题中有什么用处", "a") < 0.22, "覆盖率被问句长度摊薄"


def test_recurring_matches_is_what_makes_a_question_answerable():
    """判据：命中的词要是教材**反复在讲的概念**（df >= RECURRING_DF），与问句长短无关。

    同一个知识点，短问句与长问句都应被判成「有依据」——旧的覆盖率口径下这两者
    一个 1.0、一个 0.167，长问句会被拒答。
    """
    docs = {
        "a": "导数定义为函数在某一点处的瞬时变化率。",
        "b": "导数的几何意义是曲线在该点的切线斜率。",
        "c": "春天来了，花园里的花开得很美。",
    }
    index = BM25Index(docs)

    assert index.recurring_matches("导数", "a") == ["导数"]
    assert index.recurring_matches("导数在实际问题中有什么用处", "a") == ["导数"], (
        "长问句同样命中复现词，不该因为问得长就判成无依据"
    )

    assert RECURRING_DF >= 2, "阈值取 1 等于「只要有一个词命中就算有依据」，会放行题外问句"


def test_recurring_matches_rejects_one_off_coincidences():
    """题外问句只可能撞上「只出现在一处」的伪词，不该被判成有依据。

    「月亮有多圆」在教材里唯一撞上的是跨词边界的 `有多`（df=1）——它看着像词，
    其实是「有」和「多圆」被二元组切分切出来的巧合。这正是覆盖率口径分不开的两类。
    """
    docs = {
        "a": "导数定义为函数在某一点处的瞬时变化率。",
        "b": "极限描述的是趋势，而不是某一个具体取值，有多接近都可以讨论。",
    }
    index = BM25Index(docs)

    assert index.recurring_matches("今天晚上的月亮有多圆", "b") == []
    assert index.df["有多"] == 1, "前提：这个巧合词只出现在一个段落里"


def test_empty_corpus_safe():
    index = BM25Index({})
    assert index.search("任何问题") == []
