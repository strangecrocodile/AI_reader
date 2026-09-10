"""向量嵌入工厂（检索升级，P2-core）。

策略从强到弱自动选择，保证任何环境下都能建库：
1) 配置了 EMBED_BASE_URL + EMBED_API_KEY + EMBED_MODEL
   → OpenAI 兼容 /embeddings（如硅基流动 BGE-M3、OpenAI 等）；
2) 仅配置了 EMBED_MODEL 且本机可 import sentence-transformers
   → 本地语义模型（如 BAAI/bge-m3）；
3) 以上都不可用/失败 → 回退 HashEmbedder（零依赖、离线、确定）。

环境变量只从进程环境读取（建议由 .env 注入），本模块不落盘任何密钥。
所有实现提供统一接口：embed(text) -> list[float]、embed_many(texts)。
"""
from __future__ import annotations

import json
import logging
import os
from urllib.error import URLError
from urllib.request import Request, urlopen

from .build_kb import HashEmbedder
from .config_env import ensure_env

logger = logging.getLogger("kb_agent.embeddings")

ENV_BASE = "EMBED_BASE_URL"
ENV_KEY = "EMBED_API_KEY"
ENV_MODEL = "EMBED_MODEL"


class OpenAICompatEmbedder:
    """调用 OpenAI 兼容 /embeddings 接口（联网时启用）。"""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _post(self, texts: list[str]) -> list[list[float]]:
        body = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        req = Request(
            f"{self.base_url}/embeddings",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        with urlopen(req, timeout=self.timeout) as resp:  # noqa: S310（内网/自配网关场景）
            payload = json.load(resp)
        rows = sorted(payload["data"], key=lambda d: d.get("index", 0))
        return [row["embedding"] for row in rows]

    def embed(self, text: str) -> list[float]:
        return self._post([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        """分批嵌入：单次请求条数过多会超时/被限流，按 EMBED_BATCH_SIZE 分批。"""
        batch = int(os.getenv("EMBED_BATCH_SIZE", "32"))
        out: list[list[float]] = []
        for i in range(0, len(texts), batch):
            out.extend(self._post(texts[i : i + batch]))
        return out


class _LocalSTSEmbedder:
    """本地 sentence-transformers 语义模型（可选依赖）。"""

    def __init__(self, model):
        self._model = model

    def embed(self, text: str) -> list[float]:
        return self._model.encode([text])[0].tolist()

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.encode(texts)]


def make_embedder():
    """按环境配置选择嵌入器；一切失败回退 HashEmbedder。"""
    ensure_env()
    base, key, model = (os.getenv(ENV_BASE, ""), os.getenv(ENV_KEY, ""), os.getenv(ENV_MODEL, ""))
    try:
        if base and key and model:
            emb = OpenAICompatEmbedder(base, key, model)
            emb.embed("探测")  # 建库前先探活，失败即回退
            logger.info("使用 OpenAI 兼容 embedding：%s (%s)", model, base)
            return emb
        if model:
            from sentence_transformers import SentenceTransformer  # 可选依赖

            try:
                st = SentenceTransformer(model)
            except Exception:
                # HuggingFace 直连失败时走镜像重试一次
                if not os.getenv("HF_ENDPOINT"):
                    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
                    logger.warning("HF 直连失败，改用 hf-mirror.com 重试下载 %s", model)
                    st = SentenceTransformer(model)
                else:
                    raise
            emb = _LocalSTSEmbedder(st)
            emb.embed("探测")
            logger.info("使用本地语义模型 embedding：%s", model)
            return emb
    except (URLError, OSError, Exception) as exc:  # noqa: BLE001 —— 探测失败统一回退
        logger.warning("真实 embedding 不可用（%s），回退 HashEmbedder", exc)
    return HashEmbedder()
