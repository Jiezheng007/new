"""Acceptance tests for Phase 9 / Issue 11: audit log review.

Covers:
  - Authentication: unauthenticated requests are rejected with 401.
  - Authorization: only auditor and admin can list audit logs;
    risk_control / handler / viewer are blocked with 403.
  - Required fields: every row carries actor, action, target, result,
    IP, timestamp.
  - Filters: action, actor, target_type, target_id, result, time range,
    and detail keyword.
  - Login auditing: success / failure / disabled-user / unknown-user
    each write a row with the right shape.
  - Cross-feature coverage: events from user/role, data-source, rule,
    alert, ticket, report.create, and report.download all show up in
    the log.
  - Facets endpoint returns distinct actions, target types, results,
    actors.
  - The audit-log API itself is read-only - no write methods exist.
  - The /web/audit page renders for auditor and admin but not for
    handler / risk_control / viewer.
"""
from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import session as session_module
from app.models.audit import AuditLog
from app.models.datasource import DataSource
from app.models.role_codes import RoleCode
from app.models.user import User


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


def _audit_rows(action: str | None = None) -> list[AuditLog]:
    db = _session()
    try:
        q = db.query(AuditLog)
        if action:
            q = q.filter(AuditLog.action == action)
        return q.order_by(AuditLog.id.asc()).all()
    finally:
        db.close()


def _seed_static_demo(client: TestClient) -> int:
    """Trigger the static-demo fetch as admin so audit rows from many
    domains (datasource.fetch, opinion.analyze, alert events,
    ticket events) exist in the log."""
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


def _user_id(username: str) -> int:
    db = _session()
    try:
        return db.query(User).filter(User.username == username).one().id
    finally:
        db.close()


# ---------- auth ----------


def test_audit_logs_requires_authentication(client: TestClient) -> None:
    res = client.get("/api/audit-logs")
    assert res.status_code == 401


def test_audit_logs_allowed_for_auditor_and_admin(client: TestClient) -> None:
    for username, password in [("auditor", "auditor123"), ("admin", "admin123")]:
        _login(client, username, password)
        res = client.get("/api/audit-logs")
        assert res.status_code == 200, (username, res.text)
        body = res.json()
        assert "items" in body
        assert "total" in body
        _logout(client)


def test_audit_logs_blocked_for_other_roles(client: TestClient) -> None:
    for username, password in [
        ("risk", "risk123"),
        ("handler", "handler123"),
        ("viewer", "viewer123"),
    ]:
        _login(client, username, password)
        res = client.get("/api/audit-logs")
        assert res.status_code == 403, (username, res.text)
        # Also block the facet and detail endpoints.
        res = client.get("/api/audit-logs/facets")
        assert res.status_code == 403, username
        res = client.get("/api/audit-logs/1")
        assert res.status_code == 403, username
        _logout(client)


# ---------- required fields ----------


def test_every_row_carries_required_fields(client: TestClient) -> None:
    # Produce a deterministic, non-empty audit trail: login,
    # data-source fetch, and a rule creation.
    _seed_static_demo(client)
    _login(client, "admin", "admin123")
    client.post(
        "/api/rules/sensitive-keywords",
        json={"keyword": "审计测试词", "category": "审计", "severity": "low", "remark": "测试"},
    )

    res = client.get("/api/audit-logs?limit=200")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] > 0
    for row in body["items"]:
        assert "id" in row and row["id"] > 0
        assert "action" in row and row["action"]
        assert "actor_username" in row
        assert "actor_id" in row
        assert "target_type" in row
        assert "target_id" in row
        assert "result" in row and row["result"] in {"success", "failure"}
        assert "ip_address" in row
        assert "created_at" in row and row["created_at"]
        assert "detail" in row
    _logout(client)


# ---------- filtering ----------


def test_filter_by_action(client: TestClient) -> None:
    _seed_static_demo(client)
    _login(client, "admin", "admin123")
    res = client.get("/api/audit-logs?action=datasource.fetch")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] > 0
    for row in body["items"]:
        assert row["action"] == "datasource.fetch"


