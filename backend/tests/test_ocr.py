"""扫描件 OCR 的测试。

**全部不联网、不加载 ONNX。** 识别质量是模型的事，这里测的是我们自己的逻辑：
抽样判扫描件、结构还原、印刷页码换算、任务状态机、失败时一行都不落库。
所以一律注入假引擎——`RapidOcrEngine` 的适配层是唯一碰真引擎的地方，
那里也只看它的**输出对象**长什么样，从不构造 `RapidOCR`。
"""
import pytest

from app.llm.client import MockLLM
from app.main import create_app
from app.parsing.ocr_engine import OcrLine, RapidOcrEngine
from app.parsing.ocr_pdf import FOOTER_BAND_RATIO, HEADER_BAND_RATIO, ocr_pdf_bytes
from app.parsing.pdf import probe_pdf
from app.services.ingest import OCR_SOURCE_NOTE, SCANNED_NO_OCR_MESSAGE, store_parsed_book
from app.services.ocr import DONE, FAILED, OcrTaskService, OcrUnavailable

DPI = 200


def make_pdf(pages: int = 4):
    """造一本空白 PDF：`probe_pdf` 只看文本层，没文字就是扫描件。

    页面尺寸必须是 A4——结构还原里的页眉/页脚带都是按页高比例算的。
    """
    import pymupdf

    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page(width=595, height=842)
    data = doc.tobytes()
    doc.close()
    return data


def line(text: str, y: float, height: float = 40.0) -> OcrLine:
    return OcrLine(text=text, score=0.99, x0=150.0, y0=y, x1=150.0 + len(text) * 12, y1=y + height)


class FakeOcrEngine:
    """按调用次序吐预置的行。第 n 次 `recognize` 返回第 n 页。"""

    name = "fake"

    def __init__(self, pages, record_png: bool = False):
        self._pages = pages
        self.calls = 0
        self.pngs = [] if record_png else None

    def recognize(self, image_png: bytes):
        self.calls += 1
        if self.pngs is not None:
            self.pngs.append(image_png)
        return self._pages[self.calls - 1]


#: 正文行，必须两两不同——重复的正文会被 `_repeated_margin_lines` 当水印剔掉
BODY = [
    "数学上我们把这种对应关系称为函数，对每个x都有唯一的y与之对应。",
    "函数的表示方法常见的有解析式、表格和图像三种。",
    "函数的单调性是指在某个区间内函数值随自变量的增大而增大或减小。",
    "比值 Δy 除以 Δx 衡量区间内的平均快慢，称为平均变化率。",
    "让 Δx 趋近于 0，平均变化率趋近的那个数就定义为导数。",
    "如果函数在闭区间上连续、在开区间内可导，就称它满足罗尔定理的条件。",
    "把导数等于零的点称为驻点，它可能是极大值点也可能是极小值点。",
    "定积分可以看作曲线与坐标轴围成的曲边梯形的面积。",
    "连续函数在闭区间上必定取得最大值与最小值，这是最值定理的内容。",
    "夹逼准则说的是如果两个函数的极限相同，中间那个函数也只能趋近同一个值。",
    "无穷小量与有界量的乘积仍然是无穷小量，这个结论在求极限时经常用到。",
    "两个等价无穷小量之比趋近于一，因此在乘除运算中可以直接替换。",
    "分段函数在分界点处的连续性要分别考察左右极限是否相等。",
    "可导必连续，但连续未必可导，例如绝对值函数在原点处就不可导。",
    "二阶导数刻画的是切线斜率的变化快慢，可以用来判断曲线的凹凸性。",
    "若函数在某区间内二阶导数大于零，则曲线在该区间上是凹的。",
    "拉格朗日中值定理是罗尔定理的推广，它去掉了两端点函数值相等的要求。",
    "柯西中值定理把两个函数的增量之比与它们导数之比联系了起来。",
    "洛必达法则适用于零比零型和无穷比无穷型两类未定式极限的计算。",
    "泰勒公式用多项式去逼近函数，余项刻画的是这种逼近的误差大小。",
    "麦克劳林公式是泰勒公式在原点处展开的特殊情形，形式更为简洁。",
    "不定积分是求导运算的逆运算，其结果要加上一个任意常数。",
    "换元积分法的关键是把被积表达式整体替换成一个新变量。",
    "分部积分法由乘积的求导法则变形而来，适用于两类函数相乘的情形。",
    "定积分的几何意义是曲边梯形的面积，当函数取负值时表示面积的相反数。",
    "变上限积分关于上限的导数就是被积函数本身，这是微积分基本定理。",
    "牛顿莱布尼茨公式把定积分的计算归结为求原函数在两端点的差。",
    "反常积分是积分区间无限或被积函数无界时的推广形式。",
    "微分方程是含有未知函数及其导数的方程，求解就是找出满足条件的函数。",
    "一阶线性微分方程可以用常数变易法求出通解的一般表达式。",
    "向量组的线性相关性刻画的是其中是否存在可以被其余向量表出的向量。",
    "矩阵的秩等于其行向量组的秩，也等于其列向量组的秩，二者必然相等。",
]

