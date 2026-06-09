"""Built-in static demo data source (Phase 3 / Issue 4 fallback).

The course demo must work even when the public internet is unreachable, so
the app ships with one always-available ``static_demo`` source. It returns a
hand-curated set of opinion items that exercise every downstream component
(alert, ticket, report, audit) without depending on RSS feeds.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.datasource import DataSource
from app.services.connectors import BaseConnector, RawRecord


def _utc(year: int, month: int, day: int, hour: int = 9, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# Hand-curated demo items. Timestamps are anchored to "now - N hours" at
# fetch time so the dashboard's seven-day trend is non-empty in any demo run.
# Items 003 and 004 include clearly negative content + sensitive keywords so
# the risk-scoring pipeline (Phase 4) has a non-trivial demo path.
def _build_demo_records() -> list[RawRecord]:
    now = datetime.now(timezone.utc)
    return [
        RawRecord(
            external_id="demo-001",
            title="示例科技公司发布季度财报,营收同比增长 12%",
            content="示例科技公司今日发布最新季度财报,营收同比增长 12%,净利润略增。分析认为这是稳健的业务增长,但市场份额仍面临竞争。",
            url="https://example.com/news/demo-001",
            author="演示编辑",
            language="zh",
            published_at=now - timedelta(hours=2),
            raw_payload={"demo": True, "category": "财经"},
        ),
        RawRecord(
            external_id="demo-002",
            title="监管部门召开行业座谈会,强调合规经营",
            content="监管部门今日召开行业座谈会,要求相关企业严格遵守法律法规,强调合规经营的重要性,并对近期违规案例进行了通报。",
            url="https://example.com/news/demo-002",
            author="演示通讯",
            language="zh",
            published_at=now - timedelta(hours=5),
            raw_payload={"demo": True, "category": "监管"},
        ),
        RawRecord(
            external_id="demo-003",
            title="网友爆料:某品牌产品出现严重质量问题,监管部门已介入",
            content="多名网友在社交平台反映,某品牌产品在使用过程中出现严重质量问题,涉及安全事故,疑似重大隐患,呼吁监管部门介入调查。监管部门表示已启动核查程序,对该企业开展合规检查。",
            url="https://example.com/news/demo-003",
            author="演示用户",
            language="zh",
            published_at=now - timedelta(hours=8),
            raw_payload={"demo": True, "category": "消费"},
        ),
        RawRecord(
            external_id="demo-004",
            title="某公司被曝数据泄露事件,涉嫌违规被查处",
            content="某公司今日被曝发生用户数据泄露事件,涉及大量个人信息,监管部门已介入调查,初步认定涉嫌违规,责令其立即整改并公开通报。",
            url="https://example.com/news/demo-004",
            author="演示记者",
            language="zh",
            published_at=now - timedelta(hours=14),
            raw_payload={"demo": True, "category": "安全"},
        ),
        RawRecord(
            external_id="demo-005",
            title="行业领袖公开演讲,畅谈未来发展方向",
            content="在最近举行的行业峰会上,多位行业领袖发表主题演讲,共同探讨行业未来发展方向,以及技术创新的可能路径。",
            url="https://example.com/news/demo-005",
            author="演示观察",
            language="zh",
            published_at=now - timedelta(days=1, hours=2),
            raw_payload={"demo": True, "category": "行业"},
        ),
        RawRecord(
            external_id="demo-006",
            title="消费者反馈:服务体验显著提升",
            content="多位消费者在公开渠道反馈,近期某品牌的服务体验较此前有显著提升,客服响应速度和解决问题的能力都得到改善。",
            url="https://example.com/news/demo-006",
            author="演示用户",
            language="zh",
            published_at=now - timedelta(days=2),
            raw_payload={"demo": True, "category": "服务"},
        ),
    ]


class StaticDemoConnector(BaseConnector):
    source_type = "static_demo"

    def fetch(self, source: DataSource) -> list[RawRecord]:
        # The static demo is always available and never fails - that's its job.
        return _build_demo_records()
