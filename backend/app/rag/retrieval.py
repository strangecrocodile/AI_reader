"""混合检索服务：BM25 必选 + 向量可选，按 RRF 融合名次。

检索粒度：段落（section）。命中结果带 `chapter_id`，因此跨章命中时
前端仍能知道「依据来自哪一章的哪一段」并跳转过去。

两种检索范围：
- `search`：只在本章内检索（用于「这一章讲了什么」这类明确按章组织的场景）；
- `search_book`：**全书检索**，本章命中加权。问答走这条——教材常把总述/定义
  放在靠前的总论章、把例题放在具体章节，只查本章就拿不到定义（见该函数文档）。

「有没有依据」的判定不在本模块，见 `bm25.BM25Index.recurring_matches`：它只看命中的词
是不是教材反复在讲的概念，与问句长短无关。**不要退回按覆盖率判定**——那个比例随问句
变长而下降，会把教材讲清楚的内容判成「未找到依据」，实测两类问句的覆盖区间重叠、
换分词也分不开（见 `bm25.coverage` 的文档字符串）。
"""
from typing import Any, Dict, List, Optional, Tuple

from ..config import Settings
from ..db import Database
from .bm25 import BM25Index
from .vector import VectorIndex

#: RRF 融合常数：只依赖名次，免疫 BM25 无界分与余弦 0~1 的量纲差
RRF_K = 60
#: 每个通道取多少个候选再融合（比最终 k 宽，给 RRF 留出交叉的余地）
CANDIDATE_MULTIPLIER = 3
#: 全书检索时，当前章节命中的加权系数。加在 **BM25 原始分上、排名次之前**，
#: 所以它只是一条「分数接近时本章优先」的倾向，不是门槛——1.35 倍越不过数量级
#: 的差距，其它章节明显更相关的段落照样排在前面。
#: 不能改加在融合分上：RRF 分被压缩在 1/(60+rank)，同一个乘数会变成几十名的
#: 提前量，直接把「只影响排序」变成「本章说了算」。
CHAPTER_BOOST = 1.35


