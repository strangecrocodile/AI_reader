"""可选向量检索：OpenAI 兼容 /embeddings（如 SiliconFlow 的 BGE-M3）+ 本地余弦。

未配置 EMBEDDING_URL/API_KEY 或本机为 Python 3.8（无兼容 ChromaDB）时，
向量通道自动禁用，检索回退到纯 BM25（见 retrieval.py）。
"""
import math
from typing import List, Optional


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-9
    nb = math.sqrt(sum(y * y for y in b)) or 1e-9
    return dot / (na * nb)


class VectorIndex:
    """内存向量索引：嵌入请求走 OpenAI 兼容接口。"""

    def __init__(self, embedding_url: str, api_key: str, model: str, timeout: float = 60.0):
        import httpx

        self._httpx = httpx
        self.url = embedding_url.rstrip("/") + "/embeddings"
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._vectors: dict = {}  # doc_id -> [float]

    def _embed(self, texts: List[str]) -> List[List[float]]:
        resp = self._httpx.post(
            self.url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        data.sort(key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]

    def add(self, doc_ids: List[str], texts: List[str]) -> None:
        if not doc_ids:
            return
        for doc_id, vec in zip(doc_ids, self._embed(texts)):
            self._vectors[doc_id] = vec

    def search(self, query: str, k: int = 5, allowed_ids=None) -> List[tuple]:
        if not self._vectors:
            return []
        try:
            [qvec] = self._embed([query])
        except Exception:
            return []
        allowed = set(allowed_ids) if allowed_ids is not None else None
        scored = [
            (doc_id, _cosine(qvec, vec))
            for doc_id, vec in self._vectors.items()
            if allowed is None or doc_id in allowed
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]