def test_filter_by_actor_username(client: TestClient) -> None:
    _seed_static_demo(client)
    _login(client, "admin", "admin123")
    res = client.get("/api/audit-logs?actor=admin")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] > 0
    for row in body["items"]:
        assert row["actor_username"] == "admin"


def test_filter_by_actor_id(client: TestClient) -> None:
    _seed_static_demo(client)
    admin_id = _user_id("admin")
    _login(client, "admin", "admin123")
    res = client.get(f"/api/audit-logs?actor={admin_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] > 0
    for row in body["items"]:
        assert row["actor_id"] == admin_id or row["actor_username"] == str(admin_id)


def test_filter_by_target_type_and_id(client: TestClient) -> None:
    _seed_static_demo(client)
    source_id_db = None
    db = _session()
    try:
        source_id_db = db.query(DataSource).filter(DataSource.code == "demo_static").one().id
    finally:
        db.close()
    _login(client, "admin", "admin123")
    res = client.get(f"/api/audit-logs?target_type=datasource&target_id={source_id_db}")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] > 0
    for row in body["items"]:
        assert row["target_type"] == "datasource"
        assert row["target_id"] == str(source_id_db)


def test_filter_by_result_failure(client: TestClient) -> None:
    # A bad-password login produces a single failure row.
    res = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert res.status_code == 401
    _login(client, "auditor", "auditor123")
    res = client.get("/api/audit-logs?result=failure")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] >= 1
    for row in body["items"]:
        assert row["result"] == "failure"


def test_invalid_result_filter_is_rejected(client: TestClient) -> None:
    _login(client, "auditor", "auditor123")
    res = client.get("/api/audit-logs?result=bogus")
    assert res.status_code == 400


def test_filter_by_time_range(client: TestClient) -> None:
    # Empty before any activity; one row after a login.
    _login(client, "auditor", "auditor123")
    # Use a tight window in the far future to get an empty result set.
    res = client.get("/api/audit-logs?start_at=2999-01-01T00:00:00Z")
    assert res.status_code == 200
    assert res.json()["total"] == 0


def test_filter_by_detail_keyword(client: TestClient) -> None:
    _seed_static_demo(client)
    _login(client, "admin", "admin123")
    res = client.post(
        "/api/rules/sensitive-keywords",
        json={"keyword": "唯一标识词xyz", "category": "kw", "severity": "low", "remark": ""},
    )
    assert res.status_code == 201, res.text
    res = client.get("/api/audit-logs?q=唯一标识词xyz")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] >= 1
    assert any("唯一标识词xyz" in row["detail"] for row in body["items"])


def test_pagination(client: TestClient) -> None:
    _seed_static_demo(client)
    _login(client, "auditor", "auditor123")
    res1 = client.get("/api/audit-logs?limit=5&offset=0")
    res2 = client.get("/api/audit-logs?limit=5&offset=5")
    assert res1.status_code == 200 and res2.status_code == 200
    page1 = res1.json()
    page2 = res2.json()
    assert page1["total"] == page2["total"]
    assert len(page1["items"]) <= 5
    if page1["total"] > 5:
        ids1 = {r["id"] for r in page1["items"]}
        ids2 = {r["id"] for r in page2["items"]}
        assert ids1.isdisjoint(ids2)


# ---------- login auditing ----------


def test_successful_login_writes_audit_row(client: TestClient) -> None:
    res = client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    assert res.status_code == 200
    rows = _audit_rows("auth.login")
    assert len(rows) >= 1
    row = rows[-1]
    assert row.result == "success"
    assert row.actor_username == "risk"
    assert row.target_type == "user"
    assert row.target_id == str(_user_id("risk"))


def test_bad_password_login_writes_failure_row(client: TestClient) -> None:
    res = client.post("/api/auth/login", json={"username": "risk", "password": "WRONG"})
    assert res.status_code == 401
    rows = _audit_rows("auth.login")
    failures = [r for r in rows if r.result == "failure"]
    assert any("bad_password" in (r.detail or "") for r in failures)


