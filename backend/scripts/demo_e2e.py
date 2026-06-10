"""End-to-end course-demo verification (Phase 10 / Issue 12).

Walks the full demo path against a running dev server:

    1. admin    -> trigger built-in static demo fetch
    2. admin    -> load the bundled CSV / JSON sample bundle
    3. risk     -> list pending alerts, confirm one, ignore one
    4. risk     -> convert the confirmed alert to a ticket and assign 'handler'
    5. handler  -> complete the ticket with a handling result
    6. risk     -> archive the completed ticket
    7. risk     -> queue an Excel report task
    8. risk     -> poll until the task is completed (background worker)
    9. risk     -> download the .xlsx file
   10. admin    -> hit the dashboard summary
   11. auditor  -> read the audit log, filter by action, dump highlights

Compared to ``tests/test_e2e_happy_path.py`` this script targets a real
running server (``uvicorn app.main:app``) rather than the in-process
``TestClient`` - useful for demos and for verifying that the
``BackgroundTasks`` worker actually completes when the request session
is torn down before the worker fires.

Usage::

    # In one terminal:
    uvicorn app.main:app --reload --port 8000

    # In another:
    python scripts/demo_e2e.py                # defaults to http://localhost:8000
    python scripts/demo_e2e.py --base-url http://localhost:8000
    python scripts/demo_e2e.py --report-name "演示报告 2026"
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx


# Demo credentials are the ones bootstrap creates on first boot. If
# you changed BOOTSTRAP_ADMIN_PASSWORD in .env you need to override
# the admin credentials with --admin-password.
DEFAULT_USERS: dict[str, tuple[str, str]] = {
    "admin":   ("admin",   "admin123"),
    "risk":    ("risk",    "risk123"),
    "handler": ("handler", "handler123"),
    "auditor": ("auditor", "auditor123"),
}

DEFAULT_REPORT_TITLE = "演示路径 - 高风险周报"


# ---------- ANSI styling (no extra dep) ----------

USE_COLOR = sys.stdout.isatty()
def _c(code: str, text: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if USE_COLOR else text

def info(msg: str) -> None:
    print(_c("36", "[•]") + " " + msg)

def ok(msg: str) -> None:
    print(_c("32", "[✓]") + " " + msg)

def warn(msg: str) -> None:
    print(_c("33", "[!]") + " " + msg)

def fail(msg: str) -> None:
    print(_c("31", "[✗]") + " " + msg)


@dataclass
class DemoContext:
    base_url: str
    users: dict[str, tuple[str, str]]
    report_title: str
    poll_timeout_s: float = 30.0
    poll_interval_s: float = 0.5


# ---------- HTTP helpers ----------


class DemoError(RuntimeError):
    """Raised when an API call returns an unexpected response."""


def _login(client: httpx.Client, username: str, password: str) -> None:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    if res.status_code != 200:
        raise DemoError(f"login as {username} failed: HTTP {res.status_code} {res.text}")


def _logout(client: httpx.Client) -> None:
    # Logout always returns 200 even if there's no active session.
    client.post("/api/auth/logout")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise DemoError(message)


def _expect_json(res: httpx.Response, what: str) -> Any:
    if res.status_code >= 400:
        raise DemoError(f"{what} -> HTTP {res.status_code} {res.text}")
    try:
        return res.json()
    except ValueError as e:
        raise DemoError(f"{what} -> non-JSON response: {e!r} {res.text[:200]}") from e


# ---------- demo steps ----------


def _resolve_static_source_id(client: httpx.Client) -> int:
    """Find the built-in 'demo_static' data source id by listing sources."""
    body = _expect_json(client.get("/api/datasources"), "list datasources")
    for row in body:
        if row.get("code") == "demo_static":
            return int(row["id"])
    raise DemoError(
        "static demo source not found - did you run scripts/seed_data.py first?"
    )


def _resolve_handler_id(client: httpx.Client) -> int:
    """Look up the handler user's id by listing users (admin-only call)."""
    body = _expect_json(client.get("/api/users"), "list users")
    for row in body:
        if row.get("username") == "handler":
            return int(row["id"])
    raise DemoError("handler user not found")


