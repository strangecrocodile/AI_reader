"""TXT 输入测试：自动编码识别 + 按行分段 + 章节文本识别 + 拆书。"""
import json
from pathlib import Path

from kb_agent.parse import read_paragraphs
from kb_agent.split import detect_chapters, split_book

# 原创测试文本（无版权问题）
_SAMPLE_TXT = """微积分简明讲义（测试版）
第一章 函数与极限
函数是描述两个变量之间依赖关系的数学对象。
极限刻画的是变量变化过程中无限趋近于某个确定值的趋势。
第二章 导数与微分
导数描述函数在某一点的瞬时变化率。
导数的几何意义是曲线在该点处切线的斜率。
"""


def _write(path: Path, encoding: str) -> Path:
    path.write_text(_SAMPLE_TXT, encoding=encoding)
    return path


def test_read_txt_utf8(tmp_path: Path):
    p = _write(tmp_path / "a.txt", "utf-8")
    rows = read_paragraphs(p)
    assert rows[0].text == "微积分简明讲义（测试版）"
    assert len(rows) == 7  # 1 标题 + 2 章标题 + 4 正文
    assert all(r.level == 0 for r in rows)  # TXT 无样式 → 全按正文


def test_read_txt_gb18030(tmp_path: Path):
    """GBK/GB2312 编码也要能读（中文 txt 常见编码）。"""
    p = _write(tmp_path / "b.txt", "gb18030")
    rows = read_paragraphs(p)
    assert len(rows) == 7
    assert rows[2].text.startswith("函数是描述")


def test_txt_chapter_detection_by_text(tmp_path: Path):
    p = _write(tmp_path / "c.txt", "utf-8")
    chapters = detect_chapters(read_paragraphs(p))
    assert [c.title for c in chapters] == ["第一章 函数与极限", "第二章 导数与微分"]


def test_txt_split_book_end_to_end(tmp_path: Path):
    p = _write(tmp_path / "d.txt", "utf-8")
    out = tmp_path / "chapters"
    report = split_book(p, out, book_id="t1", limit=100_000)
    m = report["manifest"]
    assert [c["title"] for c in m["chapters"]] == ["第一章 函数与极限", "第二章 导数与微分"]
    assert (out / "t1-ch1.docx").exists()
    assert (out / "t1-ch2.docx").exists()
    assert m["book"]["counts"]["cjk"] > 50
