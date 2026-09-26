"""全局配置：从环境变量读取，支持 .env 文件（见 .env.example）。"""
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

#: 默认允许的前端来源。**刻意不用 `*`**：后端没有任何鉴权，而 `*` 意味着用户
#: 浏览的任意网页都能在后台读走整本教材原文（`GET /api/books/{id}/chapters/{cid}`），
#: 或直接 `DELETE /api/books/{id}` 把教材删掉——id 从 `GET /api/books` 就能拿到。
#: 这里放的是本机开发默认端口（前端 vite.config.mjs 用 3000），部署时用
#: `AI_READER_CORS_ORIGINS` 显式列出真实来源。
DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


class Settings:
    def __init__(self, data_dir: Optional[Path] = None):
        """`data_dir` 是给测试用的注入缝：传了就整棵数据目录（库、原文件、插图）
        都落在它下面，不传则读环境变量。

        只覆盖 `db_path` 是不够的——`sources_dir` / `assets_dir` 由 `data_dir`
        派生、且写入发生在入库过程中而不经过 `db_path`（见 tests/conftest.py）。
        """
        default_dir = Path(__file__).resolve().parent.parent / "data"
        self.data_dir = Path(data_dir or os.getenv("AI_READER_DATA_DIR", str(default_dir)))
        self.db_path = Path(os.getenv("AI_READER_DB", str(self.data_dir / "ai_reader.db")))
        # 上传的原始教材文件：保留原字节流，「下载原文件」与「重新解析」都靠它。
        # 必须是 data_dir 的相对子目录，换部署目录时不用改库里的记录。
        self.sources_dir = self.data_dir / "sources"
        # 从原文件抽出的插图（PDF 内嵌图片等），由 /assets 静态挂载对外提供。
        self.assets_dir = self.data_dir / "assets"
        # LLM：OpenAI 兼容接口（DeepSeek / SiliconFlow / 通义等均可）
        self.llm_base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
        self.llm_api_key = os.getenv("LLM_API_KEY", "")
        self.llm_model = os.getenv("LLM_MODEL", "deepseek-chat")
        self.llm_timeout = float(os.getenv("LLM_TIMEOUT", "60"))
        # 向量嵌入（可选）：OpenAI 兼容 /embeddings
        self.embedding_url = os.getenv("EMBEDDING_URL", "").rstrip("/")
        self.embedding_api_key = os.getenv("EMBEDDING_API_KEY", "")
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
        # 扫描件 OCR（可选）：依赖见 requirements-ocr.txt，未安装时自动降级
        self.ocr_enabled = os.getenv("AI_READER_OCR", "on").strip().lower() not in ("0", "off", "false")
        self.ocr_dpi = int(os.getenv("AI_READER_OCR_DPI", "200"))
        #: ONNX 默认会用满所有核心；在 Web 服务里是坏邻居，这里显式收敛
        self.ocr_threads = int(os.getenv("AI_READER_OCR_THREADS", "4"))
        self.ocr_max_bytes = int(os.getenv("AI_READER_OCR_MAX_MB", "200")) * 1024 * 1024
        # 空库时自动导入一本团队原创的示例教材（见 services/demo.py）。
        # 关掉它的唯一理由是「我要一个真正空的书架」，例如跑测试或部署到已有数据的库。
        self.auto_demo = os.getenv("AI_READER_AUTO_DEMO", "on").strip().lower() not in (
            "0",
            "off",
            "false",
        )
        # 允许的前端来源（逗号分隔）。留空则用 DEFAULT_CORS_ORIGINS，见其说明。
        configured_origins = [
            origin.strip()
            for origin in os.getenv("AI_READER_CORS_ORIGINS", "").split(",")
            if origin.strip()
        ]
        self.cors_origins = configured_origins or list(DEFAULT_CORS_ORIGINS)

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key)

    @property
    def embedding_configured(self) -> bool:
        return bool(self.embedding_url and self.embedding_api_key)

    @property
    def ocr_configured(self) -> bool:
        """是否**打算**启用 OCR。注意这里不探测依赖包是否装了——
        与 `embedding_configured` 同一口径：配置归配置，装没装由构造时兜住。"""
        return self.ocr_enabled


settings = Settings()
