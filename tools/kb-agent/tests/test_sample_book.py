"""样例教材生成器测试：生成的 docx 可正常打开，且标题/正文齐全。"""
from pathlib import Path

from docx import Document

from make_sample_book import CHAPTERS, build_sample_book


def test_build_sample_book(tmp_path: Path):
    out = build_sample_book(tmp_path / "sample.docx")
    assert out.exists()

    doc = Document(out)
    texts = [p.text for p in doc.paragraphs]

    # 标题在最前面
    assert texts[0] == "微积分简明讲义（样例）"

    # 每章标题（Heading 1）与正文都在
    for chapter in CHAPTERS:
        assert chapter["title"] in texts
        for para in chapter["paragraphs"]:
            assert para in texts, f"缺少正文段落：{para[:20]}..."

    # 总内容量非零
    joined = "".join(texts)
    assert len(joined) > 100
