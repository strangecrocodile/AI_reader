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
        # LLM：OpenAI 兼容接口（DeepSeek / SiliconFlow / 通义等均可）
        self.llm_base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
        self.llm_api_key = os.getenv("LLM_API_KEY", "")
        self.llm_model = os.getenv("LLM_MODEL", "deepseek-chat")
        self.llm_timeout = float(os.getenv("LLM_TIMEOUT", "60"))
        # 向量嵌入（可选）：OpenAI 兼容 /embeddings
        self.embedding_url = os.getenv("EMBEDDING_URL", "").rstrip("/")
        self.embedding_api_key = os.getenv("EMBEDDING_API_KEY", "")
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key)

    @property
    def embedding_configured(self) -> bool:
        return bool(self.embedding_url and self.embedding_api_key)


settings = Settings()
