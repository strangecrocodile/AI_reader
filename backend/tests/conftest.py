"""pytest 公共夹具：应用、客户端与示例教材。"""
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "scripts"))

from app.llm.client import MockLLM  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture
def app(tmp_path):
    return create_app(db_path=tmp_path / "test.db", llm=MockLLM())


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


@pytest.fixture(scope="session")
def demo_pdf_bytes(tmp_path_factory):
    import make_demo_pdf

    out = tmp_path_factory.mktemp("pdf") / "demo.pdf"
    make_demo_pdf.build_demo_pdf(out)
    return out.read_bytes()
