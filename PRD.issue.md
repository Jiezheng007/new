# PRD: 舆情风控管理系统 MVP

## Problem Statement

软件体系结构作业需要一个能够实际编码实现和课堂展示的舆情风控管理系统，而不是只停留在架构概念层面的说明。当前需求已经明确系统采用事件驱动、管道-过滤器、数据为中心和 FastAPI 模块化单体的混合架构，但还需要把这些架构决策转化为可实现、可验收、可测试的产品需求。

用户需要一个 MVP 原型，能够接入真实可展示的数据源，调用现成 NLP 模型或服务完成中文情感分析，并完成从舆情数据接入、风险识别、预警确认、工单处置到报告生成的闭环。

## Solution

构建一个后台管理式 Web 系统和 FastAPI 后端服务。系统支持配置公开 RSS/新闻源，并提供 CSV/JSON 手动导入作为演示兜底。舆情数据进入系统后，经过标准化、清洗、去重、NLP 情感分析和规则评分，自动生成风险等级。高风险或严重风险舆情进入待确认预警，由风控人员确认、忽略或转为工单。处置人员处理分配给自己的工单，系统记录关键操作审计日志。用户可以在工作台查看风险概览，并在报告中心异步生成和下载 Excel 报告。

MVP 保留五类角色：系统管理员、风控人员、处置人员、审计人员、普通查看人员。系统实现基础 RBAC 权限控制，优先完成核心业务闭环，不实现复杂审批、企业级微服务治理、大规模爬虫或自研 NLP 模型。

## User Stories

