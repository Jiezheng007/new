# 舆情风控管理系统 MVP

FastAPI + SQLAlchemy + Jinja2 modular monolith implementing the public-opinion
risk-control MVP. See `PRD.md`, `requirement.md`, and `PRD.issue.md` for the
full product, architecture, and issue plan; `generated-issues.md` is the
phased issue list (current scope: Phase 10 — Course-demo happy path).

## Phase 10 status — Course-demo happy path

Phases 1–9 built every piece the PRD calls for (auth shell, user
management, rules, ingestion, NLP + scoring, alerts, tickets,
dashboard, reports, audit). Phase 10 ties the whole loop together
and proves the architecture decisions through working behaviour:

- **Bundled demo data refresh** (`backend/static/demo/sample_opinions.{csv,json}`):
  the CSV was rewritten to use Chinese punctuation inside the
  content field so the CSV parser no longer splits long sentences
  on the row delimiter. `csv-004` now carries a clearly negative,
  sensitive-keyword-rich payload (`某公司被通报严重违规`,
  `重大安全隐患`, `数据泄露事故`, `查处`), so the import-only path
  also produces a high/severe-risk alert without needing the
  built-in `static_demo` source.
- **End-to-end happy-path test**
  (`backend/tests/test_e2e_happy_path.py`): one test walks
  login → static-demo fetch → bundled CSV/JSON import → auto-analysis
  → alert confirm/ignore → ticket convert → handler completes →
  risk_control archives → report queue → background worker → xlsx
  download → admin dashboard → auditor reviews the full audit
  trail. The test asserts at every state transition and verifies
  that every expected `auth.login` / `datasource.fetch` /
  `import.demo` / `alert.*` / `ticket.*` / `report.*` audit row
  is present.
- **Scripted demo verifier** (`backend/scripts/demo_e2e.py`): a
  CLI version of the same loop, but it talks to a real running
  `uvicorn` instance over HTTP instead of the in-process
  `TestClient`. Useful when demoing to a live audience and when
  validating that the report-center `BackgroundTasks` worker
  actually completes after the request session is torn down.
  Each step prints a single coloured line so the demo terminal is
  easy to follow:

      python scripts/demo_e2e.py --base-url http://localhost:8000

- **Architecture in the loop**: the happy path exercises every
  architecture decision the PRD lists:
  - *event-driven*: confirming an alert -> creating a ticket ->
    completing a ticket -> queuing a report each writes an audit
    event picked up by the auditor view at the end.
  - *pipeline-filter*: `static_demo` + CSV + JSON all flow through
    the shared `ingest_records` → cleaner → dedup → `analyze_batch`
    funnel; the same code path produces the same opinion-item
    shape regardless of source.
  - *data-centred / SQLAlchemy*: every state transition lands in
    the database before the response returns, and the auditor
    view at the end reads it back through the same ORM the writers
    used.

Test totals: **290 / 290 green** (289 from Phases 1–9 + 1 new
end-to-end test for Phase 10).

## Phase 9 status — Audit log review

Phases 1–8 already write audit rows for every important state change
(login, user/role, data-source, rule, alert, ticket, report create /
download). Phase 9 surfaces those rows: an auditor-facing list page
with filters, an API, and the missing `auth.login` / `auth.logout`
hooks so the login domain shows up alongside the rest.

- **Login auditing** (`app/api/auth.py`): every login attempt now
  writes one `auth.login` row. Success carries the user id; failure
  is split into `unknown_user`, `user_disabled`, and `bad_password`
  in the detail blob so an operator can tell brute-force from a
  disabled-account ping. A best-effort `auth.logout` row is written
  when the cookie still resolves to a user.
- **Audit service** (`app/services/audit.py`): the existing
  `record_audit` writer is unchanged. New read helpers
  (`list_audit_logs`, `get_audit_log`, `audit_log_facets`) own the
  filter translation so the API stays thin. Filters are
  AND-combined: `action`, `target_type`, `target_id`, `actor`
  (matches username or numeric id), `result`, `start_at` / `end_at`,
  and `q` (substring against the JSON `detail`).
- **API** (`/api/audit-logs`): paginated list, `facets` for distinct
  dropdown values, and `{id}` detail. The router is read-only by
  contract — a regression test enumerates the routes and asserts no
  POST / PUT / PATCH / DELETE exists. Reading the log is itself
  *not* audited; doing so would produce an unbounded
  `audit.list → audit row → audit.list` recursion.
- **Authorization**: only `admin` and `auditor` can read. Every
  other role (risk_control, handler, viewer) gets a 403 on every
  endpoint, including `facets` and detail.
- **Web UI** (`/web/audit`): server-rendered page with the same
  panel/form/table shape as the other backend-management pages.
  Action and target dropdowns are populated from `/facets` so a new
  audit action shows up automatically without a UI patch. Detail
  blobs are JSON-pretty-printed in a dialog when an operator clicks
  a row. The page sits in the auditor + admin navs only.
- **Demo path** (continues from Phase 8): admin fetches data →
  ingestion + analysis + alert + ticket + report rows are written →
  auditor opens `/web/audit`, filters by `action=report.download`,
  expands a row, and sees the full IP / actor / target / detail
  trail. Login failures (bad password, unknown user) and successes
  show up alongside.

Test totals: **289 / 289 green** (262 from Phases 1–8 + 27 new for Phase 9).

## Phase 8 status — Report center

