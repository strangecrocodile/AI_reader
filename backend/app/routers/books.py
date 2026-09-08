"""教材/章节/规划接口。"""
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from ..models import AskRequest
from ..serializers import book_meta, chapter_content
from ..services.ask import answer_question
from ..services.ingest import ingest_pdf_bytes

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
    """上传文本型 PDF 教材：解析目录/章节/段落并入库。"""
    db, llm, retrieval, _ = _state(request)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    try:
        info = ingest_pdf_bytes(db, data, default_title=title or file.filename or "未命名教材")
    except (ValueError, Exception) as e:  # noqa: BLE001
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
