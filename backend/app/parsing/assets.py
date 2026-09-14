"""从 PDF 页面抽出插图与表格，落盘成渲染层能直接用的资源。

为什么要单独一个模块：这两件事的**开销差了两个数量级**（实测同一本 444 页教材，
`get_images` 0.4 ms/页，`find_tables` 74 ms/页 —— 全书提表格要 33 秒）。
调用方必须能按书的体量决定做到哪一步，所以这里把「便宜的部分」和「贵的部分」
拆成两个函数，并把阈值显式写出来，而不是藏在解析器里。

插图落盘到 `assets_dir`，文件名带 `section_id`，因此同一个资源在库里是可定位的；
`ParsedSection.text` 仍是纯文本（图注/表格文字），检索与锚点不受影响。
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24
except ImportError:  # pragma: no cover
    import fitz

#: 表格提取的页数上限。超过就只提图片、表格降级成「读不到」的提示。
#:
#: 阈值取 200 的依据：实测 74 ms/页，200 页约 15 秒——已经是用户能忍耐的上限；
#: 而被跳过的 240 页若强行提取要多花 18 秒，收益（一本教材通常只有个位数表格）
#: 远不值得。演示用的小体量教材都在这个阈值内，功能完整。
TABLE_SCAN_MAX_PAGES = 200

#: 小于这个尺寸的图当装饰/图标丢弃（像素），避免落一堆没有信息量的资源。
MIN_IMAGE_PIXELS = 4000

#: 表格纯文本里单元格之间的分隔符。检索与锚点用纯文本，渲染用 content.rows。
CELL_SEPARATOR = " | "


@dataclass
class PageAsset:
    """页面上的一个非文字块（插图或表格），带纵向位置用于插回正文顺序。"""

    kind: str  # image | table
    y: float
    content: Dict[str, Any]
    text: str = ""
    #: 图片落盘后的文件名（相对 assets_dir）；表格没有
    asset: str = ""


@dataclass
class PageAssets:
    items: List[PageAsset] = field(default_factory=list)
    #: 本页有没有因为体积阈值而**没去提**的表格
    tables_skipped: bool = False


def extract_page_assets(
    page,
    page_no: int,
    book_id: str,
    assets_dir: Optional[Path],
    *,
    with_tables: bool,
    table_over_limit: bool = False,
) -> PageAssets:
    """抽一页的插图与表格。

    `with_tables=False` 时完全不碰 `find_tables`（它才是慢的那一步），
    并把 `tables_skipped` 标出来供上层提示用户。
    """
    result = PageAssets()
    if assets_dir is not None:
        result.items.extend(_extract_images(page, page_no, book_id, assets_dir))
    if table_over_limit:
        result.tables_skipped = True
    elif with_tables:
        result.items.extend(_extract_tables(page, page_no))
    return result


def _extract_images(page, page_no: int, book_id: str, assets_dir: Path) -> List[PageAsset]:
    """把页内插图落盘；读不出来或太小就跳过（图片是锦上添花，不该让解析失败）。

    用 `doc.extract_image()` 取**原始图片字节**直接落盘：既避免重新编码造成失真，
    也比 `fitz.Pixmap` 更宽容——`get_image_rects()` 内部会构造 Pixmap 并算 MD5，
    对某些 PDF（例如本仓库的样例生成器产物）会直接抛 "is no image"，
    位置因此改用文字层 block 的几何去匹配。
    """
    items: List[PageAsset] = []
    try:
        images = page.get_images(full=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取第 %s 页插图列表失败：%s", page_no, exc)
        return items
    if not images:
        return items

    image_rects = _image_block_rects(page)
    for index, info in enumerate(images):
        try:
            xref = info[0]
            rect = _rect_for_image(page, xref, index, image_rects)
            if rect is None:
                continue
            if rect.width * rect.height < MIN_IMAGE_PIXELS:
                continue
            extracted = page.parent.extract_image(xref)
            blob = extracted.get("image")
            if not blob:
                continue
            ext = (extracted.get("ext") or "png").lower()
            name = f"{book_id}-p{page_no}-{index}.{ext}"
            assets_dir.mkdir(parents=True, exist_ok=True)
            (assets_dir / name).write_bytes(blob)
        except Exception as exc:  # noqa: BLE001
            logger.debug("第 %s 页第 %s 张图提取失败：%s", page_no, index, exc)
            continue
        items.append(
            PageAsset(
                kind="image",
                y=rect.y0,
                asset=name,
                content={
                    "asset": name,
                    "width": round(rect.width, 1),
                    "height": round(rect.height, 1),
                },
                # 插图本身没有文字；统一交给 assemble_book 填占位说明，
                # 这样 PDF 与 Word 两种来源的 kind/text 口径完全一致。
                text="",
            )
        )
    return items


def _image_block_rects(page) -> List[Any]:
    """文字层里 type=1 的块就是图片，它们的 bbox 可当插图位置用。"""
    try:
        blocks = page.get_text("dict").get("blocks", [])
    except Exception:  # noqa: BLE001
        return []
    return [fitz.Rect(block["bbox"]) for block in blocks if block.get("type") == 1 and block.get("bbox")]


def _rect_for_image(page, xref: int, index: int, image_rects: List[Any]):
    """图片在页面上的位置：优先精确 API，失败时按顺序匹配图片块。"""
    try:
        rects = page.get_image_rects(xref)
        if rects:
            return rects[0]
    except Exception as exc:  # noqa: BLE001 —— 见 _extract_images 的说明
        logger.debug("get_image_rects 失败（xref=%s）：%s", xref, exc)
    if index < len(image_rects):
        return image_rects[index]
    return None


def _extract_tables(page, page_no: int) -> List[PageAsset]:
    """把页内表格抽成行列结构；同时给一份纯文本供检索用。"""
    items: List[PageAsset] = []
    try:
        found = page.find_tables()
    except Exception as exc:  # noqa: BLE001
        logger.debug("第 %s 页表格提取失败：%s", page_no, exc)
        return items

    for index, table in enumerate(getattr(found, "tables", []) or []):
        try:
            rows = [[_cell_text(cell) for cell in row] for row in table.extract()]
        except Exception as exc:  # noqa: BLE001
            logger.debug("第 %s 页第 %s 个表格读取单元格失败：%s", page_no, index, exc)
            continue
        rows = [row for row in rows if any(cell for cell in row)]
        if not rows:
            continue
        bbox = getattr(table, "bbox", None) or (0, 0, 0, 0)
        plain = "\n".join(CELL_SEPARATOR.join(row) for row in rows)
        items.append(
            PageAsset(
                kind="table",
                y=bbox[1],
                text=f"（第 {page_no} 页表格）\n{plain}",
                content={
                    "rows": [[{"text": cell} for cell in row] for row in rows],
                    # 首行当表头：教材表格绝大多数首行是列名，渲染层据此加粗
                    "header": len(rows) > 1,
                },
            )
        )
    return items


def _cell_text(cell: Any) -> str:
    """单元格文本归一化：PyMuPDF 可能给 None，也可能把换行拼在里面。"""
    if cell is None:
        return ""
    return " ".join(str(cell).split())
