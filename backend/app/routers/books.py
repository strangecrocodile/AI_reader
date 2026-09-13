"""教材/章节/规划接口。"""
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from ..models import AskRequest, ProgressRequest
from ..serializers import book_meta, chapter_content
from ..services.ask import answer_question
from ..services.ingest import SUPPORTED_MESSAGE, detect_format, ingest_file_bytes
from ..services.knowledge import get_knowledge

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
    """记录一次章节学习事件，并更新教材总进度。"""
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


@router.post("/api/ask")
def ask(payload: AskRequest, request: Request):
    db, llm, retrieval, _ = _state(request)
    book = db.get_book(payload.bookId)
    chapter = db.get_chapter(payload.bookId, payload.chapterId)
    if not book or not chapter:
        raise HTTPException(status_code=404, detail="教材或章节不存在")
    return answer_question(
        db, retrieval, llm, payload.bookId, payload.chapterId,
        payload.question, payload.selectedText or "",
    )


@router.post("/api/books/{book_id}/plan")
def regenerate_plan(book_id: str, request: Request):
    db, llm, _, _ = _state(request)
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="教材不存在")
    from ..services.plan import get_plan

    return get_plan(db, llm, book, db.chapters_of(book_id), force=True)
