"""扫描件 PDF → ParsedBook：OCR 出文字，再还原出「章节 → 段落 + 真实页码」。

这是把 marker 那套「PDF 转结构化 Markdown」的思路自己实现一遍：不追求版式还原，
只求出教材学习真正需要的东西——章节边界、段落、以及**对得上纸质书的页码**。

## 结构是怎么判出来的（在真实 231 页扫描教材上验证过）

**页眉页脚按位置剔除，不靠重复度。** 实测那本书是「奇数页页眉＝章名 / 偶数页页眉＝书名」，
每章页眉文字都不同，占比到不了 `_repeated_margin_lines` 的阈值；但它们的**位置**很稳定：
页眉在 `y < 页高/12`，页码在 `y > 页高*0.95`。按位置一刀切干净利落。

**标题 = 文本模式 AND 高度比。两个判据缺一不可**（实测数据）：

| 行 | 文本模式 | 高度比 | 结论 |
|---|---|---|---|
| `5.2.1最短距离法` | ✅ | x1.2 | 真标题 |
| `4.1 设五维空间的线性方程为：`（习题） | ✅ | x0.9 | 只用模式会误判 |
| `[Cd]`（公式碎片） | ❌ | x1.4 | 只用高度会误判 |

只按高度判也不行：数学公式的积分号、上下标会把文本框撑高（`∫φ(u)du =1` 比正文还高），
而且大量公式碎片会把框高中位数拉低，阈值直接落进正文高度带。

**已知局限**：单栏假设——双栏教材的左右栏会被交错读进来。v1 不处理。
"""
import re
from typing import Callable, List, Optional, Sequence, Tuple

from .base import (
    CHAPTER_TITLE_RE,
    SECTION_TITLE_RE,
    Block,
    ParsedBook,
    ParsedChapter,
    ParsedSection,
    build_blocks,
    chapter_level_of,
    is_toc_noise,
    looks_like_formula,
)
from .ocr_engine import OcrEngine, OcrLine, lines_to_text
from .pdf import (
    BIGRAM_RE,
    HEADING_MAX_LEN,
    HEADING_MIN_SIZE_RATIO,
    WORD_RE,
    _repeated_margin_lines,
    _split_paragraphs,
)

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24
except ImportError:  # pragma: no cover
    import fitz

#: 顶部 1/16 是页眉带。这个值在真实扫描教材上量过：页眉落在 y0/H ∈ [0.044, 0.052]，
#: 正文首行 ≥ 0.077，0.0625 正好卡在空隙里。取 1/12（0.083）会切进正文——
#: 实测有几页的首行在 0.077 左右，会被整行吃掉，静默丢内容是最坏的失败方式。
HEADER_BAND_RATIO = 1 / 16
#: 底部 5% 是页码带。不能再放宽：图注偶尔排到 0.92H 附近。
FOOTER_BAND_RATIO = 0.95
#: 一页识别出的文字少于这个数，当作空白页/图版跳过
MIN_PAGE_CHARS = 20
#: 页脚里那种「孤零零一个数字」的行就是印刷页码
PAGE_NUMBER_RE = re.compile(r"^\d{1,4}$")
#: 至少要有这么多页读出页码，才敢按印刷页码换算（个别页错读不足为凭）
PAGE_OFFSET_MIN_SAMPLES = 3
#: 印刷页码与 PDF 页序的差超过这个数就认为读错了，放弃换算
PAGE_OFFSET_LIMIT = 100

_LEVEL_CHAPTER = 1
_LEVEL_SECTION = 2
_LEVEL_BODY = 0


def _is_heading_line(line: OcrLine, body_h: float, page_h: float) -> Optional[int]:
    """判断一行是不是标题，返回标题层级；不是则返回 None。

    判据是「文本模式 AND 高度比」——详见模块文档字符串里的实测对照表。
    """
    text = line.text
    if len(text) > HEADING_MAX_LEN:
        return None
    if line.y0 < page_h * HEADER_BAND_RATIO or line.y0 > page_h * FOOTER_BAND_RATIO:
        return None  # 页眉/页脚里的文字不可能是章节标题
    if body_h > 0 and line.height < body_h * HEADING_MIN_SIZE_RATIO:
        return None
    if looks_like_formula(text):
        return None
    if BIGRAM_RE.search(text) is None and WORD_RE.search(text) is None:
        return None
    if CHAPTER_TITLE_RE.match(text):
        return _LEVEL_CHAPTER
    if SECTION_TITLE_RE.match(text):
        return _LEVEL_SECTION
    return None


