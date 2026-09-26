"""删教材必须连磁盘上的字节一起删。

README 承诺「删除不可恢复」，用户据此认为教材副本已经不在机器上了。过去的删除
只清数据库行，`data/sources` 与 `data/assets` 里的文件原样留着——一本 300 页扫描件
几十 MB，删十本等于白占几百 MB；而且那是他人教材的副本，留在磁盘上还有合规含义。

这些测试走完整的 HTTP 路径，因为承诺是对用户做出的，而不是对某个内部函数。
"""
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _upload(client, name: str, data: bytes) -> str:
    res = client.post("/api/books", files={"file": (name, data, DOCX_MIME)})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _sources(tmp_path):
    return tmp_path / "sources"


def _assets_of(tmp_path, book_id):
    return sorted((tmp_path / "assets").glob(f"{book_id}-*"))


def test_delete_removes_source_file_and_extracted_images(client, tmp_path, demo_docx_with_assets_bytes):
    """两条落盘路径（原文件、插图）都要清掉。"""
    book_id = _upload(client, "带图教材.docx", demo_docx_with_assets_bytes)
    source = _sources(tmp_path) / f"{book_id}.docx"
    assets = _assets_of(tmp_path, book_id)
    # 先确认夹具真的产出了这两类文件，否则下面的断言是空转
    assert source.is_file()
    assert assets

    assert client.delete(f"/api/books/{book_id}").status_code == 204

    assert not source.exists(), "原文件没被删掉"
    assert [p for p in assets if p.exists()] == [], "插图没被删掉"


def test_delete_is_scoped_to_one_book(client, tmp_path, demo_docx_with_assets_bytes):
    """删一本不能碰到另一本的任何文件。前缀匹配必须精确到 book_id。"""
    drop = _upload(client, "要删的.docx", demo_docx_with_assets_bytes)
    keep = _upload(client, "要留的.docx", demo_docx_with_assets_bytes)
    keep_source = _sources(tmp_path) / f"{keep}.docx"
    keep_assets = _assets_of(tmp_path, keep)
    assert keep_source.is_file() and keep_assets

    assert client.delete(f"/api/books/{drop}").status_code == 204

    assert keep_source.is_file(), "另一本教材的原文件被误删"
    assert [p for p in keep_assets if p.exists()] == keep_assets, "另一本教材的插图被误删"


def test_delete_leaves_unrelated_files_in_assets_alone(client, tmp_path, demo_docx_bytes):
    """assets 目录里不属于这本书的文件（比如别的书、或用户自己放的）一律不碰。"""
    stray = tmp_path / "assets" / "someone-else-p1-0.png"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"not-ours")

    book_id = _upload(client, "普通教材.docx", demo_docx_bytes)
    assert client.delete(f"/api/books/{book_id}").status_code == 204

    assert stray.is_file()


def test_delete_succeeds_when_files_are_already_gone(client, tmp_path, demo_docx_bytes):
    """原文件被用户手工删掉时，「删除教材」仍要成功——字节残留不该变成失败的删除。"""
    book_id = _upload(client, "手动删过.docx", demo_docx_bytes)
    (_sources(tmp_path) / f"{book_id}.docx").unlink()

    assert client.delete(f"/api/books/{book_id}").status_code == 204
    assert client.get(f"/api/books/{book_id}").status_code == 404


def test_delete_without_saved_source_still_works(client, tmp_path, demo_docx_bytes):
    """没有留存原文件的教材（该功能上线前导入的）删除同样要干净利落。"""
    book_id = _upload(client, "无原文件.docx", demo_docx_bytes)
    client.app.state.db.set_book_source(book_id, "", "")

    assert client.delete(f"/api/books/{book_id}").status_code == 204


def test_delete_twice_is_404_not_error(client, tmp_path, demo_docx_bytes):
    """第二次删同一本返回 404，而不是 500——重复点击「删除」不该炸。"""
    book_id = _upload(client, "删两次.docx", demo_docx_bytes)

    assert client.delete(f"/api/books/{book_id}").status_code == 204
    assert client.delete(f"/api/books/{book_id}").status_code == 404
