# 舆情风控管理系统 MVP

FastAPI + SQLAlchemy + Jinja2 modular monolith implementing the public-opinion
risk-control MVP. See `PRD.md`, `requirement.md`, and `PRD.issue.md` for the
full product, architecture, and issue plan; `generated-issues.md` is the
phased issue list (Phase 1 = current scope).

## Phase 1 status — Bootstrap authenticated MVP shell

Phase 1 establishes the runnable foundation that every later workflow uses:

- FastAPI modular-monolith backend with SQLAlchemy ORM and SQLite (file-based)
- Five MVP roles seeded: 系统管理员, 风控人员, 处置人员, 审计人员, 普通查看人员
- Salted PBKDF2-HMAC-SHA256 password hashes (per-user random salt)
- JWT access tokens (HS256) plus a same-site cookie for the Web UI
- `/api/auth/login`, `/api/auth/logout`, `/api/auth/me`
- Role-protected sample endpoints under `/api/protected/*` to prove RBAC
- Server-rendered Web UI: login page + management-style shell with role-aware side navigation and placeholders for every required page
- pytest suite covering login, profile, RBAC, and password storage

## Project layout

```
backend/
  app/
    api/        FastAPI routers (auth, protected placeholders, future business APIs)
    core/       settings + security primitives (password hashing, JWT)
    db/         SQLAlchemy engine, session, Base
    models/     ORM models (User, Role) and role code/permission/seed tables
    schemas/    pydantic request/response models
    services/   bootstrap (table creation, role/admin seeding)
    web/        Jinja2 page routes
    main.py     create_app() entrypoint
  static/       CSS + JS for the Web UI
  templates/    Jinja2 templates
  tests/        pytest suite
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

# Initialize the database (creates tables, seeds roles and admin user)
python scripts/seed_data.py

# Run the dev server
uvicorn app.main:app --reload --port 8000
```

Open <http://localhost:8000/login> and sign in with `admin / admin123`.

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

| method | path                       | auth         | purpose                                |
| ------ | -------------------------- | ------------ | -------------------------------------- |
| POST   | `/api/auth/login`          | none         | username + password → JWT (sets cookie) |
| POST   | `/api/auth/logout`         | none         | clear access_token cookie              |
| GET    | `/api/auth/me`             | bearer/cookie| current user profile + permissions    |
| GET    | `/api/protected/risk-control` | admin/risk | sample role-restricted endpoint        |
| GET    | `/api/protected/handler`   | admin/handler| sample role-restricted endpoint        |
| GET    | `/api/protected/auditor`   | admin/auditor| sample role-restricted endpoint       |
| GET    | `/api/protected/admin`     | admin        | sample role-restricted endpoint        |
| GET    | `/api/protected/dashboard` | any role     | sample authenticated endpoint          |

Web UI: `GET /login` (form), `GET /web/<page>` (role-aware pages: workbench,
datasources, rules, import, opinions, alerts, tickets, reports, users, audit).

## Testing

```bash
cd backend
source .venv/bin/activate
pytest
```

The suite provisions an isolated SQLite database per test run, seeds all five
roles plus a disabled user, and verifies:

- successful login + JWT issuance + cookie set
- wrong-password / unknown-user / disabled-user login rejection
- `/me` accepts a valid token, rejects missing/invalid tokens
- password storage uses a per-user salt (no plaintext, distinct hashes for equal passwords)
- unauthenticated business API calls return 401
- admin can access every protected area; risk/handler/auditor/viewer each get 200 only on their own areas and 403 elsewhere
- login page renders; root redirects unauthenticated visitors; role-aware nav contains the right items; cross-role page access returns 403

## What's next

Phases 2–12 of `generated-issues.md` will build user/role management, risk
rules, ingestion, analysis, alerts, tickets, reports, dashboard, and audit on
top of this foundation.
