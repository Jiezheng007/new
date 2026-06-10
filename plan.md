# 微博数据源适配与自动拉取计划

## 1. 背景与目标

当前系统已经采用“数据源适配器 + 统一舆情数据格式”的设计。RSS、JSON URL、内置演示数据都通过连接器转换为统一的 `RawRecord`，再进入清洗、去重、入库、分析、预警和工单流程。

微博数据源也应继续沿用这一设计，不建议在核心业务流程中直接写微博平台专用逻辑。

近期目标：

- 支持微博风格 JSON 数据源。
- 支持后台定时自动拉取启用的数据源。
- 拉取结果自动进入现有舆情分析和风险预警流程。
- 保证课程演示稳定，不依赖真实微博网页、登录态或反爬绕过。

后续扩展目标：

- 可接入微博官方 API、第三方采集服务或内部采集代理。
- 可在合规和稳定性可控的前提下支持真实微博网页采集。
- 可扩展微博热度字段，用于风险评分和趋势分析。

## 2. 为什么不直接抓取真实微博网页

真实微博网页，例如：

```text
https://weibo.com/u/7791585071
```

并不是稳定的数据接口，而是面向浏览器的页面。直接抓取存在以下问题：

- 登录态要求：很多内容需要 Cookie 或登录状态，未登录可能跳转到登录页。
- 反爬限制：请求频率、User-Agent、浏览器指纹、Cookie 状态都可能触发限制。
- 前端渲染：页面本身不一定包含完整微博列表，数据常由前端接口异步加载。
- 接口不稳定：内部接口参数和返回结构没有公开契约，后续容易失效。
- Cookie 维护：即使配置 Cookie，也会过期，需要人工更新。
- 演示不稳定：课程答辩时可能因为网络、账号、平台策略变化导致功能失败。
- 合规风险：需要注意平台条款、访问频率和公开数据使用边界。

因此，课程作业阶段采用“微博 JSON 适配器 + 定时拉取”更稳妥；真实微博网页采集作为后续扩展能力描述。

## 3. 近期方案：微博 JSON 适配器

### 3.1 数据源配置

新增或使用已有的数据源类型：

```text
source_type = "weibo"
```

数据源 URL 必须返回 JSON，而不是微博 HTML 页面。

示例 URL：

```text
http://127.0.0.1:8000/static/demo/weibo_sample.json
```

### 3.2 支持的 JSON 结构

连接器支持以下常见结构：

```json
{
  "statuses": []
}
```

```json
{
  "data": {
    "statuses": []
  }
}
```

```json
[
  {}
]
```

每条微博记录建议包含：

```json
{
  "idstr": "weibo-demo-001",
  "text_raw": "网友爆料某品牌产品存在严重质量问题,监管部门已介入调查。",
  "created_at": "2026-06-08T10:00:00+00:00",
  "user": {
    "id": "1001",
    "screen_name": "微博用户A"
  },
  "reposts_count": 12,
  "comments_count": 8,
  "attitudes_count": 99
}
```

### 3.3 字段映射

微博 JSON 记录统一转换为系统内部 `RawRecord`：

| 微博字段 | 系统字段 | 说明 |
| --- | --- | --- |
| `idstr` / `mid` / `id` | `external_id` | 外部 ID |
| `text_raw` / `text` / `content` | `content` | 微博正文 |
| 正文前 80 字或 `title` | `title` | 舆情标题 |
| `user.screen_name` | `author` | 作者 |
| `created_at` / `published_at` | `published_at` | 发布时间 |
| `url` / `scheme` / 自动拼接 | `url` | 原文链接 |
| 完整记录 | `raw_payload` | 保留平台特有字段 |

转发数、评论数、点赞数等字段暂时保存在 `raw_payload` 中，不急于扩展数据库表。

## 4. 近期方案：后台定时自动拉取

### 4.1 目标

后台自动任务每隔 N 分钟扫描所有启用的数据源，并执行抓取。

自动拉取范围：

```text
rss
json_url
weibo
static_demo
```

不自动拉取：

```text
csv
json_import
```

原因是 CSV 和 JSON Import 属于上传导入型数据源，不应该由后台定时抓取。

### 4.2 推荐模块拆分

新增抓取服务：

```text
backend/app/services/datasource_fetch.py
```

职责：

- 根据 `source_type` 获取连接器。
- 调用 `ingest_via_connector()`。
- 更新 `latest_fetch_at`、`latest_fetch_status`、`latest_fetch_message`、`latest_items_count`。
- 对新增舆情调用 `analyze_batch()`。
- 记录审计日志。

手动抓取和自动抓取都复用它。

建议函数：

```python
def fetch_datasource(db, source, *, actor=None, origin="manual"):
    ...
```

手动接口：

```text
POST /api/datasources/{id}/fetch
  -> fetch_datasource(db, source, actor=admin, origin="manual")
```

自动任务：

```text
scheduler loop
  -> fetch_datasource(db, source, actor=None, origin="scheduled")
```

### 4.3 新增调度模块

新增：

```text
backend/app/services/scheduler.py
```

职责：

- 应用启动时创建后台任务。
- 每隔固定时间扫描启用数据源。
- 串行或小批量执行抓取。
- 捕获单个数据源异常，避免一个源失败导致整个循环退出。
- 防止上一轮未结束时下一轮重复执行。

伪代码：