#: 印刷页码与 PDF 页序的差。真书几乎都有前言页——实测那本 231 页的教材差 10。
PRINTED_OFFSET = 8


def scanned_page(pdf_no: int, header: str, extras=(), offset: int = 0, footer=True) -> list:
    """一页扫描件的识别结果：页眉 + 若干特行 + 8 行正文 + 页脚。"""
    rows = [line(header, 100, 30)]  # 页眉带
    rows += list(extras)
    rows += [line(t, 700 + i * 40) for i, t in enumerate(BODY[offset : offset + 8])]
    if footer:
        rows.append(line(str(pdf_no + PRINTED_OFFSET), 2250))  # 页脚带：印刷页码
    return rows


FOUR_PAGES = [
    scanned_page(1, "第1章 函数与极限", [line("第1章 函数与极限", 400, 100), line("1.1 函数的概念", 600, 52)]),
    scanned_page(
        2,
        "第1章 函数与极限",
        [line("[Cd]", 500, 56), line("1.2 函数的性质", 600, 52)],
        offset=8,
    ),
    scanned_page(
        3,
        "第1章 函数与极限",
        [line("第2章 导数与微分", 400, 100), line("4.1 设五维空间的线性方程为：", 600, 36)],
        offset=16,
    ),
    scanned_page(4, "第2章 导数与微分", [line("2.1 导数的概念", 600, 52)], offset=24),
]


@pytest.fixture
def four_page_book():
    return ocr_pdf_bytes(make_pdf(4), FakeOcrEngine(FOUR_PAGES), default_title="扫描件样例", dpi=DPI)


# ---------------------------------------------------------------- probe_pdf


def test_probe_marks_image_only_pdf_as_scanned():
    probe = probe_pdf(make_pdf(6))
    assert probe is not None
    assert probe.scanned is True
    assert probe.pages == 6
    assert probe.chars_per_page == 0


def test_probe_leaves_text_pdf_alone(demo_pdf_bytes):
    probe = probe_pdf(demo_pdf_bytes)
    assert probe is not None
    assert probe.scanned is False
    assert probe.chars_per_page > 0


def test_probe_returns_none_for_garbage():
    assert probe_pdf(b"not a pdf at all") is None


# ---------------------------------------------------------------- 结构还原


def test_ocr_splits_chapters_and_keeps_printed_page_numbers(four_page_book):
    book = four_page_book
    assert [c.title for c in book.chapters] == ["第1章 函数与极限", "第2章 导数与微分"]
    # 章的页码范围也是印刷页码
    assert (book.chapters[0].page_start, book.chapters[0].page_end) == (1 + PRINTED_OFFSET, 2 + PRINTED_OFFSET)
    assert (book.chapters[1].page_start, book.chapters[1].page_end) == (3 + PRINTED_OFFSET, 4 + PRINTED_OFFSET)
    pages = [s.page for c in book.chapters for s in c.sections]
    assert pages == sorted(pages)
    assert pages[0] == 1 + PRINTED_OFFSET and pages[-1] == 4 + PRINTED_OFFSET


