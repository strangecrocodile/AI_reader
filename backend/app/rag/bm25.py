"""自实现的 BM25 检索（团队自主实现，无第三方检索依赖）。

分词策略：中文按相邻字符二元组切分，英文/数字按词切分。
对教材段落（粒度=章节内段落）建立倒排索引并打分。
"""
import math
import re
from typing import Dict, Iterable, List, Tuple

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
WORD_RE = re.compile(r"[a-z0-9_]+")

K1 = 1.5
B = 0.75

#: 「复现词」判据的阈值：命中的词要在索引里至少这么多个文档中出现过，
#: 才算碰到了教材**真在讲的概念**（见 `BM25Index.recurring_matches`）。
#: 取 2 有实测余量（demo 教材 22 段）：合法问句的「命中词最大 df」最小是 7，
#: 题外问句最大是 1，可分区间是 (1, 7]——取最小的 2 最不容易误拒。
RECURRING_DF = 2


def tokenize(text: str) -> List[str]:
    """中文 → 字符二元组 + 英文/数字词；小写化。"""
    tokens: List[str] = []
    cjk = "".join(CJK_RE.findall(text))
    for i in range(len(cjk) - 1):
        tokens.append(cjk[i:i + 2])
    for word in WORD_RE.findall(text.lower()):
        tokens.append(word)
    return tokens


class BM25Index:
    def __init__(self, documents: Dict[str, str]):
        """documents: {doc_id: text}"""
        self.doc_ids: List[str] = list(documents)
        self.doc_tokens: Dict[str, List[str]] = {}
        self.doc_lens: Dict[str, int] = {}
        self.df: Dict[str, int] = {}
        self.avgdl = 1.0

        for doc_id, text in documents.items():
            toks = tokenize(text)
            self.doc_tokens[doc_id] = toks
            self.doc_lens[doc_id] = len(toks)
            for t in set(toks):
                self.df[t] = self.df.get(t, 0) + 1

        total = sum(self.doc_lens.values()) or len(documents)
        self.avgdl = total / max(1, len(documents))

    def _idf(self, term: str) -> float:
        n = len(self.doc_ids)
        df = self.df.get(term, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def score(self, query: str, doc_id: str) -> float:
        q_tokens = tokenize(query)
        if not q_tokens:
            return 0.0
        doc_tokens = self.doc_tokens.get(doc_id, [])
        if not doc_tokens:
            return 0.0
        tf_map: Dict[str, int] = {}
        for t in doc_tokens:
            tf_map[t] = tf_map.get(t, 0) + 1
        dl = self.doc_lens[doc_id]
        score = 0.0
        for t in set(q_tokens):
            tf = tf_map.get(t, 0)
            if tf == 0:
                continue
            score += self._idf(t) * (tf * (K1 + 1)) / (tf + K1 * (1 - B + B * dl / self.avgdl))
        return score

    def search(self, query: str, k: int = 5) -> List[Tuple[str, float]]:
        scored = [(doc_id, self.score(query, doc_id)) for doc_id in self.doc_ids]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [(doc_id, s) for doc_id, s in scored if s > 0][:k]

    def coverage(self, query: str, doc_id: str) -> float:
        """查询词在文档中出现的比例（0~1）。

        **只作展示与排查参考，不再是「有没有依据」的判据**——判定见
        `recurring_matches`。原因：这个比例的分母是问句词数，问得越长越低，
        于是**认真提问反被拒答**（实测同一本教材，「导数是什么」0.250，
        「导数在实际问题中有什么用处」只有 0.167）。

        换分词救不了这个形状：已实测 jieba 分词后两类的覆盖区间**仍然重叠**
        （合法长问句 0.182 / 题外问句 0.250）——「量子纠缠的实验验证」里的
        「实验」「验证」是教材通用词，比例反而比合法长问句更高。问题不在分词，
        在「按比例」这个形状本身。
        """
        q_tokens = set(tokenize(query))
        if not q_tokens:
            return 0.0
        doc_set = set(self.doc_tokens.get(doc_id, []))
        return len(q_tokens & doc_set) / len(q_tokens)

    def recurring_matches(self, query: str, doc_id: str) -> List[str]:
        """命中该文档、且在索引里至少 `RECURRING_DF` 个文档出现过的词。

        这是「教材里有没有依据」的判据：只看命中的词是不是**教材反复在讲的概念**，
        不看它占问句的多大比例，所以与问句长短无关——正是 `coverage` 做不到的
        （见它的文档字符串）。

        实测分离度（demo 教材 22 段）：7 个合法问句全部至少命中 1 个复现词，
        4 个题外问句（「今天晚上的月亮有多圆」「红烧肉怎么做才好吃」「明天北京的
        天气怎么样」「请介绍一下量子纠缠的实验验证」）一个都没有，最大 df 只有 1。

        注意 df 是按**建索引时的文档集合**算的：全书索引给出的是全书复现词，
        章节索引给出的是本章内的复现词。判定「教材里有没有」要用全书索引。
        """
        q_tokens = set(tokenize(query))
        if not q_tokens:
            return []
        doc_tokens = set(self.doc_tokens.get(doc_id, []))
        return sorted(
            token for token in q_tokens & doc_tokens if self.df.get(token, 0) >= RECURRING_DF
        )