Phases 1–7 built the shell, users, rules, ingestion, analysis, alerts,
tickets, and the workbench dashboard. Phase 8 closes the demo loop with
an asynchronous Excel report center: risk-control users can queue a
report against any filter combination, watch it run in the background,
and download the resulting `.xlsx` once it lands.

- **`ReportTask` ORM model** (`app/models/report.py`): one row per
  queued report, with a four-state machine
  `pending → generating → completed | failed` and a snapshot of the
  filters (`start_at`, `end_at`, `risk_level`, `subject_keyword`),
  matched / included counts, file path / size, and a creator snapshot
  so the row still tells a coherent story if the user is later
  disabled. `started_at` / `completed_at` / `error_message` round out
  the lifecycle columns.
- **Service** (`app/services/reports.py`): one place owns the filter
  translation, the worker, and the Excel writer. The
  `_build_base_query` helper is shared by the list endpoint, the
  worker, and the test helper so the report is, by definition, the
  filtered list rendered into a file. `_normalize_filters` rejects
  bad combinations (start > end, unknown risk level) at the service
  boundary with a typed `ReportInputError`.
- **Async worker** (`process_report_task`): the API schedules the
  worker with FastAPI's `BackgroundTasks`. The worker opens its own
  short-lived `SessionLocal` (the request-scoped session is already
  closed by the time a BackgroundTask fires) and walks
  `pending → generating → completed` or `→ failed`. Re-running on
  a row already in `generating` is a no-op so a duplicate background
  fire cannot double-write the file.
- **Excel writer**: 3-sheet workbook via `openpyxl` —
  概览 (one-row filter summary + count-by-risk), 汇总 (count-by-source /
  -day / -sentiment), 明细 (one row per matched opinion with all the
  columns the user can see in the opinion list, with explanation text
  inlined from the Phase 4 factors dict). Columns are auto-sized in a
  CJK-aware way (Chinese chars count as 2× wide). File path defaults
  to a sibling of the SQLite DB so a workspace copy stays
  self-contained; `REPORT_STORAGE_DIR` env override is honoured (the
  test suite uses this for isolation).
- **API** (`/api/reports`): list (`status` filter, `creator_id`),
  detail, `summary` (counts by status), `POST` to create, and
  `GET .../download` to stream the generated `.xlsx`. Read access
  for admin / risk_control / auditor / viewer; write access for
  admin / risk_control only. Handler is blocked from every endpoint
  (read or write). A pending / generating / failed task returns 409
  on download; a completed task whose file is missing returns 410
  (the operator can see what happened from the audit log).
- **Audit trail**: every state change writes an `AuditLog` row with
  actor, action (`report.create` / `report.download`), target_id,
  result (`success` or `failure`), IP, and a JSON detail. A
  `failure` row is written for: invalid filters, missing / not-ready
  task, and missing file — so an operator can later trace
  "who tried to fetch what" without losing context.
- **Web UI** (`/web/reports`): server-rendered page with two panels —
  "生成新报告" (filter form) and "报告任务" (list with status pill,
  matched count, download link). A detail dialog shows the full
  filter summary, lifecycle timestamps, file size, and a download
  button when the task is `completed`. The page polls every 5
  seconds while any visible task is still `pending` / `generating`
  so an operator who walks away with a long task in flight still
  sees the transition.
- **Demo path** (continues from Phase 6): admin fetches the static
  demo → 2 pending alerts → risk_control confirms one → converts to
  ticket → handler completes → risk_control archives. Phase 8
  extends this with: risk_control creates a report task
  (`risk_level=high`, optional time range), the background worker
  produces the `.xlsx` in a fraction of a second, the list page
  shows a `已生成` link, the user downloads the file, and the
  audit log records both the create and the download.

Test totals: **262 / 262 green** (230 from Phases 1–7 + 32 new for Phase 8).

## Phase 7 status — Workbench dashboard

Phases 1–6 built the shell, users, rules, ingestion, analysis, alerts,
and the ticket lifecycle. Phase 7 layers a workbench dashboard on top
of the data wired up by the earlier phases: a one-screen overview that
risk-control can glance at to gauge the current state of the queue.

- **Workbench panel** (`/web/workbench`): KPI cards (opinion total,
  positive / neutral / negative breakdown, alert pressure, open
  tickets) plus a 7-day trend chart and a "latest alerts" / "my
  open tickets" feed. Server-rendered through the same Jinja shell
  so no new client-side framework is added.
- **`/api/dashboard/summary`**: a single endpoint that aggregates
  the metrics the panel needs (counts + trend buckets + latest
  items) so the page can render in one round trip.
- **Role-aware**: every role lands on `/web/workbench` after login;
  the cards adapt to what that role is allowed to see (handler
  sees "my tickets" instead of the full ticket pipeline).

Test totals: **230 / 230 green** (209 from Phases 1–6 + 21 new for Phase 7).

## Phase 6 status — Ticket lifecycle

Phase 1 built the authenticated shell; Phase 2 added user & role
management; Phase 3 layered risk-rule configuration, public-data
ingestion, and CSV / JSON import; Phase 4 wired the analysis + risk
scoring pipeline; Phase 5 turned high / severe-risk items into a
first-class alert lifecycle. Phase 6 closes the loop with a full ticket
workflow on top of the confirmed alerts from Phase 5:

- **`Ticket` ORM model** (`app/models/ticket.py`): one row per
  confirmed alert, unique on `alert_id`. Four states — `unassigned`,
  `in_progress`, `completed`, `archived` — plus snapshot fields
  (risk level / score / title / description) and audit-friendly
  per-transition columns (`assignee_*`, `started_at`, `completed_*`,
  `archived_*`, `created_by_*`). The `OpinionItem` is also FK-linked
  so the ticket still tells a coherent story if its source alert
  is later re-computed.
- **State machine** (`app/services/tickets.py`):
  - `create_ticket_from_alert` — only `confirmed` alerts can be
    converted (pending / ignored are rejected with HTTP 409).
    Optional `assignee_id` jumps the ticket straight to
    `in_progress`; otherwise it starts in `unassigned`.
  - `assign_ticket` — legal from `unassigned` (→ `in_progress`),
    `in_progress`, or `completed`. `archived` rejects with 409.
  - `start_ticket` — handler accept. `completed` / `archived`
    reject; assigned handler enforced both at API and service
    layer so direct callers cannot bypass.
  - `complete_ticket` — handler submits a non-blank
    `handling_result` (≥ 2 chars). `in_progress` only.
  - `archive_ticket` — risk-control closes the loop from
    `completed` only. Already-archived is a no-op.
- **API** (`/api/tickets`): list (filters: status, level, assignee,
  keyword, time range), detail, `POST /from-alert`, `POST .../assign`,
  `POST .../start`, `POST .../complete`, `POST .../archive`,
  `GET .../summary`. Read access for admin / risk_control / handler
  (handler is auto-scoped to their own tickets) / auditor. Write
  access for admin / risk_control; handler can only `start` /
  `complete` on their own assignments. Viewers are blocked from
  every endpoint.
- **Audit trail**: every state change writes an `AuditLog` row with
  actor, action (`ticket.create` / `ticket.assign` / `ticket.start`
  / `ticket.complete` / `ticket.archive`), target_id, result, IP
  address, and a JSON detail (alert id, opinion id, risk level /
  score, assignee, status). Invalid-state attempts and assignment
  to a non-handler also write a `failure` audit row before the
  error response.
- **Web UI** (`/web/tickets`): server-rendered list page with the
  same filter form as alerts, a status pill for the ticket state,
  a detail dialog with full opinion + alert snapshot, an "assign /
  re-assign" dialog (manager-only), a "submit handling result"
  dialog (handler-only), and an "archive" action. The
  `/web/alerts` detail dialog surfaces a "转为工单" shortcut that
  deep-links into `/web/tickets?from_alert=<id>` and opens the
  create dialog pre-populated with the alert's opinion title.
- **Demo path** (continues from Phase 5): admin fetches the static
  demo → 2 pending alerts → risk_control confirms one → risk_control
  converts to ticket and assigns `handler` → handler completes with
  a result → risk_control archives. The full chain is end-to-end
  exerciseable in the UI without database edits.

Test totals: **209 / 209 green** (171 from Phases 1–5 + 38 new for Phase 6).

## Phase 5 status — Alert lifecycle

Phase 1 built the authenticated shell; Phase 2 added user & role
management; Phase 3 layered risk-rule configuration, public-data
ingestion, and CSV / JSON import; Phase 4 wired the analysis + risk
scoring pipeline on top. Phase 5 turns the high / severe-risk items
from Phase 4 into a first-class alert lifecycle that risk-control users
operate on:

- **`Alert` ORM model** (`app/models/alert.py`): one row per high /
  severe-risk opinion, unique on `opinion_item_id`. Three states —
  `pending`, `confirmed`, `ignored` — plus a snapshot of the
  Phase 4 score explanation so the alert still tells a coherent story
  if the underlying analysis row is later re-computed.
- **Auto-creation hook** (`app/services/alerts.py` +
  `app/services/analysis.py`): `analyze_opinion` calls
  `ensure_alert_for_analysis` after every successful analysis. A new
  `pending` row is inserted iff the analysis succeeded, the level is
  `high` or `severe`, and no alert already exists for that opinion.
  This means `manual_fetch`, `import/csv`, `import/json`,
  `import/demo`, `POST /api/opinions/{id}/analyze`, and
  `POST /api/opinions/analyze-pending` all auto-create alerts through
  the same funnel — no extra wiring in each call site.
- **State machine**: confirmed / ignored alerts reject further
  transitions with HTTP 409. Ignore requires a non-blank reason (≥ 2
  characters); the reason is required at both the pydantic schema and
  the service layer so it cannot be bypassed by a direct call.
- **API** (`/api/alerts`): list (filters: status, level, source,
  keyword, time range), detail, `POST .../confirm`,
  `POST .../ignore`, `GET .../summary`. Read access for admin /
  risk_control / auditor; write access for admin / risk_control only.
  Handlers and viewers are blocked from every endpoint.
- **Audit trail**: every state change writes an `AuditLog` row with
  actor, action (`alert.confirm` / `alert.ignore`), target_id,
  result, IP address, and a JSON detail (`risk_level`, `risk_score`,
  `opinion_item_id`, and — on ignore — the reason). Invalid-state
  attempts also write a `failure` audit row before the 409 response.
- **Web UI** (`/web/alerts`): server-rendered list page with the same
  filter form as the opinion list, a status pill for the alert
  (`pending` / `confirmed` / `ignored`), a detail dialog that shows
  the original opinion + the Phase 4 score explanation, and confirm
  / ignore actions. Auditor and handler / viewer sessions see the
  list + detail in read-only mode; only admin / risk_control see the
  action buttons.
- **Re-uses Phase 4 demo data**: a fresh `seed_data.py` + a static
  demo fetch leaves two `pending` alerts in the DB, ready for
  confirmation / ignoring in the demo.