def test_ocr_maps_each_paragraph_to_its_own_printed_page(four_page_book):
    """页码保真的回归防线：溯源里的「教材依据 · 第 N 页」要能照着翻到纸上。"""
    sections = {s.text: s for c in four_page_book.chapters for s in c.sections}
    for prefix, pdf_no in [
        ("数学上我们把这种对应关系称为函数", 1),
        ("函数的单调性是指", 1),
        ("连续函数在闭区间上必定取得最大值", 2),
        ("拉格朗日中值定理是罗尔定理的推广", 3),
        ("定积分的几何意义是曲边梯形的面积", 4),
    ]:
        got = next(s.page for text, s in sections.items() if text.startswith(prefix))
        assert got == pdf_no + PRINTED_OFFSET, f"{prefix[:14]} 应在第 {pdf_no + PRINTED_OFFSET} 页，实际 {got}"


def test_ocr_heading_needs_both_text_pattern_and_height(four_page_book):
    """两个判据缺一不可，三种情形都覆盖到（详见 ocr_pdf 的实测对照表）。"""
    kinds = {s.text: s.kind for c in four_page_book.chapters for s in c.sections}
    assert kinds["1.1 函数的概念"] == "heading"  # 模式 ✅ 高度 x1.3 ✅
    assert kinds["1.2 函数的性质"] == "heading"
    assert kinds["2.1 导数的概念"] == "heading"
    assert kinds["4.1 设五维空间的线性方程为："] == "p"  # 模式 ✅ 高度 x0.9 ❌
    assert kinds["[Cd]"] == "p"  # 模式 ❌ 高度 x1.4 ✅
    # 章标题只作为章边界，不重复出现在正文里
    assert not any(t.startswith("第1章 函数与极限") for t in kinds)
    assert not any(t.startswith("第2章 导数与微分") for t in kinds)


def test_ocr_strips_headers_and_footers_by_position(four_page_book):
    """页眉带 / 页脚带按位置剔除，不能靠「重复度」兜底——真书每章页眉都不同。"""
    texts = [s.text for c in four_page_book.chapters for s in c.sections]
    assert not any("函数与极限" in t for t in texts), "页眉漏进正文了"
    assert not any(t.strip().isdigit() for t in texts), "页码漏进正文了"


def test_ocr_does_not_claim_page_fidelity_without_page_numbers():
    """读不到原书页码时必须说实话，不能默认「与纸质书一致」。"""
    no_footer = [scanned_page(i, "第1章 函数与极限", offset=(i - 1) * 8, footer=False) for i in range(1, 5)]
    book = ocr_pdf_bytes(make_pdf(4), FakeOcrEngine(no_footer), default_title="无页码样例", dpi=DPI)
    note = " ".join(book.notes)
    assert "可能与纸质书印刷页码不一致" in note
    assert "与纸质书印刷页码一致" not in note
    # 页码退回 PDF 页序
    assert min(s.page for c in book.chapters for s in c.sections) == 1


def test_ocr_drops_watermark_lines_repeated_on_every_page():
    watermark = line("内部资料 请勿外传", 1500)
    pages = [scanned_page(i, "第1章 函数与极限", offset=(i - 1) * 8) + [watermark] for i in range(1, 5)]
    book = ocr_pdf_bytes(make_pdf(4), FakeOcrEngine(pages), default_title="带水印", dpi=DPI)
    texts = [s.text for c in book.chapters for s in c.sections]
    assert not any("内部资料" in t for t in texts)
    assert len(texts) > 20, "水印之外的内容不该被连带删掉"


def test_ocr_reports_progress_per_page():
    seen = []
    ocr_pdf_bytes(make_pdf(4), FakeOcrEngine(FOUR_PAGES), default_title="x", dpi=DPI, on_page=lambda d, t: seen.append((d, t)))
    assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_ocr_passes_png_bytes_to_the_engine():
    """必须传 PNG 字节：喂 numpy 数组会因 RGB→BGR 未修正而导致识别质量下降。"""
    engine = FakeOcrEngine(FOUR_PAGES, record_png=True)
    ocr_pdf_bytes(make_pdf(4), engine, default_title="x", dpi=DPI)
    assert len(engine.pngs) == 4
    assert all(png[:8] == b"\x89PNG\r\n\x1a\n" for png in engine.pngs)


