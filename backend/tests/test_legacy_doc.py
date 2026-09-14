"""旧版 .doc 支持：有 LibreOffice 就转换后解析，没有就给出能照做的提示。

`.doc` 是 OLE 二进制复合文档，`python-docx` 读不了，只能靠 LibreOffice 转换。
本机不一定装了它，所以这里把「转换成功」用替身跑通，「转换器缺失」用真实探测跑通
（那正是生产里最常见的分支）。

覆盖：
- 格式识别：.doc / application/msword 都认；content-type 退回也认；
- 缺失 LibreOffice：报明确的错，且**不降级成纯文本**；
- 转换成功：走既有 Word 解析链路，章节、行内版式、表格都照常拿到；
- 转换器存在但产出为空（文件损坏/加密）：报「另存为 .docx」这类可照做的提示；
- /api/capabilities 如实上报当前环境能不能吃 .doc。
"""
import io
import subprocess

import pytest
from docx import Document

from app.parsing.docx import parse_docx_bytes
from app.services import legacy_doc
from app.services.ingest import DOC, DOCX, TEXT, detect_format, parse_bytes


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    """探测结果是进程级缓存，用例之间必须隔离。"""
    legacy_doc.reset_cache()
    yield
    legacy_doc.reset_cache()


def _docx_bytes() -> bytes:
    document = Document()
    document.add_heading("第1章 旧格式教材", level=1)
    paragraph = document.add_paragraph()
    paragraph.add_run("这段是")
    bold = paragraph.add_run("粗体")
    bold.bold = True
    paragraph.add_run("，用于验证行内版式没有在转换中丢掉。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "甲"
    table.cell(0, 1).text = "乙"
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


# ---------- 格式识别 ----------


def test_detect_doc_by_extension_and_content_type():
    assert detect_format("book.doc") == DOC
    assert detect_format("BOOK.DOC") == DOC
    assert detect_format("blob", "application/msword") == DOC
    # .docx 不能被误判成 .doc
    assert detect_format("book.docx") == DOCX
    assert detect_format("book.txt") == TEXT


# ---------- 没有 LibreOffice：优雅降级 ----------


def test_missing_converter_raises_actionable_error(monkeypatch):
    monkeypatch.setattr(legacy_doc, "find_soffice", lambda: None)

    with pytest.raises(ValueError) as excinfo:
        parse_bytes(DOC, b"\xd0\xcf\x11\xe0old-doc-bytes", "书名")

    message = str(excinfo.value)
    assert "LibreOffice" in message
    # 提示必须是用户能照做的下一步
    assert ".docx" in message


def test_missing_converter_never_falls_back_to_plain_text(monkeypatch):
    """绝不能悄悄抽成纯文本：那会丢掉全部行内版式，用户还以为导入成功了。"""
    monkeypatch.setattr(legacy_doc, "find_soffice", lambda: None)
    called = {"parse_docx": 0}

    import app.services.ingest as ingest

    real = ingest.parse_docx_bytes

    def spy(*args, **kwargs):
        called["parse_docx"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(ingest, "parse_docx_bytes", spy)
    with pytest.raises(ValueError):
        ingest.parse_bytes(DOC, b"old", "书名")

    assert called["parse_docx"] == 0


def test_probe_result_is_cached_so_repeat_uploads_do_not_respawn(monkeypatch):
    """探测结果要缓存：每个 .doc 上传都白起一次进程太浪费。"""
    calls = {"n": 0}

    def fake_which(name):
        calls["n"] += 1
        return None

    monkeypatch.setattr(legacy_doc.shutil, "which", fake_which)
    legacy_doc.reset_cache()

    assert legacy_doc.find_soffice() is None
    assert legacy_doc.find_soffice() is None
    # 两个候选名各查一次，且只查这一轮
    assert calls["n"] == len(legacy_doc._BINARY_NAMES)


def test_explicit_binary_path_via_env(monkeypatch):
    monkeypatch.setenv("AI_READER_SOFFICE", r"D:\LibreOffice\program\soffice.exe")
    legacy_doc.reset_cache()

    assert legacy_doc.find_soffice() == r"D:\LibreOffice\program\soffice.exe"


# ---------- 有 LibreOffice：转换后走既有 Word 链路 ----------


def test_converted_docx_keeps_chapters_rich_text_and_tables(monkeypatch):
    """转换成功后必须走**同一条** Word 解析链路，能力不打折。"""
    monkeypatch.setattr(legacy_doc, "find_soffice", lambda: "soffice")
    converted = _docx_bytes()

    def fake_run(args, **kwargs):
        # 替身扮演 LibreOffice：把 --outdir 下的 input.doc 变成 input.docx
        outdir = args[args.index("--outdir") + 1]
        (legacy_doc.Path(outdir) / "input.docx").write_bytes(converted)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(legacy_doc.subprocess, "run", fake_run)

    book = parse_bytes(DOC, b"\xd0\xcf\x11\xe0old", "书名")

    assert [c.title for c in book.chapters] == ["第1章 旧格式教材"]
    sections = [s for c in book.chapters for s in c.sections]
    assert any(s.kind == "table" for s in sections)
    bold_runs = [
        run
        for s in sections
        if s.content
        for run in (s.content.get("runs") or [])
        if "b" in run.get("style", [])
    ]
    assert bold_runs, "转换后的行内粗体不能丢"
    assert any("粗体" in run["text"] for run in bold_runs)


def test_converted_bytes_are_the_ones_parsed(monkeypatch):
    """解析的必须是转换产出的字节，而不是原始 .doc 字节。"""
    monkeypatch.setattr(legacy_doc, "find_soffice", lambda: "soffice")
    converted = _docx_bytes()
    seen = {}

    def fake_run(args, **kwargs):
        outdir = args[args.index("--outdir") + 1]
        (legacy_doc.Path(outdir) / "input.docx").write_bytes(converted)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(legacy_doc.subprocess, "run", fake_run)

    import app.services.ingest as ingest

    real = ingest.parse_docx_bytes

    def spy(data, *args, **kwargs):
        seen["data"] = data
        return real(data, *args, **kwargs)

    monkeypatch.setattr(ingest, "parse_docx_bytes", spy)
    ingest.parse_bytes(DOC, b"\xd0\xcf\x11\xe0-original", "书名")

    assert seen["data"] == converted


def test_converter_producing_nothing_raises_actionable_error(monkeypatch):
    """转换器在但没产出（损坏/加密）→ 提示另存为 .docx，而不是抛底层报错。"""
    monkeypatch.setattr(legacy_doc, "find_soffice", lambda: "soffice")

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, b"", b"Error: source file could not be loaded")

    monkeypatch.setattr(legacy_doc.subprocess, "run", fake_run)

    with pytest.raises(ValueError) as excinfo:
        parse_bytes(DOC, b"broken", "书名")

    assert ".docx" in str(excinfo.value)


def test_temp_dir_is_cleaned_up(monkeypatch):
    """中转目录不能残留：转换在临时目录里做，读完就删。"""
    monkeypatch.setattr(legacy_doc, "find_soffice", lambda: "soffice")
    converted = _docx_bytes()
    captured = {}

    def fake_run(args, **kwargs):
        outdir = legacy_doc.Path(args[args.index("--outdir") + 1])
        captured["dir"] = outdir
        (outdir / "input.docx").write_bytes(converted)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(legacy_doc.subprocess, "run", fake_run)
    legacy_doc.convert_doc_to_docx(b"\xd0\xcf\x11\xe0old")

    assert not captured["dir"].exists()


# ---------- 能力上报 ----------


def test_capabilities_without_libreoffice(client, monkeypatch):
    monkeypatch.setattr(legacy_doc, "find_soffice", lambda: None)
    legacy_doc.reset_cache()

    data = client.get("/api/capabilities").json()

    assert data["legacyDoc"] is False
    assert "doc" not in data["formats"]
    assert ".docx" in data["legacyDocHint"]


def test_capabilities_with_libreoffice(client, monkeypatch):
    monkeypatch.setattr(legacy_doc, "find_soffice", lambda: "soffice")
    legacy_doc.reset_cache()

    data = client.get("/api/capabilities").json()

    assert data["legacyDoc"] is True
    assert "doc" in data["formats"]
    assert data["legacyDocHint"] == ""


def test_upload_doc_without_converter_returns_422_with_hint(client, monkeypatch):
    monkeypatch.setattr(legacy_doc, "find_soffice", lambda: None)
    legacy_doc.reset_cache()

    res = client.post(
        "/api/books",
        files={"file": ("old.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1old", "application/msword")},
        data={"title": "旧格式教材"},
    )

    assert res.status_code == 422
    assert "LibreOffice" in res.json()["detail"]
