"""知识库构建与检索（P2）。

数据源：P1 产出的 manifest.json（每个段落已带唯一 anchor）。

流程：段落 → 切块（以段落为基本单位跨段合并；超大段落交给 LangChain
RecursiveCharacterTextSplitter 兜底）→ 向量化 → 持久化 → 余弦检索。

向量化说明：
- 默认内置“哈希特征向量”（确定性、零依赖、离线可用），语义由 CJK 字/
  二元组与英文单词的哈希特征表达，足够原型与测试用；
- 正式接真实模型时只替换 EMBEDDER（例如 sentence-transformers / API
  embedding），VectorKB 与检索代码无需改动。
"""
from __future__ import annotations

import json
import math
import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path

try:  # LangChain 文本切分器（超大段落兜底用）
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except Exception:  # pragma: no cover
    RecursiveCharacterTextSplitter = None

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")

DEFAULT_TARGET = 500   # 单块目标字符数
DEFAULT_DIM = 256      # 哈希向量维度


# ---------------------------------------------------------------- 向量化
class HashEmbedder:
    """零依赖哈希特征向量：CJK 字/二元组 + 英文单词，L2 归一化。"""

    def __init__(self, dim: int = DEFAULT_DIM):
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token, cnt in _features(text).items():
            idx = zlib.crc32(token.encode("utf-8")) % self.dim
            vec[idx] += cnt
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


def _features(text: str) -> dict[str, int]:
    feats: dict[str, int] = {}

    def add(tok: str):
        if tok:
            feats[tok] = feats.get(tok, 0) + 1

    cjk_chars = _CJK_RE.findall(text)
    for ch in cjk_chars:
        add(f"c:{ch}")
    for a, b in zip(cjk_chars, cjk_chars[1:]):
        add(f"b:{a}{b}")
    for w in _WORD_RE.findall(text):
        add(f"w:{w.lower()}")
    return feats


# ---------------------------------------------------------------- 切块
@dataclass
class Chunk:
    text: str = ""
    anchors: list[str] = field(default_factory=list)
    chapter_id: str = ""
    docx: str = ""


def _split_oversized(text: str, chunk_size: int) -> list[str]:
    """超大段落兜底切分：优先 LangChain 递归切分，缺失时按字符硬切。"""
    if len(text) <= chunk_size:
        return [text]
    if RecursiveCharacterTextSplitter is not None:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=0,
            separators=["\n", "。", "；", "，", " ", ""],
        )
        segs = splitter.split_text(text)
        return [s for s in segs if s.strip()] or [text]
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def chunk_paragraphs(paragraph_rows: list[dict], target: int = DEFAULT_TARGET) -> list[Chunk]:
    """把“带 anchor 的段落行”合并成 Chunk 列表（尽量不跨章）。"""
    chunks: list[Chunk] = []
    cur = Chunk()
    cur_len = 0

    def flush():
        nonlocal cur, cur_len
        if cur.text.strip():
            chunks.append(cur)
        cur = Chunk()
        cur_len = 0

    for row in paragraph_rows:
        text = row["text"]
        anchor = row["anchor"]
        for seg in _split_oversized(text, target * 2):
            seg = seg.strip()
            if not seg:
                continue
            # 跨章即另起一块，避免一块含两章内容
            if cur.chapter_id and row["chapter_id"] and cur.chapter_id != row["chapter_id"]:
                flush()
            if cur_len > 0 and cur_len + len(seg) > target:
                flush()
            cur.text += seg
            cur_len += len(seg)
            if anchor not in cur.anchors:
                cur.anchors.append(anchor)
            cur.chapter_id = row["chapter_id"]
            cur.docx = row["docx"]
    flush()
    return chunks


def load_manifest_paragraph_rows(manifest_path: str | Path) -> list[dict]:
    """从 manifest.json 展开成段落行（带章节/文件上下文）。"""
    m = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    rows: list[dict] = []
    for ch in m["chapters"]:
        for part in ch["parts"]:
            for para in part["paragraphs"]:
                rows.append(
                    {
                        "anchor": para["anchor"],
                        "text": para["text"],
                        "chapter_id": ch["id"],
                        "docx": part["file"],
                    }
                )
    return rows


# ---------------------------------------------------------------- BM25 检索
class BM25Index:
    """自实现 BM25 词法检索（k1=1.5 / b=0.75，idf 平滑）。

    分词复用 _features：CJK 单字/相邻二元组 + 英文单词。纯本地、可测试，
    与向量检索做 RRF 融合后能补上“字面精确词”的召回。
    """

    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = list(docs)
        self._tokenized = [_features(d) for d in self.docs]
        self._doc_len = [sum(t.values()) for t in self._tokenized]
        n = len(self._tokenized)
        self._avgdl = sum(self._doc_len) / n if n else 0.0
        df: dict[str, int] = {}
        for toks in self._tokenized:
            for tok in toks:
                df[tok] = df.get(tok, 0) + 1
        self._idf = {tok: math.log(1 + (n - d + 0.5) / (d + 0.5)) for tok, d in df.items()}

    def _score(self, doc_tokens: dict[str, int], query_tokens: dict[str, int]) -> float:
        score = 0.0
        for q_tok, _ in query_tokens.items():
            idf = self._idf.get(q_tok)
            if not idf:
                continue
            tf = doc_tokens.get(q_tok, 0)
            if not tf:
                continue
            dl = sum(doc_tokens.values()) or 1
            denom = tf + self.k1 * (1 - self.b + self.b * dl / (self._avgdl or 1))
            score += idf * (tf * (self.k1 + 1)) / denom
        return score

    def search(self, query: str, k: int = 5) -> list[dict]:
        """返回按 BM25 降序的命中：{score, index}。"""
        q_tokens = _features(query)
        scored = [self._score(t, q_tokens) for t in self._tokenized]
        order = sorted(range(len(scored)), key=lambda i: scored[i], reverse=True)
        out: list[dict] = []
        for i in order:
            if scored[i] <= 0:
                break
            out.append({"score": round(scored[i], 4), "index": i})
            if len(out) >= k:
                break
        return out