def test_ocr_raises_when_nothing_was_recognized():
    blank = [[line("", 500)] for _ in range(4)]
    with pytest.raises(ValueError, match="没有识别出任何文字"):
        ocr_pdf_bytes(make_pdf(4), FakeOcrEngine(blank), default_title="x", dpi=DPI)


def test_ocr_honest_note_when_no_chapter_titles_found():
    """识别不出章节也要能用——整本作一章，并在提示里说清楚。"""
    pages = [scanned_page(i, "某某教材", offset=(i - 1) * 8) for i in range(1, 4)]
    book = ocr_pdf_bytes(make_pdf(3), FakeOcrEngine(pages), default_title="无章节样例", dpi=DPI)
    assert len(book.chapters) == 1
    assert book.chapters[0].title == "无章节样例"
    assert any("没有识别出" in n for n in book.notes)


def test_ocr_band_ratios_leave_a_gap_between_header_and_body():
    """这两条阈值是实测出来的：页眉 ≤0.052，正文首行 ≥0.077。
    改这两个常量前先看 ocr_pdf 里记的实测数据，别凭感觉调。"""
    assert FOOTER_BAND_RATIO > 0.9
    assert HEADER_BAND_RATIO < 0.077, "页眉带一旦越过 0.077 就会吃掉正文首行"
    assert HEADER_BAND_RATIO > 0.052, "太窄就盖不住页眉"


# ------------------------------------------------- RapidOcrEngine 适配层


class _StubOutput:
    """冒充 `RapidOCROutput`。注意 `boxes` 可能是 None，也可能是 numpy 数组。"""

    def __init__(self, boxes, txts, scores=None):
        self.boxes = boxes
        self.txts = txts
        self.scores = scores


def test_rapid_engine_converts_output_to_lines(monkeypatch):
    engine = RapidOcrEngine()
    boxes = [[[10, 20], [110, 20], [110, 60], [10, 60]]]
    monkeypatch.setattr(engine, "_ensure_engine", lambda: lambda _png: _StubOutput(boxes, ["第1章"], [0.97]))
    lines = engine.recognize(b"png")
    assert len(lines) == 1
    assert lines[0].text == "第1章"
    assert (lines[0].x0, lines[0].y0, lines[0].x1, lines[0].y1) == (10, 20, 110, 60)
    assert lines[0].height == 40


def test_rapid_engine_tolerates_empty_result(monkeypatch):
    """无文字时三个字段都可能是 None。用 `or []` 会抛
    `ValueError: truth value of an array is ambiguous`，所以只能判 `is None`。"""
    engine = RapidOcrEngine()
    monkeypatch.setattr(engine, "_ensure_engine", lambda: lambda _png: _StubOutput(None, None, None))
    assert engine.recognize(b"png") == []


def test_rapid_engine_drops_blank_text(monkeypatch):
    engine = RapidOcrEngine()
    boxes = [[[0, 0], [10, 0], [10, 10], [0, 10]]] * 2
    monkeypatch.setattr(engine, "_ensure_engine", lambda: lambda _png: _StubOutput(boxes, ["  ", "有效"]))
    lines = engine.recognize(b"png")
    assert [ln.text for ln in lines] == ["有效"]
    assert lines[0].score == 0.0  # 没给分数时按 0 处理，而不是崩掉


def test_rapid_engine_is_unavailable_without_the_package(monkeypatch):
    class NoOcr:
        ocr_configured = True
        ocr_dpi = 200
        ocr_threads = 4

    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "rapidocr":
            raise ImportError("没装")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert RapidOcrEngine.try_create(NoOcr()) is None


def test_rapid_engine_is_unavailable_when_ocr_disabled():
    class Disabled:
        ocr_configured = False

    assert RapidOcrEngine.try_create(Disabled()) is None


# ---------------------------------------------------------- OcrTaskService