def _page_rows(
    lines: List[OcrLine], body_h: float, page_h: float, skip_lines: set
) -> List[Tuple[str, int]]:
    """把一页的识别行变成 [(文本, 层级)]，顺序与阅读顺序一致。

    连续的正文字行交给 `_split_paragraphs` 切段（复用 PDF 路径那套行尾标点规则），
    标题各自独立成行，从而保住标题与正文的先后关系。

    页眉页脚在这里就**按位置删掉**，不能只靠 `_is_heading_line` 拦：
    那只挡得住「被当成标题」，拦不住它们混进正文段落。
    """
    lines = [
        ln
        for ln in lines
        if page_h * HEADER_BAND_RATIO <= ln.y0 <= page_h * FOOTER_BAND_RATIO
    ]
    lines.sort(key=lambda ln: (ln.y0, ln.x0))
    rows: List[Tuple[str, int]] = []
    run: List[OcrLine] = []

    def flush_run() -> None:
        if not run:
            return
        for para in _split_paragraphs(lines_to_text(run), skip_lines=skip_lines):
            rows.append((para, _LEVEL_BODY))
        run.clear()

    for line in lines:
        level = _is_heading_line(line, body_h, page_h)
        if level is None:
            run.append(line)
        else:
            flush_run()
            rows.append((line.text, level))
    flush_run()
    return rows


