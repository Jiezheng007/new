"""Acceptance tests for Phase 7 / Issue 9: workbench dashboard.

Covers:
  - Auth: 401 without a session; 200 for all five roles
  - Role-aware field visibility (viewer / handler / risk_control / auditor / admin)
  - Empty-state shape: all visible counts zero, trend padded to 7 buckets
  - Seeded data: counts and ratios match the underlying data
  - Seven-day trend: correct bucketing and date ordering
  - Latest alerts: ordered desc, capped at 5, with opinion summary
  - Handler scope: ticket counts are restricted to the caller's tickets
  - Negative ratio calculation: only successful analyses count
  - Structural read-only: no mutation endpoint exists; viewer cannot
    reach a write path through the dashboard router
  - Web UI: /web/workbench renders for the right roles
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import session as session_module
from app.models.alert import (
    ALERT_STATUS_PENDING,
    Alert,
)
from app.models.analysis import (
    ANALYSIS_STATUS_SUCCESS,
    AnalysisResult,
)
from app.models.datasource import DataSource, OpinionItem
from app.models.role_codes import RoleCode
from app.models.ticket import Ticket
from app.services.nlp import SENTIMENT_NEGATIVE


# ---------- helpers ----------


def _engine():
    return session_module.engine


def _session():
    return Session(_engine())


def _login(client: TestClient, username: str, password: str) -> None:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text


def _logout(client: TestClient) -> None:
    client.post("/api/auth/logout")


def _seed_static_demo(client: TestClient) -> int:
    """Trigger the static-demo fetch as admin so demo data + analysis rows exist.

    Returns the data-source id for further use.
    """
    _login(client, "admin", "admin123")
    db = _session()
    try:
        src = db.query(DataSource).filter(DataSource.code == "demo_static").one()
        source_id = src.id
    finally:
        db.close()
    res = client.post(f"/api/datasources/{source_id}/fetch")
    assert res.status_code == 200, res.text
    _logout(client)
    return source_id


def _get_summary(client: TestClient) -> dict:
    res = client.get("/api/dashboard/summary")
    assert res.status_code == 200, res.text
    return res.json()


# ---------- auth ----------


def test_summary_requires_authentication(client: TestClient) -> None:
    res = client.get("/api/dashboard/summary")
    assert res.status_code == 401


def test_summary_returns_200_for_every_role(client: TestClient) -> None:
    for username, password in [
        ("admin", "admin123"),
        ("risk", "risk123"),
        ("handler", "handler123"),
        ("auditor", "auditor123"),
        ("viewer", "viewer123"),
    ]:
        _login(client, username, password)
        res = client.get("/api/dashboard/summary")
        assert res.status_code == 200, (username, res.text)
        body = res.json()
        assert body["role_scope"] == {
            "admin": RoleCode.ADMIN,
            "risk": RoleCode.RISK_CONTROL,
            "handler": RoleCode.HANDLER,
            "auditor": RoleCode.AUDITOR,
            "viewer": RoleCode.VIEWER,
        }[username]
        assert "generated_at" in body
        _logout(client)


# ---------- role-aware field visibility ----------


def test_admin_sees_all_aggregates(client: TestClient) -> None:
    _login(client, "admin", "admin123")
    body = _get_summary(client)
    assert body["opinion_total"] is not None
    assert body["opinion_analyzed_total"] is not None
    assert body["opinion_negative_total"] is not None
    assert body["opinion_negative_ratio"] is not None
    assert body["alerts_high_or_severe_total"] is not None
    assert body["alerts_pending"] is not None
    assert body["alerts_confirmed"] is not None
    assert body["alerts_ignored"] is not None
    assert body["tickets_unassigned"] is not None
    assert body["tickets_in_progress"] is not None
    assert body["tickets_completed"] is not None
    assert body["tickets_archived"] is not None
    assert isinstance(body["trend"], list)
    assert isinstance(body["latest_alerts"], list)


def test_risk_control_sees_all_aggregates(client: TestClient) -> None:
    _login(client, "risk", "risk123")
    body = _get_summary(client)
    for key in (
        "opinion_total",
        "alerts_pending",
        "tickets_in_progress",
    ):
        assert body[key] is not None, key


def test_auditor_sees_all_aggregates(client: TestClient) -> None:
    _login(client, "auditor", "auditor123")
    body = _get_summary(client)
    for key in (
        "opinion_total",
        "alerts_pending",
        "tickets_in_progress",
    ):
        assert body[key] is not None, key


def test_handler_only_sees_ticket_aggregates(client: TestClient) -> None:
    _login(client, "handler", "handler123")
    body = _get_summary(client)
    # Opinion: hidden because handler lacks opinion:read.
    assert body["opinion_total"] is None
    assert body["opinion_analyzed_total"] is None
    assert body["opinion_negative_total"] is None
    assert body["opinion_negative_ratio"] is None
    assert body["trend"] == []
    # Alerts: hidden because handler lacks alert:read.
    assert body["alerts_high_or_severe_total"] is None
    assert body["alerts_pending"] is None
    assert body["alerts_confirmed"] is None
    assert body["alerts_ignored"] is None
    assert body["latest_alerts"] == []
    # Tickets: visible and scoped to the handler.
    assert body["tickets_unassigned"] is not None
    assert body["tickets_in_progress"] is not None
    assert body["tickets_completed"] is not None
    assert body["tickets_archived"] is not None


def test_viewer_sees_opinion_aggregates_only(client: TestClient) -> None:
    _login(client, "viewer", "viewer123")
    body = _get_summary(client)
    # Opinion: visible.
    assert body["opinion_total"] is not None
    assert body["opinion_analyzed_total"] is not None
    assert body["opinion_negative_total"] is not None
    assert body["opinion_negative_ratio"] is not None
    assert isinstance(body["trend"], list)
    # Alerts / tickets: hidden.
    assert body["alerts_high_or_severe_total"] is None
    assert body["alerts_pending"] is None
    assert body["tickets_unassigned"] is None
    assert body["tickets_in_progress"] is None
    assert body["latest_alerts"] == []


# ---------- empty state ----------


def test_empty_state_shape(client: TestClient) -> None:
    _login(client, "admin", "admin123")
    body = _get_summary(client)
    assert body["opinion_total"] == 0
    assert body["opinion_analyzed_total"] == 0
    assert body["opinion_negative_total"] == 0
    assert body["opinion_negative_ratio"] == 0.0
    assert body["alerts_high_or_severe_total"] == 0
    assert body["alerts_pending"] == 0
    assert body["alerts_confirmed"] == 0
    assert body["alerts_ignored"] == 0
    assert body["tickets_unassigned"] == 0
    assert body["tickets_in_progress"] == 0
    assert body["tickets_completed"] == 0
    assert body["tickets_archived"] == 0
    assert body["latest_alerts"] == []
    # Trend is always seven buckets, oldest first.
    assert len(body["trend"]) == 7
    for point in body["trend"]:
        assert point["total"] == 0
        assert point["negative"] == 0
        assert point["high_or_severe"] == 0
        assert "date" in point


# ---------- counts against seeded data ----------


def test_seeded_counts_match_underlying_data(client: TestClient) -> None:
    _seed_static_demo(client)
    _login(client, "admin", "admin123")
    body = _get_summary(client)

    # Compare against a fresh DB session to avoid stale identity-map issues.
    db = _session()
    try:
        opinion_total = db.query(OpinionItem).count()
        analyzed = (
            db.query(AnalysisResult)
            .filter(AnalysisResult.status == ANALYSIS_STATUS_SUCCESS)
            .count()
        )
        negative = (
            db.query(AnalysisResult)
            .filter(
                AnalysisResult.status == ANALYSIS_STATUS_SUCCESS,
                AnalysisResult.sentiment == SENTIMENT_NEGATIVE,
            )
            .count()
        )
        high_severe_alerts = (
            db.query(Alert)
            .filter(Alert.risk_level.in_(["high", "severe"]))
            .count()
        )
    finally:
        db.close()

    assert body["opinion_total"] == opinion_total
    assert body["opinion_analyzed_total"] == analyzed
    assert body["opinion_negative_total"] == negative
    expected_ratio = round(negative / analyzed, 4) if analyzed else 0.0
    assert body["opinion_negative_ratio"] == expected_ratio
    assert body["alerts_high_or_severe_total"] == high_severe_alerts


# ---------- trend bucketing ----------


def test_trend_has_seven_buckets_oldest_first(client: TestClient) -> None:
    _seed_static_demo(client)
    _login(client, "admin", "admin123")
    body = _get_summary(client)
    trend = body["trend"]
    assert len(trend) == 7
    dates = [p["date"] for p in trend]
    assert dates == sorted(dates), "trend must be oldest-first"
    # Span is 6 days (today - 6 ... today).
    today = datetime.now(timezone.utc).date()
    assert dates[0] == (today - timedelta(days=6)).isoformat()
    assert dates[-1] == today.isoformat()


def test_trend_counts_match_published_distribution(client: TestClient) -> None:
    _seed_static_demo(client)
    _login(client, "admin", "admin123")
    body = _get_summary(client)
    # Avoid hard-coding a date math expectation here. SQLite's
    # func.date() applies the local-timezone offset, which makes the
    # exact day boundary depend on the host timezone. Instead, verify
    # the invariants that hold regardless of locale: the trend has
    # seven buckets, the totals across buckets equal opinion_total,
    # and the dates form a contiguous oldest-first window ending at
    # the host's "today" date.
    assert len(body["trend"]) == 7
    sum_of_totals = sum(p["total"] for p in body["trend"])
    assert sum_of_totals == body["opinion_total"]
    dates = [p["date"] for p in body["trend"]]
    assert dates == sorted(dates)
    expected_last = datetime.now(timezone.utc).date().isoformat()
    assert dates[-1] == expected_last
    # And there is at least one day with content - the demo has six
    # items and they all fall within seven days of fetch.
    assert any(p["total"] > 0 for p in body["trend"])


def test_trend_uses_created_at_when_published_at_missing(client: TestClient) -> None:
    _seed_static_demo(client)
    db = _session()
    try:
        # Wipe published_at on every opinion so the dashboard is
        # forced to fall back to created_at.
        opinions = db.query(OpinionItem).all()
        for opinion in opinions:
            opinion.published_at = None
        db.commit()
        expected_total = len(opinions)
        expected_dates = {o.created_at.date().isoformat() for o in opinions}
    finally:
        db.close()
    _login(client, "admin", "admin123")
    body = _get_summary(client)
    # The trend must still include the same total count, just routed
    # through the created_at fallback.
    actual_total = sum(p["total"] for p in body["trend"])
    assert actual_total == expected_total
    # And every bucket that should have content shows up.
    for d in expected_dates:
        assert d in {p["date"] for p in body["trend"]}


# ---------- latest alerts ----------


def test_latest_alerts_capped_and_ordered_desc(client: TestClient) -> None:
    _seed_static_demo(client)
    _login(client, "admin", "admin123")
    body = _get_summary(client)
    alerts = body["latest_alerts"]
    # The demo ships with 6 items; some land in high/severe, so there
    # should be at most 5 alerts surfaced.
    assert len(alerts) <= 5
    timestamps = [a["created_at"] for a in alerts]
    assert timestamps == sorted(timestamps, reverse=True)
    for a in alerts:
        assert a["id"] > 0
        assert a["risk_level"] in {"high", "severe"}
        assert a["status"] in {"pending", "confirmed", "ignored"}
        assert "opinion_title" in a
        assert "opinion_source_code" in a


def test_latest_alerts_empty_when_no_high_severe(client: TestClient) -> None:
    # Seed opinions but force them all to "low" so no alert is created.
    _seed_static_demo(client)
    db = _session()
    try:
        rows = (
            db.query(OpinionItem, AnalysisResult)
            .join(AnalysisResult, AnalysisResult.opinion_item_id == OpinionItem.id)
            .all()
        )
        for _, analysis in rows:
            analysis.level = "low"
            analysis.score = 0
        # Clean up any auto-created alerts so the count is exactly 0.
        db.query(Alert).delete()
        db.commit()
    finally:
        db.close()
    _login(client, "admin", "admin123")
    body = _get_summary(client)
    assert body["alerts_high_or_severe_total"] == 0
    assert body["alerts_pending"] == 0
    assert body["latest_alerts"] == []


# ---------- negative ratio ----------


def test_negative_ratio_excludes_failed_analyses(client: TestClient) -> None:
    _seed_static_demo(client)
    db = _session()
    try:
        # Mark half the analyses as failed; the ratio should not
        # include them in the denominator.
        rows = (
            db.query(AnalysisResult)
            .filter(AnalysisResult.status == ANALYSIS_STATUS_SUCCESS)
            .all()
        )
        for r in rows[::2]:
            r.status = "failed"
            r.sentiment = None
        db.commit()
    finally:
        db.close()
    _login(client, "admin", "admin123")
    body = _get_summary(client)
    db = _session()
    try:
        analyzed = (
            db.query(AnalysisResult)
            .filter(AnalysisResult.status == ANALYSIS_STATUS_SUCCESS)
            .count()
        )
        negative = (
            db.query(AnalysisResult)
            .filter(
                AnalysisResult.status == ANALYSIS_STATUS_SUCCESS,
                AnalysisResult.sentiment == SENTIMENT_NEGATIVE,
            )
            .count()
        )
    finally:
        db.close()
    assert body["opinion_analyzed_total"] == analyzed
    assert body["opinion_negative_total"] == negative
    expected = round(negative / analyzed, 4) if analyzed else 0.0
    assert body["opinion_negative_ratio"] == expected


# ---------- handler scope ----------


def test_handler_ticket_count_is_scoped_to_own_tickets(client: TestClient) -> None:
    _seed_static_demo(client)
    _login(client, "risk", "risk123")
    db = _session()
    try:
        alerts = (
            db.query(Alert)
            .filter(Alert.status == ALERT_STATUS_PENDING)
            .order_by(Alert.id.asc())
            .limit(2)
            .all()
        )
        assert len(alerts) >= 2
        alert_ids = [a.id for a in alerts]

        # Create a second handler to test isolation.
        from app.models.user import Role, User
        from app.core.security import hash_password

        handler_role = db.query(Role).filter(Role.code == RoleCode.HANDLER).one()
        other = User(
            username="handler2",
            full_name="处置二号",
            password_hash=hash_password("handler2pw"),
            is_active=True,
            role_id=handler_role.id,
        )
        db.add(other)
        db.commit()
        db.refresh(other)
        other_id = other.id
        default_handler = db.query(User).filter(User.username == "handler").one()
        default_handler_id = default_handler.id
    finally:
        db.close()
    # Confirm alerts so they can be turned into tickets.
    for aid in alert_ids:
        res = client.post(f"/api/alerts/{aid}/confirm")
        assert res.status_code == 200, res.text
    # Ticket 1 -> default handler (in_progress)
    res = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": alert_ids[0], "assignee_id": default_handler_id},
    )
    assert res.status_code == 201, res.text
    # Ticket 2 -> second handler (in_progress)
    res = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": alert_ids[1], "assignee_id": other_id},
    )
    assert res.status_code == 201, res.text
    _logout(client)

    # Default handler sees only ticket #1.
    _login(client, "handler", "handler123")
    body = _get_summary(client)
    assert body["tickets_in_progress"] == 1
    assert body["tickets_unassigned"] == 0
    assert body["tickets_completed"] == 0
    assert body["tickets_archived"] == 0
    _logout(client)

    # Other handler sees only ticket #2.
    _login(client, "handler2", "handler2pw")
    body = _get_summary(client)
    assert body["tickets_in_progress"] == 1
    assert body["tickets_unassigned"] == 0
    _logout(client)

    # Admin sees both tickets.
    _login(client, "admin", "admin123")
    body = _get_summary(client)
    assert body["tickets_in_progress"] == 2
    assert body["tickets_unassigned"] == 0


# ---------- structural read-only ----------


def test_dashboard_router_has_no_mutation_endpoints(client: TestClient) -> None:
    """The dashboard summary is a projection. Guard against future
    regressions that would add a write path on this router."""
    from app.main import create_app

    app = create_app()
    bad_methods = {"POST", "PUT", "PATCH", "DELETE"}
    dashboard_paths = [
        route.path for route in app.routes
        if hasattr(route, "path") and route.path.startswith("/api/dashboard")
    ]
    assert dashboard_paths == ["/api/dashboard/summary"]
    for route in app.routes:
        if not hasattr(route, "path") or not route.path.startswith("/api/dashboard"):
            continue
        for method in getattr(route, "methods", set()):
            assert method not in bad_methods, (
                f"Dashboard router must stay read-only, found {method} {route.path}"
            )


def test_viewer_cannot_reach_dashboard_write_path(client: TestClient) -> None:
    """There is no write path on the dashboard router. Verify that
    every dashboard path returns 405 / 401 for a viewer - i.e. POST
    /api/dashboard/summary is explicitly not allowed."""
    _login(client, "viewer", "viewer123")
    res = client.post("/api/dashboard/summary", json={})
    assert res.status_code in (405, 401)
    res = client.delete("/api/dashboard/summary")
    assert res.status_code in (405, 401)


# ---------- web UI ----------


def test_workbench_page_renders_for_admin(client: TestClient) -> None:
    _login(client, "admin", "admin123")
    res = client.get("/web/workbench")
    assert res.status_code == 200
    body = res.text
    assert "实时风险概览" in body
    assert "近七日舆情趋势" in body
    assert "最新预警" in body
    # The placeholder text must be gone.
    assert "阶段 9 接入真实业务数据" not in body


def test_workbench_page_renders_for_viewer(client: TestClient) -> None:
    _login(client, "viewer", "viewer123")
    res = client.get("/web/workbench")
    assert res.status_code == 200
    assert "实时风险概览" in res.text
    assert "近七日舆情趋势" in res.text


def test_workbench_blocked_for_anonymous(client: TestClient) -> None:
    res = client.get("/web/workbench")
    assert res.status_code == 401
