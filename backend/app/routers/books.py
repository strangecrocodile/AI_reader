"""教材/章节/规划接口。"""
import json
import logging
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from ..models import AskRequest, EventRequest, ProgressRequest, ThreadRequest
from ..serializers import book_meta, chapter_content
from ..services import threads as thread_service
from ..services.ask import answer_question, stream_answer
from ..services.ingest import SUPPORTED_MESSAGE, detect_format, ingest_file_bytes
from ..services.knowledge import get_knowledge
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
    """上传教材（PDF / Word / 纯文本）：解析目录/章节/段落并入库。"""
    db, llm, retrieval, _ = _state(request)
    filename = file.filename or ""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if detect_format(filename, file.content_type) is None:
        raise HTTPException(status_code=415, detail=SUPPORTED_MESSAGE)
    fallback_title = title or Path(filename).stem or "未命名教材"
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
