# 舆情风控管理系统 MVP

FastAPI + SQLAlchemy + Jinja2 modular monolith implementing the public-opinion
risk-control MVP. See `PRD.md`, `requirement.md`, and `PRD.issue.md` for the
full product, architecture, and issue plan; `generated-issues.md` is the
phased issue list (current scope: Phase 2).

## Phase 2 status — User & role management

Phase 1 established the authenticated MVP shell. Phase 2 adds administrator-
facing user and role management on top of that foundation.

- Audit log model and service: append-only `AuditLog` rows with actor, action,
  target type/id, result, JSON detail, client IP, and timestamp. Same shape
  will be reused by later phases (rules, alerts, tickets, reports, login).
- Admin-only REST API under `/api/users` and `/api/users/{id}/reset-password`,
  plus `/api/roles` for the role & permission reference.
- `/web/users` page in the management shell: create user, list users, edit
  user dialog, enable/disable toggle, password reset (admin-set or auto-
  generated), read-only role & permission overview.
- Safety guard: an admin cannot disable their own account or remove their own
  admin role, and audit records never contain passwords.
- 27 new acceptance tests; full suite is 50/50 green.

## Project layout

```
backend/
  app/
    api/        FastAPI routers (auth, protected placeholders, users)
    core/       settings + security primitives (password hashing, JWT)
    db/         SQLAlchemy engine, session, Base
    models/     ORM models (User, Role, AuditLog) and role/permission tables
    schemas/    pydantic request/response models (auth, users)
    services/   bootstrap, audit logging
    web/        Jinja2 page routes
    main.py     create_app() entrypoint
  static/       CSS + JS for the Web UI
  templates/    Jinja2 templates (login, layout, workbench, users, …)
  tests/        pytest suite (auth, web, user_management)
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
After login, admins can visit <http://localhost:8000/web/users> to manage
users and roles.

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

Sample role-protected endpoints (used to prove RBAC end-to-end):

| method | path                            | allowed roles       |
| ------ | ------------------------------- | ------------------- |
| GET    | `/api/protected/admin`          | admin               |
| GET    | `/api/protected/risk-control`   | admin, risk_control |
| GET    | `/api/protected/handler`        | admin, handler      |
| GET    | `/api/protected/auditor`        | admin, auditor      |
| GET    | `/api/protected/dashboard`      | any logged-in user  |

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

## What's next

`generated-issues.md` lists Phases 3–12. The next slice (Phase 3) is
risk-rule configuration with an audit trail, then public RSS/news ingestion
(Phase 4), CSV/JSON import (Phase 5), and analysis + risk scoring (Phase 6).
The audit log table built in Phase 2 will be reused for rule, alert, ticket,
and report events in the later phases.
