"""Acceptance tests for Phase 5 / Issue 7: alert lifecycle.

Covers:
  - Auto-creation hook: high / severe analysis -> pending alert
  - No alert for low / medium / failed analyses
  - Idempotency: re-analyzing the same opinion does not create a 2nd alert
  - Threshold change can promote a previously-medium opinion to high and
    the next analysis auto-creates an alert
  - List / detail / confirm / ignore endpoints
  - State machine: confirmed/ignored alerts reject further transitions (409)
  - Ignore reason validation
  - RBAC: handler and viewer blocked; auditor read-only; admin full
  - Audit log: every state change writes a row with actor / target / IP
  - Web UI: /web/alerts renders for the right roles
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from app.db import session as session_module
from app.models.alert import (
    ALERT_STATUS_CONFIRMED,
    ALERT_STATUS_IGNORED,
    ALERT_STATUS_PENDING,
    Alert,
)
from app.models.analysis import (
    ANALYSIS_STATUS_SUCCESS,
    AnalysisResult,
)
from app.models.audit import AuditLog
from app.models.datasource import DataSource, OpinionItem
from app.services.analysis import analyze_opinion
from app.services.nlp import SENTIMENT_NEGATIVE, NlpResult
from app.services.scoring import compute_risk


def _engine():
    return session_module.engine


def _session():
    return Session(_engine())


def _seed_static_demo(client):
    """Run the static-demo fetch as admin so the demo data + analysis rows exist."""
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    db = _session()
    try:
        src = db.query(DataSource).filter(DataSource.code == "demo_static").one()
        source_id = src.id
    finally:
        db.close()
    res = client.post(f"/api/datasources/{source_id}/fetch")
    assert res.status_code == 200, res.text
    client.post("/api/auth/logout")
    return source_id


def _high_risk_opinion_id(db) -> int:
    """Return the id of the first high/severe opinion from the seeded demo.

    The static demo ships with two items (demo-003 / demo-004) that
    contain sensitive keywords + negative sentiment; this helper finds
    whichever lands in the high or severe band after analysis.
    """
    row = (
        db.query(OpinionItem, AnalysisResult)
        .join(AnalysisResult, AnalysisResult.opinion_item_id == OpinionItem.id)
        .filter(
            AnalysisResult.status == ANALYSIS_STATUS_SUCCESS,
            AnalysisResult.level.in_(["high", "severe"]),
        )
        .order_by(OpinionItem.id.asc())
        .first()
    )
    assert row is not None, "expected at least one high/severe analysis row from the static demo"
    return row[0].id


def _medium_opinion_id(db) -> int:
    row = (
        db.query(OpinionItem, AnalysisResult)
        .join(AnalysisResult, AnalysisResult.opinion_item_id == OpinionItem.id)
        .filter(
            AnalysisResult.status == ANALYSIS_STATUS_SUCCESS,
            AnalysisResult.level.in_(["low", "medium"]),
        )
        .order_by(OpinionItem.id.asc())
        .first()
    )
    assert row is not None, "expected at least one low/medium analysis row from the static demo"
    return row[0].id


def _alert_count() -> int:
    db = _session()
    try:
        return db.query(Alert).count()
    finally:
        db.close()


def _latest_audit(action: str, target_id: str = ""):
    db = _session()
    try:
        q = db.query(AuditLog).filter(AuditLog.action == action)
        if target_id:
            q = q.filter(AuditLog.target_id == target_id)
        return q.order_by(AuditLog.id.desc()).first()
    finally:
        db.close()


# ---------- auto-creation hook ----------

def test_high_severe_analyses_auto_create_pending_alerts(client):
    """Two of the static-demo items (demo-003 / demo-004) score high or
    severe on first analysis, so the static-demo fetch should leave
    exactly two pending alerts in the DB."""
    before = _alert_count()
    _seed_static_demo(client)
    after = _alert_count()
    assert after - before == 2

    db = _session()
    try:
        alerts = db.query(Alert).order_by(Alert.id.asc()).all()
        levels = {a.risk_level for a in alerts}
        statuses = {a.status for a in alerts}
    finally:
        db.close()
    assert statuses == {ALERT_STATUS_PENDING}
    assert levels.issubset({"high", "severe"})


def test_low_medium_analyses_create_no_alert(client):
    """The first demo item is positive / low-risk: no alert should exist."""
    _seed_static_demo(client)
    db = _session()
    try:
        first_id = db.query(OpinionItem).order_by(OpinionItem.id.asc()).first().id
        analysis = (
            db.query(AnalysisResult)
            .filter(AnalysisResult.opinion_item_id == first_id)
            .one()
        )
        level = analysis.level
        alert_count = (
            db.query(Alert)
            .filter(Alert.opinion_item_id == first_id)
            .count()
        )
    finally:
        db.close()
    assert level in {"low", "medium"}
    assert alert_count == 0


def test_re_analysis_does_not_create_duplicate_alert(client):
    """Re-running NLP + scoring for an opinion that already has a pending
    alert must keep the alert count at 1 (uniqueness constraint)."""
    _seed_static_demo(client)
    db = _session()
    try:
        high_id = _high_risk_opinion_id(db)
    finally:
        db.close()
    before = _alert_count()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(f"/api/opinions/{high_id}/analyze")
    assert res.status_code == 200
    res2 = client.post(f"/api/opinions/{high_id}/analyze")
    assert res2.status_code == 200
    client.post("/api/auth/logout")
    after = _alert_count()
    assert after == before  # no new alerts


def test_threshold_change_to_high_creates_alert(client):
    """Tighten the high band so a previously-low opinion moves to high;
    re-analyzing it should auto-create a new alert."""
    _seed_static_demo(client)
    db = _session()
    try:
        low_id = _medium_opinion_id(db)  # the helper actually returns any non-high item
        before_count = (
            db.query(Alert).filter(Alert.opinion_item_id == low_id).count()
        )
    finally:
        db.close()
    assert before_count == 0

    # Push the 'high' band down to 2 so a small-score item (e.g. demo-001
    # positive, no sensitive hits) lands in 'high' on the next analysis.
    # All four thresholds must be in [0, 100] per the schema; the test
    # uses values inside that range while still being strictly increasing.
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.put(
        "/api/rules/thresholds",
        json={
            "thresholds": [
                {"level": "low", "min_score": 0},
                {"level": "medium", "min_score": 1},
                {"level": "high", "min_score": 2},
                {"level": "severe", "min_score": 3},
            ]
        },
    )
    assert res.status_code == 200, res.text
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(f"/api/opinions/{low_id}/analyze")
    assert res.status_code == 200
    client.post("/api/auth/logout")

    db = _session()
    try:
        alert = (
            db.query(Alert).filter(Alert.opinion_item_id == low_id).one_or_none()
        )
    finally:
        db.close()
    assert alert is not None
    assert alert.status == ALERT_STATUS_PENDING
    assert alert.risk_level in {"high", "severe"}


# ---------- list / detail ----------

def test_alert_list_for_risk_control(client):
    _seed_static_demo(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/api/alerts")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] >= 2
    for it in body["items"]:
        assert it["status"] in {"pending", "confirmed", "ignored"}
        assert it["risk_level"] in {"high", "severe"}
        assert "opinion" in it
        assert it["opinion"]["title"]
    client.post("/api/auth/logout")


def test_alert_list_for_auditor_is_read_only(client):
    _seed_static_demo(client)
    client.post("/api/auth/login", json={"username": "auditor", "password": "auditor123"})
    res = client.get("/api/alerts")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] >= 2
    client.post("/api/auth/logout")


def test_alert_list_blocks_handler_and_viewer(client):
    _seed_static_demo(client)
    for username, password in [("handler", "handler123"), ("viewer", "viewer123")]:
        client.post("/api/auth/login", json={"username": username, "password": password})
        res = client.get("/api/alerts")
        assert res.status_code == 403, username
        client.post("/api/auth/logout")


def test_alert_list_requires_auth(client):
    res = client.get("/api/alerts")
    assert res.status_code == 401


def test_alert_list_filter_by_status(client):
    _seed_static_demo(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/api/alerts?status=pending")
    assert res.status_code == 200
    body = res.json()
    for it in body["items"]:
        assert it["status"] == "pending"
    assert body["total"] >= 2
    client.post("/api/auth/logout")


def test_alert_list_filter_by_level(client):
    _seed_static_demo(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/api/alerts?risk_level=severe")
    assert res.status_code == 200
    body = res.json()
    for it in body["items"]:
        assert it["risk_level"] == "severe"
    client.post("/api/auth/logout")


def test_alert_list_filter_validation(client):
    _seed_static_demo(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    for bad in ["status=banana", "risk_level=low"]:
        res = client.get(f"/api/alerts?{bad}")
        assert res.status_code == 400, bad
    client.post("/api/auth/logout")


def test_alert_detail_includes_opinion_summary(client):
    _seed_static_demo(client)
    db = _session()
    try:
        alert_id = db.query(Alert).order_by(Alert.id.asc()).first().id
    finally:
        db.close()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get(f"/api/alerts/{alert_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == alert_id
    assert body["opinion"]["title"]
    assert body["opinion"]["source_code"]
    client.post("/api/auth/logout")


def test_alert_detail_404(client):
    _seed_static_demo(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/api/alerts/99999")
    assert res.status_code == 404
    client.post("/api/auth/logout")


# ---------- confirm / ignore flow ----------

def test_confirm_alert_happy_path_writes_audit(client):
    _seed_static_demo(client)
    db = _session()
    try:
        alert_id = db.query(Alert).order_by(Alert.id.asc()).first().id
    finally:
        db.close()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(f"/api/alerts/{alert_id}/confirm")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "confirmed"
    assert body["confirmed_by_username"] == "risk"
    assert body["confirmed_at"]

    entry = _latest_audit("alert.confirm", str(alert_id))
    assert entry is not None
    assert entry.actor_username == "risk"
    detail = json.loads(entry.detail)
    assert detail["risk_level"] in {"high", "severe"}
    client.post("/api/auth/logout")

    # Re-fetch to confirm DB state.
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get(f"/api/alerts/{alert_id}")
    assert res.json()["status"] == "confirmed"
    client.post("/api/auth/logout")


def test_confirm_already_confirmed_returns_409(client):
    _seed_static_demo(client)
    db = _session()
    try:
        alert_id = db.query(Alert).order_by(Alert.id.asc()).first().id
    finally:
        db.close()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res1 = client.post(f"/api/alerts/{alert_id}/confirm")
    assert res1.status_code == 200
    res2 = client.post(f"/api/alerts/{alert_id}/confirm")
    assert res2.status_code == 409
    client.post("/api/auth/logout")


def test_ignore_alert_happy_path_writes_audit(client):
    _seed_static_demo(client)
    db = _session()
    try:
        alert_id = db.query(Alert).order_by(Alert.id.desc()).first().id
    finally:
        db.close()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        f"/api/alerts/{alert_id}/ignore",
        json={"reason": "已与企业沟通确认为误报"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "ignored"
    assert body["ignored_by_username"] == "risk"
    assert body["ignore_reason"] == "已与企业沟通确认为误报"

    entry = _latest_audit("alert.ignore", str(alert_id))
    assert entry is not None
    assert entry.actor_username == "risk"
    detail = json.loads(entry.detail)
    assert detail["ignore_reason"] == "已与企业沟通确认为误报"
    client.post("/api/auth/logout")


def test_ignore_alert_rejects_blank_reason(client):
    _seed_static_demo(client)
    db = _session()
    try:
        alert_id = db.query(Alert).order_by(Alert.id.asc()).first().id
    finally:
        db.close()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    # The pydantic AlertIgnoreRequest schema rejects any reason that,
    # after stripping whitespace, is shorter than 2 characters - that
    # covers empty, whitespace-only, and 1-character inputs (all 422).
    for bad in ["", "   ", "x"]:
        res = client.post(f"/api/alerts/{alert_id}/ignore", json={"reason": bad})
        assert res.status_code == 422, (bad, res.status_code, res.text[:200])
    client.post("/api/auth/logout")


def test_ignore_alert_rejects_missing_reason(client):
    _seed_static_demo(client)
    db = _session()
    try:
        alert_id = db.query(Alert).order_by(Alert.id.asc()).first().id
    finally:
        db.close()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(f"/api/alerts/{alert_id}/ignore", json={})
    assert res.status_code == 422
    client.post("/api/auth/logout")


def test_ignore_already_ignored_returns_409(client):
    _seed_static_demo(client)
    db = _session()
    try:
        alert_id = db.query(Alert).order_by(Alert.id.asc()).first().id
    finally:
        db.close()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res1 = client.post(f"/api/alerts/{alert_id}/ignore", json={"reason": "误报测试"})
    assert res1.status_code == 200
    res2 = client.post(f"/api/alerts/{alert_id}/ignore", json={"reason": "再次尝试"})
    assert res2.status_code == 409
    client.post("/api/auth/logout")


def test_ignore_after_confirm_returns_409(client):
    _seed_static_demo(client)
    db = _session()
    try:
        alert_id = db.query(Alert).order_by(Alert.id.asc()).first().id
    finally:
        db.close()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res1 = client.post(f"/api/alerts/{alert_id}/confirm")
    assert res1.status_code == 200
    res2 = client.post(f"/api/alerts/{alert_id}/ignore", json={"reason": "已确认但又想忽略"})
    assert res2.status_code == 409
    client.post("/api/auth/logout")


def test_confirm_blocks_handler_viewer_auditor(client):
    _seed_static_demo(client)
    db = _session()
    try:
        alert_id = db.query(Alert).order_by(Alert.id.asc()).first().id
    finally:
        db.close()
    for username, password in [
        ("handler", "handler123"),
        ("viewer", "viewer123"),
        ("auditor", "auditor123"),
    ]:
        client.post("/api/auth/login", json={"username": username, "password": password})
        res = client.post(f"/api/alerts/{alert_id}/confirm")
        assert res.status_code == 403, username
        client.post("/api/auth/logout")


def test_ignore_blocks_handler_viewer_auditor(client):
    _seed_static_demo(client)
    db = _session()
    try:
        alert_id = db.query(Alert).order_by(Alert.id.asc()).first().id
    finally:
        db.close()
    for username, password in [
        ("handler", "handler123"),
        ("viewer", "viewer123"),
        ("auditor", "auditor123"),
    ]:
        client.post("/api/auth/login", json={"username": username, "password": password})
        res = client.post(
            f"/api/alerts/{alert_id}/ignore",
            json={"reason": "test-blocked"},
        )
        assert res.status_code == 403, username
        client.post("/api/auth/logout")


def test_confirm_404(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.post("/api/alerts/99999/confirm")
    assert res.status_code == 404
    client.post("/api/auth/logout")


# ---------- summary ----------

def test_summary_counts_match_status_breakdown(client):
    _seed_static_demo(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})

    res = client.get("/api/alerts/summary")
    assert res.status_code == 200
    body = res.json()
    assert body["pending"] >= 2
    assert body["total"] == body["pending"] + body["confirmed"] + body["ignored"]

    # Confirm one alert; the summary should reflect the change.
    db = _session()
    try:
        first_id = db.query(Alert).order_by(Alert.id.asc()).first().id
    finally:
        db.close()
    res = client.post(f"/api/alerts/{first_id}/confirm")
    assert res.status_code == 200
    res = client.get("/api/alerts/summary")
    body = res.json()
    assert body["pending"] >= 1
    assert body["confirmed"] >= 1
    client.post("/api/auth/logout")


def test_summary_requires_alert_reader_role(client):
    _seed_static_demo(client)
    for username, password in [("handler", "handler123"), ("viewer", "viewer123")]:
        client.post("/api/auth/login", json={"username": username, "password": password})
        res = client.get("/api/alerts/summary")
        assert res.status_code == 403, username
        client.post("/api/auth/logout")


# ---------- web UI ----------

def test_alerts_page_renders_for_risk_control_and_admin(client):
    _seed_static_demo(client)
    for username, password in [("admin", "admin123"), ("risk", "risk123"), ("auditor", "auditor123")]:
        client.post("/api/auth/login", json={"username": username, "password": password})
        res = client.get("/web/alerts")
        assert res.status_code == 200, (username, res.text[:200])
        body = res.text
        assert "预警" in body
        assert "风险等级" in body
        client.post("/api/auth/logout")


def test_alerts_page_blocks_handler_and_viewer(client):
    _seed_static_demo(client)
    for username, password in [("handler", "handler123"), ("viewer", "viewer123")]:
        client.post("/api/auth/login", json={"username": username, "password": password})
        res = client.get("/web/alerts")
        assert res.status_code == 403, username
        client.post("/api/auth/logout")


def test_alerts_page_unauthenticated_redirects_to_login(client):
    res = client.get("/web/alerts")
    assert res.status_code == 401


# ---------- auto-alert on fetch path ----------

def test_auto_alert_after_manual_fetch(client):
    """End-to-end: admin fetch on static demo -> 2 pending alerts in DB
    + accessible via the API list endpoint."""
    _seed_static_demo(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/api/alerts?status=pending")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 2
    for it in body["items"]:
        assert it["status"] == "pending"
        assert it["risk_level"] in {"high", "severe"}
    client.post("/api/auth/logout")


def test_failed_analysis_creates_no_alert(client):
    """An opinion whose analysis failed should not generate an alert,
    even on a re-analysis that later succeeds with a non-triggering
    level. We only assert the no-alert side because the failing path
    is exercised separately by the analysis tests."""
    db = _session()
    try:
        opinion = OpinionItem(
            source_id=1,
            source_code="test",
            source_type="static_demo",
            title="n/a",
            content="this text is in english so it gets a failed analysis",
            content_hash="f" * 32,
            language="fr",
        )
        db.add(opinion)
        db.commit()
        item = db.get(OpinionItem, opinion.id)
        # Force a failed analysis directly.
        result = AnalysisResult(
            opinion_item_id=opinion.id,
            status="failed",
            error_message="unsupported_language",
            provider="keyword_nlp",
        )
        db.add(result)
        db.commit()
        # A subsequent analyze_opinion should not create an alert because
        # the analysis status check is in ensure_alert_for_analysis.
        item2 = db.get(OpinionItem, opinion.id)
        analyze_opinion(db, item2)
        db.commit()
        alert_count = (
            db.query(Alert).filter(Alert.opinion_item_id == opinion.id).count()
        )
    finally:
        db.close()
    assert alert_count == 0
