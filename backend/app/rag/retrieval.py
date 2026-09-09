"""混合检索服务：BM25 必选 + 向量可选，按权重融合。

检索粒度为「章节内段落」（section），命中结果携带锚点 id 供前端回跳定位。
"""
from typing import Any, Dict, List, Optional

from ..config import Settings
from ..db import Database
from .bm25 import BM25Index
from .vector import VectorIndex

NO_EVIDENCE_THRESHOLD = 0.22  # 覆盖率低于该值视为「教材中未找到直接依据」


class RetrievalService:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self._bm25_cache: Dict[tuple, BM25Index] = {}
        self._vector: Optional[VectorIndex] = None
        self._vectors_built: set = set()

    def invalidate_book(self, book_id: str) -> None:
        """教材重新导入后清空其相关缓存。"""
        self._bm25_cache = {k: v for k, v in self._bm25_cache.items() if k[0] != book_id}
        self._vectors_built = {k for k in self._vectors_built if k[0] != book_id}

    def _get_vector(self) -> Optional[VectorIndex]:
        if self._vector is not None:
            return self._vector
        if not self.settings.embedding_configured:
            return None
        try:
            self._vector = VectorIndex(
                self.settings.embedding_url,
                self.settings.embedding_api_key,
                self.settings.embedding_model,
                self.settings.llm_timeout,
            )
            return self._vector
        except Exception:  # 引入失败（缺依赖/网络）不阻塞核心链路
            return None

    def _ensure_vector_built(self, book_id: str, chapter_id: str, sections: List[Dict[str, Any]]) -> None:
        vec = self._get_vector()
        if vec is None:
            return
        key = (book_id, chapter_id)
        if key in self._vectors_built:
            return
        docs = [(s["id"], s["text"]) for s in sections if s.get("text", "").strip()]
        try:
            vec.add([d[0] for d in docs], [d[1] for d in docs])
            self._vectors_built.add(key)
        except Exception:
            pass

    def _bm25(self, book_id: str, chapter_id: str, sections: List[Dict[str, Any]]) -> BM25Index:
        key = (book_id, chapter_id, len(sections))
        if key not in self._bm25_cache:
            docs = {s["id"]: s["text"] for s in sections}
            self._bm25_cache[key] = BM25Index(docs)
        return self._bm25_cache[key]

    def search(
        self,
        book_id: str,
        chapter_id: str,
        query: str,
        k: int = 5,
        use_vector: bool = True,
    ) -> List[Dict[str, Any]]:
        """返回 [{section_id, score, coverage}]；无任何命中时为空列表。"""
        sections = self.db.sections_of(book_id, chapter_id)
        if not sections:
            return []
        allowed_ids = {s["id"] for s in sections}
        bm25 = self._bm25(book_id, chapter_id, sections)

        bm25_hits = {doc_id: score for doc_id, score in bm25.search(query, k=max(k * 3, 10))}
        merged: Dict[str, float] = {}

        if use_vector:
            self._ensure_vector_built(book_id, chapter_id, sections)
            vec = self._get_vector()
            if vec is not None:
                try:
                    for doc_id, sim in vec.search(
                        query,
                        k=max(k * 3, 10),
                        allowed_ids=allowed_ids,
                    ):
                        if doc_id not in allowed_ids:
                            continue
                        merged[doc_id] = merged.get(doc_id, 0.0) + sim * 0.4
                except Exception:
                    pass

        for doc_id, score in bm25_hits.items():
            merged[doc_id] = merged.get(doc_id, 0.0) + score
        if not merged:
            return []

        top = sorted(merged.items(), key=lambda x: x[1], reverse=True)[:k]
        results = []
        for doc_id, score in top:
            results.append(
                {
                    "section_id": doc_id,
                    "score": round(score, 4),
                    "coverage": round(bm25.coverage(query, doc_id), 4),
                }
            )
        return results
