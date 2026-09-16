"""PDF 解析：PyMuPDF 提取文本、目录（书签）、章节结构，以及段落级行内版式。

支持两类 PDF：
1. 带目录书签（PDF 内置大纲）→ 直接以书签为章节边界；
2. 无书签 → 通过字号/粗细启发式检测章节标题。

输出 ParsedBook：章节 → 段落（含页码），段落为最小「锚点」粒度。每个段落同时带上
`content.runs`——由 span 的字号/字体名/flags/基线推出的粗体、斜体、上下标与字号档位，
阅读页据此还原教材的行内版式。`section.text` 仍是片段拼出的纯文本，检索链不受影响。

这里只处理**文本型** PDF。扫描件没有文本层，解析出来会是一本空书，所以由
`probe_pdf` 先判定、再由路由层转给 OCR（`parsing/ocr_pdf.py`），本模块不参与。
"""
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .assets import TABLE_SCAN_MAX_PAGES, extract_page_assets
from .base import (
    ParsedBook,
    ParsedChapter,
    ParsedSection,
    Run,
    is_toc_noise,
    looks_like_formula,
    make_run,
    merge_runs,
    pick_heading_level,
    runs_payload,
    text_of_runs,
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
#: 相对正文基准字号算「大一号 / 小一号」的阈值
BODY_BIG_RATIO = 1.15
BODY_SMALL_RATIO = 0.85
#: 基线偏移超过字号的这个比例，判定为上下标（PDF 没有直接的上下标标记）
VERTICAL_RATIO = 0.3

# 章标题模式（第1章 / 第1节 / Chapter 1 / Part 1 / 附录A）。
# PDF 目录书签里「节」也可能单独成层，所以这里保留「节」；Word 大纲另有更细的层级可用。
CHAPTER_TITLE_RE = re.compile(
    r"^\s*(第\s*[0-9一二三四五六七八九十百]+\s*[章节篇]|chapter\s*\d+|part\s*\d+|附录\s*[A-Za-zＡ-Ｚ])",
    re.IGNORECASE,
)
# 目录点线引导符。要求足够长的连续点/省略号，避免误伤正文里的「……」「⋯⋯」
DOT_LEADER_RE = re.compile(r"(?:\.\s*){5,}|…{4,}|⋯{4,}")


@dataclass(frozen=True)
class _Base:
    """全书排版基准，用于相对地判断字号档位。

    PDF 的字号是打印单位，绝对值没有意义（同一本书正文可能是 9.6，也可能 11.5），
    所以只记正文基准字号，其余字号都相对它判定。
    """

    body_size: float = 0.0


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


def _strip_prefix_from_content(
    content: Optional[Dict[str, Any]], stripped_text: str
) -> Optional[Dict[str, Any]]:
    """片段前缀与段落纯文本同步剥掉章节标题，保住 `text == "".join(片段)` 不变量。

    段落首段有时会把章节标题和正文提取成同一段，这时 text 被剥了标题，片段若不同步
    就会出现「渲染出来比 text 多几个字」。做法是从尾部对齐：确定要保留的字符数是
    `len(stripped_text)`，再从片段尾部倒着取这么多字符，样式逐片段保留。
    """
    runs = (content or {}).get("runs")
    if not runs:
        return None
    keep = len(stripped_text)
    if keep <= 0:
        return None
    tail: List[Dict[str, Any]] = []
    remaining = keep
    for run in reversed(runs):
        text = str(run.get("text", ""))
        if remaining <= 0:
            break
        piece = text[-remaining:]
        remaining -= len(piece)
        if piece:
            tail.append({"text": piece, "style": list(run.get("style", []))})
    tail.reverse()
    return {"runs": tail} if tail else None


# 句末标点。注意包含「．」(U+FF0E 全角句点)：不少中文教材（尤其理工类）用它作句号，
# 只认「。」(U+3002) 会导致整页文字黏成一段。
END_PUNCT = "。．？！；：!?;”』」…"
# 半角句点单独判定：它是句末标点，但也是小数点，不能无条件断句。
# 「π 约等于 3.」这种行尾小数与「3.14」这类数字中间的句点都不该断开。
ASCII_STOP_RE = re.compile(r"(?<!\d)\.\s*$")
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


def _ends_sentence(line: str) -> bool:
    """这一行是否该断段。

    中文句末标点直接算；半角句点要看前一个字符不是数字，避免把 `3.14` 或
    `π 约等于 3.` 这类数字里的点当成句号。英文教材因此也能正确断段，
    而原来（只认中文标点）会把整页英文黏成一段。
    """
    if not line:
        return False
    if line[-1] in END_PUNCT:
        return True
    return bool(ASCII_STOP_RE.search(line))


def _page_line_runs(page, base=None) -> List[Tuple[str, List[Run], float]]:
    """读出一页里每一行的 [(原始文本, 行内片段, 顶部 y)]。

    按行返回而不是整页返回：切段的噪声过滤、句末判定都发生在行上，
    只有先把行组装好，才能在**不改变段落切分规则**的前提下把样式带下去。
    一个 line 里的多个 span 在这里就合并成片段（相邻同样式会再合并一次）。

    带上 y 是为了让插图/表格能按纵向位置插回正文顺序。
    """
    lines: List[Tuple[str, List[Run], float]] = []
    try:
        data = page.get_text("dict")
    except Exception:  # noqa: BLE001 —— 单个页面读不出来不该让整本书失败
        return lines
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        block_lines = block.get("lines", [])
        # 基线按**块**统一算：块是 PDF 里一段文字的容器，行只是它的换行。
        # 若按行算，遇到「下标独占一行」就会失去参照，把下标误判成小字号。
        block_baseline = _block_baseline(block_lines)
        for line in block_lines:
            raw = "".join(span.get("text", "") for span in line.get("spans", []))
            if not raw.strip():
                continue
            lines.append((raw, _line_runs(line, base, block_baseline), _line_y(line)))
    return lines


def _span_style(span, base) -> Tuple[str, ...]:
    """PDF span 的字形信息 → 语义样式 token。

    只处理「与位置无关」的样式（粗体/斜体/flags 上的上标标记）。字号档位与
    基线推出的上下标需要合起来判断（上下标本来就比正文小，不该再叠 sm），
    所以那部分在 `_line_runs` 里统一收尾。
    """
    style: List[str] = []
    flags = span.get("flags", 0) or 0
    name = (span.get("font") or "").lower()
    # PyMuPDF flags: bit0=上标 bit1=斜体 bit2=衬线 bit3=等宽 bit4=粗体
    if flags & 16 or "bold" in name or name.endswith(("-black", "-heavy", "black")):
        style.append("b")
    if flags & 2 or "italic" in name or "oblique" in name:
        style.append("i")
    if flags & 1:
        style.append("sup")
    return tuple(style)


def _size_token(size: float, base) -> Optional[str]:
    """相对正文基准字号的档位 token。"""
    if not (base and base.body_size and size):
        return None
    if size >= base.body_size * BODY_BIG_RATIO:
        return "lg"
    if size <= base.body_size * BODY_SMALL_RATIO:
        return "sm"
    return None


def _line_runs(line, base, baseline: Optional[float] = None) -> List[Run]:
    """把一个 PDF line 的 span 变成片段。

    上下标按基线位置判定：带上下标的 span 与所在**块**的正文基线（最大字号的
    那个 span）不一致，这是纯文本提取里唯一可靠的上下标信号。没传基线时退化成
    按本行自己算。
    """
    spans = line.get("spans", [])
    if not spans:
        return []
    if baseline is None:
        baseline = _block_baseline([line])
    runs: List[Optional[Run]] = []
    for span in spans:
        style = list(_span_style(span, base))
        text = span.get("text", "")
        origin_y = (span.get("origin") or (0, 0))[1]
        size = span.get("size", 0) or 0
        if baseline is not None and size:
            delta = baseline - origin_y
            if delta > size * VERTICAL_RATIO:
                style.append("sup")
            elif delta < -size * VERTICAL_RATIO:
                style.append("sub")
        # 上下标不再叠加字号档位：它们本来就比正文小，渲染侧 sup/sub 自带缩放
        if "sup" not in style and "sub" not in style:
            token = _size_token(size, base)
            if token:
                style.append(token)
        runs.append(make_run(text, *style))
    return runs


def _block_baseline(lines) -> Optional[float]:
    """一个块（PDF 里的一段文字容器）的正文基线 = **字号最大** span 的原点 y。

    不能用「出现最多的 y」：上标与正文基线各出现一次时会打成平手，取谁全凭字典序，
    偏移量就算错了（表现为正文被当成上标、或上标完全测不出来）。上下标一定比正文小，
    所以「最大字号的基线」才是稳定判据。

    按块而不是按行算：行只是块的换行，下标完全可能独占一行，那时按行算就失去了参照。
    """
    best = None
    best_size = -1.0
    for line in lines:
        for span in line.get("spans", []):
            origin = span.get("origin")
            size = span.get("size", 0) or 0
            if not origin or not size:
                continue
            if size > best_size:
                best_size = size
                best = origin[1]
    return best


def _merge_line_runs(chunks: List[List[Run]]) -> Tuple[List[Run], str]:
    """把一段里各行拼成最终的片段与纯文本。

    拼接沿用原来的 `"".join` 语义（行在读取时已 strip）。中文教材里换行不等于
    空格，改成 `" ".join` 反而会在中文句子中间插入空格。

    **纯文本以 `_clean_paragraph` 的结果为准**（它会 strip 并剥掉尾部页脚 URL），
    片段再按这个结果对齐。反过来「从片段重新拼文本」会把刚剥掉的 URL 又带回来。
    """
    merged = merge_runs(run for chunk in chunks for run in chunk)
    text = _clean_paragraph("".join(run.text for run in merged))
    if not text:
        return [], ""
    aligned = _align_runs(merged, text)
    return aligned, text


def _align_runs(runs: List[Run], text: str) -> List[Run]:
    """让片段拼出来的文本与 `text` 完全一致（保住渲染与锚点定位的不变量）。

    两步：先按首尾空白修剪，再按字符数从**尾部**截断。尾部截断正是为了去掉
    粘在段末的页脚 URL——只用 strip 是去不掉的，那样渲染出来会比 `text` 多一截。
    """
    if not runs:
        return []
    trimmed: List[Run] = []
    last = len(runs) - 1
    for index, run in enumerate(runs):
        piece = run.text
        if index == 0:
            piece = piece.lstrip()
        if index == last:
            piece = piece.rstrip()
        if piece:
            trimmed.append(Run(text=piece, style=run.style))
    trimmed = merge_runs(trimmed)

    total = sum(len(run.text) for run in trimmed)
    excess = total - len(text)
    if excess <= 0:
        return trimmed
    kept: List[Run] = []
    for run in trimmed:
        if excess <= 0:
            kept.append(run)
            continue
        drop = min(excess, len(run.text))
        excess -= drop
        piece = run.text[: len(run.text) - drop]
        if piece:
            kept.append(Run(text=piece, style=run.style))
    return kept


def _split_styled_paragraphs(
    page, skip_lines: Optional[set] = None, base=None
) -> List[Tuple[float, List[Run], str]]:
    """按行切段，返回 [(段落顶部 y, 片段, 纯文本)]。

    切段规则与旧的 `_split_paragraphs` 完全一致（句子结束符断段、噪声行进段前剔除），
    只是把「累积字符串」换成「累积片段」，样式因此能跟着走到段落里。

    额外带上段落的顶部 y：插图与表格要按纵向位置插回正文顺序，没有这个坐标
    就只能把它们全部堆到章末，读起来完全错位。

    噪声行（页眉/页脚/页码/目录行）先整体剔除再累积切段，而不是「遇到就断开」——
    这样被页眉打断的句子能重新接上，否则一行页眉会把一句话切成两段碎片。
    """
    paras: List[Tuple[float, List[Run], str]] = []
    cur: List[List[Run]] = []
    cur_y: Optional[float] = None
    pending_y: Optional[float] = None

    def flush() -> None:
        nonlocal cur_y, pending_y
        if not cur:
            cur_y = pending_y = None
            return
        runs, text = _merge_line_runs(cur)
        if text:
            paras.append((cur_y if cur_y is not None else 0.0, runs, text))
        cur.clear()
        cur_y = pending_y = None

    for raw, runs, y in _page_line_runs(page, base):
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
        # 段落起点取第一个非噪声行的 y：噪声行不该把后面的正文往下推
        if pending_y is None:
            pending_y = y
        if cur_y is None:
            cur_y = pending_y
        cur.append(runs)
        if _ends_sentence(line) and len(line) > 6:
            flush()
    flush()
    return paras


def _split_paragraphs(text: str, skip_lines: Optional[set] = None) -> List[str]:
    """按当前 PDF 段落规则切纯文本段落，供 OCR 路径复用。

    OCR 只有文字行，没有 PDF span；但页眉/页脚过滤、句末断段和目录噪声的口径
    必须和文本型 PDF 一致，否则两条导入路径会产生不同形状的章节正文。
    """
    paras: List[str] = []
    cur: List[str] = []

    def flush() -> None:
        if not cur:
            return
        paragraph = _clean_paragraph("".join(cur))
        if paragraph:
            paras.append(paragraph)
        cur.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if skip_lines and _normalize_line(line) in skip_lines:
            continue
        if len(line) <= 8 and re.fullmatch(r"[\d\s\-—.·]+", line):
            continue
        if DOT_LEADER_RE.search(line):
            continue
        if URL_ONLY_RE.fullmatch(line):
            continue
        cur.append(line)
        if _ends_sentence(line) and len(line) > 6:
            flush()
    flush()
    return paras


def _line_y(line) -> float:
    """一行的顶部 y（用 bbox；缺失时退回 span 原点）。"""
    bbox = line.get("bbox")
    if bbox:
        return float(bbox[1])
    for span in line.get("spans", []):
        origin = span.get("origin")
        if origin:
            return float(origin[1])
    return 0.0


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


@dataclass
class PdfProbe:
    """上传前的廉价体检结果，用来决定这本 PDF 该走哪条解析路径。"""

    pages: int
    chars_per_page: float
    scanned: bool


def probe_pdf(data: bytes, sample_pages: int = 12) -> Optional[PdfProbe]:
    """廉价判定是否为扫描件：只抽样若干页统计文本量，成本与书长无关。"""
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        return None
    try:
        n_pages = doc.page_count
        if n_pages == 0:
            return None
        step = max(1, n_pages // sample_pages)
        pages = list(range(0, n_pages, step))[:sample_pages]
        chars = sum(len(doc[i].get_text("text").strip()) for i in pages)
        per_page = chars / len(pages)
        return PdfProbe(
            pages=n_pages,
            chars_per_page=per_page,
            scanned=n_pages >= 3 and per_page < SPARSE_CHARS_PER_PAGE,
        )
    finally:
        doc.close()


def parse_pdf_stream(
    data: bytes,
    default_title: str = "未命名教材",
    assets_dir=None,
    book_id: str = "",
) -> ParsedBook:
    """解析 PDF 字节流。

    `assets_dir` 给出时，页内插图会抽取落盘到该目录、表格会抽成行列结构；
    为 None 则只解析文本、不产生任何文件（单元测试默认走这条路径）。
    `book_id` 只用于给落盘的资源命名，便于定位。
    """
    doc = fitz.open(stream=data, filetype="pdf")
    assets_dir = Path(assets_dir) if assets_dir is not None else None
    tables_skipped = False
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
        base = _Base(body_size=body_size)

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
            # 只说事实，不给结论：能不能走 OCR 由路由层决定（那里才知道 OCR 是否可用）
            notes.append(
                "PDF 几乎提取不到文字，可能是扫描件或图片版（没有文本层）"
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

        # 插图/表格的提取范围：见 assets.TABLE_SCAN_MAX_PAGES 的说明。
        # 表格提取比读图贵两个数量级，大书里只提图、并把「表格没提」如实告诉用户。
        with_tables = n_pages <= TABLE_SCAN_MAX_PAGES

        # 段落切分（小节标题目前与正文同段落，仅按行尾标点断段）
        for ch in chapters:
            seq = 0
            page_nos = list(range(ch.page_start - 1, ch.page_end))
            pages = [page_texts[p] if p < len(page_texts) else "" for p in page_nos]
            margin_lines = _repeated_margin_lines(pages)
            for pno in page_nos:
                if pno >= n_pages:
                    continue
                page = doc[pno]
                # 正文段落与插图/表格按纵向位置合并，插回原来的阅读顺序
                entries: List[Tuple[float, int, ParsedSection]] = []
                for order, (y, runs, text) in enumerate(
                    _split_styled_paragraphs(page, skip_lines=margin_lines, base=base)
                ):
                    kind = "formula" if looks_like_formula(text) else "p"
                    entries.append(
                        (
                            y,
                            order,
                            ParsedSection(
                                seq=0, page=pno + 1, text=text, kind=kind, content=runs_payload(runs)
                            ),
                        )
                    )
                page_assets = extract_page_assets(
                    page,
                    pno + 1,
                    book_id,
                    assets_dir,
                    with_tables=with_tables,
                    table_over_limit=not with_tables,
                )
                if page_assets.tables_skipped:
                    tables_skipped = True
                for offset, asset in enumerate(page_assets.items):
                    entries.append(
                        (
                            asset.y,
                            len(entries) + offset,
                            ParsedSection(
                                seq=0,
                                page=pno + 1,
                                text=asset.text,
                                kind=asset.kind,
                                content=asset.content,
                            ),
                        )
                    )

                entries.sort(key=lambda item: (item[0], item[1]))
                for _y, _order, section in entries:
                    seq += 1
                    section.seq = seq
                    ch.sections.append(section)
            # 首段若以章节标题开头（提取时与正文合并），剥离标题。
            # 片段也要跟着剪掉同样的前缀，否则 text 与片段拼出来的文本会不一致。
            first = ch.sections[0] if ch.sections else None
            if first and first.text.replace(" ", "").startswith(ch.title.replace(" ", "")):
                stripped = _strip_title_prefix(first.text, ch.title) or first.text
                first.content = _strip_prefix_from_content(first.content, stripped)
                first.text = stripped

        if tables_skipped:
            notes.append(
                f"这本书超过 {TABLE_SCAN_MAX_PAGES} 页，为避免导入过慢没有提取表格，"
                "表格里的文字在阅读页看不到（正文与插图不受影响）"
            )
        chapters = [c for c in chapters if c.sections]
        return ParsedBook(title=title, chapters=chapters, notes=notes)
    finally:
        doc.close()
