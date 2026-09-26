"""孤儿文件回收：判据是「认得出归属、且教材已不在库里」，不是「看着像垃圾」。

这两条边界各有一个测试盯着：
- 库还在的书，它的原文件与插图**一个都不能删**（删错就是用户丢教材）；
- 名字不符合命名约定的文件不认领、不删除（可能是用户自己放的东西）。
"""
import pytest

from app.db import Database
from app.services import maintenance

#: 真实形态的教材 id：`uuid4().hex[:8]`，8 位小写十六进制。
#: 这里必须用真的十六进制——用 "keep0001" 这类 id 会让文件落到「认不出归属」那一类，
#: 测试就测不到归属判定了（这个坑我踩过一次）。
KEEP_ID = "a1b2c3d4"  # 库里还在，原文件与插图都指向它
MISMATCH_ID = "11223344"  # 库里还在，但 source_name 没指向磁盘上那份
GONE_ID = "deadbeef"  # 教材已被删除，磁盘上只剩残骸


@pytest.fixture
def store(tmp_path):
    """一个接近真实的数据目录：留下的书、对不上的书、已被删掉的书。"""
    database = Database(tmp_path / "m.db")
    database.init()
    database.add_book({"id": KEEP_ID, "title": "保留的书", "created_at": "2026-01-01T00:00:00+00:00"})
    database.add_book({"id": MISMATCH_ID, "title": "记录对不上的书", "created_at": "2026-01-01T00:00:00+00:00"})
    # GONE_ID 刻意**不**入库：它代表「教材已删、磁盘没清干净」的那种残骸

    settings = type("S", (), {"sources_dir": tmp_path / "sources", "assets_dir": tmp_path / "assets"})()
    settings.sources_dir.mkdir()
    settings.assets_dir.mkdir()

    # 库里还在且指向正确：必须保留
    (settings.sources_dir / f"{KEEP_ID}.pdf").write_bytes(b"keep")
    database.set_book_source(KEEP_ID, "pdf", f"{KEEP_ID}.pdf")
    (settings.assets_dir / f"{KEEP_ID}-p3-0.png").write_bytes(b"keep-img")
    # 库里还在但没指向它：可疑，只报告
    (settings.sources_dir / f"{MISMATCH_ID}.pdf").write_bytes(b"mismatch")
    # 教材已不在库里：可清理
    (settings.sources_dir / f"{GONE_ID}.docx").write_bytes(b"gone")
    (settings.assets_dir / f"{GONE_ID}-p1-0.png").write_bytes(b"gone-img")
    return database, settings, tmp_path


def test_scan_finds_only_files_without_a_live_book(store):
    database, settings, _ = store

    found = maintenance.scan(database, settings)

    assert [p.name for p in found["sources"]] == [f"{GONE_ID}.docx"]
    assert [p.name for p in found["assets"]] == [f"{GONE_ID}-p1-0.png"]


def test_scan_leaves_a_live_books_unreferenced_source_alone(store):
    """教材还在库里、只是 source_name 没指向磁盘那份时，**不能删**。

    这种状态可能来自一个 bug（列被清空），而磁盘上那份很可能是用户教材的唯一副本。
    「按名字猜它没用」就去删，是在拿别人的数据赌。
    """
    database, settings, _ = store

    found = maintenance.scan(database, settings)

    assert f"{MISMATCH_ID}.pdf" not in [p.name for p in found["sources"]]
    assert f"{MISMATCH_ID}.pdf" in [p.name for p in found["unrecognized"]]


def test_scan_never_claims_files_it_does_not_recognize(store):
    """名字不符合约定的东西不是我们的，只能报告，不能删。"""
    database, settings, _ = store
    (settings.sources_dir / "笔记.pdf").write_bytes(b"user-file")
    (settings.assets_dir / "logo.png").write_bytes(b"user-file")

    found = maintenance.scan(database, settings)

    assert {"笔记.pdf", "logo.png"} <= {p.name for p in found["unrecognized"]}
    assert "笔记.pdf" not in [p.name for p in found["sources"]]
    assert "logo.png" not in [p.name for p in found["assets"]]


def test_delete_orphans_removes_only_orphans(store):
    database, settings, _ = store
    (settings.sources_dir / "笔记.pdf").write_bytes(b"user-file")

    removed = maintenance.delete_orphans(database, settings)

    assert removed == {"sources": 1, "assets": 1, "unrecognized": 2}
    # 活着的那本安然无恙 —— 这是本模块最不能出错的地方
    assert (settings.sources_dir / f"{KEEP_ID}.pdf").is_file()
    assert (settings.assets_dir / f"{KEEP_ID}-p3-0.png").is_file()
    # 可疑的与用户自己的都留着
    assert (settings.sources_dir / f"{MISMATCH_ID}.pdf").is_file()
    assert (settings.sources_dir / "笔记.pdf").is_file()
    # 孤儿没了
    assert not (settings.sources_dir / f"{GONE_ID}.docx").exists()
    assert not (settings.assets_dir / f"{GONE_ID}-p1-0.png").exists()


def test_delete_orphans_is_idempotent(store):
    """清理要能重复跑：第一次删完，第二次应当什么都不做而不是报错。"""
    database, settings, _ = store

    maintenance.delete_orphans(database, settings)
    again = maintenance.delete_orphans(database, settings)

    assert again == {"sources": 0, "assets": 0, "unrecognized": 1}


def test_scan_tolerates_missing_directories(tmp_path):
    """全新的数据目录（什么都没导入过）不该让命令崩掉。"""
    database = Database(tmp_path / "empty.db")
    database.init()
    settings = type("S", (), {"sources_dir": tmp_path / "nope", "assets_dir": tmp_path / "nope2"})()

    found = maintenance.scan(database, settings)

    assert found == {"sources": [], "assets": [], "unrecognized": []}


def test_describe_reports_counts_and_a_sample(store):
    database, settings, _ = store

    text = maintenance.describe(maintenance.scan(database, settings))

    assert "原文件 1 个" in text
    assert "插图 1 个" in text
    assert "认不出归属、不会动：1 个" in text
    assert f"{GONE_ID}.docx" in text
