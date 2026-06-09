# 舆情风控管理系统 MVP

FastAPI + SQLAlchemy + Jinja2 modular monolith implementing the public-opinion
risk-control MVP. See `PRD.md`, `requirement.md`, and `PRD.issue.md` for the
full product, architecture, and issue plan; `generated-issues.md` is the
phased issue list (current scope: Phase 3).

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
                SubjectKeyword, RiskThreshold, DataSource, OpinionItem)
    schemas/    pydantic request/response models
    services/   bootstrap, audit logging, connectors, ingestion, importers
    web/        Jinja2 page routes
    main.py     create_app() entrypoint
  static/       CSS + JS for the Web UI, bundled demo CSV / JSON samples
  templates/    Jinja2 templates (login, layout, workbench, users, rules,
                datasources, opinions, import, …)
  tests/        pytest suite (auth, web, user_management, rules,
                datasources, imports)
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

- `admin` can visit `/web/datasources`, `/web/rules`, `/web/users`
- `risk` can visit `/web/import`, `/web/opinions`
- `handler` lands on `/web/tickets` (handler-only nav in Phase 8)
- `auditor` lands on `/web/audit` (audit log in Phase 11)
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
| GET    | `/api/opinions`                     | list with `q`, `source_id`, `start_at`, `end_at`, `limit`, `offset`     |
| GET    | `/api/opinions/{id}`                | detail of a single opinion item                                         |

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
roles plus a disabled user, the four risk thresholds, the static demo data
source, and the CSV / JSON import sinks. The full suite (114 tests) covers:

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
  manual fetch of the static demo persists 6 items and re-fetch dedupes to
  6 duplicates; disabled source returns 400; RSS without `feedparser`
  returns 502 with a clear message; opinion list / detail enforce the
  `opinion:read` role set (handler is blocked); keyword, source, and
  time-range filters work; the `/web/datasources` and `/web/opinions` pages
  render for the right roles and return 403 / 401 otherwise.
- **Imports** (`tests/test_imports.py`): CSV and JSON uploads validate
  required columns / fields; required-column-missing returns 400; per-row
  validation failures (e.g. blank title) are reported in the response body
  without aborting the import; re-upload dedupes correctly; the bundled
  demo endpoint loads 5 CSV + 4 JSON records on first call and 9 duplicates
  on re-call; non-importer roles get 403; the `/web/import` page renders for
  risk-control and returns 403 for handler.

## Demo happy path (no external network needed)

```bash
# 1. Login
curl -c cookies.txt -X POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username": "admin", "password": "admin123"}'

# 2. Fetch the built-in static demo (6 items)
curl -b cookies.txt -X POST http://localhost:8000/api/datasources/1/fetch

# 3. Load the bundled CSV + JSON sample data (5 + 4 items)
curl -b cookies.txt -X POST http://localhost:8000/api/import/demo

# 4. Risk-control user can now see 10+ opinion items
curl -b cookies.txt 'http://localhost:8000/api/opinions?limit=20'
```

Phase 3 alone demonstrates the ingestion + audit + RBAC + UI pipeline. Phase 6
will layer NLP + risk scoring on top of these same opinion items.

## What's next

`generated-issues.md` lists Phases 4–12. The next slice is **Phase 4**:
opinion analysis with an `NlpProvider` abstraction, risk-score explanation,
and integration with the rules/thresholds built here. The `OpinionItem`
content + `SensitiveKeyword` / `SubjectKeyword` / `RiskThreshold` tables are
already shaped for that next step.
