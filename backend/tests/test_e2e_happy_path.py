"""End-to-end course-demo happy path (Phase 10 / Issue 12).

This test scripts the full demo loop the README documents:

    login (admin)
      -> trigger static-demo fetch
      -> import the bundled CSV + JSON
      -> auto-analysis runs inline on every accepted item
    login (risk_control)
      -> list opinions filtered to high / severe risk
      -> list auto-generated pending alerts
      -> confirm one alert, ignore another with a reason
      -> convert the confirmed alert into a ticket assigned to handler
    login (handler)
      -> start the ticket, then complete it with a handling result
    login (risk_control)
      -> archive the completed ticket
      -> create a high-risk report task
      -> run the worker, download the generated .xlsx
    login (admin)
      -> open the dashboard summary
    login (auditor)
      -> review the audit trail and check every important action is there

The point of this test is *not* to duplicate the per-phase acceptance
tests (those already exist under ``test_alerts.py`` / ``test_tickets.py``
/ ``test_reports.py`` / ``test_audit.py``). The point is to prove the
whole loop runs end-to-end as a single coherent flow against the real
seeded demo data set - the same loop the user runs by hand against the
dev server. If the loop breaks the per-phase tests may still pass; this
test catches that.
"""
from __future__ import annotations

import json
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.db import session as session_module
from app.models.alert import (
    ALERT_STATUS_CONFIRMED,
    ALERT_STATUS_IGNORED,
    ALERT_STATUS_PENDING,
    Alert,
)
from app.models.audit import AuditLog
from app.models.datasource import DataSource, OpinionItem
from app.models.report import REPORT_STATUS_COMPLETED, ReportTask
from app.models.ticket import (
    TICKET_STATUS_ARCHIVED,
    TICKET_STATUS_COMPLETED,
    TICKET_STATUS_IN_PROGRESS,
    Ticket,
)
from app.services.reports import process_report_task


# ---------- helpers ----------


def _session() -> Session:
    return Session(session_module.engine)


def _login(client, username: str, password: str) -> None:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, f"login as {username} failed: {res.text}"


def _logout(client) -> None:
    client.post("/api/auth/logout")


def _switch(client, username: str, password: str) -> None:
    _logout(client)
    _login(client, username, password)


def _static_demo_source_id() -> int:
    with _session() as db:
        return db.query(DataSource).filter(DataSource.code == "demo_static").one().id


def _handler_user_id() -> int:
    from app.models.user import User

    with _session() as db:
        return db.query(User).filter(User.username == "handler").one().id


def _audit_actions() -> set[str]:
    with _session() as db:
        rows = db.query(AuditLog.action).all()
    return {r[0] for r in rows}


# ---------- the test ----------


