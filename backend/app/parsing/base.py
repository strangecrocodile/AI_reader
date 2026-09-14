"""解析层共享结构与跨格式通用规则。

PDF（`parsing/pdf.py`）、Word（`parsing/docx.py`）与纯文本（`parsing/text.py`）
都产出同一套 `ParsedBook`，因此入库、锚点、检索、溯源问答和知识点抽取这些下游逻辑
完全共用，不需要按格式分叉。

页码约定：
- PDF 有物理页码，直接使用；
- Word / txt / md 没有页码，按「每 1200 字折一页」估算**虚拟页码**，
  只用于阅读进度与「教材依据 · 第 N 页」的展示，不承诺与纸质书一致。
"""
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

#: 无物理页码的格式（Word / 纯文本）折算虚拟页的字符预算
CHARS_PER_PAGE = 1200

#: 章级标题：第X章 / 第X篇 / 第X部 / 第X卷 / Chapter N / Part N / 附录A
#: 注意不含「节」——Word 大纲里「节」是章内小节（见 SECTION_TITLE_RE）。
CHAPTER_TITLE_RE = re.compile(
    r"^\s*(第\s*[0-9一二三四五六七八九十百]+\s*[章篇部卷]|chapter\s*\d+|part\s*\d+|附录\s*[A-Za-zＡ-Ｚ])",
    re.IGNORECASE,
)
#: 节级标题：第X节 / 1.2 标题
SECTION_TITLE_RE = re.compile(
    r"^\s*(第\s*[0-9一二三四五六七八九十百]+\s*节|[0-9]+(?:\.[0-9]+)+\s*\S)",
    re.IGNORECASE,
)
#: 不是正文章节的条目（目录、封面、索引等）
TOC_NOISE_RE = re.compile(
    r"^(目\s*录|contents|cover|封面|书名页|版权页|索引|参考文献|后记|致谢)$",
    re.IGNORECASE,
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_FORMULA_RE = re.compile(r"[=\u2211\u222b\u2192\u2264\u2265]|[a-zA-Z]\s*\(|x\^|_\{")
FORMULA_MAX_LEN = 80


@dataclass
class ParsedSection:
    seq: int
    page: int
    text: str
    kind: str = "p"  # p | formula | heading


@dataclass
class ParsedChapter:
    num: int
    title: str
    page_start: int
    page_end: int
    sections: List[ParsedSection] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n".join(s.text for s in self.sections if s.kind != "heading")


@dataclass
class ParsedBook:
    title: str
    chapters: List[ParsedChapter]
    #: 解析受限说明（跳过了什么、章节是靠什么推断的）。前端据此提示用户
    #: 「内容可能没被完整读取」，而不是让人对着一本空教材猜原因。
    notes: List[str] = field(default_factory=list)


@dataclass
class Block:
    """解析中间态：一个「章」及其段落，段落 kind 为 p | formula | heading。"""

    title: str
    paragraphs: List[Tuple[str, str]] = field(default_factory=list)


def is_toc_noise(title: str) -> bool:
    """目录 / 封面 / 索引等条目不是正文章节。"""
    return bool(TOC_NOISE_RE.match((title or "").strip()))


def looks_like_formula(text: str) -> bool:
    """无中日韩字符、包含数学符号、较短 → 视为公式行。"""
    if len(text) > FORMULA_MAX_LEN:
        return False
    if _CJK_RE.search(text):
        return False
    if not _WORD_RE.search(text) and not _FORMULA_RE.search(text):
        return False
    return bool(_FORMULA_RE.search(text))


def pick_heading_level(
    by_level: Dict[int, List[str]],
    pattern: re.Pattern,
    fallback_max_entries: int = 80,
    min_hits: int = 3,
) -> Optional[int]:
    """从多层标题里挑出「章」所在的层级（PDF 书签与 Word/Markdown 大纲共用）。

    只取最浅一层是不够的：不少教材最浅层是「部分 / 篇 / 书名」，真正的章在下一层。

    策略：优先选标题符合章模式的层（取最浅的一个）；否则退回条目数合理的最浅层。

    `min_hits` 是「至少几条像章」的阈值：PDF 书签属于目录条目，条目少时容易误判，
    因此默认保守取 3；Word/Markdown 的标题是结构信息，传 2 即可（两章的书也常见）。
    """
    if not by_level:
        return None
    # 1) 标题模式最匹配的层
    for level in sorted(by_level):
        titles = by_level[level]
        hits = sum(1 for title in titles if pattern.match(title))
        if hits >= min_hits and hits / len(titles) >= 0.5:
            return level
    # 2) 最浅层条目过少时（如第 1 层只有「目录」「书名」一项），改取条目数合理的更深层
    shallowest = min(by_level)
    if len(by_level[shallowest]) < 2:
        for level in sorted(by_level):
            if 3 <= len(by_level[level]) <= fallback_max_entries:
                return level
    # 3) 兜底：最浅层（避免把只有两章的薄书拆错）
    return shallowest


def group_levels(rows: Iterable[Tuple[str, int]]) -> Dict[int, List[str]]:
    """把 (标题, 层级) 流按层级分组，供 pick_heading_level 判定章所在层级。"""
    by_level: Dict[int, List[str]] = defaultdict(list)
    for text, level in rows:
        if level >= 1 and text.strip() and not is_toc_noise(text):
            by_level[level].append(text.strip())
    return dict(by_level)


def _text_chapter_count(rows: Iterable[Tuple[str, int]]) -> int:
    """正文里「第X章 / Chapter N」这类条目的数量（标题层级不可信时的兜底信号）。"""
    return sum(1 for text, level in rows if level == 0 and CHAPTER_TITLE_RE.match(text or ""))


def chapter_level_of(rows: List[Tuple[str, int]]) -> Optional[int]:
    """判定「章」所在的标题层级；返回 None 表示改用文本模式识别章节。

    与 PDF 书签（`pick_heading_level`）的区别：Word/Markdown 的标题层级是结构信息，
    所以“只有一条章标题”的薄书也能认；同时要处理「最浅层孤零零一个书名」的情况。
    """
    by_level = group_levels(rows)
    if not by_level:
        return None
    levels = sorted(by_level)

    # 1) 成规模（≥2 条）且过半像章的层
    for level in levels:
        titles = by_level[level]
        hits = sum(1 for title in titles if CHAPTER_TITLE_RE.match(title))
        if hits >= 2 and hits / len(titles) >= 0.5:
            return level

    # 2) 只有一条章标题的层也算（单章样例、薄书）
    for level in levels:
        if any(CHAPTER_TITLE_RE.match(title) for title in by_level[level]):
            return level

    # 3) 最浅层只有孤零零一个书名，而正文里成规模出现「第X章」→ 交给文本模式
    shallowest = by_level[levels[0]]
    if len(shallowest) == 1 and _text_chapter_count(rows) >= 2:
        return None

    # 4) 兜底：最浅层（标题是「函数 / 极限 / 导数」这类自定义命名时）
    return levels[0]


def build_blocks(rows: List[Tuple[str, int]]) -> List[Block]:
    """把 (段落文本, 标题层级) 流切成一章一个 Block。

    - 章层级由 `chapter_level_of` 判定；比它更浅的标题（书名 / 篇名）不进正文；
    - 比它更深的标题作为章内小节，kind='heading'；
    - 没有标题层级时退回文本模式（第X章 / Chapter N / 附录A）；
    - 首个章标题之前的内容并入第一章，避免前言丢失；
    - 完全识别不到章时，整本书作为一章（标题由调用方给的书名兜底）。
    """
    rows = [(text or "", int(level or 0)) for text, level in rows]
    chapter_level = chapter_level_of(rows)
    blocks: List[Block] = []
    front: List[Tuple[str, str]] = []

    def kind_of(text: str, level: int) -> str:
        if chapter_level is not None and level > chapter_level:
            return "heading"
        if chapter_level is None and len(text) <= 40 and SECTION_TITLE_RE.match(text):
            return "heading"
        return "formula" if looks_like_formula(text) else "p"

    for text, level in rows:
        text = text.strip()
        if not text:
            continue
        # 比「章」更浅的标题是书名/篇名，不作为正文段落
        if chapter_level is not None and 1 <= level < chapter_level:
            continue
        starts_chapter = (
            level == chapter_level
            if chapter_level is not None
            else bool(CHAPTER_TITLE_RE.match(text))
        )
        if starts_chapter and not is_toc_noise(text):
            blocks.append(Block(title=text, paragraphs=[]))
            continue
        entry = (text, kind_of(text, level))
        if blocks:
            blocks[-1].paragraphs.append(entry)
        else:
            front.append(entry)

    if not blocks:
        return [Block(title="", paragraphs=front)] if front else []
    if front:
        blocks[0].paragraphs = front + blocks[0].paragraphs
    return blocks


def assemble_book(
    title: str,
    blocks: List[Block],
    default_title: str = "未命名教材",
    notes: Optional[List[str]] = None,
) -> ParsedBook:
    """把「章 → 段落」中间态装配成 ParsedBook：编号、虚拟页码、过滤空章。"""
    book_title = (title or "").strip() or default_title
    book = ParsedBook(title=book_title, chapters=[], notes=list(notes or []))
    chars_used = 0
    for block in blocks:
        chapter = ParsedChapter(
            num=len(book.chapters) + 1,
            title=block.title.strip() or book_title,
            page_start=1,
            page_end=1,
        )
        for text, kind in block.paragraphs:
            text = (text or "").strip()
            if not text:
                continue
            page = 1 + chars_used // CHARS_PER_PAGE
            chars_used += len(text)
            chapter.sections.append(
                ParsedSection(seq=len(chapter.sections) + 1, page=page, text=text, kind=kind)
            )
        if not chapter.sections:
            continue
        chapter.page_start = chapter.sections[0].page
        chapter.page_end = chapter.sections[-1].page
        book.chapters.append(chapter)
    for index, chapter in enumerate(book.chapters, start=1):
        chapter.num = index
    return book