1. As a system administrator, I want to create user accounts, so that different team members can log in to the system.
2. As a system administrator, I want to assign roles to users, so that each user only accesses the functions they are allowed to use.
3. As a system administrator, I want to disable a user account, so that users who should no longer access the system are blocked.
4. As a system administrator, I want to reset a user's password, so that account recovery can be handled without database changes.
5. As a system administrator, I want to configure RSS or public news data sources, so that the system can collect real public opinion data for demonstration.
6. As a system administrator, I want to set a source weight for each data source, so that risk scoring can account for source importance.
7. As a system administrator, I want to enable or disable a data source, so that unstable or irrelevant sources can be controlled.
8. As a system administrator, I want to manually trigger a source fetch, so that I can prepare demonstration data on demand.
9. As a system administrator, I want to view the latest fetch time and fetch result, so that I can tell whether a data source is working.
10. As a system administrator, I want to maintain sensitive keywords, so that the system can identify potentially risky content.
11. As a system administrator, I want to maintain subject keywords, so that the system can detect opinion items related to monitored organizations or topics.
12. As a system administrator, I want to maintain risk thresholds, so that the system can classify low, medium, high, and severe risks consistently.
13. As a system administrator, I want rule changes to be audited, so that later reviews can identify who changed risk logic.
14. As a risk-control user, I want to view collected opinion items, so that I can inspect current public opinion data.
15. As a risk-control user, I want to search opinion items by keyword, so that I can quickly find relevant records.
16. As a risk-control user, I want to filter opinion items by time range, source, sentiment, and risk level, so that I can focus on high-priority content.
17. As a risk-control user, I want to view opinion item details, so that I can understand the original content, source, analysis result, and risk score.
18. As a risk-control user, I want newly collected opinion items to be analyzed automatically, so that manual triage is reduced.
19. As a risk-control user, I want the system to call an existing NLP provider for sentiment analysis, so that the MVP can use a trained model without building one.
20. As a risk-control user, I want NLP analysis failures to be recorded, so that failed records can be retried or investigated.
21. As a risk-control user, I want risk scoring to combine sentiment, keywords, subject hits, source weight, and heat, so that risk levels are explainable.
22. As a risk-control user, I want high-risk and severe-risk items to generate pending alerts automatically, so that important risks are not missed.
23. As a risk-control user, I want to view pending alerts, so that I can confirm or reject system-detected risks.
24. As a risk-control user, I want to confirm a pending alert, so that it becomes an official risk item.
25. As a risk-control user, I want to ignore a pending alert with a reason, so that false positives are recorded.
26. As a risk-control user, I want confirmed alerts to be converted into tickets, so that risk handling can be assigned and tracked.
27. As a risk-control user, I want to choose an assignee when creating a ticket, so that the right handler receives the work.
28. As a risk-control user, I want to track ticket status, so that I can see whether a risk has been handled.
29. As a risk-control user, I want to archive completed tickets, so that closed work is separated from active work.
30. As a handler, I want to see only tickets assigned to me, so that my task list is focused and permission-safe.
31. As a handler, I want to update a ticket to in progress, so that others know the issue is being handled.
32. As a handler, I want to submit a handling result, so that the response to the risk is recorded.
33. As a handler, I want to mark a ticket as completed, so that risk-control users can review and archive it.
34. As an auditor, I want to view login, rule-change, alert, ticket, and report audit logs, so that important operations are traceable.
35. As an auditor, I want audit logs to include actor, action, target, result, IP address, and time, so that responsibility can be traced.
36. As a normal viewer, I want read-only access to dashboards and reports, so that I can understand public opinion status without changing data.
37. As a normal viewer, I want to view the workbench risk overview, so that I can quickly see current risk pressure.
38. As any logged-in user, I want unauthorized actions to be blocked, so that system permissions are enforced consistently.
39. As any logged-in user, I want the workbench to show opinion totals, negative ratio, high-risk alert count, pending alerts, pending tickets, and seven-day trends, so that the system status is visible immediately.
40. As a risk-control user, I want to create an Excel report task with time range, risk level, and subject filters, so that I can export analysis results for course demonstration.
41. As a risk-control user, I want report generation to run asynchronously, so that the UI is not blocked by file generation.
42. As a risk-control user, I want to see report task status, so that I know whether a report is generating, completed, or failed.
43. As a risk-control user, I want to download a completed Excel report, so that I can present summarized risk information.
44. As a risk-control user, I want CSV/JSON import as a fallback data path, so that demonstrations still work if public sources are unavailable.
45. As a risk-control user, I want invalid imported records to be rejected with reasons, so that bad data does not silently enter the system.
46. As a developer, I want the NLP provider to be replaceable, so that local models and third-party APIs can be swapped without rewriting business logic.
47. As a developer, I want the data-source connector to use an adapter-style design, so that additional public sources can be added later.
48. As a developer, I want core entities to be represented with ORM models, so that persistence logic is maintainable and consistent.
49. As a developer, I want task execution state to be stored, so that failed analysis and report jobs are observable.
50. As a course evaluator, I want the system to demonstrate architecture decisions through working features, so that the submission shows both design rationale and implementation feasibility.

## Implementation Decisions

- The system will be implemented as a FastAPI modular monolith rather than a full microservice system.
- The architecture will preserve the existing architecture decisions: event-driven flow for alert, ticket, report, and audit events; pipeline-filter flow for ingestion and analysis; data-centered repository style for persistence.
- The backend will expose RESTful APIs for authentication, users, roles, data sources, opinion items, analysis results, risk rules, alerts, tickets, reports, dashboard statistics, and audit logs.
- SQLAlchemy ORM will be used for database access.
- A relational database will store users, roles, permissions, data sources, opinion items, analysis results, risk rules, alerts, tickets, report tasks, and audit logs.
- RBAC will support five roles: system administrator, risk-control user, handler, auditor, and normal viewer.
- Passwords will be stored as salted hashes and never stored in plaintext.
- Public RSS/news source ingestion is required.
- CSV/JSON import is required as a fallback demonstration path.
- Real social platform and short-video platform scraping is out of scope for MVP.
- Ingestion will standardize records into a common opinion-item shape before analysis.
- Deduplication will use a content hash or equivalent unique fingerprint for title/content/source combinations.
- NLP analysis will call an existing Chinese sentiment model or third-party service.
- NLP implementation will be hidden behind an `NlpProvider` style interface, allowing local model and external API implementations.
- Risk scoring will be rule-based and explainable.
- Risk factors include sentiment, sensitive keyword hits, monitored subject hits, source weight, heat, and manual confirmation state.
- Risk levels will be low, medium, high, and severe.
- High and severe risk items will create pending alerts automatically.
- Alert states will be pending confirmation, confirmed, ignored, and converted to ticket.
- Ticket states will be unassigned, in progress, completed, and archived.
- Alert and ticket workflows will not include multi-level approval.
- Reports will be generated asynchronously.
- Excel report generation is required; PDF report generation is optional.
- Report tasks will store filters, status, file path, error message, creator, creation time, and completion time.
- Workbench statistics will include opinion totals, negative opinion ratio, high/severe alert count, pending alert count, pending ticket count, latest alerts, and seven-day trends.
- Audit logs will be written for login events, user and role changes, data-source changes, rule changes, alert handling, ticket status changes, report generation, and report download.
- The Web UI will be a backend-management style interface, not a marketing page.
- Required pages include login, workbench, data-source management, data import, opinion list, opinion detail, alert center, ticket management, report center, audit log, user management, and rule management.
- The default ingestion cadence will be 5-15 minutes for scheduled fetching, with manual fetch available.
- High-risk content should enter risk judgment immediately after ingestion.
- The MVP will not require Elasticsearch/OpenSearch, but the design may leave room for later full-text search.
- The MVP may use FastAPI background tasks, APScheduler, or Celery with Redis depending on implementation complexity.

