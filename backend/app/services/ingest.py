"""教材入库：多格式文件 → 解析 → SQLite（教材/章节/段落/锚点）。

支持 PDF、Word（.docx / .doc）与纯文本（.txt/.md）。各格式解析后产出同一套
章节-段落-锚点模型，因此检索、溯源问答、知识点图谱这些下游逻辑完全共用，
不需要按来源格式分叉（页码差异见 `parsing/base.py` 的虚拟页码说明）。

`.doc` 是特例：它要先经 LibreOffice 转成 .docx 才能读（见 services/legacy_doc）。
"""
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..db import Database
from ..parsing.docx import parse_docx_bytes
from ..parsing.pdf import parse_pdf_stream, probe_pdf
from ..parsing.text import parse_text_bytes
from . import legacy_doc

logger = logging.getLogger(__name__)

PDF = "pdf"
DOCX = "docx"
DOC = "doc"
TEXT = "text"

#: 格式不支持时给用户看的提示（前端也会用同样的文案做前置校验）
SUPPORTED_MESSAGE = "目前支持 PDF / Word(.docx / .doc) / 纯文本(.txt/.md) 教材"
_TEXT_SUFFIXES = (".txt", ".md", ".markdown")

#: 「下载原文件」的响应 MIME；未知格式退化成二进制流，浏览器会当附件下载。
SOURCE_MEDIA_TYPES = {
    PDF: "application/pdf",
    DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    DOC: "application/msword",
    TEXT: "text/plain; charset=utf-8",
}
#: 教材 `note` 字段里 OCR 来源的写法
OCR_SOURCE_NOTE = "扫描件 OCR"
#: 认出是扫描件但 OCR 不可用时的提示。必须给**下一步怎么做**，不能只说「识别不了」——
#: 用户看到「内容可能没被完整读取」时最需要的是能自己走的出口。
SCANNED_NO_OCR_MESSAGE = (
    "这本 PDF 是扫描件（没有文本层），需要 OCR 才能读取。"
    "服务端未启用扫描件识别，请让管理员执行 pip install -r requirements-ocr.txt 后重启；"
    "或者用带文本层的 PDF / Word / txt 重新上传"
)
#: 上传体积上限。当前主要拦扫描件——一页 200dpi 的图就要几百 KB，
#: 而 OCR 耗时与页数成正比，超大文件会长时间占住 worker。
MAX_UPLOAD_BYTES = 200 * 1024 * 1024

#: 正文总字数低于这个数就提示「内容可能没读全」。
#: 阈值取值有依据：团队自己的样例教材（kb-agent 的 `sample_book.docx`）正文只有 523 字，
#: 是合法可用的薄教材，不能被误报；而「正文全在表格 / 文本框里」的文档解析出来是 433 字。
#: 字数只负责触发提醒，**真正说明原因的是解析器报告的结构信号**（见 `ParsedBook.notes`）。
LOW_CONTENT_CHARS = 500


def detect_format(filename: str = "", content_type: str = "") -> Optional[str]:
    """按扩展名判断来源格式；扩展名缺失或不可识别时退回 content-type。"""
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".pdf":
        return PDF
    if suffix == ".docx":
        return DOCX
    if suffix == ".doc":
        return DOC
    if suffix in _TEXT_SUFFIXES:
        return TEXT

    content = (content_type or "").lower()
    if content == "application/pdf":
        return PDF
    if "wordprocessingml" in content:
        return DOCX
    if content == "application/msword":
        return DOC
    if content.startswith("text/"):
        return TEXT
    return None


def parse_bytes(
    fmt: str,
    data: bytes,
    default_title: str = "未命名教材",
    assets_dir: Optional[Path] = None,
    book_id: str = "",
):
    """按格式解析为 ParsedBook（章节 → 段落，段落为最小锚点粒度）。

    `assets_dir` 给出时，解析器把抽出的插图落盘到该目录、表格抽成行列结构；
    为 None 则只解析文本，不产生任何文件——单元测试默认走这条路径。
    `book_id` 用于给落盘的资源命名，便于从库里反查。

    `.doc` 先转成 .docx 再走 Word 解析——转换器拿不到就直接抛错（见 legacy_doc），
    不做「抽成纯文本」的降级：那会静默丢掉全部行内版式，与本次目标相悖。
    """
    if fmt == PDF:
        return parse_pdf_stream(data, default_title, assets_dir, book_id)
    if fmt == DOC:
        data = legacy_doc.convert_doc_to_docx(data)
        fmt = DOCX
    if fmt == DOCX:
        return parse_docx_bytes(data, default_title, assets_dir, book_id)
    if fmt == TEXT:
        return parse_text_bytes(data, default_title)
    raise ValueError(SUPPORTED_MESSAGE)


