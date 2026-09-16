"""教材/章节/规划接口。"""
import json
import logging
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ..models import AskRequest, EventRequest, ProgressRequest, ThreadRequest
from ..parsing.pdf import probe_pdf
from ..serializers import book_meta, chapter_content
from ..services import threads as thread_service
from ..services.ask import answer_question, stream_answer
from ..services.export import export_book_markdown
from ..services.ingest import (
    MAX_UPLOAD_BYTES,
    PDF,
    SUPPORTED_MESSAGE,
    detect_format,
    ingest_file_bytes,
)
from ..services.knowledge import get_knowledge
from ..services.ocr import OcrUnavailable
from ..services.progress import record_event

logger = logging.getLogger(__name__)

router = APIRouter()


def _state(request: Request):
    s = request.app.state
    return s.db, s.llm, s.retrieval, s.settings


@router.get("/api/health")
def health(request: Request):
    db, llm, _, _ = _state(request)
    return {"status": "ok", "llm": llm.kind, "books": len(db.list_books())}


@router.get("/api/books")
def list_books(request: Request):
    db, llm, _, _ = _state(request)
    return [book_meta(db, llm, b) for b in db.list_books()]


@router.get("/api/books/{book_id}")
def get_book(book_id: str, request: Request):
    db, llm, _, _ = _state(request)
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="教材不存在")
    return book_meta(db, llm, book)


@router.post("/api/books", status_code=201)
async def upload_book(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(""),
):
    """上传教材（PDF / Word / 纯文本）：解析目录/章节/段落并入库。

    扫描件 PDF 例外：它没有文本层，直接解析只会得到一本空书，所以改走 OCR
    异步任务——立刻返回 **202 + 任务 id**，前端轮询 `/api/ocr/tasks/{id}` 看进度。
    文字版 PDF 与其它格式的行为完全不变（201 + 教材元信息）。
    """
    db, llm, retrieval, _ = _state(request)
    filename = file.filename or ""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB 上限，请分段后再上传",
        )
    fmt = detect_format(filename, file.content_type)
    if fmt is None:
        raise HTTPException(status_code=415, detail=SUPPORTED_MESSAGE)
    fallback_title = title or Path(filename).stem or "未命名教材"

    # 抽样探一次，只对 PDF 有意义（Word/txt 没有「扫描件」这个概念）
    probe = probe_pdf(data) if fmt == PDF else None
    if probe is not None and probe.scanned:
        try:
            task = request.app.state.ocr.submit(data, filename, fallback_title, probe=probe)
        except OcrUnavailable as e:
            # 认得出来是扫描件、但服务端没有 OCR。给的是「怎么装上」而不是「解析失败」
            raise HTTPException(status_code=422, detail=str(e)) from e
        except ValueError:
            pass  # 判定与抽样结果不一致（换页再探差异），退回常规解析路径
        else:
            return JSONResponse(status_code=202, content={"task": task})

    try:
        info = ingest_file_bytes(
            db,
            data,
            filename=filename,
            content_type=file.content_type or "",
            default_title=fallback_title,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"解析失败：{e}") from e
    retrieval.invalidate_book(info["id"])
    book = db.get_book(info["id"])
    return book_meta(db, llm, book)


@router.delete("/api/books/{book_id}", status_code=204)
def delete_book(book_id: str, request: Request):
    """删除教材及其全部下游数据（章节、段落、锚点、讲解、进度、追问线程）。

    **不可恢复**，也是唯一会丢弃 OCR 结果的操作——扫描件删掉就得重新识别几十分钟。
    所以 404 与 204 的语义要严格：前者表示这本教材本来就不存在，后者才是真的删了。
    """
    db, _, retrieval, _ = _state(request)
    if not db.get_book(book_id):
        raise HTTPException(status_code=404, detail="教材不存在")
    db.delete_book(book_id)
    # 检索缓存里还留着这本书的 BM25 索引与向量，不清理的话「已删教材」仍会被检索命中
    retrieval.invalidate_book(book_id)
    return None


@router.get("/api/books/{book_id}/markdown")
def get_book_markdown(book_id: str, request: Request):
    """把教材导出为 Markdown（按需渲染，库里不存副本）。

    每个段落带 `<!-- page: N -->`，扫描件里那个 N 是原书印刷页码，
    所以导出的文件仍然可以拿去核对。
    """
    db, _, _, _ = _state(request)
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="教材不存在")
    text = export_book_markdown(db, book)
    return Response(
        content=text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": _attachment_header(book.get("title") or "教材")},
    )


def _attachment_header(title: str) -> str:
    """拼一个能带中文书名的 Content-Disposition。

    HTTP 头只能放 latin-1，中文书名直接塞进 `filename=` 会让 Starlette 抛
    UnicodeEncodeError（下载整本书的接口因为书名是中文而 500，很难查）。
    所以同时给两遍：`filename` 是 ASCII 兜底，`filename*` 是 RFC 5987 的 UTF-8 真名，
    浏览器优先用后者。
    """
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", title).strip().strip(".")[:60] or "教材"
    ascii_name = cleaned.encode("ascii", "ignore").decode("ascii").strip() or "textbook"
    quoted = quote(f"{cleaned}.md", safe="")
    return f"attachment; filename=\"{ascii_name}.md\"; filename*=UTF-8''{quoted}"


