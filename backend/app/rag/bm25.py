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
        """查询词在文档中出现的比例（0~1），用于「无依据」判定。"""
        q_tokens = set(tokenize(query))
        if not q_tokens:
            return 0.0
        doc_set = set(self.doc_tokens.get(doc_id, []))
        return len(q_tokens & doc_set) / len(q_tokens)