def _wait_for_report(
    client: httpx.Client,
    task_id: int,
    *,
    timeout_s: float,
    interval_s: float,
) -> dict[str, Any]:
    """Poll ``/api/reports/{id}`` until the task is no longer pending/generating."""
    deadline = time.monotonic() + timeout_s
    last_status: Optional[str] = None
    while time.monotonic() < deadline:
        body = _expect_json(client.get(f"/api/reports/{task_id}"), "poll report")
        status = body.get("status")
        if status != last_status:
            info(f"  report task {task_id}: status={status}")
            last_status = status
        if status in {"completed", "failed"}:
            return body
        time.sleep(interval_s)
    raise DemoError(
        f"report task {task_id} did not finish within {timeout_s:.1f}s (last status={last_status})"
    )


def run_demo(ctx: DemoContext) -> int:
    """Walk the full demo path. Returns 0 on success, non-zero on error."""
    info(f"Targeting {ctx.base_url}")
    # ``trust_env=False`` so the script ignores ambient HTTP/SOCKS proxy
    # env vars (the dev server runs on localhost - it should not go
    # through whatever proxy the operator has configured for the open
    # internet, and httpx will refuse a SOCKS proxy without an extra
    # dependency installed anyway).
    client = httpx.Client(base_url=ctx.base_url, timeout=15.0, trust_env=False)

    try:
        # ----- step 1: admin pulls static demo + bundled CSV/JSON -----
        info("Step 1: admin fetches the built-in static demo")
        _login(client, *ctx.users["admin"])
        source_id = _resolve_static_source_id(client)
        handler_id = _resolve_handler_id(client)
        fetch_body = _expect_json(
            client.post(f"/api/datasources/{source_id}/fetch"),
            "static demo fetch",
        )
        ok(f"  fetch accepted={fetch_body['accepted']} "
           f"duplicate={fetch_body['duplicate']}")

        info("Step 2: admin loads the bundled CSV + JSON sample bundle")
        import_body = _expect_json(client.post("/api/import/demo"), "import demo")
        ok(f"  import accepted={import_body['accepted']} "
           f"duplicate={import_body['duplicate']}")

        # ----- step 2: risk reviews alerts and triages -----
        info("Step 3: risk_control reviews pending alerts")
        _logout(client)
        _login(client, *ctx.users["risk"])
        alerts_body = _expect_json(
            client.get("/api/alerts?status=pending&limit=50"),
            "list pending alerts",
        )
        _assert(
            alerts_body["total"] >= 2,
            f"expected >=2 pending alerts after demo seeding, got {alerts_body['total']}",
        )
        ok(f"  pending alerts: {alerts_body['total']}")

        pending_ids = [it["id"] for it in alerts_body["items"]]
        confirmed_id = pending_ids[0]
        ignored_id = pending_ids[1]

        info(f"  confirm alert #{confirmed_id}, ignore alert #{ignored_id}")
        _expect_json(client.post(f"/api/alerts/{confirmed_id}/confirm"), "confirm alert")
        _expect_json(
            client.post(
                f"/api/alerts/{ignored_id}/ignore",
                json={"reason": "演示路径中确认为可忽略"},
            ),
            "ignore alert",
        )

        # ----- step 3: convert to ticket + handler completes -----
        info("Step 4: risk_control converts the confirmed alert to a ticket")
        ticket_body = _expect_json(
            client.post(
                "/api/tickets/from-alert",
                json={"alert_id": confirmed_id, "assignee_id": handler_id},
            ),
            "create ticket",
        )
        ticket_id = ticket_body["id"]
        ok(f"  ticket #{ticket_id} created and assigned to handler")

        info("Step 5: handler completes the ticket")
        _logout(client)
        _login(client, *ctx.users["handler"])
        _expect_json(
            client.post(
                f"/api/tickets/{ticket_id}/complete",
                json={"handling_result": "演示路径中已处置并归档"},
            ),
            "complete ticket",
        )
        ok(f"  ticket #{ticket_id} marked completed")

        info("Step 6: risk_control archives the completed ticket")
        _logout(client)
        _login(client, *ctx.users["risk"])
        _expect_json(
            client.post(f"/api/tickets/{ticket_id}/archive"),
            "archive ticket",
        )
        ok(f"  ticket #{ticket_id} archived")

        # ----- step 4: report -----
        info("Step 7: risk_control queues an Excel report task")
        report_create = _expect_json(
            client.post(
                "/api/reports",
                json={
                    "title": ctx.report_title,
                    "description": "Phase 10 端到端演示生成的报告",
                    "risk_level": "high",
                },
            ),
            "create report",
        )
        task_id = report_create["id"]
        ok(f"  report task #{task_id} created in status={report_create['status']}")

        info("Step 8: poll until the worker finishes")
        finished = _wait_for_report(
            client, task_id,
            timeout_s=ctx.poll_timeout_s,
            interval_s=ctx.poll_interval_s,
        )
        _assert(
            finished["status"] == "completed",
            f"report task #{task_id} ended in status={finished['status']!r}: "
            f"{finished.get('error_message') or ''}",
        )
        ok(f"  report task #{task_id} completed "
           f"(matched={finished.get('matched_count')}, "
           f"size={finished.get('file_size_bytes')} bytes)")

        info("Step 9: download the generated .xlsx")
        download = client.get(f"/api/reports/{task_id}/download")
        if download.status_code != 200:
            raise DemoError(
                f"download failed: HTTP {download.status_code} {download.text[:200]}"
            )
        ct = download.headers.get("content-type", "")
        _assert(
            ct.startswith("application/vnd.openxmlformats"),
            f"unexpected content-type: {ct}",
        )
        ok(f"  downloaded {len(download.content)} bytes (content-type={ct})")

        # ----- step 5: dashboard + audit log -----
        info("Step 10: admin opens the dashboard summary")
        _logout(client)
        _login(client, *ctx.users["admin"])
        summary = _expect_json(client.get("/api/dashboard/summary"), "dashboard summary")
        ok(
            f"  opinion_total={summary.get('opinion_total')}, "
            f"alerts(confirmed={summary.get('alerts_confirmed')}, "
            f"ignored={summary.get('alerts_ignored')}), "
            f"tickets(archived={summary.get('tickets_archived')})"
        )

        info("Step 11: auditor reads the audit log")
        _logout(client)
        _login(client, *ctx.users["auditor"])
        log_body = _expect_json(
            client.get("/api/audit-logs?limit=200"),
            "list audit logs",
        )
        ok(f"  audit log rows: {log_body['total']}")

        # Print one row per important action to make a demo screen useful.
        for action in (
            "auth.login", "datasource.fetch", "import.demo",
            "alert.confirm", "alert.ignore",
            "ticket.create", "ticket.complete", "ticket.archive",
            "report.create", "report.download",
        ):
            res = client.get(f"/api/audit-logs?action={action}&limit=1")
            data = _expect_json(res, f"audit list filtered by {action}")
            if data["total"] > 0:
                row = data["items"][0]
                ok(f"  {action:<22} actor={row.get('actor_username')!s:<10} "
                   f"target={row.get('target_id')!s} result={row.get('result')}")
            else:
                warn(f"  {action} -> 0 rows (something earlier in the demo skipped this)")

        ok("Demo path completed end-to-end.")
        return 0

    except DemoError as e:
        fail(str(e))
        return 1
    finally:
        _logout(client)
        client.close()