@router.get("/api/books/{book_id}/chapters/{chapter_id}")
def get_chapter(book_id: str, chapter_id: str, request: Request):
    """章节学习内容：原文段落（含锚点）+ AI 备课讲解 + 知识点大纲。"""
    db, llm, _, _ = _state(request)
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="教材不存在")
    chapter = db.get_chapter(book_id, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return chapter_content(db, llm, book, chapter)


@router.get("/api/books/{book_id}/knowledge")
def get_book_knowledge(book_id: str, request: Request):
    """返回知识点卡片与章节内学习顺序关系。"""
    db, llm, _, _ = _state(request)
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="教材不存在")
    return get_knowledge(db, llm, book)


@router.post("/api/books/{book_id}/chapters/{chapter_id}/progress")
def update_chapter_progress(
    book_id: str, chapter_id: str, payload: ProgressRequest, request: Request
):
    """手动覆盖章节进度（调试/纠偏用）；正常学习进度请走 `/events`。"""
    db, _, _, _ = _state(request)
    if not db.get_book(book_id):
        raise HTTPException(status_code=404, detail="教材不存在")
    if not db.get_chapter(book_id, chapter_id):
        raise HTTPException(status_code=404, detail="章节不存在")
    progress = db.upsert_chapter_progress(
        book_id, chapter_id, payload.status, payload.mastery
    )
    db.update_book_progress_from_chapters(book_id)
    return progress


@router.post("/api/books/{book_id}/chapters/{chapter_id}/events")
def record_learning_event(
    book_id: str, chapter_id: str, payload: EventRequest, request: Request
):
    """上报一次学习事件（进入章节 / 读到段落 / 提问 / 标记学完 / 自测）。

    掌握度由事件重算，返回值含 `breakdown`（各项权重与得分）与 `signals`（读数、提问数…）。
    """
    db, _, _, _ = _state(request)
    if not db.get_book(book_id):
        raise HTTPException(status_code=404, detail="教材不存在")
    if not db.get_chapter(book_id, chapter_id):
        raise HTTPException(status_code=404, detail="章节不存在")
    return record_event(
        db,
        book_id,
        chapter_id,
        payload.kind,
        anchor_ids=payload.anchorIds,
        question=payload.question or "",
        correct=payload.correct,
    )


def _ask_targets(db, payload: AskRequest):
    """解析检索目标：带线程时以线程所属章节为准（线程绑定原文所在章）。"""
    if payload.threadId:
        thread = thread_service.get_thread(db, payload.threadId)
        if not thread:
            raise HTTPException(status_code=404, detail="追问线程不存在")
        if not db.get_book(thread["bookId"]) or not db.get_chapter(thread["bookId"], thread["chapterId"]):
            raise HTTPException(status_code=404, detail="线程所属章节不存在")
        return thread["bookId"], thread["chapterId"], thread
    if not db.get_book(payload.bookId) or not db.get_chapter(payload.bookId, payload.chapterId):
        raise HTTPException(status_code=404, detail="教材或章节不存在")
    return payload.bookId, payload.chapterId, None


@router.post("/api/ask")
def ask(payload: AskRequest, request: Request):
    db, llm, retrieval, _ = _state(request)
    book_id, chapter_id, thread = _ask_targets(db, payload)
    return answer_question(
        db, retrieval, llm, book_id, chapter_id,
        payload.question, payload.selectedText or "", thread=thread,
    )


@router.post("/api/ask/stream")
def ask_stream(payload: AskRequest, request: Request):
    """流式问答（SSE）：meta（检索范围与证据）→ delta（逐块回答）→ done（含溯源锚点）。

    带 `threadId` 时问答会写进该追问线程。
    """
    db, llm, retrieval, _ = _state(request)
    book_id, chapter_id, thread = _ask_targets(db, payload)

    events = stream_answer(
        db, retrieval, llm, book_id, chapter_id,
        payload.question, payload.selectedText or "", thread=thread,
    )

    def frames():
        try:
            for event in events:
                yield f"event: {event['event']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001 —— 流已开始，只能以 error 事件收尾
            logger.exception("流式问答失败")
            payload_out = {"event": "error", "message": str(e)}
            yield f"event: error\ndata: {json.dumps(payload_out, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/threads", status_code=201)
def create_thread(payload: ThreadRequest, request: Request):
    """为一段选中原文新建追问线程（划词气泡打开时调用）。"""
    db, _, _, _ = _state(request)
    if not db.get_book(payload.bookId):
        raise HTTPException(status_code=404, detail="教材不存在")
    if not db.get_chapter(payload.bookId, payload.chapterId):
        raise HTTPException(status_code=404, detail="章节不存在")
    return thread_service.create_thread(
        db, payload.bookId, payload.chapterId, payload.anchorId, payload.selectedText
    )


@router.get("/api/books/{book_id}/chapters/{chapter_id}/threads")
def list_threads(book_id: str, chapter_id: str, request: Request):
    """本章的追问线程列表（最新的在前）。"""
    db, _, _, _ = _state(request)
    if not db.get_book(book_id):
        raise HTTPException(status_code=404, detail="教材不存在")
    return thread_service.list_threads(db, book_id, chapter_id)


@router.get("/api/threads/{thread_id}")
def get_thread(thread_id: str, request: Request):
    db, _, _, _ = _state(request)
    thread = thread_service.get_thread(db, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="追问线程不存在")
    return thread


@router.delete("/api/threads/{thread_id}", status_code=204)
def delete_thread(thread_id: str, request: Request):
    db, _, _, _ = _state(request)
    if not thread_service.delete_thread(db, thread_id):
        raise HTTPException(status_code=404, detail="追问线程不存在")
    return None


@router.post("/api/books/{book_id}/plan")
def regenerate_plan(book_id: str, request: Request):
    db, llm, _, _ = _state(request)
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="教材不存在")
    from ..services.plan import get_plan

    return get_plan(db, llm, book, db.chapters_of(book_id), force=True)