# ---------------------------------------------------------------- 向量库
class VectorKB:
    """向量库：存 Chunk + 向量（余弦）与 BM25 索引，支持 RRF 混合检索。

    默认向量为 HashEmbedder（零依赖）；接入真实 embedding（本地模型或
    OpenAI 兼容 /embeddings）时传入 embedder 即可，无需改检索逻辑。
    """

    def __init__(self, embedder: HashEmbedder | None = None):
        self.embedder = embedder or HashEmbedder()
        self.chunks: list[Chunk] = []
        self._vectors: list[list[float]] = []
        self.bm25: BM25Index | None = None

    @classmethod
    def build(cls, chunks: list[Chunk], embedder=None) -> "VectorKB":
        kb = cls(embedder)
        texts = [c.text for c in chunks]
        vecs = kb.embedder.embed_many(texts)
        kb.chunks, kb._vectors = chunks, vecs
        kb.bm25 = BM25Index(texts)
        return kb

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "chunks": [
                {
                    "text": c.text,
                    "anchors": c.anchors,
                    "chapter_id": c.chapter_id,
                    "docx": c.docx,
                    "vector": v,
                }
                for c, v in zip(self.chunks, self._vectors)
            ]
        }
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path, embedder=None) -> "VectorKB":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        kb = cls(embedder)
        for row in data["chunks"]:
            kb.chunks.append(
                Chunk(
                    text=row["text"],
                    anchors=row.get("anchors", []),
                    chapter_id=row.get("chapter_id", ""),
                    docx=row.get("docx", ""),
                )
            )
            kb._vectors.append(row.get("vector", []))
        kb.bm25 = BM25Index([c.text for c in kb.chunks])
        return kb

    def search(self, query: str, k: int = 3) -> list[dict]:
        """纯向量（余弦）检索，按得分降序返回（含 index 供混合检索使用）。"""
        qv = self.embedder.embed(query)
        scored: list[tuple[float, int]] = []
        for i, v in enumerate(self._vectors):
            if not v:
                continue
            dot = sum(a * b for a, b in zip(qv, v))
            scored.append((dot, i))
        scored.sort(key=lambda t: t[0], reverse=True)
        out = []
        for score, i in scored[:k]:
            c = self.chunks[i]
            out.append(
                {
                    "index": i,
                    "score": round(score, 4),
                    "method": "vector",
                    "text": c.text,
                    "anchors": c.anchors,
                    "chapter_id": c.chapter_id,
                }
            )
        return out

    def search_hybrid(self, query: str, k: int = 3, rrf_k: int = 60) -> list[dict]:
        """BM25 + 向量 的 RRF 融合检索（各取较多候选再按排名融合）。"""
        vec = self.search(query, k=max(k * 4, 8))
        bm = self.bm25.search(query, k=max(k * 4, 8)) if self.bm25 else []
        merged: dict[int, float] = {}
        for ranked in (vec, bm):
            for pos, hit in enumerate(ranked):
                merged[hit["index"]] = merged.get(hit["index"], 0.0) + 1.0 / (rrf_k + pos + 1)
        top = sorted(merged, key=merged.get, reverse=True)[:k]
        out = []
        for idx in top:
            c = self.chunks[idx]
            out.append(
                {
                    "index": idx,
                    "score": round(merged[idx], 4),
                    "method": "hybrid",
                    "text": c.text,
                    "anchors": c.anchors,
                    "chapter_id": c.chapter_id,
                }
            )
        return out


def build_knowledge_base(manifest_path: str | Path, kb_path: str | Path | None = None, target: int = DEFAULT_TARGET, embedder=None) -> dict:
    """manifest → 切块 → 向量化 → 存盘；返回统计信息。embedder 缺省为 HashEmbedder。"""
    rows = load_manifest_paragraph_rows(manifest_path)
    chunks = chunk_paragraphs(rows, target=target)
    kb = VectorKB.build(chunks, embedder=embedder)
    if kb_path is not None:
        kb.save(kb_path)
    m = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return {
        "book": m["book"]["title"],
        "paragraphs": len(rows),
        "chunks": len(chunks),
        "characters": sum(len(c.text) for c in chunks),
        "kb_path": str(kb_path) if kb_path is not None else None,
    }
