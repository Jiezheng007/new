# Generated Issues from PRD.issue.md

Source: `PRD.issue.md`
Generated: 2026-06-08
Suggested label: `ready-for-agent`

These issues are drafted locally because no GitHub remote repository is configured yet. Publish them in the order below so dependency references can be replaced with real issue identifiers.

---

## 1. Bootstrap authenticated MVP shell

Suggested label: `ready-for-agent`

## What to build

Build the initial FastAPI modular-monolith application and management-style Web UI shell with authentication, salted password storage, SQLAlchemy persistence, five MVP roles, and consistent RBAC enforcement. This slice should establish the runnable foundation that every later workflow uses.

## Acceptance criteria

- [ ] A user can log in, log out, and retrieve their current user profile.
- [ ] Passwords are stored as salted hashes and never persisted in plaintext.
- [ ] The five MVP roles exist: system administrator, risk-control user, handler, auditor, and normal viewer.
- [ ] Business APIs reject unauthenticated requests and return permission errors for unauthorized roles.
- [ ] The Web UI includes a backend-management shell with role-aware navigation placeholders for required pages.
- [ ] API tests cover successful login, disabled/invalid login rejection, and allowed/blocked access for representative roles.

## Blocked by

None - can start immediately

---

## 2. Manage users and role access

Suggested label: `ready-for-agent`

## What to build

Add administrator-facing user and role management so system administrators can create accounts, assign roles, disable users, reset passwords, and review role permissions through the Web UI and REST APIs.

## Acceptance criteria

- [ ] A system administrator can list, create, edit, disable, and reset passwords for users.
- [ ] A system administrator can assign one of the five MVP roles to a user.
- [ ] Disabled users cannot log in.
- [ ] Non-administrator roles cannot access user-management APIs or UI actions.
- [ ] User and role changes create audit records with actor, action, target, result, IP address, and timestamp.
- [ ] Authorization tests verify administrator access and non-administrator denial.

## Blocked by

- Issue 1: Bootstrap authenticated MVP shell

---

## 3. Configure risk rules with audit trail

Suggested label: `ready-for-agent`

## What to build

Add risk-rule management for sensitive keywords, monitored subject keywords, risk thresholds, and source-weight inputs. Rule configuration should be editable by administrators and auditable so later reviews can explain who changed risk logic.

## Acceptance criteria

- [ ] A system administrator can create, update, list, and disable sensitive keywords.
- [ ] A system administrator can create, update, list, and disable monitored subject keywords.
- [ ] A system administrator can maintain thresholds for low, medium, high, and severe risk levels.
- [ ] Risk-rule changes are persisted through ORM models and exposed through REST APIs and UI.
- [ ] Every rule change creates an audit log entry with actor, action, target, result, IP address, and timestamp.
- [ ] Tests verify rule persistence, permission enforcement, and audit creation.

## Blocked by

- Issue 1: Bootstrap authenticated MVP shell

---

## 4. Ingest public RSS/news sources end-to-end

Suggested label: `ready-for-agent`

## What to build

Add public RSS/news source ingestion from configuration through manual fetch to persisted opinion items. The implementation should use an adapter-style connector, normalize fetched records into the common opinion-item shape, deduplicate records, and expose fetch status for demonstration readiness.

## Acceptance criteria

- [ ] A system administrator can create, update, enable, disable, and list RSS/news data sources.
- [ ] Each data source stores a source weight, latest fetch time, and latest fetch result.
- [ ] A system administrator can manually trigger a fetch for an enabled data source.
- [ ] Fetched records are normalized, cleaned, deduplicated, and persisted as opinion items.
- [ ] Duplicate fetched records do not create duplicate opinion items.
- [ ] Risk-control users can view collected opinion items from fetched sources.
- [ ] Tests cover source configuration, manual fetch, normalization, deduplication, persistence, and fetch-result reporting.

## Blocked by

- Issue 1: Bootstrap authenticated MVP shell

---

## 5. Import CSV/JSON demo data end-to-end

Suggested label: `ready-for-agent`

## What to build

Add CSV/JSON import as a fallback demonstration data path. Imported records should use the same common opinion-item shape as RSS/news ingestion, reject invalid rows with clear reasons, deduplicate content, and make valid imported records visible in the opinion list.

## Acceptance criteria

