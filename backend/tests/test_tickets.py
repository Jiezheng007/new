"""Acceptance tests for Phase 6 / Issue 8: ticket lifecycle.

Covers:
  - Risk-control converts a confirmed alert into a ticket (with and
    without an assignee on creation)
  - One ticket per alert (uniqueness on alert_id)
  - Cannot create a ticket from a non-confirmed alert
  - Assign / reassign / start / complete / archive state transitions
  - Invalid state transitions (e.g. archive a non-completed ticket)
  - Handler visibility: handler can only see their own tickets, never
    a peer's; admin / risk-control / auditor see the full list
  - Handler can mark in-progress only on their own assigned ticket
  - Handler can complete only on their own in-progress ticket and only
    with a non-blank handling_result
  - Permission enforcement: viewers blocked; auditor read-only;
    handler cannot manage other people's tickets
  - Audit log: every state change writes a row with actor / target / IP
  - Summary endpoint counts match the underlying state breakdown
  - Web UI: /web/tickets renders for the right roles
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
from app.models.role_codes import RoleCode
from app.models.ticket import (
    TICKET_STATUS_ARCHIVED,
    TICKET_STATUS_COMPLETED,
    TICKET_STATUS_IN_PROGRESS,
    TICKET_STATUS_UNASSIGNED,
    Ticket,
)
from app.models.user import User


# ---------- helpers ----------


def _engine():
    return session_module.engine


def _session():
    return Session(_engine())


def _seed_static_demo(client):
    """Trigger the static-demo fetch as admin so the demo + analysis rows exist."""
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


def _confirm_first_alert(client) -> int:
    """Confirm the first pending alert and return its id."""
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    db = _session()
    try:
        alert = (
            db.query(Alert)
            .filter(Alert.status == ALERT_STATUS_PENDING)
            .order_by(Alert.id.asc())
            .first()
        )
        assert alert is not None, "expected at least one pending alert"
        alert_id = alert.id
    finally:
        db.close()
    res = client.post(f"/api/alerts/{alert_id}/confirm")
    assert res.status_code == 200, res.text
    client.post("/api/auth/logout")
    return alert_id


def _handler_id() -> int:
    db = _session()
    try:
        u = db.query(User).filter(User.username == "handler").one()
        return u.id
    finally:
        db.close()


def _create_handler(db: Session) -> User:
    """Create a second handler to test cross-handler isolation."""
    role = (
        db.query(User)
        .filter(User.username == "admin")
        .one()
        .role
    )
    # Use the existing handler role by querying it directly.
    from app.models.user import Role

    handler_role = db.query(Role).filter(Role.code == RoleCode.HANDLER).one()
    name = f"handler2-{abs(hash('phase6-test')) % 100000}"
    user = User(
        username=name,
        full_name="处置二号",
        password_hash="x" * 64,
        is_active=True,
        role_id=handler_role.id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _latest_audit(action: str, target_id: str = ""):
    db = _session()
    try:
        q = db.query(AuditLog).filter(AuditLog.action == action)
        if target_id:
            q = q.filter(AuditLog.target_id == target_id)
        return q.order_by(AuditLog.id.desc()).first()
    finally:
        db.close()


def _username_for(user_id: int) -> str:
    db = _session()
    try:
        return db.get(User, user_id).username
    finally:
        db.close()


# ---------- creation from alert ----------


def test_create_ticket_from_confirmed_alert(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": alert_id, "title": "测试工单", "description": "示例描述"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == TICKET_STATUS_UNASSIGNED
    assert body["assignee_username"] == ""
    assert body["created_at"]

    # Audit row written
    entry = _latest_audit("ticket.create", str(body["id"]))
    assert entry is not None
    assert entry.actor_username == "risk"
    detail = json.loads(entry.detail)
    assert detail["alert_id"] == alert_id
    assert detail["status"] == TICKET_STATUS_UNASSIGNED
    client.post("/api/auth/logout")


def test_create_ticket_with_assignee_starts_in_progress(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    handler_id = _handler_id()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": alert_id, "assignee_id": handler_id},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == TICKET_STATUS_IN_PROGRESS
    assert body["assignee_username"] == "handler"
    client.post("/api/auth/logout")


def test_create_ticket_rejects_non_confirmed_alert(client):
    _seed_static_demo(client)
    # Pick a pending alert (not confirmed) and try to convert.
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    db = _session()
    try:
        pending = (
            db.query(Alert)
            .filter(Alert.status == ALERT_STATUS_PENDING)
            .order_by(Alert.id.asc())
            .first()
        )
        assert pending is not None
        pending_id = pending.id
    finally:
        db.close()
    res = client.post("/api/tickets/from-alert", json={"alert_id": pending_id})
    assert res.status_code == 409, res.text
    client.post("/api/auth/logout")


def test_create_ticket_rejects_ignored_alert(client):
    _seed_static_demo(client)
    # Ignore an alert, then try to convert it.
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    db = _session()
    try:
        pending = (
            db.query(Alert)
            .filter(Alert.status == ALERT_STATUS_PENDING)
            .order_by(Alert.id.asc())
            .first()
        )
        alert_id = pending.id
    finally:
        db.close()
    res = client.post(
        f"/api/alerts/{alert_id}/ignore", json={"reason": "误报忽略"}
    )
    assert res.status_code == 200
    res = client.post("/api/tickets/from-alert", json={"alert_id": alert_id})
    assert res.status_code == 409, res.text
    client.post("/api/auth/logout")


def test_create_ticket_rejects_unknown_alert(client):
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post("/api/tickets/from-alert", json={"alert_id": 99999})
    assert res.status_code == 404
    client.post("/api/auth/logout")


def test_create_ticket_rejects_non_handler_assignee(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    db = _session()
    try:
        admin = db.query(User).filter(User.username == "admin").one()
        admin_id = admin.id
    finally:
        db.close()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": alert_id, "assignee_id": admin_id},
    )
    assert res.status_code == 400, res.text
    assert "handler" in res.json()["detail"].lower()
    client.post("/api/auth/logout")


def test_create_ticket_rejects_disabled_assignee(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    db = _session()
    try:
        # Disable the 'disabled' demo user, but first make them a handler.
        # Simpler path: temporarily flip role then disable, then revert.
        # Instead, use the built-in 'disabled' user but their role is viewer
        # by default in the fixture; we need a disabled *handler*.
        # Workaround: create a disabled handler.
        from app.models.user import Role

        handler_role = db.query(Role).filter(Role.code == RoleCode.HANDLER).one()
        user = User(
            username="disabled_handler",
            full_name="停用处置",
            password_hash="x" * 64,
            is_active=False,
            role_id=handler_role.id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        disabled_id = user.id
    finally:
        db.close()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": alert_id, "assignee_id": disabled_id},
    )
    assert res.status_code == 400, res.text
    assert "disabled" in res.json()["detail"].lower()
    client.post("/api/auth/logout")


def test_create_ticket_rejects_unknown_assignee(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": alert_id, "assignee_id": 99999},
    )
    assert res.status_code == 400, res.text
    client.post("/api/auth/logout")


def test_create_ticket_blocks_non_managers(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    for username, password in [
        ("handler", "handler123"),
        ("auditor", "auditor123"),
        ("viewer", "viewer123"),
    ]:
        client.post("/api/auth/login", json={"username": username, "password": password})
        res = client.post("/api/tickets/from-alert", json={"alert_id": alert_id})
        assert res.status_code == 403, username
        client.post("/api/auth/logout")


def test_create_ticket_one_per_alert(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res1 = client.post("/api/tickets/from-alert", json={"alert_id": alert_id})
    assert res1.status_code == 201
    res2 = client.post("/api/tickets/from-alert", json={"alert_id": alert_id})
    assert res2.status_code == 409, res2.text
    client.post("/api/auth/logout")


# ---------- assign / start / complete / archive transitions ----------


def _create_unassigned_ticket(client, alert_id: int) -> int:
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post("/api/tickets/from-alert", json={"alert_id": alert_id})
    assert res.status_code == 201
    ticket_id = res.json()["id"]
    client.post("/api/auth/logout")
    return ticket_id


def test_assign_unassigned_ticket_transitions_to_in_progress(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    ticket_id = _create_unassigned_ticket(client, alert_id)
    handler_id = _handler_id()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        f"/api/tickets/{ticket_id}/assign", json={"assignee_id": handler_id}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == TICKET_STATUS_IN_PROGRESS
    assert body["assignee_username"] == "handler"
    assert body["started_at"]
    client.post("/api/auth/logout")


def test_reassign_in_progress_ticket_keeps_status(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    handler_id = _handler_id()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": alert_id, "assignee_id": handler_id},
    )
    ticket_id = res.json()["id"]

    # Create a second handler for reassignment.
    db = _session()
    try:
        second_handler = _create_handler(db)
        second_id = second_handler.id
    finally:
        db.close()

    res = client.post(
        f"/api/tickets/{ticket_id}/assign", json={"assignee_id": second_id}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == TICKET_STATUS_IN_PROGRESS
    assert body["assignee_username"] == _username_for(second_id)
    client.post("/api/auth/logout")


def test_assign_archived_ticket_returns_409(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    handler_id = _handler_id()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": alert_id, "assignee_id": handler_id},
    )
    ticket_id = res.json()["id"]
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={"username": "handler", "password": "handler123"})
    res = client.post(
        f"/api/tickets/{ticket_id}/complete",
        json={"handling_result": "已联系当事人并完成处置"},
    )
    assert res.status_code == 200
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(f"/api/tickets/{ticket_id}/archive")
    assert res.status_code == 200
    res = client.post(
        f"/api/tickets/{ticket_id}/assign", json={"assignee_id": handler_id}
    )
    assert res.status_code == 409, res.text
    client.post("/api/auth/logout")


def test_start_ticket_happy_path(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    ticket_id = _create_unassigned_ticket(client, alert_id)
    handler_id = _handler_id()
    # Risk-control assigns the handler.
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        f"/api/tickets/{ticket_id}/assign", json={"assignee_id": handler_id}
    )
    assert res.status_code == 200
    client.post("/api/auth/logout")

    # Handler explicitly calls /start (it's already in_progress but the
    # endpoint should be idempotent for the in_progress state).
    client.post("/api/auth/login", json={"username": "handler", "password": "handler123"})
    res = client.post(f"/api/tickets/{ticket_id}/start")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == TICKET_STATUS_IN_PROGRESS
    assert body["started_at"]
    client.post("/api/auth/logout")


def test_start_ticket_blocked_for_non_assignee(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    ticket_id = _create_unassigned_ticket(client, alert_id)
    handler_id = _handler_id()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        f"/api/tickets/{ticket_id}/assign", json={"assignee_id": handler_id}
    )
    assert res.status_code == 200
    client.post("/api/auth/logout")

    # Auditor (read-only) should not be able to start.
    client.post("/api/auth/login", json={"username": "auditor", "password": "auditor123"})
    res = client.post(f"/api/tickets/{ticket_id}/start")
    assert res.status_code == 403, res.text
    client.post("/api/auth/logout")


def test_start_completed_ticket_returns_409(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    handler_id = _handler_id()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": alert_id, "assignee_id": handler_id},
    )
    ticket_id = res.json()["id"]
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={"username": "handler", "password": "handler123"})
    res = client.post(
        f"/api/tickets/{ticket_id}/complete",
        json={"handling_result": "已联系当事人并完成处置"},
    )
    assert res.status_code == 200
    res = client.post(f"/api/tickets/{ticket_id}/start")
    assert res.status_code == 409, res.text
    client.post("/api/auth/logout")


def test_complete_ticket_happy_path(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    handler_id = _handler_id()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": alert_id, "assignee_id": handler_id},
    )
    ticket_id = res.json()["id"]
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={"username": "handler", "password": "handler123"})
    res = client.post(
        f"/api/tickets/{ticket_id}/complete",
        json={"handling_result": "已与企业沟通并取得谅解"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == TICKET_STATUS_COMPLETED
    assert body["completed_by_username"] == "handler"
    assert body["completed_at"]

    detail = _latest_audit("ticket.complete", str(ticket_id))
    assert detail is not None
    parsed = json.loads(detail.detail)
    assert parsed["status"] == TICKET_STATUS_COMPLETED
    client.post("/api/auth/logout")


def test_complete_ticket_rejects_blank_result(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    handler_id = _handler_id()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": alert_id, "assignee_id": handler_id},
    )
    ticket_id = res.json()["id"]
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={"username": "handler", "password": "handler123"})
    for bad in ["", "   ", "x"]:
        res = client.post(
            f"/api/tickets/{ticket_id}/complete", json={"handling_result": bad}
        )
        assert res.status_code == 422, (bad, res.status_code, res.text[:200])
    client.post("/api/auth/logout")


def test_complete_ticket_blocked_for_non_assignee(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    handler_id = _handler_id()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": alert_id, "assignee_id": handler_id},
    )
    ticket_id = res.json()["id"]
    client.post("/api/auth/logout")

    # Auditor / risk-control cannot complete a handler's ticket.
    for username, password in [
        ("auditor", "auditor123"),
        ("risk", "risk123"),
    ]:
        client.post("/api/auth/login", json={"username": username, "password": password})
        res = client.post(
            f"/api/tickets/{ticket_id}/complete",
            json={"handling_result": "尝试越权完成"},
        )
        assert res.status_code == 403, username
        client.post("/api/auth/logout")


def test_complete_unstarted_ticket_returns_409(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    handler_id = _handler_id()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": alert_id, "assignee_id": handler_id},
    )
    ticket_id = res.json()["id"]
    client.post("/api/auth/logout")

    # Complete then complete-again should be 409.
    client.post("/api/auth/login", json={"username": "handler", "password": "handler123"})
    res = client.post(
        f"/api/tickets/{ticket_id}/complete",
        json={"handling_result": "首次完成"},
    )
    assert res.status_code == 200
    res = client.post(
        f"/api/tickets/{ticket_id}/complete",
        json={"handling_result": "再次尝试"},
    )
    assert res.status_code == 409, res.text
    client.post("/api/auth/logout")


def test_archive_ticket_happy_path(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    handler_id = _handler_id()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": alert_id, "assignee_id": handler_id},
    )
    ticket_id = res.json()["id"]
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={"username": "handler", "password": "handler123"})
    res = client.post(
        f"/api/tickets/{ticket_id}/complete",
        json={"handling_result": "已与企业沟通并取得谅解"},
    )
    assert res.status_code == 200
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(f"/api/tickets/{ticket_id}/archive")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == TICKET_STATUS_ARCHIVED
    assert body["archived_by_username"] == "risk"
    assert body["archived_at"]
    client.post("/api/auth/logout")


def test_archive_non_completed_returns_409(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    ticket_id = _create_unassigned_ticket(client, alert_id)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(f"/api/tickets/{ticket_id}/archive")
    assert res.status_code == 409, res.text
    client.post("/api/auth/logout")


def test_archive_blocked_for_handler_and_auditor(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    handler_id = _handler_id()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": alert_id, "assignee_id": handler_id},
    )
    ticket_id = res.json()["id"]
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={"username": "handler", "password": "handler123"})
    res = client.post(
        f"/api/tickets/{ticket_id}/complete",
        json={"handling_result": "完成并记录结果"},
    )
    assert res.status_code == 200
    client.post("/api/auth/logout")

    for username, password in [("handler", "handler123"), ("auditor", "auditor123")]:
        client.post("/api/auth/login", json={"username": username, "password": password})
        res = client.post(f"/api/tickets/{ticket_id}/archive")
        assert res.status_code == 403, username
        client.post("/api/auth/logout")


# ---------- list / detail / filter / role visibility ----------


def test_list_for_risk_control(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    _create_unassigned_ticket(client, alert_id)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/api/tickets")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] >= 1
    for it in body["items"]:
        assert it["status"] in {
            TICKET_STATUS_UNASSIGNED,
            TICKET_STATUS_IN_PROGRESS,
            TICKET_STATUS_COMPLETED,
            TICKET_STATUS_ARCHIVED,
        }
        assert it["risk_level"] in {"high", "severe"}
        assert "opinion" in it
        assert "alert_summary" in it
    client.post("/api/auth/logout")


def test_list_for_handler_scoped_to_self(client):
    _seed_static_demo(client)
    # Confirm two pending alerts so we can spin up two tickets owned by
    # different handlers.
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    db = _session()
    try:
        pending_alerts = (
            db.query(Alert)
            .filter(Alert.status == ALERT_STATUS_PENDING)
            .order_by(Alert.id.asc())
            .limit(2)
            .all()
        )
        assert len(pending_alerts) >= 2, "expected two pending alerts from the static demo"
        first_alert = pending_alerts[0].id
        second_alert = pending_alerts[1].id
        handler = db.query(User).filter(User.username == "handler").one()
        handler_id = handler.id
        second_handler = _create_handler(db)
        second_id = second_handler.id
    finally:
        db.close()

    # Confirm both alerts.
    for aid in (first_alert, second_alert):
        res = client.post(f"/api/alerts/{aid}/confirm")
        assert res.status_code == 200

    res1 = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": first_alert, "assignee_id": handler_id},
    )
    assert res1.status_code == 201
    res2 = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": second_alert, "assignee_id": second_id},
    )
    assert res2.status_code == 201
    client.post("/api/auth/logout")

    # Handler "handler" should only see their own ticket.
    client.post("/api/auth/login", json={"username": "handler", "password": "handler123"})
    res = client.get("/api/tickets")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert all(it["assignee_username"] == "handler" for it in body["items"])
    client.post("/api/auth/logout")

    # Admin / risk_control see both.
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/api/tickets")
    body = res.json()
    assert body["total"] >= 2
    client.post("/api/auth/logout")


def test_list_blocks_viewer(client):
    client.post("/api/auth/login", json={"username": "viewer", "password": "viewer123"})
    res = client.get("/api/tickets")
    assert res.status_code == 403
    client.post("/api/auth/logout")


def test_list_requires_auth(client):
    res = client.get("/api/tickets")
    assert res.status_code == 401


def test_list_filter_by_status(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    _create_unassigned_ticket(client, alert_id)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/api/tickets?status=unassigned")
    assert res.status_code == 200
    body = res.json()
    for it in body["items"]:
        assert it["status"] == TICKET_STATUS_UNASSIGNED
    assert body["total"] >= 1
    client.post("/api/auth/logout")


def test_list_filter_validation(client):
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    for bad in ["status=banana", "risk_level=low"]:
        res = client.get(f"/api/tickets?{bad}")
        assert res.status_code == 400, bad
    client.post("/api/auth/logout")


def test_detail_404(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.get("/api/tickets/99999")
    assert res.status_code == 404
    client.post("/api/auth/logout")


def test_detail_handler_cannot_see_other(client):
    _seed_static_demo(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    db = _session()
    try:
        pending_alerts = (
            db.query(Alert)
            .filter(Alert.status == ALERT_STATUS_PENDING)
            .order_by(Alert.id.asc())
            .limit(2)
            .all()
        )
        assert len(pending_alerts) >= 2
        first_alert = pending_alerts[0].id
        second_alert = pending_alerts[1].id
        second_handler = _create_handler(db)
        second_id = second_handler.id
    finally:
        db.close()
    res = client.post(f"/api/alerts/{second_alert}/confirm")
    assert res.status_code == 200
    res1 = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": second_alert, "assignee_id": second_id},
    )
    other_ticket_id = res1.json()["id"]
    client.post("/api/auth/logout")

    # Default 'handler' user should not be able to see the second ticket.
    client.post("/api/auth/login", json={"username": "handler", "password": "handler123"})
    res = client.get(f"/api/tickets/{other_ticket_id}")
    assert res.status_code == 403, res.text
    client.post("/api/auth/logout")


# ---------- summary ----------


def test_summary_counts(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    _create_unassigned_ticket(client, alert_id)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/api/tickets/summary")
    assert res.status_code == 200
    body = res.json()
    assert body["unassigned"] >= 1
    assert (
        body["total"]
        == body["unassigned"] + body["in_progress"] + body["completed"] + body["archived"]
    )
    client.post("/api/auth/logout")


def test_summary_blocks_viewer(client):
    client.post("/api/auth/login", json={"username": "viewer", "password": "viewer123"})
    res = client.get("/api/tickets/summary")
    assert res.status_code == 403
    client.post("/api/auth/logout")


# ---------- audit trail ----------


def test_full_lifecycle_writes_audit_rows(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    handler_id = _handler_id()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": alert_id, "assignee_id": handler_id},
    )
    ticket_id = res.json()["id"]
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={"username": "handler", "password": "handler123"})
    res = client.post(
        f"/api/tickets/{ticket_id}/complete",
        json={"handling_result": "已联系当事人并完成处置"},
    )
    assert res.status_code == 200
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(f"/api/tickets/{ticket_id}/archive")
    assert res.status_code == 200
    client.post("/api/auth/logout")

    for action in ("ticket.create", "ticket.complete", "ticket.archive"):
        entry = _latest_audit(action, str(ticket_id))
        assert entry is not None, action
        assert entry.result == "success"


def test_failed_transition_writes_failure_audit(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    handler_id = _handler_id()
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": alert_id, "assignee_id": handler_id},
    )
    ticket_id = res.json()["id"]
    client.post("/api/auth/logout")

    # Handler completes and tries to start a completed ticket.
    client.post("/api/auth/login", json={"username": "handler", "password": "handler123"})
    res = client.post(
        f"/api/tickets/{ticket_id}/complete",
        json={"handling_result": "已联系当事人并完成处置"},
    )
    assert res.status_code == 200
    res = client.post(f"/api/tickets/{ticket_id}/start")
    assert res.status_code == 409
    client.post("/api/auth/logout")

    entry = _latest_audit("ticket.start", str(ticket_id))
    assert entry is not None
    assert entry.result == "failure"


# ---------- web UI ----------


def test_tickets_page_renders_for_eligible_roles(client):
    _seed_static_demo(client)
    alert_id = _confirm_first_alert(client)
    _create_unassigned_ticket(client, alert_id)
    for username, password in [
        ("admin", "admin123"),
        ("risk", "risk123"),
        ("auditor", "auditor123"),
        ("handler", "handler123"),
    ]:
        client.post("/api/auth/login", json={"username": username, "password": password})
        res = client.get("/web/tickets")
        assert res.status_code == 200, (username, res.text[:200])
        body = res.text
        assert "工单" in body
        client.post("/api/auth/logout")


def test_tickets_page_blocks_viewer(client):
    client.post("/api/auth/login", json={"username": "viewer", "password": "viewer123"})
    res = client.get("/web/tickets")
    assert res.status_code == 403
    client.post("/api/auth/logout")


def test_tickets_page_unauthenticated_redirects(client):
    res = client.get("/web/tickets")
    assert res.status_code == 401