def build_service(tmp_path, engine, **kwargs):
    from app.db import Database

    db = Database(tmp_path / "ocr.db")
    db.init()
    return db, OcrTaskService(db, _StubSettings(), engine_factory=lambda: engine, runner=lambda job: job(), **kwargs)


class _StubSettings:
    ocr_configured = True
    ocr_dpi = DPI
    ocr_threads = 4


def test_submit_rejects_text_pdf(tmp_path, demo_pdf_bytes):
    """文字版 PDF 不该被丢进 OCR——它有文本层，正常解析又快又准。"""
    db, service = build_service(tmp_path, FakeOcrEngine(FOUR_PAGES))
    with pytest.raises(ValueError, match="不是扫描件"):
        service.submit(demo_pdf_bytes, "demo.pdf", "demo")
    assert db.list_books() == []


def test_submit_raises_when_engine_missing(tmp_path):
    db, service = build_service(tmp_path, None)
    with pytest.raises(OcrUnavailable) as e:
        service.submit(make_pdf(3), "书.pdf", "书")
    assert SCANNED_NO_OCR_MESSAGE in str(e.value)
    assert db.list_books() == []


def test_success_path_stores_book_and_reports_progress(tmp_path):
    db, service = build_service(tmp_path, FakeOcrEngine(FOUR_PAGES))
    task = service.submit(make_pdf(4), "扫描教材.pdf", "扫描教材")
    assert task["status"] == DONE
    assert (task["donePages"], task["totalPages"]) == (4, 4)
    assert task["percent"] == 100
    assert task["bookId"]

    book = db.get_book(task["bookId"])
    assert book["note"] == f"来源格式：{OCR_SOURCE_NOTE}"
    assert "与纸质书印刷页码一致" in book["content_warning"]
    assert db.chapters_of(task["bookId"])
    assert service.get(task["id"])["status"] == DONE


def test_failure_path_writes_nothing(tmp_path):
    """全有或全无：跑到一半失败，一本半截教材都不能留下。"""
    bad = FakeOcrEngine(FOUR_PAGES[:2] + [RuntimeError("模拟识别崩溃")])

    class Exploding:
        name = "boom"

        def __init__(self):
            self.calls = 0

        def recognize(self, _png):
            self.calls += 1
            page = bad.recognize(_png)
            if isinstance(page, Exception):
                raise page
            return page

    db, service = build_service(tmp_path, Exploding())
    task = service.submit(make_pdf(4), "坏书.pdf", "坏书")
    assert task["status"] == FAILED
    # 第 3 页炸的，前 2 页已完整识别——报的是「真的做完了多少页」，不是页序
    assert "2/4" in task["message"] and "模拟识别崩溃" in task["message"]
    # 关键断言：教材/章节/段落一行都没写
    assert db.list_books() == []
    assert task["bookId"] == ""


def test_failure_before_any_page_reports_without_counts(tmp_path):
    class NeverWorks:
        name = "boom"

        def recognize(self, _png):
            raise RuntimeError("引擎起不来")

    db, service = build_service(tmp_path, NeverWorks())
    task = service.submit(make_pdf(3), "坏书.pdf", "坏书")
    assert task["status"] == FAILED
    assert task["message"].startswith("识别失败：")
    assert db.list_books() == []


def test_get_returns_none_for_unknown_task(tmp_path):
    _, service = build_service(tmp_path, FakeOcrEngine(FOUR_PAGES))
    assert service.get("nope") is None


def test_engine_factory_failure_degrades_to_unavailable(tmp_path):
    def boom():
        raise RuntimeError("onnxruntime 装坏了")

    db, service = build_service(tmp_path, None)
    service._engine_factory = boom
    with pytest.raises(OcrUnavailable):
        service.submit(make_pdf(3), "书.pdf", "书")


# --------------------------------------------------------------- 任务对账