# ---------- CLI ----------


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the running dev server (default: %(default)s)",
    )
    p.add_argument(
        "--report-name",
        default=DEFAULT_REPORT_TITLE,
        help="Title to use for the generated report task",
    )
    p.add_argument("--admin-username",   default=DEFAULT_USERS["admin"][0])
    p.add_argument("--admin-password",   default=DEFAULT_USERS["admin"][1])
    p.add_argument("--risk-username",    default=DEFAULT_USERS["risk"][0])
    p.add_argument("--risk-password",    default=DEFAULT_USERS["risk"][1])
    p.add_argument("--handler-username", default=DEFAULT_USERS["handler"][0])
    p.add_argument("--handler-password", default=DEFAULT_USERS["handler"][1])
    p.add_argument("--auditor-username", default=DEFAULT_USERS["auditor"][0])
    p.add_argument("--auditor-password", default=DEFAULT_USERS["auditor"][1])
    p.add_argument(
        "--report-timeout",
        type=float, default=30.0,
        help="Seconds to wait for the background report worker (default: %(default)s)",
    )
    p.add_argument(
        "--report-interval",
        type=float, default=0.5,
        help="Seconds between report status polls (default: %(default)s)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    users = {
        "admin":   (args.admin_username,   args.admin_password),
        "risk":    (args.risk_username,    args.risk_password),
        "handler": (args.handler_username, args.handler_password),
        "auditor": (args.auditor_username, args.auditor_password),
    }
    ctx = DemoContext(
        base_url=args.base_url.rstrip("/"),
        users=users,
        report_title=args.report_name,
        poll_timeout_s=args.report_timeout,
        poll_interval_s=args.report_interval,
    )
    return run_demo(ctx)


if __name__ == "__main__":
    sys.exit(main())