def test_unknown_user_login_writes_failure_row(client: TestClient) -> None:
    res = client.post("/api/auth/login", json={"username": "does-not-exist", "password": "anything"})
    assert res.status_code == 401
    rows = _audit_rows("auth.login")
    failures = [r for r in rows if r.result == "failure"]
    # Actor is unknown, so actor_id is null and actor_username is empty.
    assert any(
        r.actor_id is None
        and "unknown_user" in (r.detail or "")
        and r.target_id == "does-not-exist"
        for r in failures
    )


def test_disabled_user_login_writes_failure_row(client: TestClient) -> None:
    res = client.post("/api/auth/login", json={"username": "disabled", "password": "disabled123"})
    assert res.status_code == 401
    rows = _audit_rows("auth.login")
    failures = [r for r in rows if r.result == "failure"]
    assert any("user_disabled" in (r.detail or "") for r in failures)


def test_logout_writes_audit_row(client: TestClient) -> None:
    _login(client, "viewer", "viewer123")
    client.post("/api/auth/logout")
    rows = _audit_rows("auth.logout")
    assert len(rows) >= 1
    assert rows[-1].actor_username == "viewer"


# ---------- cross-feature representation ----------


def test_audit_covers_user_data_rule_alert_ticket_report_actions(client: TestClient) -> None:
    """Issue 11 requires that login, user-and-role, data-source, rule,
    alert, ticket, report.create, and report.download events all show
    up in the audit log when those features run."""
    # Build a chain of actions that visits each domain at least once.
    _seed_static_demo(client)  # auth.login + datasource.fetch + opinion.* + alert.*

    _login(client, "admin", "admin123")
    # user.create
    res = client.post(
        "/api/users",
        json={"username": "extra", "full_name": "x", "password": "extrapw123", "is_active": True,
              "role_id": 1},
    )
    assert res.status_code in (201, 409)
    # rule.sensitive.create
    res = client.post(
        "/api/rules/sensitive-keywords",
        json={"keyword": "审计测试词2", "category": "审计", "severity": "low", "remark": ""},
    )
    assert res.status_code == 201, res.text

    # Pick a pending alert and confirm -> create ticket -> assign + start + complete
    db = _session()
    try:
        from app.models.alert import Alert, ALERT_STATUS_PENDING

        alert = db.query(Alert).filter(Alert.status == ALERT_STATUS_PENDING).order_by(Alert.id.asc()).first()
        alert_id = alert.id if alert else None
        handler_id = _user_id("handler")
    finally:
        db.close()
    assert alert_id is not None, "demo data should have produced at least one pending alert"
    _logout(client)

    _login(client, "risk", "risk123")
    res = client.post(f"/api/alerts/{alert_id}/confirm")
    assert res.status_code == 200
    res = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": alert_id, "assignee_id": handler_id, "title": "审计测试工单"},
    )
    assert res.status_code == 201, res.text
    ticket_id = res.json()["id"]
    # Generate a report -> report.create
    res = client.post(
        "/api/reports",
        json={"title": "审计测试报告", "risk_level": "", "subject_keyword": ""},
    )
    assert res.status_code == 201, res.text
    report_id = res.json()["id"]
    _logout(client)

    # Handler completes the ticket -> ticket.start + ticket.complete
    _login(client, "handler", "handler123")
    res = client.post(f"/api/tickets/{ticket_id}/start")
    assert res.status_code == 200, res.text
    res = client.post(f"/api/tickets/{ticket_id}/complete", json={"handling_result": "已处置"})
    assert res.status_code == 200, res.text
    _logout(client)

    # Risk-control archives + downloads (download requires the report to
    # have finished; the runner is a fastapi BackgroundTask which the
    # TestClient drains synchronously).
    _login(client, "risk", "risk123")
    res = client.post(f"/api/tickets/{ticket_id}/archive")
    assert res.status_code == 200, res.text
    res = client.get(f"/api/reports/{report_id}/download")
    # Report should have completed by now; if not, the download writes a
    # failure audit row anyway, which still proves report.download is
    # represented.
    assert res.status_code in (200, 409)
    _logout(client)

    # Verify the audit log contains an entry for each required domain.
    _login(client, "auditor", "auditor123")
    res = client.get("/api/audit-logs?limit=200")
    assert res.status_code == 200
    actions = {row["action"] for row in res.json()["items"]}
    # The 200-item window is generous; if the log overflows we widen it.
    if "alert.confirm" not in actions:
        res = client.get("/api/audit-logs?limit=200&action=alert.confirm")
        assert res.json()["total"] >= 1
        actions.add("alert.confirm")

    required = {
        "auth.login",
        "user.create",
        "datasource.fetch",
        "rule.sensitive.create",
        "alert.confirm",
        "ticket.create",
        "ticket.complete",
        "report.create",
        "report.download",
    }
    missing = []
    for action in required:
        # Re-query each action individually so a long log doesn't push
        # an early row out of the limit=200 window.
        res = client.get(f"/api/audit-logs?action={action}&limit=1")
        assert res.status_code == 200
        if res.json()["total"] == 0:
            missing.append(action)
    assert not missing, f"missing audit actions: {missing}"


