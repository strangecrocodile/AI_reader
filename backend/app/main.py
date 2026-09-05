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
from .routers import books

__version__ = "0.1.0"


def _build_llm(settings: Settings):
    if settings.llm_configured:
        return CloudLLM(settings.llm_base_url, settings.llm_api_key, settings.llm_model, settings.llm_timeout)
    return MockLLM()


def create_app(
    settings: Optional[Settings] = None,
    db_path: Optional[Path] = None,
    llm=None,
) -> FastAPI:
    settings = settings or default_settings
    db = Database(db_path or settings.db_path)
    db.init()
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

    app.include_router(books.router)
    return app


app = create_app()

if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
