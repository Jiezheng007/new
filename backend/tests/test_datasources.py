"""Acceptance tests for Phase 3 / Issue 4: data source management & opinion items.

Covers:
  - admin CRUD on data sources + manual fetch
  - static demo connector persists 6 items with dedup on re-fetch
  - RSS connector without feedparser / unreachable host fails gracefully
  - opinion list/detail with filters and role-based access
  - every state change writes an AuditLog row
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db import session as session_module
from app.models.alert import Alert
from app.models.audit import AuditLog
from app.models.datasource import DataSource, OpinionItem


def _engine():
    return session_module.engine


def _latest_audit(action: str, target_id: str = ""):
    db = Session(_engine())
    try:
        q = db.query(AuditLog).filter(AuditLog.action == action)
        if target_id:
            q = q.filter(AuditLog.target_id == target_id)
        return q.order_by(AuditLog.id.desc()).first()
    finally:
        db.close()


# ---------- data source CRUD ----------

def test_list_datasources_requires_admin(client):
    res = client.get("/api/datasources")
    assert res.status_code == 401
    for user, pwd in [("risk", "risk123"), ("handler", "handler123"), ("auditor", "auditor123"), ("viewer", "viewer123")]:
        client.post("/api/auth/login", json={"username": user, "password": pwd})
        res = client.get("/api/datasources")
        assert res.status_code == 403, user
        client.post("/api/auth/logout")


def test_list_datasources_includes_static_demo_for_admin(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.get("/api/datasources")
    assert res.status_code == 200
    codes = {s["code"] for s in res.json()}
    assert "demo_static" in codes
    assert "import_csv" in codes
    assert "import_json" in codes


def test_create_datasource_as_admin(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.post(
        "/api/datasources",
        json={
            "code": "rss_demo",
            "name": "RSS 演示",
            "source_type": "rss",
            "url": "https://example.com/feed.xml",
            "weight": 1.5,
            "description": "测试源",
            "is_enabled": True,
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["code"] == "rss_demo"
    assert body["weight"] == 1.5

    entry = _latest_audit("datasource.create", str(body["id"]))
    assert entry is not None
    assert entry.result == "success"
    detail = json.loads(entry.detail)
    assert detail["code"] == "rss_demo"


def test_create_datasource_rejects_duplicate_code(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.post(
        "/api/datasources",
        json={"code": "demo_static", "name": "冲突", "source_type": "rss", "url": "https://x"},
    )
    assert res.status_code == 409


def test_create_datasource_rejects_missing_url_for_rss(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.post(
        "/api/datasources",
        json={"code": "nourl", "name": "no url", "source_type": "rss"},
    )
    assert res.status_code == 422


def test_create_weibo_datasource_as_admin(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.post(
        "/api/datasources",
        json={
            "code": "weibo_demo",
            "name": "微博演示",
            "source_type": "weibo",
            "url": "https://example.com/weibo.json",
            "weight": 2.0,
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["code"] == "weibo_demo"
    assert body["source_type"] == "weibo"


def test_create_weibo_datasource_rejects_missing_url(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.post(
        "/api/datasources",
        json={"code": "weibo_nourl", "name": "微博无地址", "source_type": "weibo"},
    )
    assert res.status_code == 422


def test_create_news_search_datasource_uses_query_not_url(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.post(
        "/api/datasources",
        json={
            "code": "rock_news",
            "name": "洛克王国新闻监控",
            "source_type": "news_search",
            "query": "洛克王国 OR 洛克王国手游",
            "fetch_interval_minutes": 30,
            "max_items_per_fetch": 3,
            "config": {"language": "zh", "region": "CN"},
            "description": "关键词驱动新闻监控",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["source_type"] == "news_search"
    assert body["query"] == "洛克王国 OR 洛克王国手游"
    assert body["url"] == ""
    assert body["fetch_interval_minutes"] == 30
    assert body["max_items_per_fetch"] == 3
    assert body["config"]["region"] == "CN"


def test_create_news_search_datasource_rejects_missing_query(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.post(
        "/api/datasources",
        json={"code": "news_no_query", "name": "无关键词", "source_type": "news_search"},
    )
    assert res.status_code == 422


def test_test_news_search_datasource_returns_samples(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.post(
        "/api/datasources/test",
        json={
            "source_type": "news_search",
            "query": "洛克王国",
            "max_items_per_fetch": 2,
            "config": {"language": "zh", "region": "CN"},
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["sample_count"] == 2
    assert len(body["samples"]) == 2
    assert "洛克王国" in body["samples"][0]["title"]
    assert body["message"] == "测试成功,可抓取 2 条样例"


def test_create_datasource_blocks_non_admin(client):
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        "/api/datasources",
        json={"code": "x", "name": "x", "source_type": "rss", "url": "https://x"},
    )
    assert res.status_code == 403


def test_update_datasource_enables_and_disables(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    create = client.post(
        "/api/datasources",
        json={"code": "upd", "name": "upd", "source_type": "rss", "url": "https://x"},
    )
    target_id = str(create.json()["id"])
    res = client.patch(f"/api/datasources/{target_id}", json={"is_enabled": False, "weight": 2.0})
    assert res.status_code == 200
    body = res.json()
    assert body["is_enabled"] is False
    assert body["weight"] == 2.0

    entry = _latest_audit("datasource.disable", target_id)
    assert entry is not None
    assert entry.result == "success"


def test_update_datasource_404(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.patch("/api/datasources/99999", json={"name": "x"})
    assert res.status_code == 404


# ---------- fetch ----------

def test_manual_fetch_static_demo_persists_items(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    db = Session(_engine())
    try:
        src = db.query(DataSource).filter(DataSource.code == "demo_static").one()
        source_id = src.id
    finally:
        db.close()
    res = client.post(f"/api/datasources/{source_id}/fetch")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["accepted"] == 6
    assert body["duplicate"] == 0

    db = Session(_engine())
    try:
        items = db.query(OpinionItem).filter(OpinionItem.source_id == source_id).all()
    finally:
        db.close()
    assert len(items) == 6
    titles = {it.title for it in items}
    assert any("重大" in t or "泄露" in t for t in titles)


def test_manual_fetch_dedupes_on_repeat(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    db = Session(_engine())
    try:
        src = db.query(DataSource).filter(DataSource.code == "demo_static").one()
        source_id = src.id
    finally:
        db.close()
    first = client.post(f"/api/datasources/{source_id}/fetch")
    assert first.status_code == 200
    second = client.post(f"/api/datasources/{source_id}/fetch")
    assert second.status_code == 200
    body = second.json()
    assert body["accepted"] == 0
    assert body["duplicate"] == 6


def test_manual_fetch_records_audit_and_status(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    db = Session(_engine())
    try:
        src = db.query(DataSource).filter(DataSource.code == "demo_static").one()
        source_id = src.id
    finally:
        db.close()
    client.post(f"/api/datasources/{source_id}/fetch")
    db = Session(_engine())
    try:
        src = db.query(DataSource).filter(DataSource.code == "demo_static").one()
        assert src.latest_fetch_status in ("success", "partial")
        assert src.latest_fetch_at is not None
        assert src.latest_items_count == 6
    finally:
        db.close()
    entry = _latest_audit("datasource.fetch", str(source_id))
    assert entry is not None
    assert entry.result in ("success", "partial")
    detail = json.loads(entry.detail)
    assert detail["accepted"] == 6


def test_manual_fetch_blocked_when_disabled(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    create = client.post(
        "/api/datasources",
        json={"code": "off", "name": "off", "source_type": "rss", "url": "https://x", "is_enabled": True},
    )
    target_id = create.json()["id"]
    client.patch(f"/api/datasources/{target_id}", json={"is_enabled": False})
    res = client.post(f"/api/datasources/{target_id}/fetch")
    assert res.status_code == 400
    assert "停用" in res.json()["detail"]


def test_manual_fetch_blocked_for_non_admin(client):
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post("/api/datasources/1/fetch")
    assert res.status_code == 403


def test_rss_connector_without_feedparser_falls_back(monkeypatch, client):
    """If feedparser is not importable, RSS connector reports a clear 502 error."""
    # Import the rss subpackage directly so we can swap its module attribute.
    from app.services.connectors import rss as rss_mod
    # Force the lazy `import feedparser` inside RssConnector.fetch to raise.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "feedparser":
            raise ImportError("simulated missing feedparser")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    create = client.post(
        "/api/datasources",
        json={"code": "rss_no_parser", "name": "rss", "source_type": "rss", "url": "https://example.com/feed"},
    )
    target_id = create.json()["id"]
    res = client.post(f"/api/datasources/{target_id}/fetch")
    assert res.status_code == 502
    assert "feedparser" in res.json()["detail"]


def test_manual_fetch_weibo_json_persists_and_dedupes(monkeypatch, client):
    from app.services.connectors import weibo as weibo_mod

    payload = {
        "statuses": [
            {
                "idstr": "501",
                "text_raw": "网友爆料某品牌存在严重质量问题,监管部门已介入。",
                "created_at": "2026-06-08T10:00:00+00:00",
                "user": {"id": "1001", "screen_name": "微博用户A"},
                "reposts_count": 12,
                "comments_count": 8,
                "attitudes_count": 99,
            },
            {
                "mblog": {
                    "id": "502",
                    "text": "<span>消费者投诉售后响应缓慢</span>",
                    "created_at": "Mon, 08 Jun 2026 11:00:00 GMT",
                    "user": {"idstr": "1002", "screen_name": "微博用户B"},
                }
            },
        ]
    }

    class FakeResponse:
        content = b""

        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            assert url == "https://example.com/weibo.json"
            return FakeResponse()

    monkeypatch.setattr(weibo_mod.httpx, "Client", FakeClient)

    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    create = client.post(
        "/api/datasources",
        json={
            "code": "weibo_fetch",
            "name": "微博抓取",
            "source_type": "weibo",
            "url": "https://example.com/weibo.json",
        },
    )
    assert create.status_code == 201, create.text
    source_id = create.json()["id"]

    first = client.post(f"/api/datasources/{source_id}/fetch")
    assert first.status_code == 200, first.text
    assert first.json()["accepted"] == 2

    db = Session(_engine())
    try:
        items = (
            db.query(OpinionItem)
            .filter(OpinionItem.source_id == source_id)
            .order_by(OpinionItem.id)
            .all()
        )
        assert len(items) == 2
        assert items[0].external_id == "501"
        assert items[0].author == "微博用户A"
        assert items[0].source_type == "weibo"
        assert "严重质量问题" in items[0].content
        assert "reposts_count" in items[0].raw_payload
        assert items[1].title == "消费者投诉售后响应缓慢"
    finally:
        db.close()

    second = client.post(f"/api/datasources/{source_id}/fetch")
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["accepted"] == 0
    assert body["duplicate"] == 2


def test_manual_fetch_news_search_persists_keyword_news(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    create = client.post(
        "/api/datasources",
        json={
            "code": "keyword_news_fetch",
            "name": "关键词新闻抓取",
            "source_type": "news_search",
            "query": "洛克王国",
            "max_items_per_fetch": 2,
        },
    )
    assert create.status_code == 201, create.text
    source_id = create.json()["id"]

    first = client.post(f"/api/datasources/{source_id}/fetch")
    assert first.status_code == 200, first.text
    assert first.json()["accepted"] == 2

    db = Session(_engine())
    try:
        items = (
            db.query(OpinionItem)
            .filter(OpinionItem.source_id == source_id)
            .order_by(OpinionItem.id)
            .all()
        )
        assert len(items) == 2
        assert items[0].source_type == "news_search"
        assert "洛克王国" in items[0].title
        assert items[0].url.startswith("https://news.example.test/")
        assert "mock_news_search" in items[0].raw_payload
    finally:
        db.close()

    second = client.post(f"/api/datasources/{source_id}/fetch")
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["accepted"] == 0
    assert body["duplicate"] == 2


def test_manual_fetch_news_search_creates_pending_alert_for_high_risk_news(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    create = client.post(
        "/api/datasources",
        json={
            "code": "keyword_news_alert",
            "name": "关键词新闻预警",
            "source_type": "news_search",
            "query": "洛克王国",
            "max_items_per_fetch": 2,
        },
    )
    assert create.status_code == 201, create.text
    source_id = create.json()["id"]

    fetch = client.post(f"/api/datasources/{source_id}/fetch")
    assert fetch.status_code == 200, fetch.text

    db = Session(_engine())
    try:
        alerts = (
            db.query(Alert)
            .join(OpinionItem, OpinionItem.id == Alert.opinion_item_id)
            .filter(OpinionItem.source_id == source_id)
            .all()
        )
        assert alerts
        assert any(a.status == "pending" and a.risk_level in {"high", "severe"} for a in alerts)
    finally:
        db.close()


# ---------- opinion list/detail ----------

def _seed_demo_items(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    db = Session(_engine())
    try:
        src = db.query(DataSource).filter(DataSource.code == "demo_static").one()
        source_id = src.id
    finally:
        db.close()
    client.post(f"/api/datasources/{source_id}/fetch")
    client.post("/api/auth/logout")


def test_list_opinions_requires_auth(client):
    res = client.get("/api/opinions")
    assert res.status_code == 401


def test_list_opinions_blocks_handler(client):
    client.post("/api/auth/login", json={"username": "handler", "password": "handler123"})
    res = client.get("/api/opinions")
    assert res.status_code == 403


def test_list_opinions_returns_items_for_risk_control(client):
    _seed_demo_items(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/api/opinions?limit=10")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 6
    assert len(body["items"]) == 6
    item = body["items"][0]
    assert item["source_code"] == "demo_static"
    assert item["title"]


def test_list_opinions_keyword_filter(client):
    _seed_demo_items(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/api/opinions?q=财报")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert "财报" in body["items"][0]["title"]


def test_list_opinions_source_filter(client):
    _seed_demo_items(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    db = Session(_engine())
    try:
        src = db.query(DataSource).filter(DataSource.code == "demo_static").one()
    finally:
        db.close()
    res = client.get(f"/api/opinions?source_id={src.id}")
    assert res.status_code == 200
    assert res.json()["total"] == 6


def test_list_opinions_time_range_filter(client):
    _seed_demo_items(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/api/opinions?end_at=2020-01-01T00:00:00Z")
    assert res.status_code == 200
    assert res.json()["total"] == 0


def test_get_opinion_detail(client):
    _seed_demo_items(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/api/opinions/1")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == 1
    assert body["title"]


def test_get_opinion_404(client):
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/api/opinions/99999")
    assert res.status_code == 404


# ---------- web UI page ----------

def test_datasources_page_renders_for_admin(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.get("/web/datasources")
    assert res.status_code == 200
    body = res.text
    assert "数据源" in body
    assert "关键词监控" in body
    assert "测试抓取" in body


def test_datasources_page_403_for_viewer(client):
    client.post("/api/auth/login", json={"username": "viewer", "password": "viewer123"})
    res = client.get("/web/datasources")
    assert res.status_code == 403


def test_opinions_page_renders_for_risk_control(client):
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/web/opinions")
    assert res.status_code == 200
    body = res.text
    assert "舆情" in body


def test_opinions_page_403_for_handler(client):
    client.post("/api/auth/login", json={"username": "handler", "password": "handler123"})
    res = client.get("/web/opinions")
    assert res.status_code == 403