def low_content_warning(chars: int) -> str:
    """正文过少的提示文案；字数正常时返回空串。阈值口径只此一处。"""
    if chars >= LOW_CONTENT_CHARS:
        return ""
    return f"整本教材只解析出 {chars} 个字的正文，内容可能大部分没被读出来"


def content_warning_of(parsed, extra_notes: Optional[List[str]] = None) -> str:
    """汇总「内容可能没被完整读取」的提示；一切正常时返回空串。

    两类信号合起来用：正文总字数低到不正常（用户能直接感知到的症状），
    以及解析器报告的**跳过了什么**（表格 / 文本框 / 图片，是根因）。

    `extra_notes` 给 OCR 路径补一句「这本是识别出来的」——它不属于 `ParsedBook.notes`
    （那是解析器的自述），但同样要显示在同一个提示位。
    """
    chars = sum(
        len(section.text)
        for chapter in parsed.chapters
        for section in chapter.sections
        if section.kind != "heading"
    )
    symptom = low_content_warning(chars)
    notes: List[str] = [symptom] if symptom else []
    notes.extend(parsed.notes or [])
    notes.extend(extra_notes or [])
    return "；".join(n for n in notes if n)


def backfill_content_warnings(db: Database) -> int:
    """给升级前入库的教材补一次提示（这些书当时还没有这个字段）。"""
    return db.backfill_content_warning(low_content_warning)


def store_parsed_book(
    db: Database,
    parsed,
    note: str,
    default_title: str = "未命名教材",
    extra_notes: Optional[List[str]] = None,
    book_id: str = "",
) -> Dict[str, Any]:
    """把已解析好的 ParsedBook 写进库，返回教材元信息（含章节）。

    与解析完全解耦，因为 OCR 路径要复用：扫描件的文字来源不同，但落库之后
    章节/段落/锚点的形状一模一样，下游检索与溯源不需要知道它是扫出来的。

    整本写入是一个事务（`add_book_bundle`），所以**不存在「写了一半」的教材**——
    OCR 中途失败时一行都不落库，正是靠这里兜住。
    """
    if not parsed.chapters:
        raise ValueError("未能从文件中识别出章节内容")

    book_id = book_id or uuid.uuid4().hex[:8]
    book_row = {
        "id": book_id,
        "title": parsed.title or default_title,
        "author": "",
        "note": f"来源格式：{note}",
        "progress_pct": 0.0,
        "content_warning": content_warning_of(parsed, extra_notes=extra_notes),
        # 扫描件的「印刷页码 − PDF 页序」。原版 PDF 阅读面按 PDF 页序翻页，
        # 减掉它才跳得对；其它解析器没有这层换算，默认 0。
        "page_offset": int(getattr(parsed, "page_offset", 0) or 0),
        "created_at": _now(),
    }

    chapter_rows: List[Dict[str, Any]] = []
    section_rows: List[Dict[str, Any]] = []
    anchor_rows: List[Dict[str, Any]] = []
    for chapter in parsed.chapters:
        chapter_id = f"{book_id}-ch{chapter.num}"
        chapter_rows.append(
            {
                "id": chapter_id,
                "book_id": book_id,
                "num": chapter.num,
                "title": chapter.title,
                "page_start": chapter.page_start,
                "page_end": chapter.page_end,
                "full_text": chapter.full_text,
            }
        )
        for section in chapter.sections:
            section_id = f"{book_id}-s{chapter.num}-{section.seq}"
            section_rows.append(
                {
                    "id": section_id,
                    "book_id": book_id,
                    "chapter_id": chapter_id,
                    "seq": section.seq,
                    "text": section.text,
                    "page": section.page,
                    "kind": section.kind,
                    # 行内版式 / 插图 / 表格结构。空字典表示「没有额外版式」，
                    # 渲染层据此把 text 当成单个纯文本片段。
                    "content": section.content or {},
                }
            )
            anchor_rows.append(
                {
                    "id": section_id,
                    "book_id": book_id,
                    "chapter_id": chapter_id,
                    "section_id": section_id,
                    "text": section.text,
                    "page": section.page,
                }
            )

    db.add_book_bundle(book_row, chapter_rows, section_rows, anchor_rows)
    return {
        "id": book_id,
        "title": parsed.title,
        "contentWarning": book_row["content_warning"],
        "chapters": chapter_rows,
    }


