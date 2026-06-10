# 舆情风控管理系统 MVP

> FastAPI + SQLAlchemy + Jinja2 模块化单体,实现从舆情接入到工单归档的完整可演示闭环。

---

## 一、项目概述

### 1.1 它解决什么问题

网络舆情来源分散、传播速度快,组织需要及时发现与自身相关的负面信息,对高危内容做出预警并推动责任人员完成处置。本系统面向**舆情监测 → 风险识别 → 分级预警 → 协同处置 → 报告审计**的端到端业务场景,提供一套可运行的管理端 Web 应用与后端服务。

### 1.2 核心业务闭环

```
数据接入(数据源拉取 / CSV·JSON 导入)
        ↓
  标准化、清洗、去重
        ↓
  NLP 情感分析
        ↓
  风险规则评分(敏感词 / 主体 / 来源权重 / 热度)
        ↓
  高 / 严重风险自动生成待确认预警
        ↓
  风控人员确认 / 忽略
        ↓
  已确认预警转工单 → 派发处置人员 → 提交结果 → 归档
        ↓
  异步生成 Excel 报告(概览 / 汇总 / 明细)
        ↓
  关键操作全程审计可追溯
```

### 1.3 五类角色

| 角色 | 主要职责 | 典型操作 |
|---|---|---|
| 系统管理员 `admin` | 维护用户、角色、权限、数据源、风险规则 | 用户管理、规则配置、数据源配置 |
| 风控人员 `risk_control` | 查看舆情、确认预警、创建工单、生成报告 | 舆情分析、预警处置、工单派发、报告下载 |
| 处置人员 `handler` | 处理分配给自己的工单 | 接受工单、提交处理结果 |
| 审计人员 `auditor` | 查看操作日志和规则变更记录 | 审计日志多维查询 |
| 普通查看 `viewer` | 只读查看工作台、舆情、报告 | 浏览 KPI、阅读报告 |

### 1.4 架构风格

本系统采用**事件驱动 + 管道-过滤器 + 数据为中心**的混合架构(详见 `requirement.md`):

- **事件驱动**:预警生成、工单流转、报告异步生成、审计写入均通过事件/任务解耦
- **管道-过滤器**:采集 → 标准化 → 清洗 → 去重 → NLP → 风险评分,每个阶段独立可替换
- **数据为中心**:舆情、预警、工单、报告、用户权限、审计日志统一通过 SQLAlchemy ORM 持久化

课程实现落地形式为 **FastAPI 模块化单体**,业务模块按域拆分,内部通过 Service 层解耦,便于后续演进为微服务。

### 1.5 前端技术形态

管理端采用 **服务端渲染 (Jinja2) + 原生 JavaScript** 的方案,**不引入前端框架或独立 `frontend/` 目录**:

- 页面骨架由 `backend/templates/_layout.html` 与各业务页模板服务端渲染输出,首屏即可用
- 列表/筛选/对话框/轮询等交互逻辑由 `backend/static/*.js` 中各页面级 JS 文件承担
- 风格统一样式位于 `backend/static/app.css`

这种取舍是为了把课程作业的复杂度集中在后端业务闭环上;若需演进为 SPA,可将现有 JS 抽离为独立前端项目并复用 `app/api/` 下的 OpenAPI 契约。

---

## 二、功能特性一览

- **认证与 RBAC**:JWT + Cookie 双通道、五类角色、按权限点细粒度鉴权
- **数据源管理**:RSS / JSON URL / 内置 `static_demo` 三种类型,支持手动拉取与最近拉取状态展示
- **数据导入**:CSV / JSON 文件上传,以及一键加载内置演示包
- **舆情管理**:分页、按关键词/来源/时间/情感/风险等级/分析状态多维筛选
- **可插拔 NLP**:`NlpProvider` 抽象 + 默认 `KeywordNlpProvider` 离线词典实现,可替换为第三方 API
- **风险评分**:0-100 分综合评分,自动映射到 `低 / 中 / 高 / 严重` 四档,管理员可调阈值
- **预警生命周期**:高/严重风险自动建 `pending` 预警 → 确认 / 填写原因忽略
- **工单流转**:已确认预警转工单,四态状态机(待派发 / 处理中 / 已完成 / 已归档)
- **报告中心**:异步生成三页 Excel(概览 + 汇总 + 明细),支持按风险等级/时间/主体关键词过滤
- **工作台**:登录首页一屏展示舆情、负面占比、待确认预警、待处理工单、7 日趋势
- **审计日志**:登录/退出、用户/角色/数据源/规则/预警/工单/报告关键操作全程留痕,审计员可多维过滤

