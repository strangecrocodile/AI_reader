"""教材入库：多格式文件 → 解析 → SQLite（教材/章节/段落/锚点）。

支持 PDF、Word（.docx / .doc）与纯文本（.txt/.md）。各格式解析后产出同一套
章节-段落-锚点模型，因此检索、溯源问答、知识点图谱这些下游逻辑完全共用，
不需要按来源格式分叉（页码差异见 `parsing/base.py` 的虚拟页码说明）。

`.doc` 是特例：它要先经 LibreOffice 转成 .docx 才能读（见 services/legacy_doc）。
"""
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..db import Database
from ..parsing.docx import parse_docx_bytes
from ..parsing.pdf import parse_pdf_stream
from ..parsing.text import parse_text_bytes
from . import legacy_doc

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
        sources_dir = Path(settings.sources_dir)
        sources_dir.mkdir(parents=True, exist_ok=True)
        source_name = f"{info['id']}.{fmt}"
        (sources_dir / source_name).write_bytes(file_bytes)
        db.set_book_source(info["id"], fmt, source_name)
        info["sourceName"] = source_name

    info["sourceBytes"] = len(file_bytes)
    return info


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


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