## Testing Decisions

- Tests should validate external behavior at the highest practical seam: API requests, workflow state transitions, generated report outputs, and role-permission outcomes.
- Tests should avoid asserting private implementation details such as internal service call order unless those calls are part of an explicit contract.
- Authentication and authorization tests should verify that each role can access allowed endpoints and is blocked from disallowed endpoints.
- Data-source tests should verify that a configured source can be fetched, normalized, deduplicated, and persisted.
- CSV/JSON import tests should verify successful import, required-field validation, invalid-row reporting, and duplicate handling.
- NLP tests should use a fake or stub provider to verify sentiment result persistence, failure recording, and retry behavior without depending on an external model or network.
- Risk scoring tests should verify that known combinations of sentiment, keyword hits, subject hits, source weight, and heat produce expected risk levels.
- Alert workflow tests should verify automatic pending alert creation, confirmation, ignoring with reason, and conversion to ticket.
- Ticket workflow tests should verify assignment, assignee visibility, in-progress updates, completion, and archive behavior.
- Report tests should verify task creation, asynchronous status changes, failure handling, and generated Excel content for a controlled dataset.
- Dashboard tests should verify that summary counts and trends match seeded business data.
- Audit tests should verify that key operations create audit records with actor, action, target, result, and timestamp.
- UI tests, if implemented, should cover the core happy path: login, fetch/import data, view analysis, confirm alert, create ticket, complete ticket, generate report.
- Since the repository currently contains requirement documents only and no codebase tests, there is no existing test prior art. New tests should be introduced alongside implementation using the selected backend and frontend frameworks.

## Out of Scope

- Training a custom NLP model.
- Complex rumor detection.
- Cross-platform propagation graph analysis.
- Real-time second-level streaming ingestion.
- Large-scale distributed crawling.
- Bypassing login, anti-crawling controls, or non-public APIs.
- Full enterprise microservice governance.
- Service registry, distributed tracing, container orchestration, and distributed transactions.
- Multi-level approval workflows.
- Report template editor.
- Mandatory PDF report generation.
- Mandatory Elasticsearch/OpenSearch integration.
- Production-grade high-concurrency guarantees.

## Further Notes

- The implementation should prioritize a complete demonstrable loop over breadth: ingest or import data, analyze it, generate risk, confirm alert, create and process ticket, produce report, and record audit logs.
- Public data-source instability is expected, so seeded CSV/JSON demonstration data should be prepared before presentation.
- NLP provider instability should be handled by an abstraction and a fallback strategy, so the demonstration does not fail solely because a remote service is unavailable.
- This PRD should remain aligned with the existing architecture document: the product requirements should demonstrate the architecture decisions instead of expanding beyond the course scope.
- Suggested issue label: `ready-for-agent`.