---

## 三、快速开始

### 3.1 环境要求

- Python ≥ 3.10(建议 3.12)
- SQLite(默认,开箱即用)或任何 SQLAlchemy 支持的关系型数据库

### 3.2 安装与启动

```bash
cd backend
python3 -m venv .venv

source .venv/bin/activate
pip install -r requirements.txt
pip install feedparser        # 可选:仅在需要真实 RSS 拉取时安装

# 初始化数据库(创建表 + 种子五类角色、风险阈值、演示数据源、五类演示账号)
python scripts/seed_data.py

# 启动开发服务器
uvicorn app.main:app --reload --port 8000
```

浏览器打开 <http://localhost:8000/login> 即可登录。

### 3.3 内置演示账号

`seed_data.py` 会为每类角色创建一个演示账号,密码可在 `.env` 中修改:

| 角色 | 账号 | 密码 |
|---|---|---|
| 系统管理员 | `admin` | `admin123` |
| 风控人员 | `risk` | `risk123` |
| 处置人员 | `handler` | `handler123` |
| 审计人员 | `auditor` | `auditor123` |
| 普通查看 | `viewer` | `viewer123` |

---

## 四、端到端演示

启动 dev server 后,有两种方式跑通完整业务闭环。

### 4.1 脚本化验证(推荐用于课程演示)

`scripts/demo_e2e.py` 会按真实用户角色串起 `admin → risk → handler → auditor` 的全流程,每步输出一行彩色日志,适合现场演示。

```bash
# 终端一:保持服务运行
uvicorn app.main:app --reload --port 8000

# 终端二:一键跑通闭环
python scripts/demo_e2e.py
```

执行步骤:触发静态演示数据源 → 加载 CSV/JSON 演示包 → 风控确认/忽略预警 → 转工单派发 → 处置人员完成 → 风控归档 → 异步生成 Excel 报告 → 下载 → 审计员查询日志。

### 4.2 手动 curl 走查

```bash
BASE=http://localhost:8000

# --- 1. 管理员登录 ---
curl -c admin.txt -X POST $BASE/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}'

# --- 2. 触发内置静态演示数据源(6 条舆情,自动分析,2 条高/严重风险自动建待确认预警) ---
curl -b admin.txt -X POST $BASE/api/datasources/1/fetch

# --- 3. 一键加载内置 CSV/JSON 演示包 ---
curl -b admin.txt -X POST $BASE/api/import/demo

# --- 4. 查看高风险舆情 ---
curl -b admin.txt "$BASE/api/opinions?risk_level=high"

# --- 5. 风控人员确认一条预警 ---
curl -b admin.txt -X POST $BASE/api/alerts/1/confirm

# --- 6. 已确认预警转工单(assignee_id=3 即 handler 演示账号) ---
curl -b admin.txt -X POST $BASE/api/tickets/from-alert \
  -H 'Content-Type: application/json' \
  -d '{"alert_id":1,"assignee_id":3}'

# --- 7. 处置人员登录并提交处理结果 ---
curl -c handler.txt -X POST $BASE/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"handler","password":"handler123"}'
curl -b handler.txt -X POST $BASE/api/tickets/1/complete \
  -H 'Content-Type: application/json' \
  -d '{"handling_result":"已与企业沟通并取得谅解"}'

# --- 8. 风控人员归档已完成的工单 ---
curl -b admin.txt -X POST $BASE/api/tickets/1/archive

# --- 9. 异步生成 Excel 报告(高风险) ---
curl -b admin.txt -X POST $BASE/api/reports \
  -H 'Content-Type: application/json' \
  -d '{"title":"高风险周报","risk_level":"high"}'

# --- 10. 轮询直至完成,下载 .xlsx ---
curl -b admin.txt $BASE/api/reports/summary
curl -b admin.txt -OJ $BASE/api/reports/1/download
```

> 默认演示数据完全内置,无需任何外部网络或第三方服务。

---

