"""章末自测：让掌握度里那 25% 的「自测正确率」有东西可算。

这个闭环此前是断的——掌握度公式里自测占 25 分，界面上却永远显示「未计入」，
而产品文档把「练习无反馈」列为第二大痛点。断点不在公式，在于**根本没有出题的地方**。

两条设计约束值得单独测：
- **答案不下发**：前端只报「选了第几项」，判卷在后端，掌握度才不是「前端自己说对了」；
- **题面可复现**：同一章每次进来看到的选项顺序一致，用户不会觉得题目在乱跳。
"""
import pytest

from app.config import Settings
from app.llm.client import MockLLM
from app.main import create_app

#: 用强标记词「称为 / 是指」造定义句，规则抽取器（MockLLM 下走的那条）认这个。
PARAS = [
    "在生产实践中，一个量相对于另一个量的变化快慢称为变化率，它描述的是整体表现。",
    "让增量趋近于零时所得到的那个数称为导数，它刻画某一点上的精确变化率。",
    "如果对每个自变量都有唯一的函数值与之对应，这样的对应关系称为函数。",
    "用来衡量区间内平均快慢的量称为平均速度，它与瞬时速度不同。",
]


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path)
    settings.embedding_url = ""
    settings.embedding_api_key = ""
    settings.auto_demo = False
    app = create_app(settings=settings, db_path=tmp_path / "q.db", llm=MockLLM())

    db = app.state.db
    db.add_book({"id": "bk1", "title": "自测测试教材", "created_at": "2026-01-01T00:00:00+00:00"})
    db.add_chapters([
        {"id": "c1", "book_id": "bk1", "num": 1, "title": "第1章 变化率", "page_start": 1, "page_end": 3, "full_text": ""},
    ])
    db.add_sections([
        {"id": f"s{i}", "book_id": "bk1", "chapter_id": "c1", "seq": i, "page": 1, "kind": "p", "text": text}
        for i, text in enumerate(PARAS, start=1)
    ])
    db.add_anchors([
        {"id": f"s{i}", "book_id": "bk1", "chapter_id": "c1", "section_id": f"s{i}", "text": text, "page": 1}
        for i, text in enumerate(PARAS, start=1)
    ])

    from fastapi.testclient import TestClient

    return TestClient(app)


def _quiz(client):
    res = client.get("/api/books/bk1/chapters/c1/quiz")
    assert res.status_code == 200
    return res.json()


def _answer_key(client):
    """第一道题的正确下标。

    **从服务层拿，而不是逐项提交试出来**：试的过程本身会落好几条 quiz 事件，
    把掌握度搅浑，后面断言正确率就全是噪音。
    """
    from app.services import quiz as quiz_service

    db = client.app.state.db
    book = db.get_book("bk1")
    chapter = db.get_chapter("bk1", "c1")
    questions = quiz_service.build_questions(db, MockLLM(), book, chapter)
    assert questions, "这个夹具应当能出题"
    return questions[0]["id"], int(questions[0]["answerIndex"])


def test_quiz_has_questions_with_options(client):
    body = _quiz(client)

    assert body["total"] >= 1
    first = body["questions"][0]
    assert "____" in first["prompt"]
    assert len(first["options"]) >= 2
    assert first["id"]


def test_quiz_never_leaks_the_answer(client):
    """答案不下发：前端拿不到，判卷只能在服务端做。"""
    body = _quiz(client)

    for question in body["questions"]:
        assert "answerIndex" not in question
        assert "answer" not in question
        assert "concept" not in question


def test_question_prompts_blank_out_the_concept(client):
    """题干必须是「把某句定义挖空」，而不是一段看不出问什么的话。"""
    body = _quiz(client)

    for question in body["questions"]:
        assert "____" in question["prompt"]


