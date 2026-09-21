"""兜底路径：模型「没接」与「接了但没吐正文」必须分开说，且预算要够推理用。

两个真实故障：

1. `max_tokens` 取 900 时，推理模型的 `reasoning_content` 与正文共用这笔预算——
   实测「这一段为什么成立」会先烧掉 1232~1346 字推理，正文为 0，
   `finish_reason=length`。代码把「正文为空」当成「模型没回答」，静默回退兜底。
2. 回退时的文案只有一句「未接入大模型」。模型明明配置着，却告诉用户没接，
   排查方向直接跑偏。

用桩模型验证，不联网、不依赖 Key。
"""
import pytest

from app.services.ask import (
    ASK_MAX_TOKENS,
    FALLBACK_NOTICE,
    MODEL_EMPTY_NOTICE,
    NO_EVIDENCE_TEXT,
    answer_question,
    stream_answer,
)

QUESTION = "导数的定义是什么"


class CloudStub:
    """冒充已配置的云端模型；`reply` 为空即模拟「推理吃掉预算、正文为 0」。"""

    kind = "cloud"
    name = "cloud:stub"

    def __init__(self, reply=""):
        self.reply = reply
        self.seen_max_tokens = None

    def chat(self, messages, temperature=0.3, max_tokens=1500):
        self.seen_max_tokens = max_tokens
        return self.reply

    def chat_stream(self, messages, temperature=0.3, max_tokens=1500):
        self.seen_max_tokens = max_tokens
        if self.reply:
            yield self.reply


def _upload(client, data):
    resp = client.post("/api/books", files={"file": ("demo.pdf", data, "application/pdf")})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _targets(app, client, data):
    book = _upload(client, data)
    chapter = book["chapters"][0]
    return app.state.db, app.state.retrieval, book["id"], chapter["id"]


def test_budget_leaves_room_for_reasoning(app, client, demo_pdf_bytes):
    """传给模型的预算必须够推理 + 正文两头用。

    `>= 3000` 是这条测试的全部意义：这个值回到一千上下，正文又会被推理挤成 0，
    而那种失败是**静默**的（表现为兜底答案），没有别的地方能拦住。
    """
    db, retrieval, book_id, chapter_id = _targets(app, client, demo_pdf_bytes)
    stub = CloudStub(reply="导数是平均变化率的极限 [1]。")

    answer_question(db, retrieval, stub, book_id, chapter_id, QUESTION)

    assert stub.seen_max_tokens == ASK_MAX_TOKENS
    assert ASK_MAX_TOKENS >= 3000


def test_empty_model_reply_blames_the_model_not_the_config(app, client, demo_pdf_bytes):
    """模型返回空正文 → 文案说「模型没返回内容」，不能说「未接入大模型」。"""
    db, retrieval, book_id, chapter_id = _targets(app, client, demo_pdf_bytes)

    result = answer_question(db, retrieval, CloudStub(reply=""), book_id, chapter_id, QUESTION)

    assert result["answer"] != NO_EVIDENCE_TEXT  # 检索是通的，问题出在模型这一步
    assert result["answer"].startswith(MODEL_EMPTY_NOTICE)
    assert FALLBACK_NOTICE not in result["answer"]
    assert result["sources"]  # 兜底答案依然可溯源


def test_mock_llm_says_not_connected(app, client, demo_pdf_bytes):
    """真的没配模型时，才说「未接入大模型」。"""
    db, retrieval, book_id, chapter_id = _targets(app, client, demo_pdf_bytes)
    from app.llm.client import MockLLM

    result = answer_question(db, retrieval, MockLLM(), book_id, chapter_id, QUESTION)

    assert result["answer"].startswith(FALLBACK_NOTICE)


def test_stream_empty_model_reply_uses_the_same_notice(app, client, demo_pdf_bytes):
    """流式路径的兜底文案要与非流式一致——前端两条路都走。"""
    db, retrieval, book_id, chapter_id = _targets(app, client, demo_pdf_bytes)

    events = list(
        stream_answer(db, retrieval, CloudStub(reply=""), book_id, chapter_id, QUESTION)
    )

    done = events[-1]
    assert done["event"] == "done"
    assert done["answer"].startswith(MODEL_EMPTY_NOTICE)
    assert [e["event"] for e in events][:1] == ["meta"]


@pytest.mark.parametrize("stream", [False, True])
def test_model_answer_is_used_when_present(app, client, demo_pdf_bytes, stream):
    """模型有正文时就用模型的，不走兜底（反向确认上面几条不是恒真）。"""
    db, retrieval, book_id, chapter_id = _targets(app, client, demo_pdf_bytes)
    stub = CloudStub(reply="导数是平均变化率的极限 [1]。")

    if stream:
        result = list(stream_answer(db, retrieval, stub, book_id, chapter_id, QUESTION))[-1]
    else:
        result = answer_question(db, retrieval, stub, book_id, chapter_id, QUESTION)

    assert result["answer"] == "导数是平均变化率的极限 [1]。"