def _measure_body_height(pages: List[Tuple[int, float, List[OcrLine]]]) -> float:
    """全书正文行高的中位数，作为「字号」基准。

    取全书而不是单页：扉页、图版页的行数太少，单页中位数不可靠。
    同时只统计**正文带内**的行——页眉页脚若混进来会污染基准。

    分两轮：先粗估中位数，再剔掉明显高于它的行重算。章标题能到正文的 2.5 倍高，
    在练习册、图表页这类标题密度大的书里会把中位数整体抬高，把只高 1.3 倍的节标题
    挤出阈值（实测复现过）。剔一轮就够，收敛很快；不剔低行——公式碎片把基准拉低
    才是更危险的误判方向。
    """
    heights = sorted(
        line.height
        for _, page_h, lines in pages
        for line in lines
        if page_h * HEADER_BAND_RATIO <= line.y0 <= page_h * FOOTER_BAND_RATIO
    )
    if not heights:
        return 0.0
    rough = heights[len(heights) // 2]
    body = [h for h in heights if h <= rough * 1.5]
    return body[len(body) // 2] if body else rough


def _printed_page_number(lines: Sequence[OcrLine], page_h: float) -> Optional[int]:
    """页脚带里那个孤零零的数字——**原书印的页码**。没有则返回 None。"""
    numbers = [
        int(line.text.strip())
        for line in lines
        if line.y0 > page_h * FOOTER_BAND_RATIO and PAGE_NUMBER_RE.match(line.text.strip())
    ]
    return numbers[-1] if numbers else None


def _page_offset(pages: List[Tuple[int, float, List[OcrLine]]]) -> Optional[int]:
    """PDF 页序 → 印刷页码的固定偏移；样本不足或离谱时返回 None。

    扫描件几乎都有前言页，于是 PDF 第 101 页印的是「第 91 页」（真实教材实测差 10）。
    溯源要报的是读者能照着翻到的那个数，所以必须换算，否则「教材依据 · 第 101 页」
    在书上根本找不到——那正是这个功能要避免的。

    取**中位数**而不是平均值或首个样本：个别页 OCR 错读、图版页压根没页码都无所谓。
    """
    deltas = []
    for pdf_no, page_h, lines in pages:
        printed = _printed_page_number(lines, page_h)
        if printed is not None:
            deltas.append(printed - pdf_no)
    if len(deltas) < PAGE_OFFSET_MIN_SAMPLES:
        return None
    deltas.sort()
    offset = deltas[len(deltas) // 2]
    if abs(offset) > PAGE_OFFSET_LIMIT:
        return None  # 差得离谱，多半是把别的东西读成了页码
    return offset


def _chapter_start_flags(rows: List[Tuple[str, int]]) -> List[bool]:
    """标记哪些行会成为一章的起点（与 `build_blocks` 的判定保持一致）。

    用途见 `_assemble_ocr_book` 里对页面行与段落的一一对应关系。
    """
    chapter_level = chapter_level_of(rows)
    flags = []
    for text, level in rows:
        if chapter_level is not None:
            starts = level == chapter_level
        else:
            starts = bool(CHAPTER_TITLE_RE.match(text))
        flags.append(starts and not is_toc_noise(text))
    return flags


def _assemble_ocr_book(
    title: str,
    blocks: List[Block],
    para_pages: List[int],
    notes: List[str],
) -> ParsedBook:
    """把「章 → 段落」装配成 ParsedBook，**页码用 OCR 时的真实页号**。

    为什么不复用 `base.assemble_book`：它按「每 1200 字折一页」合成虚拟页码，
    那是给没有物理页码的 Word/txt 用的。扫描件有真实页码，合成出来的数字
    会让溯源里的「教材依据 · 第 N 页」对不上书，正是本功能要避免的。

    所以这里刻意重复一小段编号逻辑，换取真实页码；代价是约 25 行。
    """
    book = ParsedBook(title=(title or "").strip() or "未命名教材", chapters=[], notes=list(notes))
    pages = iter(para_pages)
    for block in blocks:
        chapter = ParsedChapter(
            num=len(book.chapters) + 1,
            title=block.title.strip() or book.title,
            page_start=1,
            page_end=1,
        )
        for entry in block.paragraphs:
            text, kind = entry[0], entry[1]
            content = entry[2] if len(entry) > 2 else None
            page = next(pages, 1)
            chapter.sections.append(
                ParsedSection(
                    seq=len(chapter.sections) + 1,
                    page=page,
                    text=text,
                    kind=kind,
                    content=content,
                )
            )
        if not chapter.sections:
            continue
        chapter.page_start = chapter.sections[0].page
        chapter.page_end = chapter.sections[-1].page
        book.chapters.append(chapter)
    for index, chapter in enumerate(book.chapters, start=1):
        chapter.num = index
    return book


def ocr_pdf_bytes(
    data: bytes,
    engine: OcrEngine,
    default_title: str = "未命名教材",
    dpi: int = 200,
    on_page: Optional[Callable[[int, int], None]] = None,
) -> ParsedBook:
    """扫描件 PDF → ParsedBook（章节 + 段落 + 真实页码）。

    `on_page(done, total)` 每识别完一页回调一次，供上层推进度。
    """
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        n_pages = doc.page_count
        if n_pages == 0:
            raise ValueError("PDF 为空")

        # 1) 逐页渲染 + 识别
        pages: List[Tuple[int, float, List[OcrLine]]] = []
        for index in range(n_pages):
            page = doc[index]
            pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
            # 传 PNG 字节而不是 pix 数组：RapidOCR 只对解码类输入修正 RGB→BGR
            lines = engine.recognize(pix.tobytes("png"))
            pages.append((index + 1, float(pix.height), lines))
            del pix
            if on_page is not None:
                on_page(index + 1, n_pages)

        # 2) 基准行高 + 跨页重复行（水印、书名页眉这类正文内的重复）+ 印刷页码偏移
        body_h = _measure_body_height(pages)
        margin_lines = _repeated_margin_lines([lines_to_text(lines) for _, _, lines in pages])
        offset = _page_offset(pages)
        page_shift = offset or 0

        # 3) 逐页还原成 [(文本, 层级)]，同时记住每一行来自**原书第几页**
        rows: List[Tuple[str, int]] = []
        row_pages: List[int] = []
        for page_no, page_h, lines in pages:
            if sum(len(line.text) for line in lines) < MIN_PAGE_CHARS:
                continue  # 空白页 / 图版页
            printed = max(1, page_no + page_shift)
            for text, level in _page_rows(lines, body_h, page_h, margin_lines):
                if not text.strip():
                    continue
                rows.append((text, level))
                row_pages.append(printed)

        notes: List[str] = []
        if not rows:
            raise ValueError("整本扫描件没有识别出任何文字，请确认文件内容是否清晰")

        # 4) 切章。`build_blocks` 只丢弃「比章更浅的标题」，而章标题正是我们给的
        #    最浅层级（1），所以它不会丢行——下面据此做页码的一一对应。
        chapter_level = chapter_level_of(rows)
        if chapter_level is None and not any(CHAPTER_TITLE_RE.match(t) for t, _ in rows):
            notes.append("扫描件没有识别出「第X章」这类章节标题，整本作为一章；页码仍然对应原书")
        blocks = build_blocks(rows)

        flags = _chapter_start_flags(rows)
        para_pages = [p for p, is_start in zip(row_pages, flags) if not is_start]
        total_paras = sum(len(block.paragraphs) for block in blocks)
        if len(para_pages) != total_paras:
            # 兜底：对应关系对不上时退回第 1 页，宁可页码失真也不要整体失败
            para_pages = [1] * total_paras

        # 书名优先级：PDF 元数据 → 上传时的文件名（调用方传进来的 default_title）。
        # 刻意**不**退回「第一个章标题」：扫描件的元数据标题多为空，那样会让整本书
        # 在书架上叫「第1章 函数与极限」，反而不如文件名好认。
        title = (doc.metadata or {}).get("title", "").strip() or default_title

        # 页码来源要说实话：读到了页脚数字才敢承诺「与纸质书一致」，
        # 没读到就说清是 PDF 页序——「教材依据 · 第 N 页」翻不到书上是会让人对整个
        # 溯源功能失去信任的，宁可先说清楚。
        if offset is not None:
            notes.append(
                "本教材由扫描件识别而来，公式、图表与页眉页脚可能存在误差；"
                "页码取自原书页脚，与纸质书印刷页码一致"
            )
        else:
            notes.append(
                "本教材由扫描件识别而来，公式、图表与页眉页脚可能存在误差；"
                "未能读到原书页码，这里的页码是 PDF 页序，可能与纸质书印刷页码不一致"
            )
        return _assemble_ocr_book(title, blocks, para_pages, notes)
    finally:
        doc.close()
