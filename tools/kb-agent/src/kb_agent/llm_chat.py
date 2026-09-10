"""DeepSeek（OpenAI 兼容 chat）客户端——问答生成层（P3 增强）。

仅做“照着检索到的教材原文回答”这一件事：
- 输入：用户问题 + 检索命中的原文块（含锚点）；
- 输出：以教材为边界的回答文本（锚点回链由调用方从 hits 另取）。

未配置 LLM_* 环境变量时 build_chat_llm() 返回 None（无模型模式）。
密钥从 .env 读取，绝不落盘/打印。
"""
from __future__ import annotations

import json
import logging
import os
from urllib.error import URLError
from urllib.request import Request, urlopen

from .config_env import ensure_env

logger = logging.getLogger("kb_agent.llm_chat")

_SYSTEM_PROMPT = (
    "你是「AI讲师」，只依据用户提供的教材原文回答问题。"
    "回答要贴合原文表述；原文没有依据时，明确说“教材中未找到直接依据”，不要编造。"
    "涉及引用时用 [来源N] 标注对应原文编号。"
)


class ChatLLM:
    """OpenAI 兼容 /chat/completions 的极简客户端（非流式）。"""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _complete(self, messages: list[dict]) -> str:
        body = json.dumps({"model": self.model, "messages": messages, "temperature": 0.3}).encode("utf-8")
        req = Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        with urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            payload = json.load(resp)
        return payload["choices"][0]["message"]["content"] or ""

    def __call__(self, query: str, contexts: list[dict]) -> str:
        """contexts: [{text, anchors, chapter_id}]，来自混合检索命中。"""
        if not contexts:
            return "教材中未找到直接依据。"
        parts = []
        for i, ctx in enumerate(contexts, start=1):
            markers = "、".join(ctx.get("anchors", [])[:3])
            parts.append(f"[来源{i}]（锚点 {markers}）{ctx['text']}")
        user = f"{query}\n\n教材原文：\n" + "\n".join(parts)
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": user}]
        return self._complete(messages)

    def complete(self, messages: list[dict]) -> str:
        """公开的消息级补全：供知识点抽取等结构化任务复用（不走问答提示词）。"""
        return self._complete(messages)


def build_chat_llm() -> ChatLLM | None:
    """按 .env/环境变量构造问答 LLM；缺 key 返回 None。"""
    ensure_env()
    base = os.getenv("LLM_BASE_URL", "").rstrip("/")
    key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "") or "deepseek-chat"
    if not (base and key):
        return None
    return ChatLLM(base, key, model)
