# 舆情风控管理系统 MVP

FastAPI + SQLAlchemy + Jinja2 modular monolith implementing the public-opinion
risk-control MVP. See `PRD.md`, `requirement.md`, and `PRD.issue.md` for the
full product, architecture, and issue plan; `generated-issues.md` is the
phased issue list (current scope: Phase 5).

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
                AnalysisResult, Alert)
    schemas/    pydantic request/response models
    services/   bootstrap, audit logging, connectors, ingestion, importers,
                nlp (provider abstraction + keyword implementation),
                scoring (rule-based risk score), analysis (orchestration),
                alerts (auto-create + confirm / ignore lifecycle)
    web/        Jinja2 page routes
    main.py     create_app() entrypoint
  static/       CSS + JS for the Web UI, bundled demo CSV / JSON samples
  templates/    Jinja2 templates (login, layout, workbench, users, rules,
                datasources, opinions, import, …)
  tests/        pytest suite (auth, web, user_management, rules,
                datasources, imports, analysis, alerts)
  scripts/      dev helpers (seed_data.py)
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

- `admin` can visit `/web/datasources`, `/web/rules`, `/web/users`, `/web/alerts`
- `risk` can visit `/web/import`, `/web/opinions`, `/web/alerts`
- `handler` lands on `/web/tickets` (handler-only nav in Phase 8)
- `auditor` lands on `/web/audit`; can read `/web/alerts` + `/web/opinions` (Phase 11)
- `viewer` lands on `/web/workbench` only

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
sinks. The full suite (171 tests) covers:

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

# 9. Drill into a single opinion — the response includes the analysis
#    section (sentiment, score, level, factors, explanation).
curl -b cookies.txt http://localhost:8000/api/opinions/3 | python3 -m json.tool
```

Phases 1–5 together demonstrate the full ingest → analyze → risk →
alert pipeline. Phase 6 will layer the ticket lifecycle (confirmed
alert → assigned → completed → archived) on top of the confirmed
alerts.

## What's next

`generated-issues.md` lists Phases 6–12. The next slice is **Phase 6
(Issue 8)**: the ticket lifecycle (confirmed alert → assigned →
completed → archived) on top of the confirmed alerts from Phase 5.
