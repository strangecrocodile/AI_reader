""".env 加载器测试（纯本地，不读真实 .env、不碰网络）。"""
from pathlib import Path

from kb_agent.config_env import load_env_file


def test_parse_basic(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "LLM_BASE_URL=https://api.deepseek.com/v1\n"
        "LLM_API_KEY=sk-abc\n"
        "# 注释行\n"
        "\n"
        'EMBED_MODEL="BAAI/bge-m3"\n',
        encoding="utf-8",
    )
    data = load_env_file(env)
    assert data["LLM_BASE_URL"] == "https://api.deepseek.com/v1"
    assert data["LLM_API_KEY"] == "sk-abc"
    assert data["EMBED_MODEL"] == "BAAI/bge-m3"
    assert "注释" not in data


def test_parse_ignores_broken_lines(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("NO_EQUALS_SIGN\n=orphan\nKEEP=1\n", encoding="utf-8")
    assert load_env_file(env) == {"KEEP": "1"}