def parse_and_store(
    db: Database,
    fmt: str,
    data: bytes,
    default_title: str = "未命名教材",
    assets_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """解析字节流并入库，返回教材元信息（含章节）。

    **只负责解析与入库，不落盘**——落盘是 `ingest_file_bytes` 的事。
    这样「原文件是否留存」与「能否解析」解耦：先解析，全书读不出来就整体失败，
    不会在磁盘上留下一个对应的空教材文件。
    """
    # book_id 先于解析生成：插图落盘要用它命名，好让资源和教材能互相反查
    book_id = uuid.uuid4().hex[:8]
    parsed = parse_bytes(fmt, data, default_title, assets_dir, book_id)
    return store_parsed_book(
        db,
        parsed,
        note=fmt,
        default_title=default_title,
        book_id=book_id,
    )


def ingest_file_bytes(
    db: Database,
    file_bytes: bytes,
    filename: str = "",
    content_type: str = "",
    default_title: str = "未命名教材",
    settings=None,
) -> Dict[str, Any]:
    """解析并入库任意受支持格式，返回教材元信息（含章节）。

    解析成功后把**原始字节流**留在 `data/sources/{book_id}.{fmt}` 里，并在 books
    上记下来源格式与文件名。留原文件有两个用途：一是「下载原文件」让用户能对照原书；
    二是以后想重新解析（换切段规则、补富文本）不必让用户重新上传。
    """
    fmt = detect_format(filename, content_type)
    if fmt is None:
        raise ValueError(SUPPORTED_MESSAGE)

    assets_dir = Path(settings.assets_dir) if settings is not None else None
    info = parse_and_store(db, fmt, file_bytes, default_title, assets_dir)

    source_name = ""
    if settings is not None:
        source_name = save_source_file(db, settings, info["id"], file_bytes, fmt)
        info["sourceName"] = source_name

    info["sourceBytes"] = len(file_bytes)
    return info


def save_source_file(
    db: Database,
    settings,
    book_id: str,
    file_bytes: bytes,
    fmt: str,
) -> str:
    """把原文件字节落到 `data/sources/{book_id}.{fmt}` 并记进 books，返回文件名。

    单独抽出来是因为**有两条入库路径**：常规上传（`ingest_file_bytes`）与扫描件
    OCR（`services/ocr.py`）。OCR 那条以前不落盘，于是扫描件既没有「下载原文件」，
    也无法用原版 PDF 阅读面打开——识别了几十分钟的结果只剩一份重构出来的文字，
    这跟「保留原书的观感」是拧着的。两条路径共用这一份实现，命名与记录口径才不会分叉。

    调用方负责决定「落盘失败要不要算失败」：这里的 OSError 会原样抛出。
    """
    sources_dir = Path(settings.sources_dir)
    sources_dir.mkdir(parents=True, exist_ok=True)
    source_name = f"{book_id}.{fmt}"
    (sources_dir / source_name).write_bytes(file_bytes)
    db.set_book_source(book_id, fmt, source_name)
    return source_name


def source_path_of(db: Database, book: Dict[str, Any], settings) -> Optional[Path]:
    """教材原始文件的落盘位置；没留存或文件已丢失时返回 None。

    `source_name` 存的是 basename（见 `db._ADDED_COLUMNS`），所以这里再取一次
    `Path(...).name` 做纵深防御：即便库里的值被改成了带目录的路径，也只会解析到
    `sources_dir` 之内，不会读到任意文件。
    """
    name = Path(book.get("source_name") or "").name
    if not name:
        return None
    path = Path(settings.sources_dir) / name
    return path if path.is_file() else None


def delete_book_files(book: Dict[str, Any], settings) -> int:
    """删掉这本教材在磁盘上的原文件与抽出的插图，返回删掉的文件数。

    **数据库行由调用方负责，且必须在删行之后调用**（见 `routers/books.py`）。
    顺序不能反：万一删文件失败，留下的是没有任何记录指向的孤儿文件；反过来先删
    文件的话，库里会留一本「有记录、文件却没了」的教材，用户点「下载原文件」
    拿到 404——后者更难解释，也没有补救动作。

    只删这本书自己的东西：

    - 原文件按库里记的 basename 取，并沿用 `source_path_of` 的目录穿越防御；
    - 插图按 `{book_id}-` 前缀认（命名见 `parsing/assets.py`）。`book_id` 是定长
      8 位十六进制，不可能成为另一本的前缀，所以前缀匹配不会误伤。

    删不掉（文件已不在、被占用、权限不足）都只是记一条 warning 并继续：用户点的是
    「删除这本教材」，字节残留不该让它变成一次失败的操作。
    """
    removed = 0
    book_id = str(book.get("id") or "")

    sources_dir = Path(getattr(settings, "sources_dir", "") or ".")
    name = Path(book.get("source_name") or "").name
    if name and sources_dir.is_dir():
        removed += _unlink(sources_dir / name)

    assets_dir = Path(getattr(settings, "assets_dir", "") or ".")
    if book_id and assets_dir.is_dir():
        prefix = f"{book_id}-"
        for path in assets_dir.iterdir():
            if path.is_file() and path.name.startswith(prefix):
                removed += _unlink(path)
    return removed


def _unlink(path: Path) -> int:
    """删一个文件并返回个数（0 表示本来就不在）。不抛异常，理由见上方。"""
    try:
        path.unlink()
    except FileNotFoundError:
        return 0
    except OSError as exc:
        logger.warning("删除教材文件失败，已跳过：%s（%s）", path, exc)
        return 0
    return 1


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


#: 替换时认出扫描件的提示。P0 不做「替换成扫描件」：识别是异步任务，而替换要求
#: 「旧的先留着、新的解析成功才动库」，两件事的时序是拧的。不硬凑半成品。
REPLACE_SCANNED_MESSAGE = (
    "替换暂不支持扫描件 PDF（识别要跑几十分钟，而替换必须先解析成功才动原教材）。"
    "请先删除这本教材，再重新上传扫描件"
)


def replace_book_file(
    db: Database,
    book_id: str,
    file_bytes: bytes,
    filename: str = "",
    content_type: str = "",
    settings=None,
) -> Dict[str, Any]:
    """用新文件重新解析并替换某本教材的内容，**保住学习记录**。

    存在这条路的理由：老教材入库时还没有「留存原文件」，原版 PDF 阅读面因此打不开。
    让用户删掉重传的代价是学习事件、追问线程、笔记与掌握度全部清零——那些是用户
    自己积累的东西，不该为一次功能升级买单。

    顺序刻意做成「先解析成功 → 再动库 → 最后动盘」：

    1. 解析到**临时目录**（插图先落那儿），这一步失败就到此为止，旧教材一个字不动；
    2. 单事务替换章节/段落/锚点（章节走 UPDATE，理由见 `Database.replace_book_bundle`）；
    3. 搬插图、删掉旧解析留下的那些，再换原文件；
    4. 还活着但锚点失效的笔记/线程按文本重挂，对不上的置空并如实计数。
    """
    fmt = detect_format(filename, content_type)
    if fmt is None:
        raise ValueError(SUPPORTED_MESSAGE)
    if fmt == PDF:
        probe = probe_pdf(file_bytes)
        if probe is not None and probe.scanned:
            raise ValueError(REPLACE_SCANNED_MESSAGE)

    book = db.get_book(book_id)
    if book is None:
        raise LookupError("教材不存在")

    staging = Path(settings.data_dir) / ".replace_tmp" / book_id
    _remove_tree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        # 用同一个 book_id 解析：插图文件名与库里的记录才对得上（见 parsing/assets.py）
        parsed = parse_bytes(fmt, file_bytes, book["title"] or "未命名教材", staging, book_id)
        if not parsed.chapters:
            raise ValueError("未能从文件中识别出章节内容")

        counts = db.replace_book_bundle(
            book_id,
            book_row_of(parsed, fmt),
            *bundle_rows_of(book_id, parsed),
        )
        # 先把新插图搬到位并清掉旧解析的残留，再删临时目录
        _move_assets(staging, Path(settings.assets_dir), book_id, _asset_names(parsed))
    finally:
        _remove_tree(staging)

    summary = {**counts, **_restore_anchors(db, book, parsed, book_id)}
    _swap_source_file(db, settings, book, file_bytes, fmt)
    return {"book": db.get_book(book_id), "replace": summary}


def _swap_source_file(db: Database, settings, book: Dict[str, Any], data: bytes, fmt: str) -> None:
    """换上新的原文件字节；换了格式就把旧扩展名那份删掉。

    落盘失败只记 warning：教材内容此刻已经换好了，为了「下载原文件」这一个入口
    把整次替换报成失败，会让用户以为白传了一遍。
    """
    old_name = Path(book.get("source_name") or "").name
    try:
        new_name = save_source_file(db, settings, book["id"], data, fmt)
    except OSError as exc:
        logger.warning("替换后写入原文件失败：%s（%s）", book["id"], exc)
        return
    if old_name and old_name != new_name:
        _unlink(Path(settings.sources_dir) / old_name)


def book_row_of(parsed, fmt: str) -> Dict[str, Any]:
    """替换时写回 books 的字段。书名与进度不在这里——书名沿用原记录，进度压根不动。"""
    return {
        "title": parsed.title or "未命名教材",
        "note": f"来源格式：{fmt}",
        "content_warning": content_warning_of(parsed),
        "page_offset": int(getattr(parsed, "page_offset", 0) or 0),
    }


def bundle_rows_of(book_id: str, parsed):
    """ParsedBook → (章节行, 段落行, 锚点行)。id 规则与 `store_parsed_book` 完全一致。"""
    chapters: List[Dict[str, Any]] = []
    sections: List[Dict[str, Any]] = []
    anchors: List[Dict[str, Any]] = []
    for chapter in parsed.chapters:
        chapter_id = f"{book_id}-ch{chapter.num}"
        chapters.append(
            {
                "id": chapter_id,
                "book_id": book_id,
                "num": chapter.num,
                "title": chapter.title,
                "page_start": chapter.page_start,
                "page_end": chapter.page_end,
                "full_text": chapter.full_text,
            }
        )
        for section in chapter.sections:
            section_id = f"{book_id}-s{chapter.num}-{section.seq}"
            sections.append(
                {
                    "id": section_id,
                    "book_id": book_id,
                    "chapter_id": chapter_id,
                    "seq": section.seq,
                    "text": section.text,
                    "page": section.page,
                    "kind": section.kind,
                    "content": section.content or {},
                }
            )
            anchors.append(
                {
                    "id": section_id,
                    "book_id": book_id,
                    "chapter_id": chapter_id,
                    "section_id": section_id,
                    "text": section.text,
                    "page": section.page,
                }
            )
    return chapters, sections, anchors


def _asset_names(parsed) -> set:
    """本次解析产出的插图文件名（来自 `content.asset`）。"""
    names = set()
    for chapter in parsed.chapters:
        for section in chapter.sections:
            asset = (section.content or {}).get("asset")
            if asset:
                names.add(Path(str(asset)).name)
    return names


def _move_assets(staging: Path, assets_dir: Path, book_id: str, keep: set) -> None:
    """把新插图搬进 assets_dir，并删掉这本书**旧解析**留下的插图。

    「旧的」= 前缀属于这本书、但不在本次产物里的那些；同名的会被新内容覆盖。
    搬完目录里只剩本次解析真正用到的那几张，不会越换越胖。
    """
    assets_dir.mkdir(parents=True, exist_ok=True)
    for path in assets_dir.glob(f"{book_id}-*"):
        if path.is_file() and path.name not in keep:
            _unlink(path)
    for path in staging.glob(f"{book_id}-*"):
        if not path.is_file():
            continue
        try:
            (assets_dir / path.name).write_bytes(path.read_bytes())
        except OSError as exc:
            logger.warning("替换后写入插图失败：%s（%s）", path.name, exc)


def _restore_anchors(db: Database, book: Dict[str, Any], parsed, book_id: str) -> Dict[str, int]:
    """把笔记与追问线程的锚点接到新解析出来的段落上，返回重挂/失锚计数。

    先看**原锚点还在不在**：同一本书重传一次，段落序号通常没变、锚点 id 也就没变，
    这时一个字段都不该动。只有确实失效了才按文本重找——否则「重传一本没改过的书」
    都会因为文本匹配的偶然失手而把锚点抹掉。

    文本匹配的口径与前端 `utils/anchorPage.js` 的 `matchAnchorForSelection` 一致
    （归一化后找包含关系、取最长的那个）：前端划词认锚点、后端重挂锚点，同一套直觉。
    """
    alive = {
        f"{book_id}-s{chapter.num}-{section.seq}"
        for chapter in parsed.chapters
        for section in chapter.sections
    }
    texts: Dict[str, List[Dict[str, Any]]] = {}
    for chapter in parsed.chapters:
        chapter_id = f"{book_id}-ch{chapter.num}"
        texts[chapter_id] = [
            {"id": f"{book_id}-s{chapter.num}-{s.seq}", "text": s.text} for s in chapter.sections
        ]

    counts = {"notesReanchored": 0, "notesUnanchored": 0, "threadsReanchored": 0, "threadsUnanchored": 0}
    note_updates = []
    for note in db.notes_of_book(book_id):
        current = note.get("anchor_id") or ""
        if current and current in alive:
            continue
        found = _match_anchor(texts.get(note.get("chapter_id") or "", []), note.get("quoted_text") or "")
        if found == current:
            continue
        if found:
            note_updates.append((note["id"], found))
            counts["notesReanchored"] += 1
        elif current:
            # 锚点对不上：笔记正文照旧留着（用户写的东西不能丢），只是不能再跳回原文
            note_updates.append((note["id"], ""))
            counts["notesUnanchored"] += 1

    thread_updates = []
    for thread in db.threads_of_book(book_id):
        current = thread.get("anchor_id") or ""
        if current and current in alive:
            continue
        found = _match_anchor(
            texts.get(thread.get("chapter_id") or "", []), thread.get("selected_text") or ""
        )
        if found == current:
            continue
        thread_updates.append((thread["id"], found))
        if found:
            counts["threadsReanchored"] += 1
        elif current:
            counts["threadsUnanchored"] += 1

    if note_updates or thread_updates:
        db.reanchor(note_updates, thread_updates)
    return counts


def _match_anchor(anchors: List[Dict[str, Any]], needle: str) -> str:
    """在一章的锚点里找回那条笔记/线程对应的段落；找不到给空串。"""
    target = _normalize_for_match(needle)
    if len(target) < 4:  # 太短的选择可能哪里都有，不猜
        return ""
    best_id = ""
    best_len = 0
    for anchor in anchors:
        text = _normalize_for_match(anchor.get("text") or "")
        if target in text and len(text) > best_len:
            best_id = anchor["id"]
            best_len = len(text)
    return best_id


def _normalize_for_match(value: str) -> str:
    """归一化：全角转半角、去所有空白、去连字符断词（与前端同一口径）。"""
    out = []
    for ch in str(value or ""):
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            ch = chr(code - 0xFEE0)
        if ch.isspace() or ch in "-‐‑‒–—":
            continue
        out.append(ch)
    return "".join(out)


def _remove_tree(path: Path) -> None:
    """删掉临时目录。失败只记一条 warning：一次替换不该因为清理不掉临时文件而失败。"""
    if not path.exists():
        return
    try:
        for child in sorted(path.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            else:
                child.rmdir()
        path.rmdir()
    except OSError as exc:
        logger.warning("清理临时目录失败：%s（%s）", path, exc)
