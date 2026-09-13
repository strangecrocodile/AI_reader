"""章节掌握度：由真实学习事件算出，而不是前端写死的数字。

可解释公式（满分 100）：

    覆盖度     = 读过的正文段落数 / 本章正文段落总数        权重 50
    互动度     = min(提问过的不同问题数, 5) / 5             权重 25
    自测正确率 = 答对题数 / 答题总数（无答题记录时该项缺失）  权重 25

设计约束：

- 没有自测记录时，自测权重按比例并入前两项（覆盖度 66.7 / 互动度 33.3），
  避免「没做测验就永远拿不到高分」；
- 覆盖度只统计**本章真实存在**的锚点，前端乱报锚点不计分；
- 提问按不同问题去重并封顶 5 次，重复提问不刷分；
- 状态规则：`complete` 事件或掌握度 ≥ 80 → learned；有任意事件 → learning；否则 planned；
- 掌握度只增不减（`chapter_progress` 侧取 max），因此同时给出：
    `computed` 本次按事件算出的值、`mastery` 实际生效值。

`breakdown` 返回每一项的权重与得分，前端据此展示「掌握度是怎么来的」。
"""
from typing import Any, Dict, Iterable, List, Optional

from ..db import Database

COVERAGE_WEIGHT = 50.0
ENGAGEMENT_WEIGHT = 25.0
QUIZ_WEIGHT = 25.0
MAX_COUNTED_QUESTIONS = 5
LEARNED_THRESHOLD = 80.0
MAX_QUESTION_CHARS = 200


def body_anchor_ids(db: Database, book_id: str, chapter_id: str) -> set:
    """本章可用于覆盖度统计的正文锚点（小节标题不算，读者不会逐字读标题）。"""
    return {
        section["id"]
        for section in db.sections_of(book_id, chapter_id)
        if section.get("kind", "p") != "heading"
    }


def compute_progress(db: Database, book_id: str, chapter_id: str) -> Dict[str, Any]:
    """按事件重算掌握度与状态（不写库）。"""
    valid_anchors = body_anchor_ids(db, book_id, chapter_id)
    events = db.learning_events_of(book_id, chapter_id)

    read_anchors = {
        event["anchor_id"]
        for event in events
        if event["kind"] == "read" and event["anchor_id"] in valid_anchors
    }
    questions = {event["detail"] for event in events if event["kind"] == "ask" and event["detail"]}
    answers = [float(event["value"]) for event in events if event["kind"] == "quiz"]
    completed = any(event["kind"] == "complete" for event in events)

    coverage = len(read_anchors) / len(valid_anchors) if valid_anchors else 0.0
    engagement = min(len(questions), MAX_COUNTED_QUESTIONS) / MAX_COUNTED_QUESTIONS
    accuracy: Optional[float] = (sum(answers) / len(answers)) if answers else None

    if accuracy is None:
        # 没有自测记录：把自测权重按比例并入覆盖度与互动度
        kept = COVERAGE_WEIGHT + ENGAGEMENT_WEIGHT
        coverage_weight = COVERAGE_WEIGHT / kept * 100
        engagement_weight = ENGAGEMENT_WEIGHT / kept * 100
        quiz_weight = 0.0
        note = "暂无自测记录，自测权重已按比例并入前两项"
    else:
        coverage_weight, engagement_weight, quiz_weight = COVERAGE_WEIGHT, ENGAGEMENT_WEIGHT, QUIZ_WEIGHT
        note = "已计入自测正确率"

    parts = [
        ("coverage", "已读段落", coverage, coverage_weight),
        ("engagement", "提问互动", engagement, engagement_weight),
        ("quiz", "自测正确率", accuracy if accuracy is not None else 0.0, quiz_weight),
    ]
    breakdown = [
        {
            "key": key,
            "label": label,
            "value": None if (key == "quiz" and accuracy is None) else round(value, 3),
            "weight": round(weight, 1),
            "score": round(value * weight, 1),
        }
        for key, label, value, weight in parts
    ]
    computed = round(sum(item["score"] for item in breakdown))
    status = (
        "learned"
        if completed or computed >= LEARNED_THRESHOLD
        else ("learning" if events else "planned")
    )
    return {
        "bookId": book_id,
        "chapterId": chapter_id,
        "status": status,
        "computed": computed,
        "mastery": computed,
        "breakdown": breakdown,
        "note": note,
        "signals": {
            "paragraphsRead": len(read_anchors),
            "paragraphsTotal": len(valid_anchors),
            "askCount": len(questions),
            "quizCount": len(answers),
            "quizAccuracy": round(accuracy, 3) if accuracy is not None else None,
            "completed": completed,
        },
    }


def refresh_progress(db: Database, book_id: str, chapter_id: str) -> Dict[str, Any]:
    """重算并写入章节进度（只增不减），再回写教材总进度。"""
    result = compute_progress(db, book_id, chapter_id)
    row = db.upsert_chapter_progress(book_id, chapter_id, result["status"], result["mastery"])
    db.update_book_progress_from_chapters(book_id)
    # upsert 是「只增不减」语义，回读生效值，保证接口返回的就是界面上看到的
    result["status"] = row["status"]
    result["mastery"] = round(float(row["mastery"]))
    return result


def record_event(
    db: Database,
    book_id: str,
    chapter_id: str,
    kind: str,
    anchor_ids: Iterable[str] = (),
    question: str = "",
    correct: Optional[bool] = None,
) -> Dict[str, Any]:
    """记录一次学习事件并返回重算后的进度。"""
    if kind == "read":
        valid = body_anchor_ids(db, book_id, chapter_id)
        already = {
            event["anchor_id"]
            for event in db.learning_events_of(book_id, chapter_id)
            if event["kind"] == "read"
        }
        for anchor_id in dict.fromkeys(anchor_ids):  # 去重且保持顺序
            if anchor_id in valid and anchor_id not in already:
                db.add_learning_event(book_id, chapter_id, "read", anchor_id=anchor_id)
    elif kind == "ask":
        db.add_learning_event(
            book_id, chapter_id, "ask", detail=(question or "").strip()[:MAX_QUESTION_CHARS]
        )
    elif kind == "quiz":
        db.add_learning_event(book_id, chapter_id, "quiz", value=1.0 if correct else 0.0)
    else:  # open / complete
        db.add_learning_event(book_id, chapter_id, kind)

    return refresh_progress(db, book_id, chapter_id)
