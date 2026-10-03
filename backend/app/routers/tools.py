"""阅读工具的 HTTP 层：翻译与总结（都走 SSE，与问答同一套事件形状）。

为什么单独一个 router 而不是塞进 books.py：那个文件已经五百多行，装的是教材与学习
生命周期的接口；翻译/总结是「读的时候顺手用一下」的工具，作用对象是读者眼前那段东西，
与教材管理不是一类事。

三个端点：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/tools/translate` | SSE：译选中的原文 / 某一页的正文段落 |
| POST | `/api/tools/summarize` | SSE：总结选中的原文 / 整章（长章分块后合并） |
| GET | `/api/books/{id}/chapters/{cid}/summary` | 读回缓存的本章总结 |

事件形状与 `/api/ask/stream` 一致（`meta` → `delta` → `done`，出错以 `error` 收尾），
所以前端复用同一个 SSE 解析器；总结多一个 `progress`（分块进度）。
"""
import json
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..models import SummaryRequest, TranslateRequest
from ..services import tools as tools_service

logger = logging.getLogger(__name__)

router = APIRouter()

#: 事件流始终以 done 收尾；出错时补一个 error，前端据此把「正在生成」停下来
SSE_MEDIA_TYPE = "text/event-stream"


def _targets(request: Request, book_id: str, chapter_id: str):
    """取 (db, llm, book, chapter, sections, 锚点对照表)；教材或章节不存在时 404。"""
    db = request.app.state.db
    llm = request.app.state.llm
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="教材不存在")
    chapter = db.get_chapter(book_id, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    sections = db.sections_of(book_id, chapter_id)
    anchors: Dict[str, str] = {}
    for section in sections:
        anchors[section["id"]] = section["id"]
    for anchor in db.anchors_of(book_id, chapter_id):
        anchors[anchor["section_id"]] = anchor["id"]
    return db, llm, book, chapter, sections, anchors


def _sse(events) -> StreamingResponse:
    """把事件序列包成 SSE 响应；流已经开始后出错只能以 `error` 事件收尾。"""

    def frames():
        try:
            for event in events:
                yield f"event: {event['event']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001
            logger.exception("阅读工具流式生成失败")
            payload = {"event": "error", "message": str(e)}
            yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        frames(),
        media_type=SSE_MEDIA_TYPE,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/tools/translate")
def translate(payload: TranslateRequest, request: Request):
    db, llm, book, chapter, sections, anchors = _targets(
        request, payload.bookId, payload.chapterId
    )
    return _sse(
        tools_service.stream_translate(
            db,
            llm,
            book,
            chapter,
            sections,
            anchors,
            selected_text=payload.selectedText or "",
            anchor_id=payload.anchorId or "",
            page=payload.page,
            target=payload.target or "",
        )
    )


@router.post("/api/tools/summarize")
def summarize(payload: SummaryRequest, request: Request):
    db, llm, book, chapter, sections, anchors = _targets(
        request, payload.bookId, payload.chapterId
    )
    return _sse(
        tools_service.stream_summarize(
            db,
            llm,
            book,
            chapter,
            sections,
            anchors,
            selected_text=payload.selectedText or "",
            anchor_id=payload.anchorId or "",
        )
    )


@router.get("/api/books/{book_id}/chapters/{chapter_id}/summary")
def get_summary(book_id: str, chapter_id: str, request: Request):
    """本章总结（缓存）。没生成过时返回空壳——**不在这里现生成**：
    生成要几十秒，而那是个能取消、能看进度的动作，不该藏在一次 GET 里。"""
    db, _, book, chapter, _, _ = _targets(request, book_id, chapter_id)
    return tools_service.cached_summary(db, book, chapter)
