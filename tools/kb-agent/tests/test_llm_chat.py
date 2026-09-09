"""DeepSeek 生成层测试（mock 网络，不真调 API）。"""
import json
import io

from kb_agent.llm_chat import ChatLLM, build_chat_llm


class _Resp:
    def __init__(self, content: str):
        payload = {"choices": [{"message": {"content": content}}]}
        self._buf = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._buf.read()


def _fake_urlopen_ok():
    def urlopen(req, timeout=60):
        return _Resp("导数的定义是：……（教材依据见上）")

    return urlopen


def test_chat_llm_builds_context_prompt(monkeypatch):
    monkeypatch.setattr("kb_agent.llm_chat.urlopen", _fake_urlopen_ok())
    llm = ChatLLM("https://api.deepseek.com/v1", "sk-test", "deepseek-chat")
    ans = llm("什么是导数？", [{"text": "导数的定义…", "anchors": ["b1-ch2-p001"], "chapter_id": "ch2"}])
    assert "导数" in ans


def test_chat_llm_empty_context_no_call(monkeypatch):
    def boom(req, timeout=60):
        raise AssertionError("不应发起网络请求")

    monkeypatch.setattr("kb_agent.llm_chat.urlopen", boom)
    llm = ChatLLM("https://x/v1", "k", "m")
    assert llm("任意问题", []) == "教材中未找到直接依据。"


def test_build_chat_llm_none_without_key(monkeypatch):
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert build_chat_llm() is None
