"""LangSmith 追踪开关测试：无 key 时零影响、不误联网。"""
from kb_agent.langsmith_trace import enable_langsmith, is_enabled, wrap


def _clear_langsmith(monkeypatch):
    for name in ("LANGCHAIN_API_KEY", "LANGCHAIN_TRACING_V2", "LANGCHAIN_PROJECT", "LANGCHAIN_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)


def test_disabled_without_key(monkeypatch):
    _clear_langsmith(monkeypatch)
    assert enable_langsmith() is False
    assert is_enabled() is False

    # 未启用时 wrap 是透传：函数行为不变、可正常调用
    called = []
    def fn(x):
        called.append(x)
        return x * 2

    wrapped = wrap("dummy", "chain")(fn)
    assert wrapped(3) == 6
    assert called == [3]
    # 透传不应产生网络副作用（无 langsmith 客户端被创建）


def test_enabled_flag_with_key_no_run(monkeypatch):
    """配了 key 时 enable 返回 True 且 wrap 产出可调用对象；
    但不真正调用（避免触发网络上报）。"""
    monkeypatch.setenv("LANGCHAIN_API_KEY", "lsv2_fake_for_test")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGCHAIN_PROJECT", "kb-agent-test")
    assert enable_langsmith() is True

    wrapped = wrap("fake.step", "chain")(lambda: "ok")
    assert callable(wrapped)
