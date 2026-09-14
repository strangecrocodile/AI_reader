"""原文件留存与下载：上传后能拿回一模一样的字节流。

覆盖：
- 上传成功后原文件落在 data/sources/ 下，Bytes 完全一致（不是重新生成的等价物）；
- books 上记下来源格式与文件名，书元信息据此暴露 hasSource；
- GET /api/books/{id}/source 下载到原字节，且带附件的 Content-Disposition；
- 没留存原文件的教材（早于该功能上线导入）返回 404 而不是坏链接；
- source_name 被改成带目录的路径时，解析结果仍被限制在 sources 目录内。
"""
from pathlib import Path

from app.services.ingest import source_path_of


def _upload(client, content: bytes, filename: str, content_type: str = "application/pdf"):
    return client.post(
        "/api/books",
        files={"file": (filename, content, content_type)},
        data={"title": "原文件测试教材"},
    )


def test_uploaded_source_is_kept_byte_identical(client, app, demo_pdf_bytes):
    res = _upload(client, demo_pdf_bytes, "demo.pdf")
    assert res.status_code == 201

    book = res.json()
    assert book["hasSource"] is True
    assert book["sourceFormat"] == "pdf"

    record = app.state.db.get_book(book["id"])
    stored = Path(app.state.settings.sources_dir) / record["source_name"]
    assert stored.is_file()
    # 关键：必须与上传的字节完全一致，而不是「重新渲染出来的近似文件」
    assert stored.read_bytes() == demo_pdf_bytes


def test_download_source_returns_original_bytes(client, app, demo_pdf_bytes):
    book = _upload(client, demo_pdf_bytes, "demo.pdf").json()

    res = client.get(f"/api/books/{book['id']}/source")

    assert res.status_code == 200
    assert res.content == demo_pdf_bytes
    assert res.headers["content-type"] == "application/pdf"
    # 附件形式：浏览器下载而不是在标签页里预览
    assert "attachment" in res.headers["content-disposition"]


def test_docx_source_uses_word_media_type(client, demo_docx_bytes):
    res = _upload(
        client,
        demo_docx_bytes,
        "demo.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    book = res.json()

    assert book["sourceFormat"] == "docx"
    download = client.get(f"/api/books/{book['id']}/source")
    assert download.status_code == 200
    assert download.content == demo_docx_bytes
    assert "wordprocessingml" in download.headers["content-type"]


def test_source_download_404_for_book_without_original(client, app):
    """没有留存原文件的教材要明确 404，前端才能把按钮置灰。"""
    db = app.state.db
    db.add_book(
        {
            "id": "legacy01",
            "title": "升级前导入的教材",
            "author": "",
            "note": "",
            "progress_pct": 0.0,
            "content_warning": "",
            "created_at": "2024-01-01T00:00:00+00:00",
        }
    )

    assert client.get("/api/books/legacy01").json()["hasSource"] is False
    res = client.get("/api/books/legacy01/source")
    assert res.status_code == 404
    assert "原文件" in res.json()["detail"]


def test_source_download_404_when_file_vanished(client, app, demo_pdf_bytes):
    """库里记了名字但文件被删（比如只备份了 db）→ 404，不是 500。"""
    book = _upload(client, demo_pdf_bytes, "demo.pdf").json()
    record = app.state.db.get_book(book["id"])
    (Path(app.state.settings.sources_dir) / record["source_name"]).unlink()

    assert client.get(f"/api/books/{book['id']}/source").status_code == 404


def test_unknown_book_source_returns_404(client):
    assert client.get("/api/books/nope/source").status_code == 404


def test_source_path_stays_inside_sources_dir(tmp_path):
    """source_name 被改成带目录的路径时，也只能解析到 sources 目录内。"""
    settings = type("S", (), {"sources_dir": tmp_path})()
    secret = tmp_path.parent / "secret.pdf"
    secret.write_bytes(b"should not be readable")

    assert source_path_of({}, {"source_name": "../secret.pdf"}, settings) is None
    assert source_path_of({}, {"source_name": ""}, settings) is None
    assert source_path_of({}, {}, settings) is None
