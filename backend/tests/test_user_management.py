"""Acceptance tests for Phase 2 / Issue 2: user & role management.

Covers:
  - admin can list/create/edit/disable/reset-password
  - non-admin roles cannot access user-management endpoints
  - unauthenticated requests are rejected
  - disabled users cannot log in
  - audit log entries are written with actor, action, target, result, IP, timestamp
  - admin can review role permissions
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.db import session as session_module
from app.models.audit import AuditLog
from app.models.user import User
from app.models.role_codes import RoleCode


def _test_engine():
    """Return the engine the test fixture installed in app.db.session.

    Importing `engine` at module scope would capture the original value before
    the fixture monkey-patches it.
    """
    return session_module.engine


def _role_id(username: str) -> int:
    db = Session(_test_engine())
    try:
        return db.query(User).filter(User.username == username).one().role_id
    finally:
        db.close()


def _user_id(username: str) -> int:
    db = Session(_test_engine())
    try:
        return db.query(User).filter(User.username == username).one().id
    finally:
        db.close()


def _latest_audit(target_id: str, action: str):
    db = Session(_test_engine())
    try:
        return (
            db.query(AuditLog)
            .filter(AuditLog.target_id == target_id, AuditLog.action == action)
            .order_by(AuditLog.id.desc())
            .first()
        )
    finally:
        db.close()


# ---------- list users ----------

def test_list_users_requires_authentication(client):
    res = client.get("/api/users")
    assert res.status_code == 401


def test_list_users_blocks_non_admins(client):
    for user, pwd in [("risk", "risk123"), ("handler", "handler123"), ("auditor", "auditor123"), ("viewer", "viewer123")]:
        client.post("/api/auth/login", json={"username": user, "password": pwd})
        res = client.get("/api/users")
        assert res.status_code == 403, user
        client.post("/api/auth/logout")


def test_list_users_returns_all_users_for_admin(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.get("/api/users")
    assert res.status_code == 200
    body = res.json()
    usernames = {u["username"] for u in body}
    assert {"admin", "risk", "handler", "auditor", "viewer", "disabled"} <= usernames
    sample = next(u for u in body if u["username"] == "admin")
    assert sample["role"] == "admin"
    assert sample["role_name"] == "系统管理员"
    assert sample["is_active"] is True
    assert "role_id" in sample
    assert "updated_at" in sample


# ---------- create user ----------

def _admin_role_id(db: Session) -> int:
    return db.query(User).filter(User.username == "admin").one().role_id


def test_create_user_as_admin(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    target_role = _role_id("auditor")
    res = client.post(
        "/api/users",
        json={
            "username": "newcomer",
            "full_name": "新成员",
            "password": "passw0rd",
            "role_id": target_role,
            "is_active": True,
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["username"] == "newcomer"
    assert body["role"] == "auditor"
    assert body["is_active"] is True


def test_newly_created_user_can_log_in(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    target_role = _role_id("viewer")
    create = client.post(
        "/api/users",
        json={"username": "fresh", "password": "freshpwd1", "role_id": target_role, "is_active": True},
    )
    assert create.status_code == 201
    client.post("/api/auth/logout")

    res = client.post("/api/auth/login", json={"username": "fresh", "password": "freshpwd1"})
    assert res.status_code == 200


def test_create_user_rejects_duplicate_username(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    target_role = _role_id("viewer")
    res = client.post(
        "/api/users",
        json={"username": "risk", "password": "newpass1", "role_id": target_role},
    )
    assert res.status_code == 409


def test_create_user_rejects_invalid_role(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.post(
        "/api/users",
        json={"username": "ghost", "password": "ghost123", "role_id": 99999},
    )
    assert res.status_code == 400


def test_create_user_blocks_non_admin(client):
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(
        "/api/users",
        json={"username": "x", "password": "x123456", "role_id": 1},
    )
    assert res.status_code == 403


def test_create_user_writes_audit_log(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    target_role = _role_id("viewer")
    res = client.post(
        "/api/users",
        json={"username": "audited", "password": "audited1", "role_id": target_role},
    )
    assert res.status_code == 201
    target_id = str(res.json()["id"])
    entry = _latest_audit(target_id, "user.create")
    assert entry is not None
    assert entry.actor_username == "admin"
    assert entry.result == "success"
    assert entry.target_type == "user"
    assert entry.ip_address  # TestClient populates client.host
    assert entry.created_at is not None
    detail = json.loads(entry.detail)
    assert detail["username"] == "audited"
    assert detail["role"] == "viewer"


# ---------- update user ----------

def test_update_user_full_name_and_role(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    target_id = _user_id("handler")
    risk_role_id = _role_id("risk")
    res = client.patch(
        f"/api/users/{target_id}",
        json={"full_name": "首席处置员", "role_id": risk_role_id},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["full_name"] == "首席处置员"
    assert body["role"] == "risk_control"


def test_admin_can_disable_user(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    target_id = _user_id("handler")
    res = client.patch(f"/api/users/{target_id}", json={"is_active": False})
    assert res.status_code == 200
    assert res.json()["is_active"] is False

    client.post("/api/auth/logout")
    blocked = client.post("/api/auth/login", json={"username": "handler", "password": "handler123"})
    assert blocked.status_code == 401


def test_admin_can_reenable_user(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    target_id = _user_id("disabled")
    res = client.patch(f"/api/users/{target_id}", json={"is_active": True})
    assert res.status_code == 200
    assert res.json()["is_active"] is True


def test_admin_cannot_disable_self(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    admin_id = _user_id("admin")
    res = client.patch(f"/api/users/{admin_id}", json={"is_active": False})
    assert res.status_code == 400
    assert "own" in res.json()["detail"]


def test_admin_cannot_demote_self(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    admin_id = _user_id("admin")
    viewer_role = _role_id("viewer")
    res = client.patch(f"/api/users/{admin_id}", json={"role_id": viewer_role})
    assert res.status_code == 400
    assert "admin" in res.json()["detail"]


def test_update_user_blocks_non_admin(client):
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.patch("/api/users/1", json={"full_name": "x"})
    assert res.status_code == 403


def test_update_user_404_for_missing(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.patch("/api/users/99999", json={"full_name": "x"})
    assert res.status_code == 404


def test_update_writes_audit_log(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    target_id = _user_id("handler")
    res = client.patch(f"/api/users/{target_id}", json={"full_name": "新处置员"})
    assert res.status_code == 200
    entry = _latest_audit(str(target_id), "user.update")
    assert entry is not None
    assert entry.result == "success"
    assert entry.actor_username == "admin"
    assert entry.ip_address


# ---------- reset password ----------

def test_reset_password_with_explicit_value(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    target_id = _user_id("handler")
    res = client.post(f"/api/users/{target_id}/reset-password", json={"new_password": "brand-new-pw"})
    assert res.status_code == 200
    body = res.json()
    assert body["new_password"] == "brand-new-pw"
    assert body["generated"] is False

    client.post("/api/auth/logout")
    ok = client.post("/api/auth/login", json={"username": "handler", "password": "brand-new-pw"})
    assert ok.status_code == 200


def test_reset_password_auto_generates(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    target_id = _user_id("risk")
    res = client.post(f"/api/users/{target_id}/reset-password", json={})
    assert res.status_code == 200
    body = res.json()
    assert body["generated"] is True
    assert len(body["new_password"]) >= 8


def test_reset_password_blocks_non_admin(client):
    client.post("/api/auth/login", json={"username": "auditor", "password": "auditor123"})
    res = client.post("/api/users/1/reset-password", json={"new_password": "ignored"})
    assert res.status_code == 403


def test_reset_password_404_for_missing(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.post("/api/users/99999/reset-password", json={"new_password": "whatever1"})
    assert res.status_code == 404


def test_reset_password_audit_log_does_not_record_password(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    target_id = _user_id("handler")
    res = client.post(f"/api/users/{target_id}/reset-password", json={"new_password": "secret-pw-1"})
    assert res.status_code == 200
    new_pw = res.json()["new_password"]
    entry = _latest_audit(str(target_id), "user.reset_password")
    assert entry is not None
    assert entry.result == "success"
    assert new_pw not in entry.detail


# ---------- roles ----------

def test_list_roles_returns_five_roles_with_permissions(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.get("/api/roles")
    assert res.status_code == 200
    body = res.json()
    codes = {r["code"] for r in body}
    assert codes == {RoleCode.ADMIN, RoleCode.RISK_CONTROL, RoleCode.HANDLER, RoleCode.AUDITOR, RoleCode.VIEWER}
    admin = next(r for r in body if r["code"] == RoleCode.ADMIN)
    assert admin["permissions"] == ["*"]
    viewer = next(r for r in body if r["code"] == RoleCode.VIEWER)
    assert "dashboard:read" in viewer["permissions"]


def test_list_roles_blocks_non_admin(client):
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/api/roles")
    assert res.status_code == 403


# ---------- web UI page ----------

def test_users_page_renders_for_admin(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.get("/web/users")
    assert res.status_code == 200
    body = res.text
    assert "用户列表" in body
    assert "创建用户" in body
    assert "角色与权限" in body


def test_users_page_403_for_viewer(client):
    client.post("/api/auth/login", json={"username": "viewer", "password": "viewer123"})
    res = client.get("/web/users")
    assert res.status_code == 403


def test_users_page_401_for_unauthenticated(client):
    res = client.get("/web/users")
    assert res.status_code == 401