- [ ] A risk-control user can upload CSV and JSON files through the UI or API.
- [ ] Valid imported records are normalized, cleaned, deduplicated, and persisted as opinion items.
- [ ] Invalid imported records are rejected with row-level or record-level reasons.
- [ ] Duplicate imported records do not create duplicate opinion items.
- [ ] Import results report accepted count, rejected count, duplicate count, and validation errors.
- [ ] Tests cover successful CSV import, successful JSON import, required-field validation, invalid-record reporting, and duplicate handling.

## Blocked by

- Issue 1: Bootstrap authenticated MVP shell

---

## 6. Analyze opinions and explain risk scores

Suggested label: `ready-for-agent`

## What to build

Analyze newly collected opinion items with a replaceable NLP provider and explainable risk scoring. The system should persist sentiment results, record NLP failures, combine sentiment, keyword hits, subject hits, source weight, and heat into a risk score, and expose searchable/filterable opinion detail views.

## Acceptance criteria

- [ ] Newly ingested or imported opinion items can be analyzed automatically or by a retryable task.
- [ ] Sentiment analysis runs through an `NlpProvider`-style abstraction with a fake or stub provider available for tests and demos.
- [ ] NLP success persists sentiment, confidence or equivalent analysis details, and task state.
- [ ] NLP failure persists error details and observable task state without losing the opinion item.
- [ ] Risk scoring combines sentiment, sensitive keyword hits, subject hits, source weight, and heat into low, medium, high, or severe levels.
- [ ] Risk-control users can search and filter opinion items by keyword, time range, source, sentiment, and risk level.
- [ ] Opinion detail shows original content, source, analysis result, risk score, and explanation.
- [ ] Tests verify provider replacement, sentiment persistence, failure recording, retry visibility, scoring outcomes, and list/detail filtering.

## Blocked by

- Issue 3: Configure risk rules with audit trail
- Issue 4 or Issue 5: At least one opinion-item data path must exist

---

## 7. Generate and triage high-risk alerts

Suggested label: `ready-for-agent`

## What to build

Automatically create pending alerts for high-risk and severe-risk opinion items, then let risk-control users review, confirm, or ignore those alerts with an explanation. Alert handling should be role-protected and auditable.

## Acceptance criteria

- [ ] High-risk and severe-risk analyzed opinion items automatically generate pending alerts.
- [ ] Duplicate pending alerts are not created for the same triggering opinion item.
- [ ] Risk-control users can view pending alerts.
- [ ] Risk-control users can confirm a pending alert.
- [ ] Risk-control users can ignore a pending alert with a required reason.
- [ ] Alert states include pending confirmation, confirmed, and ignored.
- [ ] Alert operations create audit records with actor, action, target, result, IP address, and timestamp.
- [ ] Tests verify automatic alert creation, duplicate prevention, confirmation, ignore-with-reason validation, permission enforcement, and audit creation.

## Blocked by

- Issue 6: Analyze opinions and explain risk scores

---

## 8. Manage the ticket lifecycle

Suggested label: `ready-for-agent`

## What to build

Add the complete MVP ticket lifecycle from confirmed alert to assignment, handling, completion, tracking, and archiving. Risk-control users should create tickets from confirmed alerts and assign handlers, while handlers should only see and update tickets assigned to them.

## Acceptance criteria

- [ ] A risk-control user can convert a confirmed alert into a ticket.
- [ ] A risk-control user can choose a handler assignee when creating or assigning a ticket.
- [ ] Ticket states support unassigned, in progress, completed, and archived.
- [ ] Risk-control users can track active and completed tickets.
- [ ] A handler can see only tickets assigned to them.
- [ ] A handler can mark an assigned ticket in progress.
- [ ] A handler can submit a handling result and mark the ticket completed.
- [ ] A risk-control user can archive completed tickets so closed work is separated from active work.
- [ ] Ticket creation and status changes create audit records with actor, action, target, result, IP address, and timestamp.
- [ ] Tests verify alert-to-ticket conversion, assignment, handler visibility, in-progress updates, completion, archiving, permission enforcement, and audit creation.

## Blocked by

- Issue 7: Generate and triage high-risk alerts

---

## 9. Build workbench dashboard

Suggested label: `ready-for-agent`

## What to build

Build the workbench dashboard that gives logged-in users a role-aware, read-only overview of current public-opinion risk pressure. The dashboard should summarize opinion totals, negative ratio, alert pressure, pending work, latest alerts, and seven-day trends from real persisted business data.