```python
AUTO_FETCH_TYPES = {"rss", "json_url", "weibo", "static_demo"}
_running = False

async def scheduler_loop():
    while True:
        await asyncio.sleep(settings.scheduler_interval_seconds)
        await run_once()

async def run_once():
    global _running
    if _running:
        return
    _running = True
    try:
        with SessionLocal() as db:
            sources = (
                db.query(DataSource)
                .filter(DataSource.is_enabled == True)
                .filter(DataSource.source_type.in_(AUTO_FETCH_TYPES))
                .all()
            )
            for source in sources:
                try:
                    fetch_datasource(db, source, actor=None, origin="scheduled")
                    db.commit()
                except Exception:
                    db.rollback()
                    # 记录失败状态和日志
    finally:
        _running = False
```

### 4.4 配置项

在：

```text
backend/app/core/config.py
```

增加：

```python
scheduler_enabled: bool = True
scheduler_interval_seconds: int = 300
scheduler_fetch_batch_limit: int = 20
```

`.env` 示例：

```env
SCHEDULER_ENABLED=true
SCHEDULER_INTERVAL_SECONDS=300
SCHEDULER_FETCH_BATCH_LIMIT=20
```

课程演示时可以将间隔改短：

```env
SCHEDULER_INTERVAL_SECONDS=30
```

### 4.5 FastAPI 启动集成

在 `create_app()` 的 startup 中启动调度器：

```python
@app.on_event("startup")
def _on_startup() -> None:
    init_db()
    start_scheduler_if_enabled()
```

注意：

- 测试环境应允许关闭 scheduler，避免测试不稳定。
- 可以通过环境变量 `SCHEDULER_ENABLED=false` 关闭。

## 5. 审计与状态记录

自动抓取也应写审计日志。

建议审计内容：

```json
{
  "code": "weibo_demo",
  "origin": "scheduled",
  "accepted": 2,
  "rejected": 0,
  "duplicate": 1,
  "analyzed": 2
}
```

状态字段继续复用 `data_sources` 表：

- `latest_fetch_at`
- `latest_fetch_status`
- `latest_fetch_message`
- `latest_items_count`

`latest_fetch_status` 建议取值：

```text
success
partial
failure
```

## 6. 测试计划

### 6.1 微博 JSON 适配器测试

覆盖：

- 可以创建 `source_type=weibo` 的数据源。
- 缺少 URL 时返回 422。
- 微博 JSON 抓取后能入库。
- 重复抓取能去重。
- HTML 页面或非 JSON 响应给出明确错误。

### 6.2 自动拉取测试

覆盖：

- 自动任务只抓取启用数据源。
- 自动任务跳过停用数据源。
- 自动任务跳过 `csv` 和 `json_import`。
- 自动任务抓取微博 JSON 后能入库并触发分析。
- 单个数据源失败不会影响其他数据源。
- 上一轮未结束时不会重复启动下一轮。

### 6.3 演示测试

演示步骤：

1. 启动系统。
2. 新增微博数据源，URL 使用：

   ```text
   http://127.0.0.1:8000/static/demo/weibo_sample.json
   ```

3. 等待自动任务执行，或将间隔设为 30 秒。
4. 查看数据源最近抓取状态。
5. 查看舆情列表中出现微博数据。
6. 查看高风险内容是否进入预警流程。

## 7. 后续扩展：真实微博采集

真实微博采集不直接写入当前 `WeiboConnector`，建议作为独立适配器或外部采集服务。

可选路线：

### 7.1 官方 API

优点：

- 合规性和稳定性较好。
- 返回结构更清晰。
- 便于控制权限和频率。

限制：

- 需要申请接口权限。
- 可访问的数据范围可能有限。

### 7.2 第三方采集服务

优点：

- 系统只需要对接稳定 JSON API。
- 复杂的登录、反爬、解析由外部服务处理。
- 便于课程系统保持简洁。

限制：

- 依赖第三方服务可用性。
- 可能有费用和合规要求。

### 7.3 内部采集代理

架构：

```text
真实微博网页 / 移动端接口
        ↓
内部采集代理
        ↓
标准微博 JSON
        ↓
本系统 WeiboConnector
```

优点：

- 主系统不用关心微博反爬细节。
- 代理可以独立维护 Cookie、限流、重试和解析逻辑。
- 主系统仍保持“JSON 适配器 + 标准格式”的稳定设计。

限制：

- 需要额外维护一个采集服务。
- 需要处理账号、Cookie、访问频率和合规边界。

## 8. 推荐里程碑

### 阶段一：稳定演示版

- 完成微博 JSON 适配器。
- 提供内置 `weibo_sample.json`。
- 支持手动抓取。
- 文档说明不能直接填微博网页。

### 阶段二：自动拉取版

- 抽取 `fetch_datasource()` 服务。
- 新增后台 scheduler。
- 支持配置自动拉取间隔。
- 补充自动拉取测试。

### 阶段三：平台能力增强

- 将转发、评论、点赞等热度字段纳入风险评分。
- 在舆情详情中展示微博原始互动信息。
- 支持按微博作者、话题、热度筛选。

### 阶段四：真实微博采集扩展

- 评估官方 API、第三方服务或内部代理。
- 将真实采集结果统一转换为微博 JSON。
- 保持主系统只消费标准 JSON，不直接承担网页反爬逻辑。

## 9. 结论

课程作业阶段推荐采用：

```text
微博 JSON 适配器 + 后台定时自动拉取
```

真实微博网页采集作为后续扩展：

```text
官方 API / 第三方采集服务 / 内部采集代理
```

这样既能体现系统的扩展设计，又能保证演示稳定、代码边界清晰、后续演进空间充分。