def test_fail_stale_ocr_tasks(tmp_path):
    from app.db import Database

    db = Database(tmp_path / "stale.db")
    db.init()
    now = "2026-01-01T00:00:00+00:00"
    for task_id, status in [("a", "running"), ("b", "pending"), ("c", "done"), ("d", "failed")]:
        db.add_ocr_task(
            {"id": task_id, "status": status, "created_at": now, "updated_at": now}
        )
    assert db.fail_stale_ocr_tasks("服务重启导致识别中断，请重新上传这本教材") == 2
    assert db.get_ocr_task("a")["status"] == FAILED
    assert db.get_ocr_task("a")["message"].startswith("服务重启")
    assert db.get_ocr_task("b")["status"] == FAILED
    # 已经结束的任务不能被改写
    assert db.get_ocr_task("c")["status"] == DONE
    assert db.get_ocr_task("d")["status"] == FAILED


def test_update_ocr_task_rejects_unknown_fields(tmp_path):
    from app.db import Database

    db = Database(tmp_path / "guard.db")
    db.init()
    db.add_ocr_task({"id": "x", "status": "running", "created_at": "t", "updated_at": "t"})
    with pytest.raises(ValueError, match="未知的 ocr_tasks 字段"):
        db.update_ocr_task("x", status="done", **{"id=?--": "boom"})


# ------------------------------------------------------------- 端到端


def build_ocr_app(tmp_path, engine, **kwargs):
    return create_app(
        db_path=tmp_path / "app.db",
        llm=MockLLM(),
        ocr_engine_factory=lambda: engine,
        ocr_runner=lambda job: job(),  # 同步执行：无线程、可断言
        **kwargs,
    )


