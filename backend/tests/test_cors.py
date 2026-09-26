"""CORS 只能放行前端自己，不能是 `*`。

后端没有任何鉴权，所以 `allow_origins=["*"]` 的含义是：用户在浏览器里打开的**任意**
网页，都能在后台读走整本教材原文（`GET /api/books/{id}/chapters/{cid}`），或者直接
`DELETE /api/books/{id}` 把教材删掉——教材 id 从 `GET /api/books` 就能免费拿到。

判据是「跨源请求拿不到响应 / 拿不到跨源授权」，而不是「后端返回 403」：
CORS 由浏览器执行，服务端只负责**不发放**授权头、并对预检直接拒绝。
"""
import pytest

from app.config import DEFAULT_CORS_ORIGINS, Settings

ALLOWED = "http://localhost:3000"
EVIL = "https://evil.example"


def test_default_origins_never_include_wildcard():
    """`*` 是这次要修掉的东西，默认值和解析结果里都不许再出现。"""
    assert "*" not in DEFAULT_CORS_ORIGINS
    assert "*" not in Settings(data_dir=".").cors_origins


def test_allowed_origin_gets_cross_origin_grant(client):
    res = client.get("/api/health", headers={"Origin": ALLOWED})

    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == ALLOWED


def test_foreign_origin_gets_no_cross_origin_grant(client):
    """别的网站读不到响应：授权头必须缺席，浏览器才会拦住。"""
    res = client.get("/api/books", headers={"Origin": EVIL})

    assert res.headers.get("access-control-allow-origin") is None


def test_foreign_origin_cannot_preflight_a_delete(client):
    """删除是这条防线真正要拦的动作：预检必须被拒，浏览器才不会发出 DELETE。"""
    res = client.options(
        "/api/books/some-book-id",
        headers={
            "Origin": EVIL,
            "Access-Control-Request-Method": "DELETE",
        },
    )

    assert res.status_code == 400
    assert res.headers.get("access-control-allow-origin") is None


def test_allowed_origin_can_preflight_a_delete(client):
    """前端该走的路不能被误伤——本机来源的删除预检要放行。"""
    res = client.options(
        "/api/books/some-book-id",
        headers={
            "Origin": ALLOWED,
            "Access-Control-Request-Method": "DELETE",
        },
    )

    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == ALLOWED


def test_env_var_overrides_origins(monkeypatch):
    """部署到别的域名时靠这个开关放行，否则用户会被自己的 CORS 挡在门外。"""
    monkeypatch.setenv("AI_READER_CORS_ORIGINS", "https://a.example, https://b.example ,")

    settings = Settings(data_dir=".")

    assert settings.cors_origins == ["https://a.example", "https://b.example"]


@pytest.mark.parametrize("origin", DEFAULT_CORS_ORIGINS)
def test_local_dev_ports_are_allowed_by_default(origin):
    """README 让用户在本机 3000 端口开前端，这条路径默认必须是通的。"""
    assert origin in Settings(data_dir=".").cors_origins
