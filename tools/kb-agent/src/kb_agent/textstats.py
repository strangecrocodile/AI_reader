"""字数统计工具（P0）。

把“字数”的口径统一在这里，解析、报告、测试都用同一套，避免各算各的：

- cjk（中文字数）：Unicode CJK 统一表意文字（含扩展 A、兼容区）；
- chars_no_ws（总字符，不含空白）：去掉所有空白（空格/换行/制表）后的字符数；
- en_words（英文单词/数字串）：连续的 [A-Za-z0-9] 片段计数；
- estimate_tokens（估算模型 token 数）：仅供估算，公式：
  中文字符 1 字 ≈ 1 token，英文每 4 个字符 ≈ 1 token。
"""
from __future__ import annotations

import re
from typing import Iterable

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_WS_RE = re.compile(r"\s+")

_FIELDS = ("cjk", "chars_no_ws", "en_words")


def count_text(text: str | None) -> dict[str, int]:
    """统计单段文本的字数，返回 {cjk, chars_no_ws, en_words}。"""
    t = text or ""
    return {
        "cjk": len(_CJK_RE.findall(t)),
        "chars_no_ws": len(_WS_RE.sub("", t)),
        "en_words": len(_WORD_RE.findall(t)),
    }


def total_of(counts_list: Iterable[dict[str, int]]) -> dict[str, int]:
    """把多段文本的统计结果累加为全书/全章汇总。"""
    total = {"cjk": 0, "chars_no_ws": 0, "en_words": 0}
    for counts in counts_list:
        for key in _FIELDS:
            total[key] += int(counts.get(key, 0))
    return total


def estimate_tokens(counts: dict[str, int]) -> int:
    """由统计结果估算 token 数（仅用于量级估算）。"""
    return counts.get("cjk", 0) + counts.get("en_words", 0) // 4
