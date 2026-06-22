# Issue 分析与修复顺序

> 分析日期:2026-06-16
> 分析对象:`Jiezheng007/new` 仓库 8 个 OPEN issue
> 项目:中文舆情监测 / 风险控制系统(FastAPI + SQLAlchemy + SQLite + Jinja2)

---

## 一、项目概况

### 技术栈
- **后端**:FastAPI + SQLAlchemy(SQLite)
- **前端**:Jinja2 模板 + 原生 JS(`/backend/static/*.js`)
- **架构**:Phase 1-11 渐进式交付

### 代码结构
```
backend/app/
├── api/          ← REST 端点 (reports.py, alerts.py, datasources.py...)
├── services/     ← 业务逻辑 (reports.py, alerts.py, datasource_fetch.py, nlp/, scoring.py)
├── db/session.py ← 全局单例 engine (SQLite 默认配置,无 WAL)
├── models/       ← ORM
├── schemas/      ← Pydantic
├── static/       ← 前端 JS
└── templates/    ← HTML
```

### 提交历史关键节点
| Phase | Issue | 内容 |
|---|---|---|
| 1 | #1 | Bootstrap authenticated MVP shell |
| 2 | #2 | User & role management |
| 3 | #3 | Risk rules, data sources, ingestion, imports |
| 4 | #6 | Opinion analysis + risk scoring |
| 5 | #7 | Alert lifecycle |
| 6 | #8 | Ticket lifecycle |
| 7 | #9 | Workbench dashboard |
| 8 | #10 | Report center |
| 9 | #11 | Audit log review |
| 10 | #12 | Course-demo happy path |
| 11 | #14 | Unified data-source fetch service(微博 / RSS / 调度器) |

---

## 二、Issue 根因定位

| # | 标题 | 类别 | 根因(已定位) | 涉及文件 | 状态 |
|---|---|---|---|---|---|
| **#5** | SQLite 死锁 | 后端 | `session.py:14-15` 完全没有 WAL + busy_timeout,长事务独占写锁 | `app/db/session.py` | ✅ **已修复 (2026-06-16)** |
| **#7** | 预警无法确认 | **前端** | 后端 `confirm_alert`/`ignore_alert` 完美,只是 `static/alerts.js` 没渲染确认/忽略按钮 | `backend/static/alerts.js` |
| **#8** | 报告中心按钮无反应 | **前端** | 后端 `POST /api/reports` + `BackgroundTasks` 完整,JS 事件未绑定或回调未刷新列表 | `backend/static/reports.js` |
| **#6** | 无法生成报告 | 前端+后端 | 同 #8,后端 `process_report_task` 在 #5 死锁时会被 timeout 牵连失败 | `reports.js` + `reports.py` |
| **#4** | 情绪分析错误 | 后端 | `KeywordNlpProvider` 是**简单关键词计数器**,词典 ~50 词,不覆盖"不是正面""也不是负面"这类反讽/否定句 | `app/services/nlp/keyword.py` |
| **#3** | 数据源无删除 | **前端+后端** | `api/datasources.py` **缺 `DELETE` 端点**,前端也无删除按钮 | `app/api/datasources.py` + `static/datasources.js` | ✅ DONE 2026-06-17 — 新增删除 API、列表删除按钮；支持勾选后级联删除历史舆情及相关数据 |
| **#1** | 微博抓取失败 | **配置/UX** | 不是 bug。用户用了 `api.weibo.com` OAuth 接口(需要鉴权),但 `WeiboConnector` 设计是消费 JSON feed。错误消息已经说明了 | 文档 + 前端表单提示 |
| **#2** | RSS 抓取失败 | **配置/UX** | 不是 bug。用户填的 `https://rss.sina.com.cn/news/allnews/roll.xml` **新浪已下线**(404),需要换成有效 RSS | 文档 + 前端可用 RSS 列表 |

---

## 三、Issue 依赖关系图

```
                       [✅] #5 (SQLite 死锁)  ──── 根因,已修复(2026-06-16)
                       /        |        \
                      v         v         v
              #6 生成报告   #8 报告按钮   #1/#2/#3 数据源相关
              (BackgroundTask (前端无刷新
               长事务易被     + 后端 500)
               锁等待超时)

#7 预警按钮  ── 独立的前端 bug
#4 情绪分析  ── 独立的 NLP 词典问题
#3 数据源删  ── 独立的 API+前端缺失
#1 微博抓取  ── 独立的文档/UX 问题
#2 RSS 抓取  ── 独立的文档/UX 问题
```

**关键依赖链**:`#5` 已修复,`#6` 和 `#8` 中**因为死锁导致的部分 500 错误会自动消失**;但它们的**前端 bug** 仍然存在,需要单独修。

---

## 四、推荐修复顺序

### 🚦 P0 — 第一优先(阻塞性问题,改 1 个文件)

#### 1. #5 SQLite WAL + busy_timeout ✅
- **位置**:`backend/app/db/session.py`
- **方案**:issue 里已给出完整代码,实际实现按其微调
- **改动要点**:
  - 注入 `event.listens_for(engine, "connect")` 钩子
  - `PRAGMA journal_mode=WAL`
  - `PRAGMA synchronous=NORMAL`
  - `PRAGMA busy_timeout=30000`
  - `connect_args["timeout"] = 30.0`
  - 抽出辅助函数 `register_sqlite_pragmas(engine)`,供生产 engine 和测试
    conftest 的临时 engine 复用,保证两边 PRAGMA 配置一致
  - 测试 conftest 在创建 `test_engine` 时同步把 `timeout=30.0` 写进
    `connect_args` 并调用 `register_sqlite_pragmas(test_engine)`
