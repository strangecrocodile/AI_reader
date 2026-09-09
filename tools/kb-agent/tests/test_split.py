"""split 模块测试：章节识别、拆书、manifest 锚点清单。"""
import json
from pathlib import Path

from docx import Document

from kb_agent.parse import ParaRow, read_paragraphs
from kb_agent.split import (
    detect_chapters,
    split_book,
    split_chapter,
)
from kb_agent.textstats import count_text, total_of
from make_sample_book import build_sample_book


def _build_big_chapter_book(tmp_path: Path, chapter_paras: int, para_len: int) -> Path:
    """生成一本两章的书，第一章每段约 para_len 字符（用于触发按字数切分）。"""
    doc = Document()
    doc.add_heading("大章测试书", level=0)
    doc.add_heading("第一章 巨型章节", level=1)
    for _ in range(chapter_paras):
        doc.add_paragraph("内容" * (para_len // 2))
    doc.add_heading("第二章 短章节", level=1)
    doc.add_paragraph("这是短章节的一段内容。")
    p = tmp_path / "big.docx"
    doc.save(p)
    return p


class TestDetectChapters:
    def test_heading_styles_split_chapters(self, tmp_path: Path):
        book = build_sample_book(tmp_path / "s.docx")
        chapters = detect_chapters(read_paragraphs(book))
        assert [c.title for c in chapters] == ["第一章 函数与极限", "第二章 导数与微分"]
        # 每章应包含各自的正文（非空）
        assert all(c.paragraphs for c in chapters)

    def test_no_heading_falls_back_to_text_pattern(self):
        rows = [
            ParaRow("书的开篇导语", "Normal", 0, 0),
            ParaRow("第一章 基础", "Normal", 0, 1),
            ParaRow("这是第一章的正文", "Normal", 0, 2),
            ParaRow("第二章 进阶", "Normal", 0, 3),
            ParaRow("这是第二章的正文", "Normal", 0, 4),
        ]
        chapters = detect_chapters(rows)
        assert [c.title for c in chapters] == ["第一章 基础", "第二章 进阶"]
        # 开篇导语并入第一份（前言无标题时跟随第一章）
        assert "书的开篇导语" in [p.text for p in chapters[0].paragraphs]


class TestSplitChapter:
    def test_split_large_chapter_into_parts(self):
        paras = [ParaRow(f"内容{i}" + "字" * 300, "Normal", 0, i) for i in range(10)]
        ch = type("Ch", (), {"id": "ch1", "title": "大章", "paragraphs": paras})()
        parts = split_chapter(ch, limit=1000)
        assert len(parts) >= 2
        # 不丢字：各份总字符 == 原章总字符
        orig = total_of(count_text(p.text) for p in paras)
        joined = total_of(count_text(p.text) for part in parts for p in part)
        assert joined["chars_no_ws"] == orig["chars_no_ws"]

    def test_single_huge_paragraph_split_by_chars(self):
        text = "字" * 2500
        paras = [ParaRow(text, "Normal", 0, 0)]
        ch = type("Ch", (), {"id": "ch1", "title": "超长段章", "paragraphs": paras})()
        parts = split_chapter(ch, limit=1000)
        assert len(parts) >= 3
        out_text = "".join(p.text for part in parts for p in part)
        assert out_text == text  # 不丢字


class TestSplitBook:
    def test_split_sample_book_creates_files_and_manifest(self, tmp_path: Path):
        book = build_sample_book(tmp_path / "sample.docx")
        out = tmp_path / "chapters"
        report = split_book(book, out, book_id="b1", limit=100_000)  # 上限很大 → 一章一份

        # 两个章节文件
        files = sorted(p.name for p in out.glob("*.docx"))
        assert files == ["b1-ch1.docx", "b1-ch2.docx"]

        # manifest 结构与统计
        m = report["manifest"]
        assert m["book"]["title"] == "微积分简明讲义（样例）"
        assert m["book"]["counts"]["cjk"] > 100
        assert [c["title"] for c in m["chapters"]] == ["第一章 函数与极限", "第二章 导数与微分"]

        # 锚点唯一且格式正确
        anchors = [p["anchor"] for c in m["chapters"] for part in c["parts"] for p in part["paragraphs"]]
        assert len(anchors) == len(set(anchors))
        assert all(a.startswith("b1-") and a.endswith(tuple(f"-p{i:03d}" for i in range(1, 60))) for a in anchors)

        # manifest.json 真的写盘了
        mp = Path(report["manifest_path"])
        assert mp.exists()
        assert json.loads(mp.read_text(encoding="utf-8"))["book"]["id"] == "b1"

        # 生成的文件可被再次读取且包含章标题
        ch1 = Document(out / "b1-ch1.docx")
        texts = [p.text for p in ch1.paragraphs]
        assert any("第一章 函数与极限" in t for t in texts)

    def test_split_big_chapter_into_multiple_files(self, tmp_path: Path):
        big = _build_big_chapter_book(tmp_path, chapter_paras=8, para_len=600)  # 第一章 ~2400 字
        out = tmp_path / "chapters"
        report = split_book(big, out, book_id="b1", limit=1000)

        parts = report["chapters"][0]["parts"]
        assert len(parts) >= 2  # 第一章被切成多份
        files = [part["file"] for part in parts]
        for f in files:
            assert (out / f).exists()
        # 不丢字：分份前后字符总数一致
        ch = report["chapters"][0]
        part_sum = sum(part["counts"]["chars_no_ws"] for part in ch["parts"])
        assert part_sum == ch["counts"]["chars_no_ws"]
