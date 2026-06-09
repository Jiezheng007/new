"""Web UI smoke tests: login page renders, login flow redirects, nav items match role."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_login_page_renders(client: TestClient) -> None:
    res = client.get("/login")
    assert res.status_code == 200
    assert "登录" in res.text


def test_root_redirects_to_login_when_unauthenticated(client: TestClient) -> None:
    res = client.get("/", follow_redirects=False)
    assert res.status_code in (301, 302, 307)
    assert res.headers["location"] in ("/login", "/web/login")


def test_admin_can_view_workbench_with_admin_nav(client: TestClient) -> None:
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.get("/web/workbench")
    assert res.status_code == 200
    body = res.text
    assert "工作台" in body
    assert "用户与角色" in body
    assert "审计日志" in body


def test_viewer_sees_only_dashboard_nav(client: TestClient) -> None:
    client.post("/api/auth/login", json={"username": "viewer", "password": "viewer123"})
    res = client.get("/web/workbench")
    assert res.status_code == 200
    body = res.text
    assert "工作台" in body
    assert "用户与角色" not in body
    assert "审计日志" not in body


def test_viewer_blocked_from_users_page(client: TestClient) -> None:
    client.post("/api/auth/login", json={"username": "viewer", "password": "viewer123"})
    res = client.get("/web/users")
    assert res.status_code == 403


def test_unauthenticated_user_redirected_or_blocked(client: TestClient) -> None:
    res = client.get("/web/workbench")
    assert res.status_code == 401
