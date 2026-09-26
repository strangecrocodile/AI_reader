"""pytest 公共夹具：应用、客户端与示例教材。"""
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "scripts"))

from app.config import Settings  # noqa: E402
from app.llm.client import MockLLM  # noqa: E402
from app.main import create_app  # noqa: E402

#: 生产数据目录（跟着 `AI_READER_DATA_DIR` 走）。测试**一个文件都不该往里写**。
REAL_SOURCES = Path(Settings().sources_dir)
REAL_ASSETS = Path(Settings().assets_dir)
REAL_DATA_DIRS = (REAL_SOURCES, REAL_ASSETS)


def snapshot_names(directory: Path) -> set:
    """目录下的文件名集合；目录不存在时为空集。"""
    return {p.name for p in directory.glob("*")} if directory.is_dir() else set()


def isolated_settings(tmp_path: Path) -> Settings:
    """一份**完全落在 `tmp_path` 里**的配置。

    为什么不能只覆盖 `db_path`：`sources_dir` / `assets_dir` 是从 `data_dir`
    派生的，而原文件与插图的落盘发生在 `services/ingest` 里、根本不经过
    `db_path`。于是每个上传教材的测试都会往**真实的** `backend/data/sources`
    写一份原文件，且没有任何东西回收它——跑几十次测试，磁盘上就多出上千个
    孤儿文件（实测过一次：库里 3 本书，`data/sources/` 有 1876 个文件）。

    同时把 embedding 配置清空：README 承诺「测试不依赖模型 Key、也不访问外网」，
    而开发者本机的 `.env` 里可能配了 `EMBEDDING_*`。
    """
    settings = Settings(data_dir=tmp_path)
    settings.embedding_url = ""
    settings.embedding_api_key = ""
    return settings


@pytest.fixture(scope="session", autouse=True)
def _real_data_dir_stays_clean():
    """整场测试前后，真实数据目录必须一个文件都不多。

    这条比逐个测试断言更严：它管的是**所有**测试，包括以后新写的。任何
    「只传 db_path、忘了 settings」的 `create_app(...)` 都会被它兜住，
    而不必指望下一个写测试的人记得这条规则。
    """
    before = {directory: snapshot_names(directory) for directory in REAL_DATA_DIRS}
    yield
    added = {
        str(directory): sorted(snapshot_names(directory) - before[directory])
        for directory in REAL_DATA_DIRS
        if snapshot_names(directory) - before[directory]
    }
    assert not added, (
        f"测试往真实数据目录写了文件：{added}。"
        "多半是某处 create_app(...) 只传了 db_path 而没传 settings="
        "isolated_settings(tmp_path)（见本文件的说明）。"
    )


@pytest.fixture
def app(tmp_path):
    return create_app(
        settings=isolated_settings(tmp_path),
        db_path=tmp_path / "test.db",
        llm=MockLLM(),
    )


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


@pytest.fixture(scope="session")
def demo_docx_bytes():
    """用 python-docx 现场生成的原创 Word 教材（内容团队原创，版权安全）。"""
    import io

    from docx import Document

    document = Document()
    document.add_heading("微积分入门（Word 版）", level=0)  # Title 样式 = 书名
    document.add_heading("第1章 函数与极限", level=1)
    document.add_heading("1.1 函数的概念", level=2)
    document.add_paragraph("数学上，我们把这种对应关系称为函数：对每个 x 都有唯一的 y 与之对应。")
    document.add_paragraph("函数的表示方法常见的有解析式、表格和图像三种。")
    document.add_heading("第2章 导数与微分", level=1)
    document.add_heading("2.1 导数的概念", level=2)
    document.add_paragraph("比值 Δy / Δx 衡量区间内的平均快慢，称为平均变化率。")
    document.add_paragraph("让 Δx 趋近于 0，平均变化率趋近的那个数就定义为导数。")
    document.add_paragraph("f(x) = 2x + 1")

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture(scope="session")
def demo_markdown_bytes():
    """Markdown 教材样例：一级标题是书名，二级是章，三级是节。"""
    text = (
        "# 微积分入门（Markdown 版）\n\n"
        "## 第1章 函数与极限\n\n"
        "### 1.1 函数的概念\n\n"
        "数学上，我们把这种对应关系称为函数：对每个 x 都有唯一的 y 与之对应。\n\n"
        "## 第2章 导数与微分\n\n"
        "### 2.1 导数的概念\n\n"
        "让 Δx 趋近于 0，平均变化率趋近的那个数就定义为导数，记作 f′(x₀)。\n\n"
        "## 第3章 微分中值定理\n\n"
        "### 3.1 罗尔定理\n\n"
        "如果函数在闭区间上连续、在开区间内可导，就称它满足罗尔定理的条件。\n"
    )
    return text.encode("utf-8")


@pytest.fixture(scope="session")
def demo_docx_with_assets_bytes():
    """带**表格与插图**的 Word 教材样例（现场生成，版权安全）。

    这两类内容都不在 `doc.paragraphs` 里：表格是 body 的同级 `w:tbl`，
    图片藏在 run 的 `w:drawing` 里。所以专门造一份来验证它们确实被读出来了。
    """
    import io

    from docx import Document
    from docx.shared import Inches

    document = Document()
    document.add_heading("第1章 带图表的教材", level=1)
    document.add_paragraph("下面是一张表：")
    table = document.add_table(rows=2, cols=3)
    for index, text in enumerate(("概念", "记号", "含义")):
        table.cell(0, index).text = text
    for index, text in enumerate(("导数", "f′(x)", "瞬时变化率")):
        table.cell(1, index).text = text
    document.add_paragraph("下面是一张图：")
    document.add_picture(io.BytesIO(_tiny_png()), width=Inches(1.2))
    document.add_paragraph("图后还有一段正文。")

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _tiny_png() -> bytes:
    """8x8 的纯色 PNG（够小，但足以验证落盘与可读）。"""
    import struct
    import zlib

    width = height = 8
    raw = b"".join(b"\x00" + bytes([200, 60, 60]) * width for _ in range(height))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


@pytest.fixture(scope="session")
def demo_pdf_with_image_bytes():
    """带插图的 PDF 样例（现场生成）：验证插图会被抽出、落盘、可访问。"""
    import io

    import pymupdf as fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 80), "Chapter 1 Demo", fontsize=20)
    # 用英文句号断句（切段规则见 pdf._ends_sentence）：
    # PDF 内置字体画不出中文，样例用 ASCII 更稳妥。
    page.insert_text((72, 120), "Body text before the figure.", fontsize=11)
    page.insert_image(fitz.Rect(72, 160, 272, 300), stream=_tiny_png())
    page.insert_text((72, 340), "Body text after the figure.", fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data