def test_upload_scanned_pdf_returns_202_then_task_completes(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(build_ocr_app(tmp_path, FakeOcrEngine(FOUR_PAGES)))
    res = client.post(
        "/api/books",
        files={"file": ("扫描教材.pdf", make_pdf(4), "application/pdf")},
    )
    assert res.status_code == 202, res.text
    task = res.json()["task"]
    assert task["status"] == DONE  # runner 是同步的，POST 返回时已经跑完

    polled = client.get(f"/api/ocr/tasks/{task['id']}")
    assert polled.status_code == 200
    assert polled.json()["bookId"] == task["bookId"]

    meta = client.get(f"/api/books/{task['bookId']}").json()
    assert meta["title"] == "扫描教材"  # 扫描件元数据没标题时用文件名兜底
    assert "扫描件" in meta["note"]


def test_ask_cites_the_printed_page_of_a_scanned_book(tmp_path):
    """页码保真的端到端防线：答案里的「教材依据 · 第 N 页」必须是原书印刷页码。

    这是整个改成 OCR 方案的核心承诺——翻不到书上的页码等于溯源失效。
    """
    from fastapi.testclient import TestClient

    client = TestClient(build_ocr_app(tmp_path, FakeOcrEngine(FOUR_PAGES)))
    task = client.post(
        "/api/books", files={"file": ("扫描教材.pdf", make_pdf(4), "application/pdf")}
    ).json()["task"]
    book_id = task["bookId"]
    chapter_id = client.get(f"/api/books/{book_id}").json()["chapters"][0]["id"]

    data = client.post(
        "/api/ask",
        json={"bookId": book_id, "chapterId": chapter_id, "question": "什么是导数？"},
    ).json()
    assert data["sourceDetails"], data
    pages = {item["page"] for item in data["sourceDetails"]}
    assert pages, "溯源必须带页码"
    # 全部落在 1+OFFSET ~ 4+OFFSET 之间，而不是 PDF 页序的 1~4
    assert min(pages) > PRINTED_OFFSET, f"页码 {pages} 看着还是 PDF 页序，没换算成印刷页码"


def test_upload_scanned_pdf_without_ocr_gets_actionable_422(tmp_path):
    """没装 OCR 依赖时的提示必须给出下一步，而不是含糊的「解析失败」。"""
    from fastapi.testclient import TestClient

    client = TestClient(build_ocr_app(tmp_path, None))
    res = client.post(
        "/api/books", files={"file": ("扫描教材.pdf", make_pdf(4), "application/pdf")}
    )
    assert res.status_code == 422
    assert "requirements-ocr.txt" in res.json()["detail"]


def test_text_pdf_keeps_the_old_201_path(tmp_path, demo_pdf_bytes):
    """文字版 PDF 完全不受影响——它压根不该走到 OCR 那条分支上。"""
    from fastapi.testclient import TestClient

    engine = FakeOcrEngine(FOUR_PAGES)
    client = TestClient(build_ocr_app(tmp_path, engine))
    res = client.post(
        "/api/books", files={"file": ("demo.pdf", demo_pdf_bytes, "application/pdf")}
    )
    assert res.status_code == 201
    assert "chapters" in res.json()
    assert engine.calls == 0, "文字版 PDF 不该触发任何 OCR"


def test_ocr_task_404_is_explicit_about_restart(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(build_ocr_app(tmp_path, FakeOcrEngine(FOUR_PAGES)))
    res = client.get("/api/ocr/tasks/deadbeef")
    assert res.status_code == 404
    assert "重新上传" in res.json()["detail"]


# --------------------------------------------------------------- 导出 Markdown


def test_markdown_export_keeps_chapters_and_pages(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(build_ocr_app(tmp_path, FakeOcrEngine(FOUR_PAGES)))
    task = client.post(
        "/api/books", files={"file": ("模式识别.pdf", make_pdf(4), "application/pdf")}
    ).json()["task"]

    res = client.get(f"/api/books/{task['bookId']}/markdown")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/markdown")
    body = res.text
    assert body.startswith("# ")
    assert "## 第1章 函数与极限" in body
    assert "## 第2章 导数与微分" in body
    assert "### 1.1 函数的概念" in body
    # 页码以 HTML 注释保留：渲染时看不见，核对时看得见
    assert f"<!-- page: {1 + PRINTED_OFFSET} -->" in body
    # 中文书名不能把响应头撑爆（Content-Disposition 只能放 latin-1）
    assert "filename*=UTF-8''" in res.headers["content-disposition"]


def test_render_markdown_escapes_nothing_but_keeps_hard_breaks():
    from app.services.export import render_markdown

    book = {"id": "b1", "title": "教材", "note": "来源格式：pdf", "content_warning": "内容可能没被完整读取"}
    chapters = [{"id": "c1", "title": "第1章"}]
    sections = {
        "c1": [
            {"id": "s1", "page": 3, "kind": "p", "text": "第一行\n第二行"},
            {"id": "s2", "page": 4, "kind": "heading", "text": "1.1 小节"},
            {"id": "s3", "page": 5, "kind": "formula", "text": "f(x) = x_1 + x_2"},
        ]
    }
    out = render_markdown(book, chapters, sections)
    assert "> ⚠️ 内容可能没被完整读取" in out
    assert "第一行  \n第二行" in out, "段内换行要转成硬换行，否则 Markdown 会并成一行"
    assert "### 1.1 小节" in out
    # 公式包进代码块，避免 `_` 被当成斜体语法
    assert "```\nf(x) = x_1 + x_2\n```" in out
    assert out.endswith("\n")


def test_store_parsed_book_rejects_empty_book(tmp_path):
    from app.db import Database
    from app.parsing.base import ParsedBook

    db = Database(tmp_path / "empty.db")
    db.init()
    with pytest.raises(ValueError, match="未能从文件中识别出章节内容"):
        store_parsed_book(db, ParsedBook(title="空", chapters=[]), note="ocr")
    assert db.list_books() == []


def test_extra_notes_are_appended_to_the_content_warning():
    """OCR 的提示要和「正文过少」并进同一个提示位，不能互相顶掉。"""
    from app.parsing.base import ParsedBook, ParsedChapter, ParsedSection
    from app.services.ingest import content_warning_of

    book = ParsedBook(
        title="薄教材",
        chapters=[
            ParsedChapter(
                num=1,
                title="第1章",
                page_start=1,
                page_end=1,
                sections=[ParsedSection(seq=1, page=1, text="很短。", kind="p")],
            )
        ],
        notes=["解析器自己的说明"],
    )
    warning = content_warning_of(book, extra_notes=["OCR 的说明"])
    assert "内容可能大部分没被读出来" in warning
    assert "解析器自己的说明" in warning
    assert "OCR 的说明" in warning
