""".env 加载（本地密钥/配置，不入库）。

把仓库根目录的 .env 读进进程环境，且**不覆盖**已有的环境变量
（例如系统里已设置的 LLM_API_KEY 优先）。.env 已被 .gitignore 忽略。
"""
from __future__ import annotations

import os
from pathlib import Path

_ENV_LOADED = False
#: .env 相对仓库根（src/kb_agent/config_env.py → 上两级即仓库根）
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def load_env_file(path: str | Path) -> dict[str, str]:
    """读取一个 .env 风格文件（KEY=VALUE、忽略 # 注释与空行），返回 dict。"""
    out: dict[str, str] = {}
    text = Path(path).read_text(encoding="utf-8")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def ensure_env() -> None:
    """幂等地把根目录 .env 载入 os.environ（不覆盖已存在变量）。

    可用 KB_ENV_AUTOLOAD=0 关闭自动加载（测试环境用，保证离线可复现）。
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    if os.getenv("KB_ENV_AUTOLOAD", "1") != "1":
        return
    if _ENV_PATH.exists():
        for key, value in load_env_file(_ENV_PATH).items():
            os.environ.setdefault(key, value)