- **新增回归测试**:`backend/tests/test_db.py`(8 用例)
  - `test_journal_mode_is_wal` / `test_synchronous_is_normal` /
    `test_busy_timeout_is_30s` — 三个 PRAGMA 真实生效
  - `test_concurrent_read_during_write_does_not_block_or_error` — 一个
    线程持有 ~1.5s 写事务,另一线程 SELECT 必须 < 1s 返回(WAL 行为),
    且无 `OperationalError`
- **验证结果**(在 conda 环境 `yuqing-test` 下):
  - `pytest tests/test_db.py -v` → **8 passed in 3.79s**
  - `pytest`(全量) → **310 passed in 222.08s**
- **预期影响**:`#6` 中至少 50% 的"无法生成报告"会自然恢复

### 🚦 P1 — 第二批(纯前端 bug,各自独立)

#### 2. #7 预警无法确认 *(独立,纯前端)*
- 改 `backend/static/alerts.js`
- 在 pending 行增加"确认"和"忽略"按钮
- 调用 `POST /api/alerts/{id}/confirm` 和 `/ignore`
- 后端 API 已经完整,不用改 Python
- 工单管理查不到数据很可能就是这个 bug 的连锁影响

#### 3. #8 报告中心按钮无反应 *(独立,纯前端,可能与 #5 联动)*
- 改 `backend/static/reports.js`
- 绑定按钮事件、提交后显示 loading、完成后刷新列表
- 配合 #5 修复后再验证一遍

#### 4. #6 无法生成报告 *(在 #5 修完后再确认)*
- 改完 #5 之后跑一次:管理员和风控登录 → 创建报告 → 看返回
- 如果仍失败,大概率就是 #8 的前端 bug 没把请求发出去
- 后端 `process_report_task` 在 #5 修完后应该能正常工作

### 🚦 P2 — 第三批(后端 bug + API 缺失)

#### 5. #3 数据源无删除 *(小范围,前后端都要加)*
- `app/api/datasources.py`:加 `DELETE /api/datasources/{id}` 端点(参考 `PATCH` 写法)
- `static/datasources.js` + `templates/datasources.html`:加删除按钮 + 二次确认
- 注意:关联 `OpinionItem` 的删除策略(级联 / 软删 / 拒绝)

#### 6. #4 情绪分析错误 *(NLP 词典扩展,或换 provider)*
- **短期方案**:扩 `app/services/nlp/keyword.py` 的 `_NEGATIVE_TOKENS` / `_POSITIVE_TOKENS` 词典,加上"不是"、"并非"、"不是正面评价"等否定/反讽模式
- **长期方案**:把 `BaseNlpProvider` 切换到外部 API(LLM/百度/腾讯情感分析),保留 `KeywordNlpProvider` 作为离线 fallback
- 还要在 `_token_count` 里加否定词检测("不"+ 正面词 → 负面)

### 🚦 P3 — 最后一批(用户教育 / UX,改不改代码都行)

#### 7. #1 微博抓取失败 *(无需改代码)*
- 在 `templates/datasources.html` 新增数据源表单旁边加提示:"微博需自行部署 JSON 中转服务,公开 weibo.com 接口需登录,不支持"
- 在 README 里加 "如何接入微博" 章节,提供一个 mock JSON URL 示例

#### 8. #2 RSS 抓取失败 *(无需改代码)*
- 同上,在新增数据源表单加"测试 RSS 链接"按钮(调 `POST /api/datasources/test-rss` 之类)
- 提供几个稳定的公开 RSS 列表作为示例(知乎日报、V2EX、36kr 等)
- 考虑加"添加前 URL 健康检查"

---

## 五、执行策略与预估

| 阶段 | 工作量 | Issue | 备注 |
|---|---|---|---|
| **Sprint 1**(单文件改动) | 1-2h | #5 | 改动 ≤ 30 行,跑回归测试 |
| **Sprint 2**(纯前端) | 1-2d | #7、#8、#6 | 三个都是前端 JS,可并行 |
| **Sprint 3**(前后端 + NLP) | 2-3d | #3、#4 | 删除 API + 词典扩展 |
| **Sprint 4**(UX 文档) | 0.5d | #1、#2 | README + 表单提示 |

**总预估**:4-6 天可全部关闭。

**关键建议**:**先修 #5** —— 因为它会"吃掉"其他 issue 的真实错误(把超时 500 误报为"按钮无反应")。如果跳过 #5 直接修前端,后续验证会很困难。

---

## 六、验证清单

修复每个 issue 后,需要跑以下验证:

- [x] **#5**:`pytest tests/test_db.py -v` → 8 passed;`pytest` → 310 passed(均在 conda 环境 `yuqing-test` 下)
- [ ] **#7**:管理员 / 风控账号登录,创建 pending 预警,点确认 / 忽略按钮 → 数据库状态翻转
- [ ] **#8 / #6**:管理员登录 → 创建报告 → 看 `reports.js` 控制台 → 后端日志 `report.create` audit 行
- [x] **#3**:删除数据源 → 无关联数据可删除并刷新列表;勾选后可级联删除历史舆情、分析结果、预警和工单
- [ ] **#4**:`pytest tests/test_nlp.py -k negative` + 手动跑"这个不是正面的评价"应判负
- [ ] **#1 / #2**:README 步骤走一遍能否复现 / 解决

---

## 七、参考资源

- 仓库:https://github.com/Jiezheng007/new
- Issue 列表:`gh issue list --state all`
- 数据库 session 配置:`backend/app/db/session.py`
- 数据库回归测试:`backend/tests/test_db.py`
- NLP 提供者:`backend/app/services/nlp/`
- 报告中心代码:`backend/app/services/reports.py`
- 预警生命周期:`backend/app/services/alerts.py`
- 测试环境规则:`CLAUDE.md`(所有 pytest 必须在 conda 环境 `yuqing-test` 下)
