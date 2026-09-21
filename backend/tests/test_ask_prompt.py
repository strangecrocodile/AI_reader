"""问答提示词的防回退：拒绝回答是兜底，不是默认出口。

模型只会照提示词办事。旧的规则 3 是「若教材片段不足以回答，直接回复
『教材中未找到直接依据』」——而片段**永远**「不完整」（教材一大本，只给 3 段），
于是模型稳定地拒绝，哪怕片段里其实有能回答的内容。实测三个典型问题，两个
因此在有可用依据的情况下被拒。

这里不逐字比对全文（文案会演进），只钉住**结构**：先尽力作答，再谈拒绝。
顺序反了就等于退回老行为——所以这几处措辞是有意固定的行为契约。
"""
from app.llm.prompts import ASK_SYSTEM, ask_user

REFUSAL = "教材中未找到直接依据"
EVIDENCE = [{"anchor_id": "a1", "page": 1, "text": "教材原文", "chapter_title": "第1章"}]


def test_system_prompt_asks_for_best_effort_before_refusing():
    assert ASK_SYSTEM.index("尽力") < ASK_SYSTEM.index(REFUSAL), (
        "「先尽力作答」必须写在拒绝条款之前，否则模型会直接拒绝"
    )


def test_user_prompt_repeats_the_same_order():
    """末段是离问题最近、权重最高的一句，这里也必须先要尽力、再谈拒绝。"""
    prompt = ask_user("这段话在讲什么", EVIDENCE)
    assert prompt.index("讲多少") < prompt.index(REFUSAL)


def test_prompts_still_forbid_fabrication():
    """放开「拒绝」不等于放开「编造」：教材边界不能一起松掉。"""
    assert "禁止编造" in ASK_SYSTEM
    assert "不得补充片段之外的教材内容" in ASK_SYSTEM
