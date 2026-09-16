"""扫描件 OCR 任务的进度查询。

任务由 `POST /api/books` 在判定为扫描件时创建（见 `routers/books.py`），
这里只负责回报进度。识别是后台线程跑的，前端用轮询而不是 SSE：
进度只是一个每几秒跳一次的整数，SSE 的逐字延迟优势在这里不存在，
而轮询天然扛得住刷新页面、标签页休眠和 `--reload`。
"""
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.get("/api/ocr/tasks/{task_id}")
def get_ocr_task(task_id: str, request: Request):
    task = request.app.state.ocr.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="识别任务不存在，可能服务已重启，请重新上传")
    return task