Test totals: **171 / 171 green** (141 from Phases 1–4 + 30 new for Phase 5).

## Phase 4 status — Analysis + risk scoring

Phase 1 built the authenticated shell; Phase 2 added user & role
management; Phase 3 layered risk-rule configuration, public-data
ingestion, and CSV / JSON import. Phase 4 wires the analysis pipeline on
top: every persisted opinion flows through a replaceable `NlpProvider`,
is scored against the active rules, and is exposed with sentiment, risk
score, level, and a per-factor explanation.

- **NLP provider abstraction** (`app/services/nlp/`): `BaseNlpProvider` +
  `NlpResult` contract. Default implementation is the deterministic
  `KeywordNlpProvider` (Chinese keyword dictionary) so the demo runs
  offline. Pluggable registry reads `NLP_PROVIDER` from settings.
- **Risk scoring** (`app/services/scoring.py`): `compute_risk` combines
  sentiment, severity-weighted sensitive-keyword hits, monitored subject
  hits, source weight, and a recency heat proxy into a 0-100 score,
  capped at 100. The score is then mapped to `low` / `medium` / `high` /
  `severe` using the `RiskThreshold` rows from Phase 3 (so changing
  thresholds re-maps every opinion without re-running NLP).
- **Analysis orchestration** (`app/services/analysis.py`): `analyze_opinion`
  runs NLP + scoring for one item and upserts the `AnalysisResult` row.
  Provider failures are caught and stored as `status='failed'` with an
  `error_message`; the function never raises. `analyze_batch` is used by
  ingestion / import / retry paths. `pending_opinions` returns items
  without a successful analysis for the manual retry endpoint.
- **Auto-analysis on ingestion**: after every successful `manual_fetch`,
  CSV / JSON upload, or `import/demo` call, the API runs `analyze_batch`
  on the freshly inserted `OpinionItem` rows. Failed analyses do not
  block the request — the fetch / import response is unaffected.
- **API + UI**: every `OpinionItemOut` now includes a nested
  `AnalysisResultOut` (sentiment, confidence, provider, score, level,
  status, error_message, factors, explanation, analyzed_at). The list
  endpoint accepts `sentiment`, `risk_level`, and `analysis_status`
  filters. Two new endpoints: `POST /api/opinions/{id}/analyze` and
  `POST /api/opinions/analyze-pending` — both admin / risk_control, both
  write audit rows. The web UI opinion list shows sentiment / level /
  status pills; the detail dialog renders the analysis section with
  factors + a "重新分析" button.
- **Demo data refresh**: the built-in `static_demo` source and the
  bundled CSV / JSON sample data were updated so two of the items
  contain clearly negative content + sensitive keywords (重大, 安全,
  严重, 泄露, 违规, 查处) and a monitored subject (监管部门, 某品牌).
  After a fresh `seed_data.py`, the demo immediately shows a
  high/severe-risk opinion in the list with a full explanation.

Test totals: **141 / 141 green** (114 from Phases 1–3 + 27 new for Phase 4).

## Phase 3 status — Risk rules, ingestion, and import

Phase 1 built the authenticated shell; Phase 2 added user & role management;
Phase 3 layers risk-rule configuration, public-data ingestion, and CSV / JSON
import on top. The audit log table built in Phase 2 is now reused for every
new write path.

- **Risk rules** (`/api/rules/*`, `/web/rules`): admin can manage sensitive
  keywords, subject (monitored) keywords, and the four risk-level thresholds
  (low / medium / high / severe). Threshold updates must be strictly
  increasing. Every change writes an `AuditLog` row.
- **Data sources** (`/api/datasources`, `/web/datasources`): admin can create
  RSS / JSON URL / static-demo sources, set per-source weight, toggle enable,
  and trigger a manual fetch. Fetch runs the configured connector, normalizes
  records into a common opinion-item shape, dedupes by `(source_id,
  content_hash)`, and reports accepted / rejected / duplicate counts.
- **Connectors**: pluggable adapter registry under
  `app/services/connectors/` with a built-in `static_demo` source so the
  course demo works without any external network. RSS uses `feedparser`
  (optional dependency) and `httpx`; missing dependency → clear 502 error.
- **Opinion items** (`/api/opinions`, `/web/opinions`): any role with
  `opinion:read` (admin / risk_control / auditor / viewer) can list and view
  details. Filters: keyword (title / content), source, time range, pagination.
- **CSV / JSON import** (`/api/import/*`, `/web/import`): risk-control can
  upload CSV or JSON, or load the bundled demo bundle (`POST /api/import/demo`).
  Imported rows go through the same ingestion funnel so dedup, audit, and
  source-tracking are identical to RSS / static-demo paths. Per-row errors are
  reported alongside the accepted counts.

Test totals: **114 / 114 green** (50 from Phases 1–2 + 64 new for Phase 3).

## Project layout

