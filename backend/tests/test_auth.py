"""Acceptance tests for Phase 1: login, logout, profile, RBAC enforcement."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_login_success_returns_token_and_sets_cookie(client: TestClient) -> None:
    res = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert "access_token" in res.cookies


def test_login_with_wrong_password_rejected(client: TestClient) -> None:
    res = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert res.status_code == 401
    assert "Invalid" in res.json()["detail"]


def test_login_with_unknown_user_rejected(client: TestClient) -> None:
    res = client.post("/api/auth/login", json={"username": "ghost", "password": "anything"})
    assert res.status_code == 401


def test_disabled_user_cannot_login(client: TestClient) -> None:
    res = client.post("/api/auth/login", json={"username": "disabled", "password": "disabled123"})
    assert res.status_code == 401


def test_logout_clears_cookie(client: TestClient) -> None:
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.post("/api/auth/logout")
    assert res.status_code == 200
    assert res.cookies.get("access_token") in (None, "")


def test_me_returns_profile_with_role_and_permissions(client: TestClient) -> None:
    login_as(client, "admin", "admin123")
    res = client.get("/api/auth/me")
    assert res.status_code == 200
    body = res.json()
    assert body["username"] == "admin"
    assert body["role"] == "admin"
    assert body["role_name"] == "系统管理员"
    assert "*" in body["permissions"]
    assert any(item["key"] == "workbench" for item in body["nav_items"])


def test_me_rejects_unauthenticated_request(client: TestClient) -> None:
    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_me_rejects_invalid_token(client: TestClient) -> None:
    client.cookies.set("access_token", "not-a-jwt")
    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_password_storage_uses_salted_hash(client: TestClient) -> None:
    from sqlalchemy.orm import Session

    from app.db.session import engine
    from app.models.user import User

    with Session(engine) as db:
        user = db.query(User).filter(User.username == "admin").one()
        assert user.password_hash != "admin123"
        # passlib's pbkdf2_sha256 hash format: $<scheme>$<iterations>$<salt>$<digest>
        assert user.password_hash.startswith("$pbkdf2-sha256$")
        assert user.password_hash.count("$") == 4


def test_two_users_with_same_password_have_different_hashes(client: TestClient) -> None:
    from app.core.security import hash_password

    h1 = hash_password("samepassword")
    h2 = hash_password("samepassword")
    assert h1 != h2
    # salt is the 3rd $-delimited segment: $<scheme>$<iterations>$<salt>$<digest>
    assert h1.split("$")[3] != h2.split("$")[3]


def test_unauthenticated_business_api_rejected(client: TestClient) -> None:
    for path in ("/api/protected/risk-control", "/api/protected/handler", "/api/protected/auditor", "/api/protected/admin", "/api/protected/dashboard"):
        res = client.get(path)
        assert res.status_code == 401, path


def test_rbac_admin_can_access_all_areas(client: TestClient) -> None:
    login_as(client, "admin", "admin123")
    for path in ("/api/protected/risk-control", "/api/protected/handler", "/api/protected/auditor", "/api/protected/admin", "/api/protected/dashboard"):
        res = client.get(path)
        assert res.status_code == 200, (path, res.text)


def test_rbac_risk_user_blocked_from_admin_area(client: TestClient) -> None:
    login_as(client, "risk", "risk123")
    assert client.get("/api/protected/risk-control").status_code == 200
    assert client.get("/api/protected/handler").status_code == 403
    assert client.get("/api/protected/auditor").status_code == 403
    assert client.get("/api/protected/admin").status_code == 403
    assert client.get("/api/protected/dashboard").status_code == 200


def test_rbac_handler_blocked_from_admin_and_auditor(client: TestClient) -> None:
    login_as(client, "handler", "handler123")
    assert client.get("/api/protected/handler").status_code == 200
    assert client.get("/api/protected/risk-control").status_code == 403
    assert client.get("/api/protected/auditor").status_code == 403
    assert client.get("/api/protected/admin").status_code == 403
    assert client.get("/api/protected/dashboard").status_code == 200


def test_rbac_auditor_blocked_from_admin_and_risk(client: TestClient) -> None:
    login_as(client, "auditor", "auditor123")
    assert client.get("/api/protected/auditor").status_code == 200
    assert client.get("/api/protected/risk-control").status_code == 403
    assert client.get("/api/protected/handler").status_code == 403
    assert client.get("/api/protected/admin").status_code == 403
    assert client.get("/api/protected/dashboard").status_code == 200


def test_rbac_viewer_only_dashboard_and_readonly(client: TestClient) -> None:
    login_as(client, "viewer", "viewer123")
    assert client.get("/api/protected/dashboard").status_code == 200
    assert client.get("/api/protected/risk-control").status_code == 403
    assert client.get("/api/protected/handler").status_code == 403
    assert client.get("/api/protected/auditor").status_code == 403
    assert client.get("/api/protected/admin").status_code == 403


def test_authorization_header_also_works(client: TestClient) -> None:
    res = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = res.json()["access_token"]
    client.cookies.clear()
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["username"] == "admin"


def login_as(client: TestClient, username: str, password: str) -> None:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
