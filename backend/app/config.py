"""全局配置：从环境变量读取，支持 .env 文件（见 .env.example）。"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Settings:
    def __init__(self):
        default_dir = Path(__file__).resolve().parent.parent / "data"
        self.data_dir = Path(os.getenv("AI_READER_DATA_DIR", str(default_dir)))
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
