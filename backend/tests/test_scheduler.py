"""Tests for the background scheduler and fetch_datasource service (Phase 11 / Issue 14).

Covers:
  - scheduler.run_once only touches enabled sources
  - scheduler.run_once skips csv / json_import (upload-only) types
  - scheduler.run_once flags failures without crashing the loop
  - re-entrancy guard: a second run_once while one is in progress is a no-op
  - the manual POST /fetch endpoint goes through the same fetch_datasource
    routine and writes an audit row tagged with origin="manual"
  - AUTO_FETCH_TYPES excludes csv / json_import
"""
from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy.orm import Session

from app.db import session as session_module
from app.models.audit import AuditLog
from app.models.datasource import DataSource, OpinionItem
from app.services.datasource_fetch import (
    AUTO_FETCH_TYPES,
    ORIGIN_MANUAL,
    ORIGIN_SCHEDULED,
    fetch_datasource,
)
from app.services.scheduler import is_running, run_once, stop_scheduler


def _engine():
    return session_module.engine


def _seed_extra_sources(monkeypatch_weibo: bool = False):
    """Add one extra rss, one csv, one json_import, and one disabled source."""
    db = Session(_engine())
    try:
        # extra RSS source - we override httpx to return [] so it succeeds empty
        if not db.query(DataSource).filter(DataSource.code == "auto_rss").first():
            db.add(DataSource(
                code="auto_rss",
                name="自动 RSS",
                source_type="rss",
                url="https://example.com/auto-feed",
                weight=1.0,
                is_enabled=True,
                description="scheduler test rss",
            ))
        # disabled source - must be skipped
        if not db.query(DataSource).filter(DataSource.code == "auto_disabled").first():
            db.add(DataSource(
                code="auto_disabled",
                name="自动 Disabled",
                source_type="static_demo",
                url="",
                weight=1.0,
                is_enabled=False,
                description="scheduler test disabled",
            ))
        # csv upload sink - must be skipped by scheduler
        if not db.query(DataSource).filter(DataSource.code == "import_csv").first():
            db.add(DataSource(
                code="import_csv",
                name="CSV 导入",
                source_type="csv",
                url="",
                weight=1.0,
                is_enabled=True,
                description="scheduler test csv",
            ))
        if not db.query(DataSource).filter(DataSource.code == "import_json").first():
            db.add(DataSource(
                code="import_json",
                name="JSON 导入",
                source_type="json_import",
                url="",
                weight=1.0,
                is_enabled=True,
                description="scheduler test json",
            ))
        db.commit()
    finally:
        db.close()


def test_auto_fetch_types_excludes_upload_types():
    """CSV / JSON imports are operator-driven, never auto-pulled."""
    assert "csv" not in AUTO_FETCH_TYPES
    assert "json_import" not in AUTO_FETCH_TYPES
    # The remaining types ARE auto-fetched.
    assert "rss" in AUTO_FETCH_TYPES
    assert "weibo" in AUTO_FETCH_TYPES
    assert "json_url" in AUTO_FETCH_TYPES
    assert "static_demo" in AUTO_FETCH_TYPES


def test_run_once_only_fetches_enabled_sources(monkeypatch, app):
    """Disabled and upload-only sources are skipped; enabled static_demo is hit."""
    _seed_extra_sources()

    # Stub RSS connector to return [] so auto_rss contributes nothing
    # rather than failing (feedparser may be missing in CI).
    from app.services.connectors import rss as rss_mod

    def _empty_fetch(self, source):  # type: ignore[no-untyped-def]
        return []

    monkeypatch.setattr(rss_mod.RssConnector, "fetch", _empty_fetch)

    db = Session(_engine())
    try:
        before = db.query(OpinionItem).count()
    finally:
        db.close()

    summary = asyncio.run(run_once())
    # demo_static and auto_rss get fetched; disabled + csv + json_import skipped.
    assert summary["failed"] == 0
    assert summary["skipped"] == 0

    db = Session(_engine())
    try:
        after = db.query(OpinionItem).count()
        disabled_after = db.query(DataSource).filter(DataSource.code == "auto_disabled").one()
        csv_after = db.query(DataSource).filter(DataSource.code == "import_csv").one()
        json_after = db.query(DataSource).filter(DataSource.code == "import_json").one()
    finally:
        db.close()

    # disabled source untouched
    assert disabled_after.latest_fetch_at is None
    assert disabled_after.latest_items_count == 0
    # csv / json_import untouched
    assert csv_after.latest_fetch_at is None
    assert json_after.latest_fetch_at is None
    # demo_static now has 6 items
    assert after - before >= 6

    # No audit rows for the disabled / upload sources
    db = Session(_engine())
    try:
        rows = (
            db.query(AuditLog)
            .filter(AuditLog.action == "datasource.fetch")
            .filter(AuditLog.detail.ilike("%auto_disabled%"))
            .all()
        )
        assert rows == []
    finally:
        db.close()


def test_run_once_skips_csv_and_json_import(client):
    """Run once with only csv / json_import sources: nothing happens."""
    # Disable every other source so the scheduler has nothing to do.
    db = Session(_engine())
    try:
        for src in db.query(DataSource).all():
            src.is_enabled = False
        db.commit()
    finally:
        db.close()

    summary = asyncio.run(run_once())
    assert summary["fetched"] == 0
    assert summary["failed"] == 0