# ---------- facets ----------


def test_facets_endpoint_lists_distinct_values(client: TestClient) -> None:
    _seed_static_demo(client)
    _login(client, "auditor", "auditor123")
    res = client.get("/api/audit-logs/facets")
    assert res.status_code == 200
    body = res.json()
    assert "actions" in body and isinstance(body["actions"], list)
    assert "target_types" in body and isinstance(body["target_types"], list)
    assert "results" in body and isinstance(body["results"], list)
    assert "actors" in body and isinstance(body["actors"], list)
    # The fetch path is guaranteed by _seed_static_demo.
    assert "datasource.fetch" in body["actions"]
    assert "datasource" in body["target_types"]
    assert "success" in body["results"]
    assert "admin" in body["actors"]


# ---------- detail ----------


def test_detail_endpoint_returns_row(client: TestClient) -> None:
    _seed_static_demo(client)
    _login(client, "auditor", "auditor123")
    res = client.get("/api/audit-logs?limit=1")
    assert res.status_code == 200
    items = res.json()["items"]
    assert items
    log_id = items[0]["id"]
    res = client.get(f"/api/audit-logs/{log_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == log_id


def test_detail_endpoint_404_for_unknown_id(client: TestClient) -> None:
    _login(client, "auditor", "auditor123")
    res = client.get("/api/audit-logs/99999999")
    assert res.status_code == 404


# ---------- read-only contract ----------


def test_audit_router_has_no_write_methods(client: TestClient) -> None:
    """The audit log is append-only and the only writer is
    record_audit. Guard against a future regression that adds a
    POST/PUT/PATCH/DELETE endpoint on this router."""
    from app.main import create_app

    app = create_app()
    bad_methods = {"POST", "PUT", "PATCH", "DELETE"}
    for route in app.routes:
        if not hasattr(route, "path") or not route.path.startswith("/api/audit-logs"):
            continue
        for method in getattr(route, "methods", set()):
            assert method not in bad_methods, (
                f"audit-logs router must stay read-only, found {method} {route.path}"
            )


# ---------- web UI ----------


def test_audit_page_renders_for_auditor(client: TestClient) -> None:
    _login(client, "auditor", "auditor123")
    res = client.get("/web/audit")
    assert res.status_code == 200
    body = res.text
    assert "审计日志" in body
    assert "/static/audit.js" in body


def test_audit_page_renders_for_admin(client: TestClient) -> None:
    _login(client, "admin", "admin123")
    res = client.get("/web/audit")
    assert res.status_code == 200
    assert "审计日志" in res.text


def test_audit_page_blocked_for_handler_risk_viewer(client: TestClient) -> None:
    for username, password in [
        ("handler", "handler123"),
        ("risk", "risk123"),
        ("viewer", "viewer123"),
    ]:
        _login(client, username, password)
        res = client.get("/web/audit")
        assert res.status_code == 403, username
        _logout(client)


def test_audit_page_blocked_for_anonymous(client: TestClient) -> None:
    res = client.get("/web/audit")
    assert res.status_code == 401
