"""agent 端到端测试：run 走完 分析→拆书→建库，ask 能检索返回锚点。"""
from pathlib import Path

from make_sample_book import build_sample_book
from kb_agent.agent import KBAgent
from kb_agent.textstats import count_text, total_of
from kb_agent.parse import read_paragraphs


def test_agent_end_to_end(tmp_path: Path):
    book = build_sample_book(tmp_path / "sample.docx")
    agent = KBAgent(book_id="b1", char_limit=100_000)
    res = agent.run(book, tmp_path / "out")

    # ① 分析：与 textstats 自洽
    manual = total_of(count_text(p.text) for p in read_paragraphs(book))
    assert res.analyze["chars_no_ws"] == manual["chars_no_ws"]
    assert res.analyze["cjk"] == manual["cjk"]

    # ② 拆书：2 章、2 份文件存在
    assert len(res.split["chapters"]) == 2
    for ch in res.split["chapters"]:
        for f in ch["files"]:
            assert (tmp_path / "out" / "chapters" / f).exists()

    # ③ 建库：块数 > 0，kb 文件落盘
    assert res.build["chunks"] > 0
    assert Path(res.kb_path).exists()

    # ask：命中第二章（导数）并带回锚点
    ans = agent.ask("什么是导数？")
    assert ans["found"]
    assert any(a.startswith("b1-ch2-p") for a in ans["sources"])
    assert any("导数" in h["text"] for h in ans["hits"])

    # 无模型模式下 answer 为 None；带 llm 回调时使用检索上下文生成
    assert ans["answer"] is None

    def fake_llm(query, contexts):
        return f"根据教材：{contexts[0]['text'][:30]}"

    agent.llm = fake_llm
    ans2 = agent.ask("什么是导数？")
    assert ans2["answer"].startswith("根据教材：")
