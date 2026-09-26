"""测试自身的卫生：跑测试不该往**真实**数据目录里写东西。

背景（这是回归测试，不是假想的洁癖）：`app` 夹具过去只覆盖 `db_path`，
`sources_dir` / `assets_dir` 仍指向 `backend/data/`。而原文件与插图的落盘在
`services/ingest` 里发生、不经过 `db_path`，于是每个上传教材的测试都会在真实
数据目录留下一份原文件，且没人回收——实测积累到「库里 3 本书、`data/sources/`
里 1876 个文件」。

这里逐条给出**精确到动作**的判据；广覆盖的那一层是 conftest 里的
`_real_data_dir_stays_clean`（会话级，管住包括以后新写的所有测试）。
"""
from pathlib import Path

from conftest import REAL_ASSETS, REAL_SOURCES, snapshot_names

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_settings_paths_live_under_tmp_path(app, tmp_path):
    """三个派生目录都必须跟着 `data_dir` 走，一个都不能漏。"""
    settings = app.state.settings
    assert Path(settings.data_dir) == tmp_path
    assert Path(settings.sources_dir) == tmp_path / "sources"
    assert Path(settings.assets_dir) == tmp_path / "assets"


def test_upload_writes_source_file_inside_tmp_path_only(client, tmp_path, demo_docx_bytes):
    before = snapshot_names(REAL_SOURCES)

    res = client.post("/api/books", files={"file": ("demo.docx", demo_docx_bytes, DOCX_MIME)})
    assert res.status_code == 201
    book_id = res.json()["id"]

    # 1) 原文件落在测试自己的目录里，字节一致（不是空壳）
    stored = tmp_path / "sources" / f"{book_id}.docx"
    assert stored.is_file()
    assert stored.read_bytes() == demo_docx_bytes

    # 2) 真实数据目录一个文件都没多——这条才是这个 bug 的判据
    assert snapshot_names(REAL_SOURCES) == before, (
        "测试把原文件写进了真实 data/sources：说明 app 夹具的 settings 没被隔离"
    )


def test_upload_extracted_images_stay_inside_tmp_path(
    client, tmp_path, demo_docx_with_assets_bytes
):
    """插图走的是 assets_dir，另一条落盘路径，同样不能漏。"""
    before = snapshot_names(REAL_ASSETS)

    res = client.post(
        "/api/books",
        files={"file": ("with-assets.docx", demo_docx_with_assets_bytes, DOCX_MIME)},
    )
    assert res.status_code == 201
    book_id = res.json()["id"]

    extracted = list((tmp_path / "assets").glob(f"{book_id}-*"))
    assert extracted, "带插图的教材应该在隔离目录里落盘出插图"
    assert snapshot_names(REAL_ASSETS) == before, (
        "测试把插图写进了真实 data/assets：说明 app 夹具的 settings 没被隔离"
    )
