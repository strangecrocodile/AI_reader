"""讲义生成测试：拓扑顺序、锚点合法性、前端契约校验。"""
import json
from pathlib import Path

from kb_agent.lesson import (
    build_all_lessons,
    build_lesson,
    collect_anchors,
    topo_order,
    validate_lesson,
)
from kb_agent.split import split_book

_TXT = """讲义测试书
第一章 基础
张量是指多维数组，是深度学习中的基本数据结构。
张量形状表示各轴长度，可以通过shape属性查看。
第二章 进阶
梯度下降定义为沿梯度方向迭代更新参数的算法。
"""


def _manifest(tmp_path: Path) -> dict:
    p = tmp_path / "b.txt"
    p.write_text(_TXT, encoding="utf-8")
    report = split_book(p, tmp_path / "chapters", book_id="t1", limit=100_000)
    return json.loads(Path(report["manifest_path"]).read_text(encoding="utf-8"))


_CONCEPTS = [
    {"id": "ch1-kp002", "concept": "张量形状", "definition": "各轴长度", "prerequisites": ["张量"], "anchors": ["t1-ch1-p003"], "example": ""},
    {"id": "ch1-kp001", "concept": "张量", "definition": "多维数组", "prerequisites": [], "anchors": ["t1-ch1-p002"], "example": ""},
    {"id": "ch2-kp001", "concept": "梯度下降", "definition": "迭代更新参数", "prerequisites": [], "anchors": ["t1-ch2-p002"], "example": ""},
]


def test_topo_order_puts_prerequisites_first():
    ordered = topo_order(_CONCEPTS[:2])  # 故意把“张量形状”放前面
    assert [c["concept"] for c in ordered] == ["张量", "张量形状"]


def test_topo_order_handles_cycle():
    cyc = [
        {"id": "ch1-kp001", "concept": "A", "definition": "a", "prerequisites": ["B"], "anchors": []},
        {"id": "ch1-kp002", "concept": "B", "definition": "b", "prerequisites": ["A"], "anchors": []},
    ]
    out = topo_order(cyc)
    assert sorted(c["concept"] for c in out) == ["A", "B"]  # 不死循环、不丢项


def test_build_lesson_matches_frontend_contract(tmp_path: Path):
    m = _manifest(tmp_path)
    payload = build_lesson(m, "ch1", _CONCEPTS)
    assert payload["chapterId"] == "ch1"
    assert payload["heading"] == "第一章 基础"
    # 知识点按拓扑：张量 先于 张量形状
    titles = [kp["title"] for kp in payload["knowledgePoints"]]
    assert titles == ["张量", "张量形状"]
    # 正文含可点击的 src 锚点片段
    segs = [s for kp in payload["knowledgePoints"] for s in kp["body"] if s["t"] == "src"]
    assert segs and all(s["id"] for s in segs)
    # 大纲序号连续
    assert [o["index"] for o in payload["outline"]] == ["01", "02"]
    assert validate_lesson(payload, collect_anchors(m)) == []


def test_validate_lesson_detects_bad_anchor(tmp_path: Path):
    m = _manifest(tmp_path)
    payload = build_lesson(m, "ch1", _CONCEPTS)
    payload["knowledgePoints"][0]["sourceId"] = "不存在-锚点"
    errs = validate_lesson(payload, collect_anchors(m))
    assert any("锚点不存在" in e for e in errs)


def test_build_all_lessons_writes_files(tmp_path: Path):
    m = _manifest(tmp_path)
    mf = tmp_path / "manifest.json"
    mf.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    cp = tmp_path / "concepts.json"
    cp.write_text(json.dumps({"concepts": _CONCEPTS}, ensure_ascii=False), encoding="utf-8")

    index = build_all_lessons(mf, cp)  # 默认写到 manifest 同目录/lessons
    out = tmp_path / "lessons"
    assert (out / "ch1.json").exists() and (out / "ch2.json").exists() and (out / "index.json").exists()
    assert [c["id"] for c in index["chapters"]] == ["ch1", "ch2"]
    assert index["chapters"][0]["knowledgePoints"] == 2
    assert all(c["errors"] == 0 for c in index["chapters"])
