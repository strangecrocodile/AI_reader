"""章末自测：掌握度里那 25% 的「自测正确率」终于有东西可算了。

## 为什么题从「已抽取的概念」里出，而不是再造一次 LLM 调用

知识点抽取（`services/concepts`）已经拿到了本章的概念名与定义句——LLM 路径下那是模型
读完整章写出来的，规则路径下是从定义句里挑出来的。自测题直接把定义句挖空、拿同章其它
概念当干扰项，于是：

- **不需要多一次模型调用**，也不引入新的失败模式（模型抽风就出不了题）；
- **答案一定在教材里**，与产品「回答以教材为边界」的口径一致，不会出现模型编一道错题；
- **可用规则兜底**，没配 Key 也能演示完整的「读 → 测 → 掌握度变化」闭环。

## 答案不下发

`GET .../quiz` 只给题干与选项，判卷在后端做（`POST .../quiz/answer`）。前端拿不到答案，
掌握度就不是「前端自己说对了」——`quiz` 学习事件由后端在判卷时落库。
"""
import hashlib
import logging
import random
from typing import Any, Dict, List, Optional

from ..db import Database

logger = logging.getLogger(__name__)

#: 一章最多出几道题。自测是随手一测，不是考试。
MAX_QUESTIONS = 5
#: 干扰项数量（不含正确答案）。
DISTRACTORS = 3
#: 挖空后题干太短就没意思（比如定义句只有概念名本身）。
MIN_PROMPT_CHARS = 12
#: 概念名太短容易被无意义地挖掉（"值"、"解" 之类）。
MIN_NAME_CHARS = 2


def _seed_for(chapter_id: str, concept: str) -> int:
    """稳定的随机种子。

    选项顺序要**可复现**：同一章每次进来看到的题面一致，用户不会觉得题目在乱跳，
    测试也才断言得住。
    """
    digest = hashlib.sha256(f"{chapter_id}:{concept}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def _concepts_of(db: Database, llm, chapter: Dict[str, Any]) -> List[Dict[str, Any]]:
    """取本章概念；没有缓存就先抽一次（与知识点大纲共用同一份缓存）。"""
    from .concepts import extract_concepts

    cached = db.get_concepts(chapter["book_id"], chapter["id"])
    if cached:
        return cached["payload"].get("concepts") or []

    book_id = chapter["book_id"]
    sections = db.sections_of(book_id, chapter["id"])
    anchors = db.anchors_of(book_id, chapter["id"])
    try:
        payload = extract_concepts(db, llm, chapter, sections, anchors)
    except Exception:  # noqa: BLE001 —— 出不了题不该让章节页报错
        logger.exception("自测题取概念失败：%s/%s", book_id, chapter["id"])
        return []
    return payload.get("concepts") or []


def build_questions(
    db: Database,
    llm,
    book: Dict[str, Any],
    chapter: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """用本章概念造填空题；材料不够就少出几道，甚至一道都不出。"""
    concepts = _concepts_of(db, llm, chapter)
    names = [
        str(c.get("concept") or "").strip()
        for c in concepts
        if len(str(c.get("concept") or "").strip()) >= MIN_NAME_CHARS
    ]
    if len(names) < 2:
        # 干扰项凑不出来。硬造（比如拿别的书的词）会让题目站不住，宁可不打题。
        return []

    questions: List[Dict[str, Any]] = []
    for concept in concepts:
        if len(questions) >= MAX_QUESTIONS:
            break
        name = str(concept.get("concept") or "").strip()
        definition = str(concept.get("definition") or "").strip()
        if not name or not definition or name not in definition:
            continue

        prompt = definition.replace(name, "____", 1)
        if len(prompt) < MIN_PROMPT_CHARS:
            continue

        others = [n for n in names if n != name]
        rng = random.Random(_seed_for(chapter["id"], name))
        # 干扰项优先取长度接近的，长短差太远一眼就能排除，题目就白出了
        others.sort(key=lambda item: (abs(len(item) - len(name)), item))
        distractors = others[:DISTRACTORS]
        if len(distractors) < DISTRACTORS:
            continue

        options = [name, *distractors]
        rng.shuffle(options)
        questions.append(
            {
                "id": f"{chapter['id']}-q{len(questions) + 1}",
                "kind": "cloze",
                "prompt": prompt,
                "options": options,
                "answerIndex": options.index(name),
                "concept": name,
                "anchorId": (concept.get("anchors") or [""])[0],
            }
        )
    return questions


def _questions(
    db: Database,
    llm,
    book: Dict[str, Any],
    chapter: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """本章题库（**含答案**）。有缓存用缓存，没有就现造一份并落缓存。

    判卷与下发都走这里，所以「没先取题就直接作答」也能工作——接口不该依赖调用顺序。
    """
    cached = db.get_quiz(book["id"], chapter["id"])
    if cached and cached["payload"].get("questions"):
        return cached["payload"]["questions"]

    questions = build_questions(db, llm, book, chapter)
    # 空题库不入缓存：材料可能会变（重新解析、补抽概念），缓存一个空结果就再也出不了题
    if questions:
        db.upsert_quiz(book["id"], chapter["id"], {"questions": questions}, getattr(llm, "name", "") or "")
    return questions


def get_quiz(db: Database, llm, book: Dict[str, Any], chapter: Dict[str, Any]) -> Dict[str, Any]:
    """取本章自测题，返回**不含答案**的结构。"""
    questions = _questions(db, llm, book, chapter)
    return {
        "chapterId": chapter["id"],
        "total": len(questions),
        "model": getattr(llm, "name", "") or "",
        "questions": [
            {
                "id": q["id"],
                "kind": q["kind"],
                "prompt": q["prompt"],
                "options": q["options"],
            }
            for q in questions
        ],
    }


def grade(
    db: Database,
    llm,
    book: Dict[str, Any],
    chapter: Dict[str, Any],
    question_id: str,
    choice: int,
) -> Optional[Dict[str, Any]]:
    """判卷并落一条 `quiz` 学习事件，返回 `{correct, answerIndex, answer, progress}`。

    题号不存在时返回 None（调用方回 404）。判卷在后端做，前端拿不到答案，
    所以掌握度里的正确率不是「前端自己说对了」。
    """
    question = next((q for q in _questions(db, llm, book, chapter) if q["id"] == question_id), None)
    if question is None:
        return None

    answer_index = int(question["answerIndex"])
    correct = int(choice) == answer_index

    # 复用既有的学习事件链路：掌握度按事件重算并返回拆分说明，前端直接更新面板
    from .progress import record_event

    progress = record_event(db, book["id"], chapter["id"], "quiz", correct=correct)
    return {
        "correct": correct,
        "answerIndex": answer_index,
        "answer": question["options"][answer_index],
        "concept": question.get("concept", ""),
        "anchorId": question.get("anchorId", ""),
        "progress": progress,
    }
