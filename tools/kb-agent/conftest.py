"""pytest 路径与隔离配置：
- 让测试能 import src/kb_agent 与 scripts 下的模块；
- 测试进程禁用 .env 自动加载并清除真实密钥环境变量，保证离线、可复现
  （不会误连 DeepSeek/embedding API，也不打印任何密钥）。
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent

for sub in ("src", "scripts"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

# 必须在导入 kb_agent 之前设置，防止任何模块把真实 .env 读进进程
os.environ["KB_ENV_AUTOLOAD"] = "0"

_SECRET_PREFIXES = ("LLM_", "EMBED_", "HF_ENDPOINT", "HF_HOME", "LANGCHAIN_")


def pytest_configure(config):
    for name in list(os.environ):
        if name.startswith(_SECRET_PREFIXES):
            os.environ.pop(name, None)


@pytest.fixture(autouse=True)
def _no_secret_env(monkeypatch):
    """每个测试前清掉可能残留的真实密钥，避免误联网。"""
    for name in list(os.environ):
        if name.startswith(_SECRET_PREFIXES):
            monkeypatch.delenv(name, raising=False)
    yield