class RetrievalService:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self._bm25_cache: Dict[tuple, BM25Index] = {}
        self._book_cache: Dict[str, tuple] = {}  # book_id -> ((book_id, doc_count), index, owner)
        self._vector: Optional[VectorIndex] = None
        self._vectors_built: set = set()  # 已建向量的 book_id

    def invalidate_book(self, book_id: str) -> None:
        """教材重新导入后清空其相关缓存。"""
        self._bm25_cache = {k: v for k, v in self._bm25_cache.items() if k[0] != book_id}
        self._book_cache.pop(book_id, None)
        self._vectors_built.discard(book_id)

    # ---------- 索引构建 ----------

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

    def _ensure_vectors(self, book_id: str) -> None:
        """按「整本书」建一次向量；章节检索靠允许列表过滤，避免重复嵌入开销。"""
        vec = self._get_vector()
        if vec is None or book_id in self._vectors_built:
            return
        docs: List[Tuple[str, str]] = []
        for chapter in self.db.chapters_of(book_id):
            for section in self.db.sections_of(book_id, chapter["id"]):
                if section.get("text", "").strip():
                    docs.append((section["id"], section["text"]))
        try:
            vec.add([d[0] for d in docs], [d[1] for d in docs])
            self._vectors_built.add(book_id)
        except Exception:
            pass

    def _bm25(self, book_id: str, chapter_id: str, sections: List[Dict[str, Any]]) -> BM25Index:
        key = (book_id, chapter_id, len(sections))
        if key not in self._bm25_cache:
            docs = {s["id"]: s["text"] for s in sections}
            self._bm25_cache[key] = BM25Index(docs)
        return self._bm25_cache[key]

    def _book_index(self, book_id: str) -> Tuple[BM25Index, Dict[str, str]]:
        """全书索引 + 段落 → 章节映射。"""
        docs: Dict[str, str] = {}
        owner: Dict[str, str] = {}
        for chapter in self.db.chapters_of(book_id):
            for section in self.db.sections_of(book_id, chapter["id"]):
                text = section.get("text", "")
                if not text.strip():
                    continue
                docs[section["id"]] = text
                owner[section["id"]] = chapter["id"]
        cached = self._book_cache.get(book_id)
        if cached and cached[0] == (book_id, len(docs)):
            return cached[1], cached[2]
        index = BM25Index(docs)
        self._book_cache[book_id] = ((book_id, len(docs)), index, owner)
        return index, owner

    # ---------- 检索 ----------

    def _rank(
        self,
        book_id: str,
        index: BM25Index,
        owner: Dict[str, str],
        query: str,
        k: int,
        allowed_ids: set,
        use_vector: bool,
        preferred_chapter: str = "",
    ) -> List[Dict[str, Any]]:
        """BM25（+ 可选向量）按 RRF 融合，返回带章节信息的命中。

        `preferred_chapter` 非空时给它名下的段落乘 `CHAPTER_BOOST`——用于全书检索
        里「本章优先」。加权发生在**排名次之前**，所以它只改 BM25 通道内的先后，
        不把任何量纲带进融合分；默认空串，因此本章内检索与它的既有行为完全不变。

        融合用 RRF（Reciprocal Rank Fusion）而不是「BM25 原始分 + 余弦×权重」：
        BM25 分是无界的（同一本书里可以从 0.x 到几十，取决于命中了多少词、
        词有多罕见），余弦只有 0~1，线性相加会让向量通道被彻底淹没——配了
        embedding 也等于没配。RRF 只看名次，天然免疫这种量纲差。
        """
        candidates = max(k * CANDIDATE_MULTIPLIER, 10)
        ranked = sorted(
            (
                (
                    doc_id,
                    score
                    * (
                        CHAPTER_BOOST
                        if preferred_chapter and owner.get(doc_id) == preferred_chapter
                        else 1.0
                    ),
                )
                for doc_id, score in index.search(query, k=candidates)
                if doc_id in allowed_ids
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        fused: Dict[str, float] = {}
        for rank, (doc_id, _) in enumerate(ranked, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (RRF_K + rank)
        for rank, doc_id in enumerate(
            self._vector_ranked(book_id, query, candidates, allowed_ids) if use_vector else [],
            start=1,
        ):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (RRF_K + rank)

        top = sorted(fused.items(), key=lambda item: item[1], reverse=True)[:k]
        return [
            {
                "section_id": doc_id,
                "chapter_id": owner.get(doc_id, ""),
                "score": round(score, 6),
                "coverage": round(index.coverage(query, doc_id), 4),
                # 命中词里「教材反复在讲的概念」。问答据此判「有没有依据」，
                # 不看覆盖率——理由见 `bm25.coverage` 与 `bm25.recurring_matches`。
                # df 的口径取决于传进来的 index：全书检索给全书口径，章节检索给本章口径。
                "recurring_terms": index.recurring_matches(query, doc_id),
            }
            for doc_id, score in top
        ]

    def _vector_ranked(self, book_id: str, query: str, k: int, allowed_ids: set) -> List[str]:
        """向量通道的名次列表（未配置/出错时为空，不影响 BM25 主链路）。"""
        self._ensure_vectors(book_id)
        vec = self._get_vector()
        if vec is None:
            return []
        try:
            return [
                doc_id
                for doc_id, _ in vec.search(query, k=k, allowed_ids=allowed_ids)
                if doc_id in allowed_ids
            ]
        except Exception:
            return []

    def search(
        self,
        book_id: str,
        chapter_id: str,
        query: str,
        k: int = 5,
        use_vector: bool = True,
    ) -> List[Dict[str, Any]]:
        """本章内检索，返回 [{section_id, chapter_id, score, coverage}]。"""
        sections = self.db.sections_of(book_id, chapter_id)
        if not sections:
            return []
        allowed_ids = {s["id"] for s in sections}
        index = self._bm25(book_id, chapter_id, sections)
        owner = {s["id"]: chapter_id for s in sections}
        return self._rank(book_id, index, owner, query, k, allowed_ids, use_vector)

    def search_book(
        self,
        book_id: str,
        chapter_id: str,
        query: str,
        k: int = 10,
        use_vector: bool = True,
    ) -> Dict[str, Any]:
        """全书检索（当前章节加权），返回 `{scope, hits}`。

        为什么不做「本章优先、本章够用就不查全书」：教材常把总述与定义放在靠前的
        总论章，把例题放在讲该主题的具体章节。实测一本扫描教材里「聚类分析」最准确
        的定义写在第 2 章，而相关例题全在第 6 章——本章命中达标就不再查全书的话，
        那个定义永远进不了证据，模型也就无从「从全书相关内容里提炼」。所以这里
        **每次都查全书**，只把本章命中加权，让同分时本章段落排前，但不排除其它章节。

        `scope` 由命中结果反推：全部落在本章是 `chapter`，跨了章是 `book`
        （前端据此提示「依据综合了多个章节」，并可跳到对应章节核对）。
        """
        index, owner = self._book_index(book_id)
        if not owner:
            return {"scope": "chapter", "hits": []}
        hits = self._rank(
            book_id, index, owner, query, k, set(owner), use_vector,
            preferred_chapter=chapter_id,
        )
        scope = "chapter" if all(hit["chapter_id"] == chapter_id for hit in hits) else "book"
        return {"scope": scope, "hits": hits}