## 五、Web UI 页面

| 路径 | 用途 | 可见角色 |
|---|---|---|
| `/web/workbench` | 工作台首页:KPI 卡片 + 7 日趋势 + 最新预警/工单 | 全部已登录角色 |
| `/web/datasources` | 数据源管理(CRUD + 手动拉取) | admin |
| `/web/rules` | 风险规则(敏感词 / 主体词 / 四档阈值) | admin |
| `/web/users` | 用户与角色管理 | admin |
| `/web/import` | CSV / JSON 导入 | admin、risk_control |
| `/web/opinions` | 舆情列表 + 详情 + 重新分析 | admin、risk_control、auditor、viewer |
| `/web/alerts` | 预警中心(确认 / 忽略) | admin、risk_control、auditor(只读) |
| `/web/tickets` | 工单管理(派发 / 完成 / 归档) | admin、risk_control、handler、auditor |
| `/web/reports` | 报告中心(创建任务 + 下载) | admin、risk_control、auditor、viewer |
| `/web/audit` | 审计日志多维查询 | admin、auditor |

---

## 六、API 速查

完整 OpenAPI 文档:启动服务后访问 <http://localhost:8000/docs>。

按业务域分组的主要接口:

| 业务域 | 路径前缀 | 主要能力 |
|---|---|---|
| 认证 | `/api/auth` | 登录、登出、当前用户信息 |
| 用户与角色 | `/api/users` · `/api/roles` | CRUD、启停、密码重置、角色分配 |
| 风险规则 | `/api/rules` | 敏感词、主体词、四档阈值 |
| 数据源 | `/api/datasources` | CRUD、启停、手动拉取 |
| 舆情 | `/api/opinions` | 多维筛选、详情、重新分析 |
| 预警 | `/api/alerts` | 列表、确认、忽略、状态汇总 |
| 工单 | `/api/tickets` | 转工单、派发、开始、完成、归档、状态汇总 |
| 报告 | `/api/reports` | 异步任务、详情、`.xlsx` 下载 |
| 导入 | `/api/import` | CSV / JSON / 演示包 |
| 工作台 | `/api/dashboard` | 聚合指标 + 趋势 + 最新项 |
| 审计 | `/api/audit-logs` | 多维过滤 + 详情(只读) |

---

## 七、项目结构

```
backend/
  app/
    api/         FastAPI 路由(各业务域 + RBAC 依赖)
    core/        配置 + 安全工具(密码哈希、JWT)
    db/          SQLAlchemy 引擎、会话、Base
    models/      ORM 模型:User / Role / AuditLog /
                 SensitiveKeyword / SubjectKeyword / RiskThreshold /
                 DataSource / OpinionItem / AnalysisResult /
                 Alert / Ticket / ReportTask
    schemas/     Pydantic 请求 / 响应模型
    services/    业务服务层:bootstrap / audit / connectors /
                 ingestion / importers / nlp / scoring / analysis /
                 alerts / tickets / reports
    web/         Jinja2 页面路由
    main.py      create_app() 入口
  static/        app.css + 各页面 JS + 演示 CSV / JSON 样例
  templates/     Jinja2 模板(_layout.html + 12 个业务页)
  tests/         13 个测试模块,共 290 个 pytest 用例
  scripts/       seed_data.py / demo_e2e.py
  requirements.txt
  pytest.ini
```

---

## 八、配置

`backend/.env` 可覆盖以下默认值(完整列表见 `backend/.env.example`):

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SECRET_KEY` | `change-me-in-prod` | HS256 签名密钥,生产环境必须修改 |
| `DATABASE_URL` | `sqlite:///./yuqing.db` | SQLAlchemy 数据库 URL |
| `ACCESS_TOKEN_TTL_MINUTES` | `480` | JWT 有效期 |
| `BOOTSTRAP_ADMIN_USERNAME` | `admin` | 首次启动时创建的管理员账号 |
| `BOOTSTRAP_ADMIN_PASSWORD` | `admin123` | 首次启动时创建的管理员密码 |
| `NLP_PROVIDER` | `keyword_nlp` | NLP Provider 名(注册于 `app/services/nlp`) |
| `REPORT_STORAGE_DIR` | _(未设置则存于 DB 旁)_ | 报告 `.xlsx` 输出目录 |

---


