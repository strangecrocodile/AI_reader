"""空库自动导入示例教材：把「不配 Key 也能跑通演示」从 README 落成事实。

README 拿「不配置任何模型 Key 也能跑通完整演示」当核心卖点，但 `backend/data/` 不进 Git，
新克隆的仓库里一本书都没有：用户按 README 起好前后端，主页停在「还没有教材」，引导还是
「去 backend 目录执行 scripts/make_demo_pdf.py」——一个网页产品的第一步被推给命令行。

判据有三条，缺一不可：
1. 空库时真的自动出现一本书，而且是**能学**的（有章节、有正文锚点）；
2. 它和用户上传的教材没有区别（有原文件可下载、能走溯源问答）；
3. 它**不会**覆盖已有数据，也**不会**让服务起不来。
"""
import pytest

from app.config import Settings
from app.db import Database
from app.llm.client import MockLLM
from app.main import create_app
from app.services import demo


def _settings(tmp_path: str, auto_demo: bool = True) -> Settings:
    settings = Settings(data_dir=tmp_path)
    settings.embedding_url = ""
    settings.embedding_api_key = ""
    settings.auto_demo = auto_demo
    return settings


def test_empty_library_gets_a_demo_book_on_startup(tmp_path):
    app = create_app(settings=_settings(tmp_path), db_path=tmp_path / "t.db", llm=MockLLM())

    books = app.state.db.list_books()

    assert len(books) == 1
    assert books[0]["title"] == demo.DEMO_TITLE


def test_seeded_book_is_actually_studiable(tmp_path):
    """「导入了一本」不算数，得是能打开、有章节、有正文的一本。"""
    app = create_app(settings=_settings(tmp_path), db_path=tmp_path / "t.db", llm=MockLLM())
    book = app.state.db.list_books()[0]

    chapters = app.state.db.chapters_of(book["id"])
    assert len(chapters) >= 2, "示例教材至少要能演示「翻章」"

    sections = app.state.db.sections_of(book["id"], chapters[0]["id"])
    body = [s for s in sections if s.get("kind", "p") != "heading"]
    assert body, "第一章要有正文段落，否则掌握度、划词、溯源都无从演示"
    assert any(len(s.get("text", "")) > 40 for s in body)

    anchors = app.state.db.anchors_of(book["id"], chapters[0]["id"])
    assert anchors, "没有锚点就没有溯源回跳，等于把产品最核心的承诺演示不出来"


def test_seeded_book_keeps_its_original_file_like_any_upload(tmp_path):
    """示例教材不许是特殊通道：原文件要留在盘上，用户能下载、也能重新解析。

    命名规则也一样是 `{book_id}.{fmt}`（`ingest_file_bytes` 的约定），
    因为它走的**就是**用户上传那条链路，没有第二套代码。
    """
    app = create_app(settings=_settings(tmp_path), db_path=tmp_path / "t.db", llm=MockLLM())
    book = app.state.db.list_books()[0]

    assert book["source_name"] == f"{book['id']}.pdf"
    stored = tmp_path / "sources" / book["source_name"]
    assert stored.is_file()
    assert stored.read_bytes().startswith(b"%PDF-")


def test_seeded_original_bytes_are_kept_verbatim(tmp_path, monkeypatch):
    """落盘的就是当时那份字节本身，不是「重新生成的等价物」。

    固定载荷来测：PyMuPDF 两次 `tobytes()` 的结果并不逐字节相同（内嵌时间戳/ID），
    拿两次生成的产物互比会得到一个偶发失败的测试。
    """
    payload = demo.build_demo_pdf_bytes()  # 只生成一次，之后固定喂给入库
    monkeypatch.setattr(demo, "build_demo_pdf_bytes", lambda: payload)
    database = Database(tmp_path / "t.db")
    database.init()

    info = demo.seed_demo_if_empty(database, _settings(tmp_path))

    assert (tmp_path / "sources" / f"{info['id']}.pdf").read_bytes() == payload


def test_existing_library_is_left_untouched(tmp_path):
    """有书就不动它。自动导入若覆盖用户数据，就是灾难而不是便利。"""
    database = Database(tmp_path / "t.db")
    database.init()
    database.add_book({"id": "mine0001", "title": "我自己的教材", "created_at": "2026-01-01T00:00:00+00:00"})

    app = create_app(settings=_settings(tmp_path), db_path=tmp_path / "t.db", llm=MockLLM())

    titles = [b["title"] for b in app.state.db.list_books()]
    assert titles == ["我自己的教材"]


def test_auto_demo_can_be_turned_off(tmp_path):
    """需要真正空的书架时（测试、或部署到已有数据的库）要能关掉。"""
    app = create_app(settings=_settings(tmp_path, auto_demo=False), db_path=tmp_path / "t.db", llm=MockLLM())

    assert app.state.db.list_books() == []


def test_seeding_failure_does_not_break_startup(tmp_path, monkeypatch):
    """示例教材是便利，不是前提。它炸了也不能让后端起不来。"""
    def boom():
        raise RuntimeError("PyMuPDF 没装")

    monkeypatch.setattr(demo, "build_demo_pdf_bytes", boom)

    app = create_app(settings=_settings(tmp_path), db_path=tmp_path / "t.db", llm=MockLLM())

    assert app.state.db.list_books() == []  # 没导入成功，但服务是活的
    assert app.state.db is not None


def test_seed_demo_if_empty_reports_what_it_did(tmp_path):
    settings = _settings(tmp_path)
    database = Database(tmp_path / "t.db")
    database.init()

    first = demo.seed_demo_if_empty(database, settings)
    second = demo.seed_demo_if_empty(database, settings)

    assert first is not None and first["title"] == demo.DEMO_TITLE
    assert second is None, "已经有书了，第二次应当什么都不做"


@pytest.mark.parametrize("value,expected", [("off", False), ("0", False), ("off ", False)])
def test_auto_demo_env_switch(monkeypatch, tmp_path, value, expected):
    monkeypatch.setenv("AI_READER_AUTO_DEMO", value)

    assert Settings(data_dir=tmp_path).auto_demo is expected
