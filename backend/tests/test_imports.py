"""Acceptance tests for Phase 3 / Issue 5: CSV / JSON import.

Covers:
  - risk-control can upload CSV / JSON
  - required fields validated, invalid rows surfaced
  - dedup works on re-upload
  - bundled demo import endpoint loads the curated samples
  - every import writes an audit row
  - non-import roles get 403
"""
from __future__ import annotations

import io
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import session as session_module
from app.models.audit import AuditLog
from app.models.datasource import OpinionItem


def _engine():
    return session_module.engine


def _latest_audit(action: str):
    db = Session(_engine())
    try:
        return (
            db.query(AuditLog)
            .filter(AuditLog.action == action)
            .order_by(AuditLog.id.desc())
            .first()
        )
    finally:
        db.close()


# ---------- CSV upload ----------

def test_csv_import_requires_auth(client):
    files = {"file": ("x.csv", "title,content\nfoo,bar", "text/csv")}
    res = client.post("/api/import/csv", files=files)
    assert res.status_code == 401


def test_csv_import_blocks_handler_and_auditor(client):
    files = {"file": ("x.csv", "title,content\nfoo,bar", "text/csv")}
    for user, pwd in [("handler", "handler123"), ("auditor", "auditor123")]:
        client.post("/api/auth/login", json={"username": user, "password": pwd})
        res = client.post("/api/import/csv", files=files)
        assert res.status_code == 403, user
        client.post("/api/auth/logout")


def test_csv_import_accepts_valid_rows(client):
    csv_text = (
        "external_id,title,content,author,language,published_at\n"
        "csv-a,导入测试 A,这是测试内容 A,测试作者,zh,2026-06-08T10:00:00\n"
        "csv-b,导入测试 B,这是测试内容 B,测试作者,zh,2026-06-08T11:00:00\n"
    )
    files = {"file": ("opinions.csv", csv_text, "text/csv")}
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post("/api/import/csv", files=files)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["format"] == "csv"
    assert body["accepted"] == 2
    assert body["rejected"] == 0
    assert body["duplicate"] == 0
    assert len(body["sample_ids"]) == 2


def test_csv_import_rejects_missing_required_columns(client):
    files = {"file": ("bad.csv", "title\nfoo\nbar\n", "text/csv")}
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post("/api/import/csv", files=files)
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "content" in (detail.get("message") or "")


def test_csv_import_dedupes_on_reupload(client):
    csv_text = (
        "external_id,title,content\n"
        "csv-dup,重复测试,重复内容\n"
    )
    files = {"file": ("dup.csv", csv_text, "text/csv")}
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    first = client.post("/api/import/csv", files=files)
    assert first.status_code == 200
    assert first.json()["accepted"] == 1
    second = client.post("/api/import/csv", files=files)
    assert second.status_code == 200
    body = second.json()
    assert body["accepted"] == 0
    assert body["duplicate"] == 1


def test_csv_import_records_audit(client):
    csv_text = "title,content\naudit-csv,审计测试\n"
    files = {"file": ("audit.csv", csv_text, "text/csv")}
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    client.post("/api/import/csv", files=files)
    entry = _latest_audit("import.csv")
    assert entry is not None
    assert entry.actor_username == "risk"
    assert entry.result == "success"
    detail = json.loads(entry.detail)
    assert detail["accepted"] == 1


def test_csv_import_partial_row_error_is_reported(client):
    csv_text = (
        "title,content\n"
        "valid-row,有效内容\n"
        ",没有标题的内容\n"
    )
    files = {"file": ("partial.csv", csv_text, "text/csv")}
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post("/api/import/csv", files=files)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["accepted"] == 1
    assert body["rejected"] >= 1
    # Row index for the missing title is 1
    reasons = [e.get("reason") for e in body["errors"]]
    assert "title_required" in reasons or "title is required" in reasons


# ---------- JSON upload ----------

def test_json_import_accepts_top_level_array(client):
    payload = json.dumps([
        {"title": "数组项 1", "content": "内容 1", "external_id": "j-1"},
        {"title": "数组项 2", "content": "内容 2", "external_id": "j-2"},
    ], ensure_ascii=False)
    files = {"file": ("opinions.json", payload, "application/json")}
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post("/api/import/json", files=files)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["accepted"] == 2
    assert body["duplicate"] == 0


def test_json_import_accepts_wrapped_object(client):
    payload = json.dumps({
        "records": [
            {"title": "包装对象项", "content": "包装内容"},
        ]
    }, ensure_ascii=False)
    files = {"file": ("opinions.json", payload, "application/json")}
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post("/api/import/json", files=files)
    assert res.status_code == 200
    assert res.json()["accepted"] == 1


def test_json_import_rejects_invalid_json(client):
    files = {"file": ("bad.json", "this is not json", "application/json")}
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post("/api/import/json", files=files)
    assert res.status_code == 400


def test_json_import_reports_missing_title(client):
    payload = json.dumps([{"content": "no title here"}], ensure_ascii=False)
    files = {"file": ("missing.json", payload, "application/json")}
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post("/api/import/json", files=files)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["accepted"] == 0
    assert body["rejected"] >= 1
    assert any("title" in str(e.get("reason", "")) for e in body["errors"])


def test_json_import_dedupes_on_reupload(client):
    payload = json.dumps([{"title": "JSON 去重", "content": "dup"}], ensure_ascii=False)
    files = {"file": ("dup.json", payload, "application/json")}
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    first = client.post("/api/import/json", files=files)
    assert first.json()["accepted"] == 1
    second = client.post("/api/import/json", files=files)
    body = second.json()
    assert body["accepted"] == 0
    assert body["duplicate"] == 1


# ---------- demo bundle ----------

def test_demo_import_loads_bundled_samples(client):
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post("/api/import/demo")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["format"] == "demo"
    assert body["accepted"] == 9  # 5 CSV + 4 JSON
    assert body["duplicate"] == 0

    db = Session(_engine())
    try:
        items = db.query(OpinionItem).all()
    finally:
        db.close()
    titles = {it.title for it in items}
    assert any("新一代产品" in t for t in titles)
    assert any("权威媒体" in t for t in titles)

    entry = _latest_audit("import.demo")
    assert entry is not None
    assert entry.result == "success"
    detail = json.loads(entry.detail)
    assert detail["csv_accepted"] == 5
    assert detail["json_accepted"] == 4


def test_demo_import_reupload_reports_duplicates(client):
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    first = client.post("/api/import/demo")
    assert first.json()["accepted"] == 9
    second = client.post("/api/import/demo")
    body = second.json()
    assert body["accepted"] == 0
    assert body["duplicate"] == 9


def test_import_demo_blocks_non_importer(client):
    client.post("/api/auth/login", json={"username": "handler", "password": "handler123"})
    res = client.post("/api/import/demo")
    assert res.status_code == 403


# ---------- web UI page ----------

def test_import_page_renders_for_risk_control(client):
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/web/import")
    assert res.status_code == 200
    body = res.text
    assert "CSV" in body
    assert "JSON" in body
    assert "演示数据" in body


def test_import_page_403_for_handler(client):
    client.post("/api/auth/login", json={"username": "handler", "password": "handler123"})
    res = client.get("/web/import")
    assert res.status_code == 403
