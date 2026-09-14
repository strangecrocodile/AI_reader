"""PDF 解析：PyMuPDF 提取文本、目录（书签）与章节结构。

支持两类 PDF：
1. 带目录书签（PDF 内置大纲）→ 直接以书签为章节边界；
2. 无书签 → 通过字号/粗细启发式检测章节标题。

输出 ParsedBook：章节 → 段落（含页码），段落为最小「锚点」粒度。
仅处理文本型 PDF；扫描件/OCR 不在范围内（见产品设计文档）。
"""
import re
from collections import defaultdict
from typing import Dict, List, Optional

from .base import (
    ParsedBook,
    ParsedChapter,
    ParsedSection,
    is_toc_noise,
    looks_like_formula,
    pick_heading_level,
)

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24
except ImportError:  # pragma: no cover
    import fitz

BIGRAM_RE = re.compile(r"[\u4e00-\u9fff]")
WORD_RE = re.compile(r"[A-Za-z0-9_]+")
HEADING_MAX_LEN = 40
HEADING_MIN_SIZE_RATIO = 1.18
HEADING_PAGE_HEIGHT = 120  # 页面前 1/12 视为页眉，忽略
#: 无书签时最多扫描多少页找标题（全书扫描在大部头上太慢，这里做取舍）
HEADING_SCAN_PAGES = 200
#: 平均每页少于这么多字，认为文本层异常（多半是扫描件）
SPARSE_CHARS_PER_PAGE = 40

# 章标题模式（第1章 / 第1节 / Chapter 1 / Part 1 / 附录A）。
# PDF 目录书签里「节」也可能单独成层，所以这里保留「节」；Word 大纲另有更细的层级可用。
CHAPTER_TITLE_RE = re.compile(
    r"^\s*(第\s*[0-9一二三四五六七八九十百]+\s*[章节篇]|chapter\s*\d+|part\s*\d+|附录\s*[A-Za-zＡ-Ｚ])",
    re.IGNORECASE,
)
# 目录点线引导符。要求足够长的连续点/省略号，避免误伤正文里的「……」「⋯⋯」
DOT_LEADER_RE = re.compile(r"(?:\.\s*){5,}|…{4,}|⋯{4,}")


def _pick_chapter_level(toc) -> Optional[int]:
    """从多层书签里挑出「章」所在的层级（层级选择规则见 base.pick_heading_level）。"""
    by_level = defaultdict(list)
    for level, title, _page in toc:
        by_level[level].append(title)
    if not by_level:
        return None
    return pick_heading_level(dict(by_level), CHAPTER_TITLE_RE)


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


# 句末标点。注意包含「．」(U+FF0E 全角句点)：不少中文教材（尤其理工类）用它作句号，
# 只认「。」(U+3002) 会导致整页文字黏成一段。
END_PUNCT = "。．？！；：!?;”』」…"
FOOTER_RE = re.compile(r"[\d\s\-—.·]+$")
# 单独成行的 URL（页脚）
URL_ONLY_RE = re.compile(r"(?:https?://|www\.)\S+")
# 紧贴正文尾部的 URL（页脚被拼进段落时）
TRAILING_URL_RE = re.compile(r"(?<=[\u4e00-\u9fff])\s*(?:https?://|www\.)\S+\s*$")


def _normalize_line(line: str) -> str:
    """行归一化：忽略空白差异，用于跨页比对页眉/页脚。"""
    return re.sub(r"\s+", "", line)


def _repeated_margin_lines(page_texts: List[str], min_pages: int = 3, ratio: float = 0.3) -> set:
    """找出在多数页面重复出现的行（页眉、页脚、水印、书名/节号标记）。

    这类行会随每一页混进正文，既污染阅读也污染检索，必须在切段前剔除。
    按「跨页重复度」判定而不是只看首尾行：真实 PDF 的提取顺序里，
    页眉未必落在第一行（前面可能先出现节号、图注等）。
    """
    total = len(page_texts)
    if total < min_pages:
        return set()
    counts: Dict[str, int] = {}
    for text in page_texts:
        for raw in text.splitlines():
            key = _normalize_line(raw.strip())
            if key:
                counts[key] = counts.get(key, 0) + 1
    threshold = max(min_pages, int(total * ratio))
    return {k for k, v in counts.items() if v >= threshold}


