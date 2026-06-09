"""Acceptance tests for Phase 3 / Issue 3: risk rule management.

Covers:
  - admin can list / create / update / disable sensitive & subject keywords
  - admin can maintain risk thresholds (replace)
  - non-admin roles get 403 on write endpoints, 200 on reads
  - every change writes an AuditLog row with actor/action/target/result/IP
  - validation rejects duplicate keywords, missing levels, non-strict ordering
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.db import session as session_module
from app.models.audit import AuditLog
from app.models.rule import RiskThreshold, SensitiveKeyword, SubjectKeyword


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


# ---------- sensitive keywords ----------

def test_list_sensitive_requires_authentication(client):
    res = client.get("/api/rules/sensitive-keywords")
    assert res.status_code == 401


def test_list_sensitive_returns_seeded_for_any_logged_in(client):
    for user, pwd in [("admin", "admin123"), ("risk", "risk123"), ("auditor", "auditor123"), ("viewer", "viewer123")]:
        client.post("/api/auth/login", json={"username": user, "password": pwd})
        res = client.get("/api/rules/sensitive-keywords")
        assert res.status_code == 200, user
        client.post("/api/auth/logout")


def test_create_sensitive_keyword_as_admin(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.post(
        "/api/rules/sensitive-keywords",
        json={"keyword": "风险", "category": "舆情", "severity": "high", "remark": "测试"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["keyword"] == "风险"
    assert body["severity"] == "high"
    assert body["is_active"] is True


def test_create_sensitive_rejects_duplicate(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    client.post("/api/rules/sensitive-keywords", json={"keyword": "重复词"})
    res = client.post("/api/rules/sensitive-keywords", json={"keyword": "重复词"})
    assert res.status_code == 409


def test_create_sensitive_rejects_invalid_severity(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.post("/api/rules/sensitive-keywords", json={"keyword": "x", "severity": "extreme"})
    assert res.status_code == 422


def test_create_sensitive_blocks_non_admin(client):
    for user, pwd in [("risk", "risk123"), ("auditor", "auditor123"), ("viewer", "viewer123"), ("handler", "handler123")]:
        client.post("/api/auth/login", json={"username": user, "password": pwd})
        res = client.post("/api/rules/sensitive-keywords", json={"keyword": f"x-{user}"})
        assert res.status_code == 403, user
        client.post("/api/auth/logout")


def test_update_sensitive_keyword_writes_audit(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    create = client.post("/api/rules/sensitive-keywords", json={"keyword": "可改"})
    target_id = str(create.json()["id"])
    res = client.patch(
        f"/api/rules/sensitive-keywords/{target_id}",
        json={"severity": "severe", "is_active": False, "remark": "升级"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["severity"] == "severe"
    assert body["is_active"] is False

    entry = _latest_audit("rule.sensitive.update", target_id)
    assert entry is not None
    detail = json.loads(entry.detail)
    assert detail["changes"]["severity"] == "severe"
    assert detail["changes"]["is_active"] is False
    assert entry.actor_username == "admin"
    assert entry.ip_address


def test_update_sensitive_404_for_missing(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.patch("/api/rules/sensitive-keywords/99999", json={"severity": "low"})
    assert res.status_code == 404


# ---------- subject keywords ----------

def test_create_subject_keyword_as_admin(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.post("/api/rules/subject-keywords", json={"keyword": "示例公司", "category": "组织"})
    assert res.status_code == 201
    assert res.json()["keyword"] == "示例公司"


def test_create_subject_rejects_duplicate(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    client.post("/api/rules/subject-keywords", json={"keyword": "同主体"})
    res = client.post("/api/rules/subject-keywords", json={"keyword": "同主体"})
    assert res.status_code == 409


def test_update_subject_can_disable(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    create = client.post("/api/rules/subject-keywords", json={"keyword": "开关测试"})
    target_id = str(create.json()["id"])
    res = client.patch(f"/api/rules/subject-keywords/{target_id}", json={"is_active": False})
    assert res.status_code == 200
    assert res.json()["is_active"] is False


def test_update_subject_blocks_non_admin(client):
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.patch("/api/rules/subject-keywords/1", json={"is_active": False})
    assert res.status_code == 403


# ---------- risk thresholds ----------

def test_thresholds_seeded_on_bootstrap(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.get("/api/rules/thresholds")
    assert res.status_code == 200
    levels = [t["level"] for t in res.json()]
    assert levels == ["low", "medium", "high", "severe"]


def test_replace_thresholds_as_admin(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.put(
        "/api/rules/thresholds",
        json={"thresholds": [
            {"level": "low", "min_score": 0},
            {"level": "medium", "min_score": 25},
            {"level": "high", "min_score": 55},
            {"level": "severe", "min_score": 80},
        ]},
    )
    assert res.status_code == 200
    body = res.json()
    assert [t["level"] for t in body] == ["low", "medium", "high", "severe"]
    assert body[2]["min_score"] == 55

    db = Session(_engine())
    try:
        stored = {r.level: r.min_score for r in db.query(RiskThreshold).all()}
    finally:
        db.close()
    assert stored["medium"] == 25
    assert stored["severe"] == 80


def test_replace_thresholds_rejects_missing_level(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.put(
        "/api/rules/thresholds",
        json={"thresholds": [
            {"level": "low", "min_score": 0},
            {"level": "medium", "min_score": 30},
            {"level": "high", "min_score": 60},
        ]},
    )
    assert res.status_code == 400


def test_replace_thresholds_rejects_non_strictly_increasing(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.put(
        "/api/rules/thresholds",
        json={"thresholds": [
            {"level": "low", "min_score": 0},
            {"level": "medium", "min_score": 30},
            {"level": "high", "min_score": 30},
            {"level": "severe", "min_score": 85},
        ]},
    )
    assert res.status_code == 400


def test_replace_thresholds_blocks_non_admin(client):
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.put(
        "/api/rules/thresholds",
        json={"thresholds": [
            {"level": "low", "min_score": 0},
            {"level": "medium", "min_score": 30},
            {"level": "high", "min_score": 60},
            {"level": "severe", "min_score": 85},
        ]},
    )
    assert res.status_code == 403


def test_replace_thresholds_writes_audit(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    client.put(
        "/api/rules/thresholds",
        json={"thresholds": [
            {"level": "low", "min_score": 0},
            {"level": "medium", "min_score": 35},
            {"level": "high", "min_score": 65},
            {"level": "severe", "min_score": 90},
        ]},
    )
    entry = _latest_audit("rule.threshold.update", "thresholds")
    assert entry is not None
    detail = json.loads(entry.detail)
    assert detail["after"]["medium"] == 35


# ---------- web UI page ----------

def test_rules_page_renders_for_admin(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.get("/web/rules")
    assert res.status_code == 200
    body = res.text
    assert "风险阈值" in body
    assert "敏感词" in body
    assert "主体词" in body


def test_rules_page_403_for_viewer(client):
    client.post("/api/auth/login", json={"username": "viewer", "password": "viewer123"})
    res = client.get("/web/rules")
    assert res.status_code == 403


def test_rules_page_401_for_unauthenticated(client):
    res = client.get("/web/rules")
    assert res.status_code == 401