```
backend/
  app/
    api/        FastAPI routers (auth, users, rules, datasources, opinions, imports)
    core/       settings + security primitives (password hashing, JWT)
    db/         SQLAlchemy engine, session, Base
    models/     ORM models (User, Role, AuditLog, SensitiveKeyword,
                SubjectKeyword, RiskThreshold, DataSource, OpinionItem,
                AnalysisResult, Alert, Ticket, ReportTask)
    schemas/    pydantic request/response models
    services/   bootstrap, audit logging, connectors, ingestion, importers,
                nlp (provider abstraction + keyword implementation),
                scoring (rule-based risk score), analysis (orchestration),
                alerts (auto-create + confirm / ignore lifecycle),
                tickets (state machine + ticket-per-alert rule),
                reports (async Excel worker + 3-sheet writer)
    web/        Jinja2 page routes
    main.py     create_app() entrypoint
  static/       CSS + JS for the Web UI, bundled demo CSV / JSON samples
  templates/    Jinja2 templates (login, layout, workbench, users, rules,
                datasources, opinions, import, …)
  tests/        pytest suite (auth, web, user_management, rules,
                datasources, imports, analysis, alerts, tickets,
                reports, audit, e2e_happy_path)
  scripts/      dev helpers (seed_data.py, demo_e2e.py — scripted
                happy-path verifier against a live uvicorn server)
  requirements.txt
  pytest.ini
```

## Quick start

```bash
cd backend
python3 -m venv .venv          # or: uv venv .venv --python 3.12
source .venv/bin/activate
pip install -r requirements.txt
pip install feedparser         # optional, only needed for live RSS

# Initialize the database (creates tables, seeds roles, thresholds,
# demo data source, admin and demo users)
python scripts/seed_data.py

# Run the dev server
uvicorn app.main:app --reload --port 8000
```

Open <http://localhost:8000/login> and sign in with `admin / admin123`.
After login:

- `admin` can visit `/web/datasources`, `/web/rules`, `/web/users`,
  `/web/alerts`, `/web/reports`
- `risk` can visit `/web/import`, `/web/opinions`, `/web/alerts`,
  `/web/tickets`, `/web/reports` (and create / download reports)
- `handler` lands on `/web/tickets` (own assignments only) and
  `/web/workbench`
- `auditor` lands on `/web/audit`; can read `/web/alerts`,
  `/web/opinions`, `/web/tickets`, `/web/reports` (read-only)
- `viewer` lands on `/web/workbench` and `/web/reports` (read-only)

## Configuration

Copy `.env.example` to `.env` to override defaults. Notable settings:

| key                          | default                       | purpose                                    |
| ---------------------------- | ----------------------------- | ------------------------------------------ |
| `SECRET_KEY`                 | `dev-only-change-me`          | HS256 signing key — change in production   |
| `DATABASE_URL`               | `sqlite:///./yuqing.db`       | SQLAlchemy database URL                    |
| `ACCESS_TOKEN_TTL_MINUTES`   | `480`                         | JWT lifetime                               |
| `BOOTSTRAP_ADMIN_USERNAME`   | `admin`                       | Admin user created on first boot           |
| `BOOTSTRAP_ADMIN_PASSWORD`   | `admin123`                    | Admin password created on first boot       |
| `NLP_PROVIDER`               | `keyword_nlp`                 | NLP provider name (registry in `app/services/nlp`) |

## API quick reference

Auth:

| method | path                       | auth         | purpose                                |
| ------ | -------------------------- | ------------ | -------------------------------------- |
| POST   | `/api/auth/login`          | none         | username + password → JWT (sets cookie) |
| POST   | `/api/auth/logout`         | none         | clear access_token cookie              |
| GET    | `/api/auth/me`             | bearer/cookie| current user profile + permissions    |

User & role management (admin only):

| method | path                                          | purpose                                |
| ------ | --------------------------------------------- | -------------------------------------- |
| GET    | `/api/users`                                  | list all users with role + permissions |
| POST   | `/api/users`                                  | create user (username, password, role) |
| GET    | `/api/users/{id}`                             | fetch a single user                    |
| PATCH  | `/api/users/{id}`                             | update full_name, role_id, is_active   |
| POST   | `/api/users/{id}/reset-password`              | reset password (admin-set or auto)     |
| GET    | `/api/roles`                                  | list the five MVP roles + permissions  |

Risk rules (writes admin only, reads any logged-in user):

| method | path                                                  | purpose                                          |
| ------ | ----------------------------------------------------- | ------------------------------------------------ |
| GET    | `/api/rules/sensitive-keywords`                       | list sensitive keywords                          |
| POST   | `/api/rules/sensitive-keywords`                       | add a sensitive keyword (severity low→severe)    |
| PATCH  | `/api/rules/sensitive-keywords/{id}`                  | update category / severity / is_active / remark  |
| GET    | `/api/rules/subject-keywords`                         | list monitored subject keywords                  |
| POST   | `/api/rules/subject-keywords`                         | add a subject keyword                            |
| PATCH  | `/api/rules/subject-keywords/{id}`                    | update category / is_active / remark             |
| GET    | `/api/rules/thresholds`                               | list low/medium/high/severe cut-offs             |
| PUT    | `/api/rules/thresholds`                               | replace all four cut-offs (must be strictly ↑)   |

Data sources (admin only):

| method | path                                          | purpose                                              |
| ------ | --------------------------------------------- | ---------------------------------------------------- |
| GET    | `/api/datasources`                            | list all data sources                                |
| POST   | `/api/datasources`                            | create (rss / json_url / static_demo)                |
| GET    | `/api/datasources/{id}`                       | fetch a single source                                |
| PATCH  | `/api/datasources/{id}`                       | update name / url / weight / is_enabled / description|
| POST   | `/api/datasources/{id}/fetch`                 | run the configured connector and persist items       |

Opinion items (any role with `opinion:read`):

