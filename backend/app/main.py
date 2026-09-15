"""AI讲师 后端入口。

本地启动：
    cd backend
    .venv\\Scripts\\python.exe -m uvicorn app.main:app --reload --port 8000

环境变量见 .env.example；未配置 LLM Key 时自动使用规则 mock 回退，
保证导入教材 → 学习 → 溯源问答的完整链路可演示。
"""
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, settings as default_settings
from .db import Database
from .llm.client import CloudLLM, MockLLM
from .rag.retrieval import RetrievalService
from .routers import books, ocr
from .services.ingest import backfill_content_warnings
from .services.ocr import OcrTaskService

__version__ = "0.1.0"

#: 启动时给上次没跑完的 OCR 任务收尾的话术
INTERRUPTED_OCR_MESSAGE = "服务重启导致识别中断，请重新上传这本教材"


def _build_llm(settings: Settings):
    if settings.llm_configured:
        return CloudLLM(settings.llm_base_url, settings.llm_api_key, settings.llm_model, settings.llm_timeout)
    return MockLLM()


def create_app(
    settings: Optional[Settings] = None,
    db_path: Optional[Path] = None,
    llm=None,
    ocr_engine_factory=None,
    ocr_runner=None,
) -> FastAPI:
    """构造应用。

    `ocr_engine_factory` / `ocr_runner` 是给测试用的注入缝，都给了默认值：
    测试传假引擎和同步 runner，就不必真的加载 ONNX 模型、也不必起线程，
    而生产路径保持原样。
    """
    settings = settings or default_settings
    db = Database(db_path or settings.db_path)
    db.init()
    # 补标记升级前入库的「正文过少」教材：它们当时还没有 content_warning 字段，
    # 但恰恰是最需要提醒的那一批。幂等——已经写过提示的书不会被覆盖。
    backfill_content_warnings(db)
    # 同理对 OCR 任务对一次账：跑 OCR 的线程随进程一起没了，但任务行还写着
    # running。不处理的话前端会一直转圈，比报错更糟。
    db.fail_stale_ocr_tasks(INTERRUPTED_OCR_MESSAGE)
    llm = llm or _build_llm(settings)
    retrieval = RetrievalService(db, settings)

    app = FastAPI(title="AI讲师 · 教材驱动学习系统", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.db = db
    app.state.llm = llm
    app.state.retrieval = retrieval
    app.state.settings = settings
    # OCR 任务是异步跑在后台守护线程里的：进程退出即中断，下次启动由
    # `fail_stale_ocr_tasks` 收尾。所以这里不需要注册关闭钩子——没有要等的东西。
    app.state.ocr = OcrTaskService(
        db,
        settings,
        retrieval=retrieval,
        engine_factory=ocr_engine_factory,
        runner=ocr_runner,
    )

    app.include_router(books.router)
    app.include_router(ocr.router)
    return app


app = create_app()

if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