def _clean_paragraph(text: str) -> str:
    """去掉粘在正文尾部的页脚 URL。"""
    return TRAILING_URL_RE.sub("", text).strip()


def _split_paragraphs(page_text: str, skip_lines: Optional[set] = None) -> List[str]:
    """按行切段：句子结束符（。？！…）视为段落结尾；忽略页码/页眉/页脚。

    噪声行（页眉/页脚/页码/目录行）先整体剔除再累积切段，而不是「遇到就断开」——
    这样被页眉打断的句子能重新接上，否则一行页眉会把一句话切成两段碎片。
    """
    paras: List[str] = []
    cur: List[str] = []

    def flush() -> None:
        if not cur:
            return
        text = _clean_paragraph("".join(cur))
        if text:
            paras.append(text)
        cur.clear()

    for raw in page_text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        # 跨页重复出现的页眉/页脚：直接删除，不打断累积中的段落
        if skip_lines and _normalize_line(line) in skip_lines:
            continue
        # 页码/页眉（纯数字或页码样式）
        if len(line) <= 8 and re.fullmatch(r"[\d\s\-—.·]+", line):
            continue
        # 目录点线引导行（如「人工智能. . . . . . . . 3」）
        if DOT_LEADER_RE.search(line):
            continue
        # 单独成行的 URL（页脚）
        if URL_ONLY_RE.fullmatch(line):
            continue
        cur.append(line)
        if line[-1] in END_PUNCT and len(line) > 6:
            flush()
    flush()
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
        notes: List[str] = []
        chapter_marks = []  # [(page0, title)]
        if toc:
            level = _pick_chapter_level(toc)
            seen = set()
            for lv, title, page in toc:
                if lv != level or is_toc_noise(title):
                    continue
                pno = min(max(0, page - 1), n_pages - 1)
                key = (pno, title.strip())
                if key in seen:  # 书签里重复的条目只取一次
                    continue
                seen.add(key)
                chapter_marks.append((pno, title))
        if not chapter_marks:
            if n_pages > HEADING_SCAN_PAGES:
                notes.append(
                    f"PDF 没有目录书签，只在前 {HEADING_SCAN_PAGES} 页里按字号找章节标题，"
                    "靠后的章节可能没有被识别出来"
                )
            else:
                notes.append("PDF 没有目录书签，章节是按字号大小推断的，标题层级可能不准确")
            for pno in range(min(n_pages, HEADING_SCAN_PAGES)):
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
        total_chars = sum(len(t.strip()) for t in page_texts)
        if n_pages >= 3 and total_chars / n_pages < SPARSE_CHARS_PER_PAGE:
            notes.append(
                "PDF 几乎提取不到文字，可能是扫描件或图片版（没有文本层），这类文件无法用于检索问答"
            )
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
            end_pno = max(end_pno, pno)  # 同页起始的相邻章节不要退化成空章
            chapters.append(ParsedChapter(num=idx + 1, title=ctitle, page_start=pno + 1, page_end=end_pno + 1))

        # 段落切分（小节标题目前与正文同段落，仅按行尾标点断段）
        for ch in chapters:
            seq = 0
            page_nos = list(range(ch.page_start - 1, ch.page_end))
            pages = [page_texts[p] if p < len(page_texts) else "" for p in page_nos]
            margin_lines = _repeated_margin_lines(pages)
            for pno, text in zip(page_nos, pages):
                for para in _split_paragraphs(text, skip_lines=margin_lines):
                    kind = "formula" if looks_like_formula(para) else "p"
                    seq += 1
                    ch.sections.append(ParsedSection(seq=seq, page=pno + 1, text=para, kind=kind))
            # 首段若以章节标题开头（提取时与正文合并），剥离标题
            first = ch.sections[0] if ch.sections else None
            if first and first.text.replace(" ", "").startswith(ch.title.replace(" ", "")):
                first.text = _strip_title_prefix(first.text, ch.title) or first.text

        chapters = [c for c in chapters if c.sections]
        return ParsedBook(title=title, chapters=chapters, notes=notes)
    finally:
        doc.close()