def test_option_order_is_stable_across_requests(client):
    """同一章两次取到的题面完全一致：选项乱跳会让人以为题目在变。"""
    first = _quiz(client)
    second = _quiz(client)

    assert [q["options"] for q in first["questions"]] == [q["options"] for q in second["questions"]]
    assert [q["id"] for q in first["questions"]] == [q["id"] for q in second["questions"]]


def test_correct_answer_is_graded_correct(client):
    question = _quiz(client)["questions"][0]
    question_id, right = _answer_key(client)

    res = client.post(
        "/api/books/bk1/chapters/c1/quiz/answer",
        json={"questionId": question_id, "choice": right},
    )

    body = res.json()
    assert body["correct"] is True
    assert body["answerIndex"] == right
    assert body["answer"] == question["options"][right]
    # 顺带把「这一段在教材哪里」带回去，用户能核对
    assert body["anchorId"]


def test_grading_records_a_quiz_event_and_returns_progress(client):
    """这就是那个断掉的闭环：答完题，掌握度里「自测正确率」不再是「未计入」。

    刻意**先不 GET 题库**：接口不该依赖调用顺序。这条曾经是 404——
    判卷只读缓存，没先取过题就答不了（真实界面里用户总会先看到题，所以只有测试
    和直接调 API 的人会撞上，但「先看题才能答题」不是一条该写进接口的约束）。
    """
    question_id, right = _answer_key(client)

    res = client.post(
        "/api/books/bk1/chapters/c1/quiz/answer",
        json={"questionId": question_id, "choice": right},
    )

    assert res.status_code == 200
    progress = res.json()["progress"]

    quiz_part = next(item for item in progress["breakdown"] if item["key"] == "quiz")
    assert quiz_part["weight"] == 25.0
    assert quiz_part["value"] == 1.0, "答对了，自测得分就该是满分权重"
    assert quiz_part["score"] == 25.0
    assert progress["signals"]["quizCount"] == 1


def test_wrong_answer_scores_zero_on_that_part(client):
    question = _quiz(client)["questions"][0]
    question_id, right = _answer_key(client)
    wrong = next(i for i in range(len(question["options"])) if i != right)

    res = client.post(
        "/api/books/bk1/chapters/c1/quiz/answer",
        json={"questionId": question_id, "choice": wrong},
    )

    body = res.json()
    assert body["correct"] is False
    assert body["answer"] == question["options"][right], "答错时要告诉用户正确答案"
    quiz_part = next(item for item in body["progress"]["breakdown"] if item["key"] == "quiz")
    assert quiz_part["value"] == 0.0


def test_unknown_question_is_404(client):
    res = client.post(
        "/api/books/bk1/chapters/c1/quiz/answer",
        json={"questionId": "不存在", "choice": 0},
    )

    assert res.status_code == 404


def test_quiz_on_missing_chapter_is_404(client):
    assert client.get("/api/books/bk1/chapters/nope/quiz").status_code == 404
    assert client.get("/api/books/nope/chapters/c1/quiz").status_code == 404


def test_chapter_without_material_returns_zero_questions_not_an_error(client):
    """材料不够就如实说没有题，而不是硬造一道站不住的题。"""
    db = client.app.state.db
    db.add_chapters([
        {"id": "c2", "book_id": "bk1", "num": 2, "title": "第2章 空白", "page_start": 4, "page_end": 4, "full_text": ""},
    ])
    db.add_sections([
        {"id": "x1", "book_id": "bk1", "chapter_id": "c2", "seq": 1, "page": 4, "kind": "p",
         "text": "这一章只有一段普通叙述，没有任何定义句。"},
    ])

    res = client.get("/api/books/bk1/chapters/c2/quiz")

    assert res.status_code == 200
    assert res.json()["total"] == 0
    assert res.json()["questions"] == []


def test_deleting_the_book_takes_its_quiz_with_it(client):
    _quiz(client)  # 先让题库落缓存

    assert client.delete("/api/books/bk1").status_code == 204

    db = client.app.state.db
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM quizzes").fetchone()[0] == 0