| method | path                                | purpose                                                                 |
| ------ | ----------------------------------- | ----------------------------------------------------------------------- |
| GET    | `/api/opinions`                     | list with `q`, `source_id`, `source_code`, `start_at`, `end_at`, `sentiment`, `risk_level`, `analysis_status`, `limit`, `offset` |
| GET    | `/api/opinions/{id}`                | detail of a single opinion item (with nested `analysis`)               |
| POST   | `/api/opinions/{id}/analyze`        | admin / risk_control — re-run NLP + scoring for one item, write audit   |
| POST   | `/api/opinions/analyze-pending`     | admin / risk_control — re-run for items without a successful analysis   |

Alerts (admin / risk_control / auditor read; admin / risk_control write):

| method | path                                | purpose                                                                 |
| ------ | ----------------------------------- | ----------------------------------------------------------------------- |
| GET    | `/api/alerts`                       | list with `status`, `risk_level`, `source_id`, `q`, `start_at`, `end_at`, `limit`, `offset` |
| GET    | `/api/alerts/summary`               | count by status (`pending` / `confirmed` / `ignored` / `total`)         |
| GET    | `/api/alerts/{id}`                  | detail of one alert (with nested opinion summary + trigger explanation) |
| POST   | `/api/alerts/{id}/confirm`          | pending → confirmed; writes audit                                       |
| POST   | `/api/alerts/{id}/ignore`           | pending → ignored; body `{ "reason": "..." }` (≥ 2 chars); writes audit |

Tickets (admin / risk_control / auditor read; admin / risk_control write;
handler scoped to own tickets):

| method | path                                | purpose                                                                 |
| ------ | ----------------------------------- | ----------------------------------------------------------------------- |
| GET    | `/api/tickets`                      | list with `status`, `risk_level`, `assignee_id`, `q`, `start_at`, `end_at`, `limit`, `offset` |
| GET    | `/api/tickets/summary`              | count by status (`unassigned` / `in_progress` / `completed` / `archived` / `total`) |
| GET    | `/api/tickets/{id}`                 | detail of one ticket (with opinion + alert summary)                     |
| POST   | `/api/tickets/from-alert`           | convert a `confirmed` alert into a ticket (optional `assignee_id`); 409 on duplicate / wrong state |
| POST   | `/api/tickets/{id}/assign`          | assign / re-assign a ticket (admin / risk_control only)                 |
| POST   | `/api/tickets/{id}/start`           | handler accept on their own assignment                                  |
| POST   | `/api/tickets/{id}/complete`        | body `{ "handling_result": "..." }` (≥ 2 chars); handler only on own ticket |
| POST   | `/api/tickets/{id}/archive`         | close the loop from `completed` only                                    |

Reports (admin / risk_control / auditor / viewer read; admin / risk_control
write; handler blocked entirely):

| method | path                                | purpose                                                                 |
| ------ | ----------------------------------- | ----------------------------------------------------------------------- |
| GET    | `/api/reports`                      | list with `status`, `creator_id`, `limit`, `offset`                     |
| GET    | `/api/reports/summary`              | count by status (`pending` / `generating` / `completed` / `failed` / `total`) |
| GET    | `/api/reports/{id}`                 | detail of one task (filter snapshot, counts, lifecycle timestamps)      |
| POST   | `/api/reports`                      | body: `title`, `description`, `start_at`, `end_at`, `risk_level`, `subject_keyword`; 201 + schedules the background worker |
| GET    | `/api/reports/{id}/download`        | stream the generated `.xlsx`; 409 if not yet `completed`, 410 if file is gone |

Imports (admin / risk_control):

| method | path                              | purpose                                                                |
| ------ | --------------------------------- | ---------------------------------------------------------------------- |
| POST   | `/api/import/csv`                 | upload a CSV file (`title` + `content` required)                        |
| POST   | `/api/import/json`                | upload a JSON file or POST `payload` field                              |
| POST   | `/api/import/demo`                | load the bundled `static/demo/sample_opinions.{csv,json}`               |

Sample role-protected endpoints (used to prove RBAC end-to-end):

| method | path                            | allowed roles       |
| ------ | ------------------------------- | ------------------- |
| GET    | `/api/protected/admin`          | admin               |
| GET    | `/api/protected/risk-control`   | admin, risk_control |
| GET    | `/api/protected/handler`        | admin, handler      |
| GET    | `/api/protected/auditor`        | admin, auditor      |
| GET    | `/api/protected/dashboard`      | any logged-in user  |

Web UI: `GET /login` (form), `GET /web/<page>` (role-aware pages:
workbench, datasources, rules, import, opinions, alerts, tickets,
reports, users, audit).

## Testing

```bash
cd backend
source .venv/bin/activate
pytest
```

The suite provisions an isolated SQLite database per test run, seeds all five
roles plus a disabled user, the four risk thresholds, the default sensitive +
subject keyword set, the static demo data source, and the CSV / JSON import
sinks. The full suite (290 tests) covers:

- **Auth** (`tests/test_auth.py`): login success / wrong-password / unknown-
  user / disabled-user rejection; logout clears the cookie; `/me` accepts
  valid tokens and rejects missing or invalid ones; password storage uses a
  per-user salt; unauthenticated business APIs return 401; admin can access
  every protected area; risk / handler / auditor / viewer get 200 only on
  their own areas and 403 elsewhere; Bearer token works the same as cookie.
- **Web** (`tests/test_web.py`): login page renders; root redirects
  unauthenticated visitors; role-aware nav contains the right items; cross-
  role page access returns 403; unauthenticated page access returns 401.