## Acceptance criteria

- [ ] Logged-in users with dashboard access can view total opinion count.
- [ ] The dashboard shows negative opinion ratio from persisted analysis results.
- [ ] The dashboard shows high/severe alert count and pending alert count.
- [ ] The dashboard shows pending ticket count.
- [ ] The dashboard shows latest alerts.
- [ ] The dashboard shows seven-day opinion or risk trends.
- [ ] Normal viewers have read-only access and cannot mutate dashboard source data.
- [ ] Tests verify dashboard counts and trends against seeded business data and role-permission behavior.

## Blocked by

- Issue 6: Analyze opinions and explain risk scores
- Issue 7: Generate and triage high-risk alerts
- Issue 8: Manage the ticket lifecycle

---

## 10. Generate asynchronous Excel reports

Suggested label: `ready-for-agent`

## What to build

Add report-center functionality for creating asynchronous Excel report tasks with time range, risk level, and subject filters. Users should be able to monitor report status, download completed reports, and inspect failures without blocking the UI.

## Acceptance criteria

- [ ] A risk-control user can create an Excel report task with time range, risk level, and subject filters.
- [ ] Report task state is persisted with filters, status, file path, error message, creator, creation time, and completion time.
- [ ] Report generation runs asynchronously and updates status to completed or failed.
- [ ] Completed Excel reports contain summarized risk information for the selected filters.
- [ ] Users can view report task status as generating, completed, or failed.
- [ ] Users can download completed Excel reports.
- [ ] Report generation and report download create audit records.
- [ ] Tests verify task creation, asynchronous status changes, failure handling, generated Excel content for a controlled dataset, download behavior, and audit creation.

## Blocked by

- Issue 6: Analyze opinions and explain risk scores
- Issue 8: Manage the ticket lifecycle

---

## 11. Expose audit log review

Suggested label: `ready-for-agent`

## What to build

Add auditor-facing audit log review so important system operations are traceable from the Web UI and API. Auditors should be able to inspect login, user and role, data-source, rule, alert, ticket, report generation, and report download events.

## Acceptance criteria

- [ ] Auditors can list audit logs.
- [ ] Audit logs include actor, action, target, result, IP address, and timestamp.
- [ ] Audit log review supports useful filters such as action type, actor, target, result, and time range.
- [ ] Auditors can access audit logs while unauthorized roles are blocked from audit review.
- [ ] Login, user and role, data-source, rule, alert, ticket, report generation, and report download events are represented in the audit log when those features exist.
- [ ] Tests verify audit log visibility, filtering, permission enforcement, and required field presence.

## Blocked by

- Issue 2: Manage users and role access
- Issue 3: Configure risk rules with audit trail
- Issue 7: Generate and triage high-risk alerts
- Issue 8: Manage the ticket lifecycle
- Issue 10: Generate asynchronous Excel reports

---

## 12. Prove the course-demo happy path

Suggested label: `ready-for-agent`

## What to build

Prepare and verify the end-to-end course demonstration path that shows the architecture decisions through working behavior: ingest or import public-opinion data, analyze it, generate risk, confirm an alert, create and process a ticket, generate an Excel report, and review audit logs.

## Acceptance criteria

- [ ] Seeded CSV/JSON demonstration data is available for reliable offline or unstable-source demos.
- [ ] A documented demo path covers login, fetch or import, analysis, alert confirmation, ticket creation, ticket completion, report generation, report download, dashboard review, and audit-log review.
- [ ] The demo path exercises event-driven alert/ticket/report/audit behavior, pipeline-style ingestion and analysis, and SQLAlchemy-backed persistence.
- [ ] The UI supports the happy path without requiring database edits or manual backend calls.
- [ ] An end-to-end test or scripted verification covers the happy path using controlled data.
- [ ] The project documentation explains how to run the app and execute the demo.

## Blocked by

- Issue 4: Ingest public RSS/news sources end-to-end
- Issue 5: Import CSV/JSON demo data end-to-end
- Issue 6: Analyze opinions and explain risk scores
- Issue 7: Generate and triage high-risk alerts
- Issue 8: Manage the ticket lifecycle
- Issue 9: Build workbench dashboard
- Issue 10: Generate asynchronous Excel reports
- Issue 11: Expose audit log review