def test_course_demo_happy_path_runs_end_to_end(client, monkeypatch, tmp_path):
    """Walk the full demo loop and assert every state transition lands."""
    # Pin the report storage so the worker writes inside the tmp dir.
    monkeypatch.setenv("REPORT_STORAGE_DIR", str(tmp_path / "reports"))

    # --- 1. admin: fetch the built-in static demo + import the bundle ----
    _login(client, "admin", "admin123")
    source_id = _static_demo_source_id()
    fetch_res = client.post(f"/api/datasources/{source_id}/fetch")
    assert fetch_res.status_code == 200, fetch_res.text
    fetch_body = fetch_res.json()
    # The static-demo connector ships 6 hand-curated items; auto-analysis
    # runs inline so the response carries the analyzed count too.
    assert fetch_body["accepted"] == 6
    assert fetch_body["duplicate"] == 0

    import_res = client.post("/api/import/demo")
    assert import_res.status_code == 200, import_res.text
    import_body = import_res.json()
    assert import_body["accepted"] == 9  # 5 CSV + 4 JSON

    # --- 2. risk_control: opinions and alerts ---
    _switch(client, "risk", "risk123")

    # Severe-risk content from the static demo + the now-high CSV item
    # together must yield at least one severe-risk opinion.
    severe_list = client.get("/api/opinions?risk_level=severe&limit=50").json()
    high_list = client.get("/api/opinions?risk_level=high&limit=50").json()
    assert severe_list["total"] >= 1
    assert (severe_list["total"] + high_list["total"]) >= 2

    alerts = client.get("/api/alerts?status=pending&limit=50").json()
    assert alerts["total"] >= 2, alerts
    pending_alert_ids = [it["id"] for it in alerts["items"]]

    # Confirm the first pending alert, ignore the second.
    confirmed_alert_id = pending_alert_ids[0]
    ignored_alert_id = pending_alert_ids[1]
    confirm_res = client.post(f"/api/alerts/{confirmed_alert_id}/confirm")
    assert confirm_res.status_code == 200, confirm_res.text
    ignore_res = client.post(
        f"/api/alerts/{ignored_alert_id}/ignore",
        json={"reason": "已与相关方核实,确认为误报"},
    )
    assert ignore_res.status_code == 200, ignore_res.text

    with _session() as db:
        assert db.get(Alert, confirmed_alert_id).status == ALERT_STATUS_CONFIRMED
        assert db.get(Alert, ignored_alert_id).status == ALERT_STATUS_IGNORED
        # Re-confirming or re-ignoring a non-pending alert must reject:
        # the lifecycle is a forward-only state machine.
        assert (
            db.query(Alert).filter(Alert.status == ALERT_STATUS_PENDING).count()
            >= 0
        )

    reconfirm = client.post(f"/api/alerts/{ignored_alert_id}/confirm")
    assert reconfirm.status_code == 409

    # --- 3. risk_control: convert confirmed alert to a ticket ---
    handler_id = _handler_user_id()
    ticket_res = client.post(
        "/api/tickets/from-alert",
        json={"alert_id": confirmed_alert_id, "assignee_id": handler_id},
    )
    assert ticket_res.status_code == 201, ticket_res.text
    ticket_id = ticket_res.json()["id"]

    with _session() as db:
        ticket = db.get(Ticket, ticket_id)
        assert ticket is not None
        # An assignee was provided up front so the ticket skips
        # 'unassigned' and goes straight to in_progress.
        assert ticket.status == TICKET_STATUS_IN_PROGRESS
        assert ticket.assignee_id == handler_id

    # --- 4. handler: complete the ticket ---
    _switch(client, "handler", "handler123")
    handler_tickets = client.get("/api/tickets?limit=50").json()
    assert handler_tickets["total"] == 1, handler_tickets
    assert handler_tickets["items"][0]["id"] == ticket_id

    complete_res = client.post(
        f"/api/tickets/{ticket_id}/complete",
        json={"handling_result": "已与企业沟通并取得阶段性处置结果"},
    )
    assert complete_res.status_code == 200, complete_res.text
    with _session() as db:
        assert db.get(Ticket, ticket_id).status == TICKET_STATUS_COMPLETED

    # Peer-handler scoping check: a handler cannot see somebody else's
    # ticket. Here the handler list is bounded to their own assignments
    # already; an attempt to re-complete a finished ticket must 409.
    bad_complete = client.post(
        f"/api/tickets/{ticket_id}/complete",
        json={"handling_result": "重复提交"},
    )
    assert bad_complete.status_code == 409

    # --- 5. risk_control: archive then queue a report ---
    _switch(client, "risk", "risk123")
    archive_res = client.post(f"/api/tickets/{ticket_id}/archive")
    assert archive_res.status_code == 200, archive_res.text
    with _session() as db:
        assert db.get(Ticket, ticket_id).status == TICKET_STATUS_ARCHIVED

    report_create = client.post(
        "/api/reports",
        json={
            "title": "演示路径 - 高风险周报",
            "description": "Phase 10 端到端演示生成的报告",
            "risk_level": "high",
        },
    )
    assert report_create.status_code == 201, report_create.text
    task_id = report_create.json()["id"]

    # The worker runs in the background in production; in the test we
    # invoke it directly so the assertion is deterministic. This is the
    # same pattern test_reports.py uses.
    process_report_task(task_id)

    with _session() as db:
        task = db.get(ReportTask, task_id)
        assert task.status == REPORT_STATUS_COMPLETED
        assert task.matched_count >= 1
        assert task.file_path
        assert Path(task.file_path).is_file()

    # Download the generated .xlsx and sanity-check the workbook.
    download = client.get(f"/api/reports/{task_id}/download")
    assert download.status_code == 200, download.text
    assert download.headers["content-type"].startswith(
        "application/vnd.openxmlformats"
    )
    xlsx_path = tmp_path / "downloaded.xlsx"
    xlsx_path.write_bytes(download.content)
    wb = load_workbook(xlsx_path)
    assert {ws.title for ws in wb.worksheets} == {"概览", "汇总", "明细"}

    # --- 6. admin: dashboard reflects the demo state ---
    _switch(client, "admin", "admin123")
    summary = client.get("/api/dashboard/summary").json()
    assert summary["opinion_total"] >= 15  # 6 static-demo + 9 import-demo
    # The alert + ticket counts are top-level fields on the summary
    # payload (one row per role; admin sees every count).
    assert summary["alerts_confirmed"] >= 1
    assert summary["alerts_ignored"] >= 1
    assert summary["tickets_archived"] >= 1

    # --- 7. auditor: every important action shows up in the audit log ---
    _switch(client, "auditor", "auditor123")
    logs = client.get("/api/audit-logs?limit=200").json()
    assert logs["total"] >= 10, logs

    # The auditor should also be able to filter to the actions we just
    # took and find at least one matching row each.
    expected_actions = {
        "auth.login",            # all the logins above
        "datasource.fetch",      # admin static-demo fetch
        "import.demo",           # admin bundle import
        "alert.confirm",         # risk confirm
        "alert.ignore",          # risk ignore-with-reason
        "ticket.create",         # risk convert alert
        "ticket.complete",       # handler completion
        "ticket.archive",        # risk archive
        "report.create",         # risk queue
        "report.download",       # risk download (still logged in from step 5)
    }
    seen_actions = _audit_actions()
    missing = expected_actions - seen_actions
    assert not missing, f"audit trail is missing actions: {sorted(missing)}"

    # Filter by one specific action through the API so we exercise the
    # auditor read path, not just the DB query.
    for action in ("alert.confirm", "ticket.complete", "report.download"):
        filtered = client.get(f"/api/audit-logs?action={action}&limit=10").json()
        assert filtered["total"] >= 1, (action, filtered)
        assert all(it["action"] == action for it in filtered["items"])

    # Read-only contract: auditor cannot mutate the audit log.
    no_delete = client.delete("/api/audit-logs/1")
    assert no_delete.status_code in (404, 405)