- **User management** (`tests/test_user_management.py`): admin can list,
  create, edit, enable/disable, and reset passwords for users; newly created
  users can log in; non-admin roles get 403; unauthenticated requests get
  401; an admin cannot disable or demote themselves; duplicate usernames
  return 409; invalid role_id returns 400; missing user returns 404; every
  state change writes an `AuditLog` row with actor, action, target, result,
  IP, and timestamp (and never the actual password); `/api/roles` returns
  the five MVP roles with permission lists; the `/web/users` page renders
  for admins and returns 403 for non-admins.
- **Risk rules** (`tests/test_rules.py`): admin can create / update /
  toggle sensitive + subject keywords; duplicate keywords return 409;
  non-admin write attempts return 403; threshold PUT requires all four
  levels and strictly increasing scores, otherwise 400; every change writes
  an audit row; the `/web/rules` page renders for admins and returns 403
  for non-admins.
- **Data sources & opinions** (`tests/test_datasources.py`): admin-only
  CRUD on data sources; missing URL for RSS / json_url is rejected with 422;
  manual fetch of the static demo persists 6 items, runs auto-analysis,
  and re-fetch dedupes to 6 duplicates; disabled source returns 400; RSS
  without `feedparser` returns 502 with a clear message; opinion list /
  detail enforce the `opinion:read` role set (handler is blocked); keyword,
  source, and time-range filters work; the `/web/datasources` and
  `/web/opinions` pages render for the right roles and return 403 / 401
  otherwise.
- **Imports** (`tests/test_imports.py`): CSV and JSON uploads validate
  required columns / fields; required-column-missing returns 400; per-row
  validation failures (e.g. blank title) are reported in the response body
  without aborting the import; re-upload dedupes correctly; the bundled
  demo endpoint loads 5 CSV + 4 JSON records on first call and 9 duplicates
  on re-call; every accepted row is auto-analyzed; non-importer roles get
  403; the `/web/import` page renders for risk-control and returns 403 for
  handler.
- **Analysis + risk scoring** (`tests/test_analysis.py`): the
  `KeywordNlpProvider` returns the expected sentiment for positive /
  negative / neutral / unsupported-language text; `compute_risk` produces
  deterministic factor math and respects the per-severity weight table;
  the cap on each factor is enforced and the raw contribution is
  preserved in the persisted factors dict; `analyze_opinion` persists a
  successful `AnalysisResult` row and never raises on provider / language
  failure (records `status='failed'` + `error_message`); `analyze_batch`
  runs against ingestion sample_ids; re-analysis replaces the prior row
  (one-to-one); `pending_opinions` returns items without a successful
  analysis; `POST /api/opinions/{id}/analyze` and
  `POST /api/opinions/analyze-pending` are gated to admin / risk_control,
  write audit rows, and update the level when thresholds change; list
  filters `sentiment` / `risk_level` / `analysis_status` work and validate
  their values; the `/web/opinions` page renders the new sentiment /
  level / status columns + 重新分析 button.
- **Alert lifecycle** (`tests/test_alerts.py`): successful high /
  severe analyses auto-create `pending` alerts (and only those — low /
  medium / failed analyses do not); re-analyzing the same opinion does
  not produce a second alert; threshold change can promote a
  previously-low opinion to high and the next analysis creates an
  alert; list / detail / confirm / ignore endpoints with filters and
  pagination; the ignore reason is required (≥ 2 non-whitespace
  characters, 422 / 400 boundary cases covered); confirmed and ignored
  alerts reject further transitions (409); handler, viewer, and
  auditor are blocked from confirm / ignore; admin and risk_control
  succeed; every state change writes an `AuditLog` row; the
  `/api/alerts/summary` count matches the per-status breakdown; the
  `/web/alerts` page renders for admin / risk_control / auditor and
  returns 403 for handler / viewer.
- **Ticket lifecycle** (`tests/test_tickets.py`): only `confirmed`
  alerts can be converted (pending / ignored return 409); one ticket
  per alert; assignee must be an active handler (admin / disabled
  / non-handler return 400); assign / start / complete / archive
  state machine with 409 on invalid transitions; handler visibility
  is scoped to their own tickets and 403 on a peer's detail; every
  state change writes an `AuditLog` row; the
  `/api/tickets/summary` count matches the per-status breakdown; the
  `/web/tickets` page renders for admin / risk_control / auditor /
  handler and returns 403 for viewer.
- **Report center** (`tests/test_reports.py`): happy-path POST
  creates a task and writes a `report.create` audit row; handler /
  auditor / viewer are blocked from the write endpoint and handler
  is blocked from the read endpoints; pydantic rejects an unknown
  `risk_level` (422) and the service rejects `start_at > end_at`
  with a `report.create` failure audit row; the worker walks
  `pending → generating → completed` and populates
  `matched_count` / `file_size_bytes` / `started_at` /
  `completed_at`; a writer that raises flips the row to `failed`
  with `error_message`; re-running on a `generating` row is a no-op;
  the generated `.xlsx` has the documented three sheets with
  styled headers and detail rows that match the static demo
  dataset; download returns the file with the right MIME type for
  `completed` tasks and 409 / 410 for pending / failed / missing-
  file paths; every download writes a `report.download` audit row
  (success or failure); the `/web/reports` page renders for admin /
  risk_control / auditor / viewer and returns 403 for handler.
