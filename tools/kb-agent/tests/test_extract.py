"""知识点抽取（V2）测试：规则兜底离线可用、LLM JSON 解析与锚点清洗、非法输出回退。"""
import json
from pathlib import Path

from kb_agent.split import split_book
from kb_agent.extract import extract_from_manifest, _parse_json_array, rule_extract


_TXT = """深度学习简明讲义（V2 测试）
第一章 基础概念
机器学习是指通过数据自动改进程序性能的一类方法，其核心是学习算法。
损失函数定义为模型预测与真实标签之间差异的度量。
第二章 优化方法
梯度下降是是指利用损失函数梯度方向更新参数以减小损失的迭代算法。
学习率是一个超参数，定义为每次更新参数时沿梯度方向移动的步长。
"""


def _prepare_manifest(tmp_path: Path) -> tuple[Path, set]:
    p = tmp_path / "book.txt"
    p.write_text(_TXT, encoding="utf-8")
    out = tmp_path / "chapters"
    report = split_book(p, out, book_id="t1", limit=100_000)
    manifest = Path(report["manifest_path"])
    anchors = {pa["anchor"] for c in json.loads(manifest.read_text(encoding="utf-8"))["chapters"] for part in c["parts"] for pa in part["paragraphs"]}
    return manifest, anchors


def test_rule_extract_offline(tmp_path: Path):
    manifest, anchors = _prepare_manifest(tmp_path)
    out = tmp_path / "concepts.json"
    res = extract_from_manifest(manifest, out_path=out)  # 无 key → 规则
    assert res["methods"] == ["rule"]
    assert res["concepts"], "含定义标记词的文本应至少抽出 1 条知识点"
    for c in res["concepts"]:
        assert {"concept", "definition", "prerequisites", "example", "anchors", "id"} <= set(c)
        assert c["anchors"] and set(c["anchors"]) <= anchors  # 锚点必须真实存在
    assert Path(out).exists()


def test_rule_extract_unit():
    rows = [{"anchor": "a1", "text": "线性回归是是指一种用于建模自变量与因变量关系的监督学习方法。"}]
    got = rule_extract(rows)
    assert got and got[0]["anchors"] == ["a1"] and "线性回归" in got[0]["concept"]


def _fake_llm(raw: str):
    class Fake:
        def complete(self, messages):  # noqa: N802
            return raw

    return Fake()


def test_llm_path_parses_and_filters_anchors(tmp_path: Path):
    manifest, anchors = _prepare_manifest(tmp_path)
    real_anchor = next(iter(anchors))
    canned = (
        "好的，结果如下：\n```json\n["
        f'{{"concept": "机器学习", "definition": "通过数据自动改进的一类方法",'
        f'"prerequisites": [], "example": "", "anchors": ["{real_anchor}", "zz-不存在"]}},'
        '{"concept": "梯度下降", "definition": "按梯度方向迭代更新参数",'
        '"prerequisites": ["损失函数"], "example": "", "anchors": ["zz-不存在"]}'
        "]\n```\n"
    )
    res = extract_from_manifest(manifest, llm=_fake_llm(canned))
    assert res["methods"] == ["llm"]
    # 假 LLM 每章返回同样的 2 条 → 两章共 4 条
    assert len(res["concepts"]) == 4
    # id 全局唯一
    assert len({c["id"] for c in res["concepts"]}) == len(res["concepts"])
    # 非法锚点被清洗：任何概念的锚点都必须是真实存在的
    assert all(set(c["anchors"]) <= anchors for c in res["concepts"])
    # 至少一条概念保留住了真实锚点
    assert any(c["anchors"] for c in res["concepts"])


def test_invalid_llm_output_falls_back_to_rule(tmp_path: Path):
    manifest, _ = _prepare_manifest(tmp_path)
    res = extract_from_manifest(manifest, llm=_fake_llm("抱歉我无法输出 JSON。"))
    assert res["methods"] == ["rule"]
    assert res["concepts"]


def test_llm_empty_then_retry_succeeds(tmp_path: Path):
    """首次返回空数组 → 缩小材料重试一次并成功（避免整章退化为规则）。"""
    manifest, anchors = _prepare_manifest(tmp_path)
    real_anchor = next(iter(anchors))

    class RetryLLM:
        def __init__(self):
            self.calls = 0

        def complete(self, messages):  # noqa: N802
            self.calls += 1
            if self.calls == 1:
                return "[]"
            return json.dumps(
                [{"concept": "概念X", "definition": "定义为某种方法", "prerequisites": [], "example": "", "anchors": [real_anchor]}],
                ensure_ascii=False,
            )

    llm = RetryLLM()
    res = extract_from_manifest(manifest, llm=llm)
    assert "llm" in res["methods"]
    assert llm.calls >= 2  # 确实发生了重试
    assert res["concepts"]


def test_parse_json_array_with_fence_and_prefix():
    raw = "好的：\n```json\n[{\"concept\": \"x\"}]\n```\n"
    assert _parse_json_array(raw) == [{"concept": "x"}]