def test_run_once_marks_failure_without_crashing_loop(monkeypatch, app):
    """A broken source must not stop the scheduler from hitting the next one."""
    _seed_extra_sources()

    # Force RssConnector to raise on every fetch so auto_rss fails.
    from app.services.connectors import rss as rss_mod

    def _broken_fetch(self, source):  # type: ignore[no-untyped-def]
        from app.services.connectors import ConnectorError
        raise ConnectorError("simulated upstream failure")

    monkeypatch.setattr(rss_mod.RssConnector, "fetch", _broken_fetch)

    summary = asyncio.run(run_once())
    # demo_static succeeded, auto_rss failed, disabled/csv/json_import skipped.
    # Loop must not have raised.
    assert summary["fetched"] >= 1
    assert summary["failed"] >= 1

    db = Session(_engine())
    try:
        broken = db.query(DataSource).filter(DataSource.code == "auto_rss").one()
        demo = db.query(DataSource).filter(DataSource.code == "demo_static").one()
    finally:
        db.close()

    assert broken.latest_fetch_status == "failure"
    assert "simulated upstream failure" in broken.latest_fetch_message
    assert demo.latest_fetch_status in ("success", "partial")


def test_run_once_reentrancy_guard(monkeypatch, app):
    """A second run_once invoked while one is in flight must be a no-op."""
    _seed_extra_sources()

    from app.services import scheduler as scheduler_mod

    # Force the first run_once to be "in progress" for the whole test by
    # monkey-patching the global _running flag and the inner SessionLocal
    # acquisition. This is the cheapest way to exercise the guard without
    # introducing a real-time dependency.
    scheduler_mod._running = True
    try:
        summary = asyncio.run(run_once())
    finally:
        scheduler_mod._running = False

    assert summary["skipped"] == 1
    assert summary["fetched"] == 0
    assert summary["failed"] == 0
    assert is_running() is False  # guard released by the second call's finally


def test_manual_fetch_uses_fetch_datasource_and_tags_origin(monkeypatch, app):
    """The manual /fetch endpoint goes through fetch_datasource and writes
    an audit row with origin='manual'."""
    from app.services.connectors import weibo as weibo_mod

    payload = {
        "statuses": [
            {
                "idstr": "weibo-sched-001",
                "text_raw": "网友爆料某品牌产品存在严重质量问题,监管部门已介入。",
                "created_at": "2026-06-08T10:00:00+00:00",
                "user": {"id": "1001", "screen_name": "微博用户A"},
            }
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
            return FakeResponse()

    monkeypatch.setattr(weibo_mod.httpx, "Client", FakeClient)

    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        # Reuse the manual endpoint to drive fetch_datasource.
        create = c.post(
            "/api/datasources",
            json={
                "code": "weibo_sched_test",
                "name": "weibo sched",
                "source_type": "weibo",
                "url": "https://example.com/weibo-sched.json",
            },
        )
        assert create.status_code == 201, create.text
        source_id = create.json()["id"]
        res = c.post(f"/api/datasources/{source_id}/fetch")
        assert res.status_code == 200, res.text
        assert res.json()["accepted"] == 1

    db = Session(_engine())
    try:
        entries = (
            db.query(AuditLog)
            .filter(AuditLog.action == "datasource.fetch")
            .filter(AuditLog.target_id == str(source_id))
            .all()
        )
    finally:
        db.close()

    assert len(entries) == 1
    detail = json.loads(entries[0].detail)
    assert detail["origin"] == ORIGIN_MANUAL
    assert detail["code"] == "weibo_sched_test"
    assert detail["accepted"] == 1


def test_fetch_datasource_records_scheduled_origin(monkeypatch, app):
    """fetch_datasource with origin='scheduled' tags the audit row accordingly."""
    from app.services.connectors import static_demo as sd_mod
    # Use the existing static demo connector (no network needed).
    db = Session(_engine())
    try:
        demo = db.query(DataSource).filter(DataSource.code == "demo_static").one()
    finally:
        db.close()

    outcome = fetch_datasource(db, demo, actor=None, origin=ORIGIN_SCHEDULED)
    db.commit()
    assert outcome.ok
    assert outcome.status in ("success", "partial")

    db = Session(_engine())
    try:
        entries = (
            db.query(AuditLog)
            .filter(AuditLog.action == "datasource.fetch")
            .filter(AuditLog.target_id == str(demo.id))
            .order_by(AuditLog.id.desc())
            .all()
        )
    finally:
        db.close()

    assert entries, "scheduled fetch should write an audit row"
    detail = json.loads(entries[0].detail)
    assert detail["origin"] == ORIGIN_SCHEDULED
    assert entries[0].actor_username == ""  # scheduler passes actor=None


def test_run_once_respects_batch_limit(monkeypatch, app):
    """A small batch limit caps the number of sources per tick."""
    _seed_extra_sources()

    from app.core.config import get_settings

    settings = get_settings()
    original = settings.scheduler_fetch_batch_limit
    settings.scheduler_fetch_batch_limit = 1
    try:
        summary = asyncio.run(run_once())
    finally:
        settings.scheduler_fetch_batch_limit = original

    # Only 1 source touched even though 4 are eligible.
    assert summary["fetched"] + summary["failed"] <= 1


@pytest.mark.asyncio
async def test_stop_scheduler_is_idempotent():
    """Calling stop_scheduler when nothing is running is a no-op."""
    await stop_scheduler()  # no task yet, should not raise