- **Audit log** (`tests/test_audit.py`): every important state
  change (login / logout, user, role, data source, rule, alert,
  ticket, report) writes an `AuditLog` row with the right actor,
  action, target, result, IP, and JSON detail; the auditor
  endpoint supports filters (action, target_type, target_id,
  actor, result, time range, free-text `q`) and `facets` returns
  the distinct action / target_type / actor / result values; only
  admin / auditor can read; every other role gets 403; the router
  is read-only by contract (no POST / PUT / PATCH / DELETE); the
  `/web/audit` page renders for admin / auditor and returns 403
  for risk_control / handler / viewer.
- **End-to-end happy path** (`tests/test_e2e_happy_path.py`):
  one test walks the full Phase 10 course demo against the
  in-process `TestClient`: admin login → static-demo fetch
  (asserts 6 accepted) → bundled CSV/JSON import (asserts 9
  accepted) → risk_control confirms one alert and ignores
  another → 409 on re-confirm → ticket from-alert with
  `assignee_id` → handler completes → 409 on re-complete →
  risk_control archives → high-risk report queued → worker
  invoked deterministically → task lands in `completed` →
  download streams a 3-sheet `.xlsx` → admin dashboard reflects
  the demo state → auditor sees the full audit trail with every
  important action present, and a filtered list still returns
  rows for the queried action.

## Demo happy path (no external network needed)

```bash
# 1. Login
curl -c cookies.txt -X POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username": "admin", "password": "admin123"}'

# 2. Fetch the built-in static demo (6 items, auto-analyzed,
#    2 high/severe items auto-create pending alerts)
curl -b cookies.txt -X POST http://localhost:8000/api/datasources/1/fetch

# 3. Load the bundled CSV + JSON sample data (5 + 4 items, auto-analyzed)
curl -b cookies.txt -X POST http://localhost:8000/api/import/demo

# 4. Risk-control user can now see 10+ opinion items with sentiment + risk
curl -b cookies.txt 'http://localhost:8000/api/opinions?limit=20'

# 5. Filter the list to high / severe risk only
curl -b cookies.txt 'http://localhost:8000/api/opinions?risk_level=high'
curl -b cookies.txt 'http://localhost:8000/api/opinions?risk_level=severe'

# 6. List the auto-created alerts
curl -b cookies.txt http://localhost:8000/api/alerts?status=pending

# 7. Confirm the first alert
curl -b cookies.txt -X POST http://localhost:8000/api/alerts/1/confirm

# 8. Ignore the second alert with a reason
curl -b cookies.txt -X POST http://localhost:8000/api/alerts/2/ignore \
  -H 'Content-Type: application/json' \
  -d '{"reason": "已与企业沟通确认为误报"}'

# 9. Convert the confirmed alert (id=1) into a ticket, then assign
#    the built-in 'handler' user (their id is stable in the demo DB).
curl -b cookies.txt -X POST http://localhost:8000/api/tickets/from-alert \
  -H 'Content-Type: application/json' \
  -d '{"alert_id": 1, "assignee_id": 3}'

# 10. Login as the handler and submit a handling result.
curl -c handler.txt -X POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username": "handler", "password": "handler123"}'
curl -b handler.txt -X POST http://localhost:8000/api/tickets/1/complete \
  -H 'Content-Type: application/json' \
  -d '{"handling_result": "已与企业沟通并取得谅解"}'

# 11. Login back as risk-control and archive the completed ticket.
curl -b cookies.txt -X POST http://localhost:8000/api/tickets/1/archive

# 12. Drill into a single opinion — the response includes the analysis
#     section (sentiment, score, level, factors, explanation).
curl -b cookies.txt http://localhost:8000/api/opinions/3 | python3 -m json.tool

# 13. Risk-control queues an Excel report (Phase 8) over the high-risk
#     items from the demo. The worker runs in the background and the
#     response returns 201 with the new task id.
curl -b cookies.txt -X POST http://localhost:8000/api/reports \
  -H 'Content-Type: application/json' \
  -d '{"title": "6 月高风险周报", "description": "Phase 8 演示", "risk_level": "high"}'

# 14. Poll the summary until the task is no longer 'pending' / 'generating',
#     then download the .xlsx. (The bundled demo is small enough that the
#     worker usually finishes by the time the second request lands.)
curl -b cookies.txt http://localhost:8000/api/reports/summary
curl -b cookies.txt -OJ http://localhost:8000/api/reports/1/download
```

Phases 1–8 together demonstrate the full ingest → analyze → risk →
alert → ticket → report pipeline. The same loop is also available as
a single CLI verifier that talks to a live `uvicorn` server over
HTTP, so a demo audience can watch every step land on a real
background worker:

```bash
# In one terminal — leave the dev server running.
uvicorn app.main:app --reload --port 8000

# In another — walk the whole path with coloured per-step output.
python scripts/demo_e2e.py --base-url http://localhost:8000
```

The script is a sibling of `tests/test_e2e_happy_path.py` — the
test uses the in-process `TestClient` and runs the report worker
directly for determinism; the script polls `BackgroundTasks` the
way a real user would, and exits non-zero on any failure.

## What's next

Phases 1–10 of `generated-issues.md` are now landed. The course demo
covers the full ingest → analyze → risk-score → alert → ticket →
report → audit loop, and a single test (`tests/test_e2e_happy_path.py`)
plus a single CLI (`scripts/demo_e2e.py`) prove it end-to-end against
both the in-process `TestClient` and a live `uvicorn` server. Any
follow-up work should be driven by new issues in
`generated-issues.md` rather than by extending the phase list.
