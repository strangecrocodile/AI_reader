"""字数统计工具（textstats）单元测试。"""
import pytest

from kb_agent.textstats import count_text, estimate_tokens, total_of


class TestCountText:
    def test_pure_chinese(self):
        assert count_text("你好世界") == {"cjk": 4, "chars_no_ws": 4, "en_words": 0}

    def test_mixed_chinese_english(self):
        # “设函数 f(x) 在点 x0” → 中文 5 字，英文/数字片段 f、x、x0 共 3 个
        c = count_text("设函数 f(x) 在点 x0")
        assert c["cjk"] == 5
        assert c["en_words"] == 3

    def test_whitespace_ignored_in_chars(self):
        # “abc 123\n456” 去掉空白后 9 个字符，英文/数字片段 3 个
        c = count_text("abc 123\n456")
        assert c["chars_no_ws"] == 9
        assert c["en_words"] == 3
        assert c["cjk"] == 0

    def test_punctuation_counts_in_chars(self):
        # 标点算“总字符”，不算“中文字数”
        c = count_text("导数，微分。")
        assert c["cjk"] == 4
        assert c["chars_no_ws"] == 6

    def test_empty_and_none(self):
        assert count_text("") == {"cjk": 0, "chars_no_ws": 0, "en_words": 0}
        assert count_text(None) == {"cjk": 0, "chars_no_ws": 0, "en_words": 0}


class TestTotalAndTokens:
    def test_total_of_sums(self):
        parts = [count_text("你好"), count_text("world 2026"), count_text(None)]
        # "你好" 去空白 2 字符 + "world 2026" 去空白 9 字符 = 11
        assert total_of(parts) == {"cjk": 2, "chars_no_ws": 11, "en_words": 2}

    def test_total_of_empty(self):
        assert total_of([]) == {"cjk": 0, "chars_no_ws": 0, "en_words": 0}

    def test_estimate_tokens(self):
        # 中文 100 字 ≈ 100 token；4 个英文词 ≈ 16 字符 → +4
        assert estimate_tokens({"cjk": 100, "en_words": 4}) == 101
