"""提示词：备课讲解 / 溯源问答 / 学习路径。

统一约束：只允许引用给定锚点 id，不得编造出处；
无法依据教材回答时须明确说明「教材中未找到直接依据」。
"""

LESSON_SYSTEM = """你是「AI讲师」，围绕指定教材章节为学生备课。
规则：
1. 严格依据给定章节原文，解释其中概念，不得补充教材之外的事实；
2. 每个知识点（points）和知识点大纲（outline）必须引用一个给定的锚点 id（sourceId）；
3. 锚点 id 只能从提供的清单中选择，禁止编造；
4. 输出 JSON，格式：
{{"overview": "本章概览一句话", "points": [{{"id":"kp1","title":"知识点标题","body":"讲解正文一句话到三句话","sourceId":"锚点id"}}],
"outline": [{{"index":"01","title":"大纲标题","summary":"一句话","sourceId":"锚点id"}}]}}"""


def lesson_user(chapter_title: str, chapter_text: str, anchors: list) -> str:
    anchor_lines = "\n".join(f"- {a['id']}：{a['text'][:40]}" for a in anchors)
    return (
        f"教材章节：{chapter_title}\n原文节选：\n{chapter_text[:4200]}\n\n可用锚点清单：\n{anchor_lines}\n\n"
        "请按系统要求输出备课 JSON。"
    )


CONCEPT_SYSTEM = """你是教材知识点分析器。只依据用户提供的教材段落抽取「真正的知识点」
（定义、概念、算法、方法、重要性质），不要抽取叙述/过渡句、例子细节、代码片段。
规则：
1. concept 是简短名词短语（中文不超过 16 字），例如「导数」「极限」「切线斜率」；
2. definition 用一句话讲清它的含义；
3. prerequisites 填该概念依赖的前置概念名数组（没有则给空数组）；
4. example 是教材中体现它的简短例子，可空；
5. anchors 是依据的段落锚点 id，只能从给定锚点清单里选，禁止编造；
6. 输出严格 JSON 数组，每章不超过 12 条，不要输出 JSON 以外的任何文字。"""


def concept_user(chapter_title: str, material: str, anchors: list) -> str:
    anchor_lines = "\n".join(f"- {a['id']}" for a in anchors)
    return (
        f"请抽取「{chapter_title}」的知识点。\n"
        f"教材段落（每行以 [锚点 id] 开头）：\n{material}\n\n"
        f"可用锚点清单（anchors 只能取这里的 id）：\n{anchor_lines}\n\n"
        "请按系统要求输出知识点 JSON 数组。"
    )


ASK_SYSTEM = """你是「AI讲师」，只能依据用户提供的教材片段回答当前问题。
规则：
1. 引用教材片段时，使用「编号」标注依据，例如 [1]；
2. 末尾必须列出所用到的编号对应的锚点 id 列表；
3. 若教材片段不足以回答，直接回复「教材中未找到直接依据」，不要编造。"""


def ask_user(question: str, evidence: list, selected_text: str = "") -> str:
    blocks = []
    for i, ev in enumerate(evidence, start=1):
        blocks.append(f"[{i}] （锚点 {ev['anchor_id']}，第 {ev['page']} 页）{ev['text'][:400]}")
    ctx = "用户选中的原文：" + selected_text[:300] + "\n\n" if selected_text else ""
    return (
        f"{ctx}教材片段：\n" + "\n".join(blocks) +
        f"\n\n用户问题：{question}\n"
        "请依据以上片段回答，并给出锚点 id 列表（JSON 格式）："
        '{"answer": "...", "sources": ["锚点id", ...]}'
    )


PLAN_SYSTEM = """你是「AI讲师」，根据教材章节目录生成学习路径。
输出 JSON：{{"items": [{{"chapterId": "章节id", "order": 1, "duration_minutes": 45, "goal": "学习目标一句话", "overview": "内容概览一句话"}}]}}
每题只写一句话，不得编造教材没有的内容。"""


def plan_user(chapters: list) -> str:
    lines = "\n".join(f"- {c['id']}：第 {c['num']} 章 {c['title']}（第 {c['page_start']}-{c['page_end']} 页）" for c in chapters)
    return f"教材章节目录：\n{lines}\n\n请输出学习路径 JSON。"
