"""PDF 解析：PyMuPDF 提取文本、目录（书签）与章节结构。

支持两类 PDF：
1. 带目录书签（PDF 内置大纲）→ 直接以书签为章节边界；
2. 无书签 → 通过字号/粗细启发式检测章节标题。

输出 ParsedBook：章节 → 段落（含页码），段落为最小「锚点」粒度。
仅处理文本型 PDF；扫描件/OCR 不在范围内（见产品设计文档）。
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24
except ImportError:  # pragma: no cover
    import fitz

BIGRAM_RE = re.compile(r"[\u4e00-\u9fff]")
WORD_RE = re.compile(r"[A-Za-z0-9_]+")
HEADING_MAX_LEN = 40
HEADING_MIN_SIZE_RATIO = 1.18
HEADING_PAGE_HEIGHT = 120  # 页面前 1/12 视为页眉，忽略


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


def _strip_title_prefix(text: str, title: str) -> str:
    """从段落开头剥离章节标题（忽略提取文本中插入的空格）。"""
    title_norm = title.replace(" ", "")
    count = 0
    for i, ch in enumerate(text):
        if ch != " ":
            count += 1
        if count >= len(title_norm):
            return text[i + 1:].lstrip(" ")
    return text


def _looks_like_formula(text: str) -> bool:
    """无中日韩字符、包含数学符号、较短 → 视为公式行。"""
    if len(text) > 80:
        return False
    if BIGRAM_RE.search(text):
        return False
    return bool(re.search(r"[=\u2211\u222b\u2192\u2264\u2265]|[a-zA-Z]\s*\(|x\^|_\{", text))


END_PUNCT = "。？！；：”』」…"
FOOTER_RE = re.compile(r"[\d\s\-—.·]+$")


def _split_paragraphs(page_text: str) -> List[str]:
    """按行切段：句子结束符（。？！…）视为段落结尾；忽略页码/页眉。"""
    paras: List[str] = []
    cur: List[str] = []
    for raw in page_text.splitlines():
        line = raw.strip()
        if not line:
            if cur:
                paras.append("".join(cur))
                cur = []
            continue
        # 页码/页眉（纯数字或页码样式）
        if len(line) <= 8 and re.fullmatch(r"[\d\s\-—.·]+", line):
            if cur:
                paras.append("".join(cur))
                cur = []
            continue
        cur.append(line)
        if line[-1] in END_PUNCT and len(line) > 6:
            paras.append("".join(cur))
            cur = []
    if cur:
        paras.append("".join(cur))
    return paras


def _detect_heading_y(page, body_size: float) -> dict:
    """返回 {y: title}：字号显著大于正文的短文本行视为标题。"""
    result = {}
    try:
        data = page.get_text("dict")
    except Exception:
        return result
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            span = max(spans, key=lambda s: s.get("size", 0))
            size = span.get("size", 0)
            text = "".join(s.get("text", "") for s in spans).strip()
            y = round(line.get("bbox", [0, 0, 0, 0])[1], 1)
            if not text or len(text) > HEADING_MAX_LEN:
                continue
            if size < body_size * HEADING_MIN_SIZE_RATIO:
                continue
            if BIGRAM_RE.search(text) is None and WORD_RE.search(text) is None:
                continue
            if re.fullmatch(r"[\d\s.—\-]+", text):
                continue  # 页码/页眉
            result[y] = text
    return result


def parse_pdf_stream(data: bytes, default_title: str = "未命名教材") -> ParsedBook:
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        n_pages = doc.page_count
        if n_pages == 0:
            raise ValueError("PDF 为空")

        # 正文基准字号：取全书正文 span 中位数
        sizes = []
        for page in doc:
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        sizes.append(span.get("size", 0))
        body_size = sorted(sizes)[len(sizes) // 2] if sizes else 11.0

        # 1) 目录书签 → 章节；2) 标题启发式
        toc = doc.get_toc()
        chapter_marks = []  # [(page0, title)]
        if toc:
            for level, title, page in toc:
                if level == 1:
                    chapter_marks.append((max(0, page - 1), title))
        if not chapter_marks:
            for pno in range(min(n_pages, 200)):
                page = doc[pno]
                heading_y = _detect_heading_y(page, body_size)
                ys = sorted(heading_y)
                top_y = page.rect.height / HEADING_PAGE_HEIGHT
                for y in ys:
                    if y < top_y:
                        continue  # 忽略页眉
                    chapter_marks.append((pno, heading_y[y]))

        # 标题优先级：PDF 元数据 → 首页首个非数字行 → 默认名
        meta_title = (doc.metadata or {}).get("title", "").strip()
        page_texts = [doc[i].get_text("text") for i in range(n_pages)]
        first_page_head = next(
            (ln.strip() for ln in page_texts[0].splitlines() if ln.strip() and not re.fullmatch(r"[\d\s\-—.]+", ln.strip())),
            "",
        )[:30] if page_texts[0].strip() else ""
        title = meta_title or (first_page_head if first_page_head else default_title)

        chapters: List[ParsedChapter] = []
        if not chapter_marks:
            # 整本作为一章
            chapter_marks = [(0, title)]
        for idx, (pno, ctitle) in enumerate(chapter_marks):
            end_pno = chapter_marks[idx + 1][0] - 1 if idx + 1 < len(chapter_marks) else n_pages - 1
            chapters.append(ParsedChapter(num=idx + 1, title=ctitle, page_start=pno + 1, page_end=end_pno + 1))

        # 段落切分（若章节已有子段落标题，合并进所属章节）
        for ch in chapters:
            seq = 0
            for pno in range(ch.page_start - 1, ch.page_end):
                text = page_texts[pno] if pno < len(page_texts) else ""
                for para in _split_paragraphs(text):
                    kind = "formula" if _looks_like_formula(para) else "p"
                    seq += 1
                    ch.sections.append(ParsedSection(seq=seq, page=pno + 1, text=para, kind=kind))
            # 首段若以章节标题开头（提取时与正文合并），剥离标题
            first = ch.sections[0] if ch.sections else None
            if first and first.text.replace(" ", "").startswith(ch.title.replace(" ", "")):
                first.text = _strip_title_prefix(first.text, ch.title) or first.text

        chapters = [c for c in chapters if c.sections]
        return ParsedBook(title=title, chapters=chapters)
    finally:
        doc.close()
