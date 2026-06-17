"""Keyword-driven news search providers.

The first provider is intentionally local and deterministic. It gives the
product a safe, low-cost keyword-monitoring path for demos/tests while keeping
the integration boundary ready for a compliant external news API later.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from app.core.config import get_settings
from app.services.connectors import ConnectorError


@dataclass(frozen=True)
class NewsSearchResult:
    external_id: str
    title: str
    content: str
    url: str
    author: str = "示例新闻"
    published_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class BaseNewsSearchProvider:
    def search(
        self,
        *,
        query: str,
        language: str = "zh",
        region: str = "CN",
        limit: int = 50,
    ) -> list[NewsSearchResult]:
        raise NotImplementedError


class MockNewsSearchProvider(BaseNewsSearchProvider):
    """Deterministic provider for local demo and tests.

    It does not crawl the web. It produces plausible news snippets that still
    flow through dedup, NLP, scoring and alerting exactly like real provider
    results would.
    """

    def search(
        self,
        *,
        query: str,
        language: str = "zh",
        region: str = "CN",
        limit: int = 50,
    ) -> list[NewsSearchResult]:
        normalized = " ".join((query or "").split())
        if not normalized:
            raise ConnectorError("新闻关键词不能为空")
        count = max(0, min(int(limit or 50), 100))
        now = datetime.now(timezone.utc).replace(microsecond=0)
        encoded = quote(normalized)
        templates = [
            ("{q} 发生重大安全事故,监管部门已介入调查", "多名用户投诉存在严重问题,疑似数据泄露和违规处理,舆论风险快速升温。"),
            ("{q} 最新进展:监管部门提示企业重视用户反馈", "公开报道显示,相关主体已开始回应争议并评估整改措施。"),
            ("{q} 舆情观察:社交平台讨论热度持续增加", "新闻摘要显示,事件传播范围扩大,负面观点与中性讨论并存。"),
            ("{q} 行业报道:类似问题引发风险管理讨论", "业内人士认为应加强信息披露、售后响应和风险沟通。"),
        ]
        results: list[NewsSearchResult] = []
        for idx in range(count):
            title_tpl, content = templates[idx % len(templates)]
            external_id = f"mock-news-{encoded}-{idx + 1}"
            results.append(NewsSearchResult(
                external_id=external_id,
                title=title_tpl.format(q=normalized),
                content=f"{content} 关键词: {normalized}",
                url=f"https://news.example.test/search/{encoded}/{idx + 1}",
                author="Mock News",
                published_at=now,
                raw={
                    "provider": "mock_news_search",
                    "query": normalized,
                    "language": language,
                    "region": region,
                    "rank": idx + 1,
                },
            ))
        return results


def get_news_search_provider() -> BaseNewsSearchProvider:
    provider = get_settings().news_search_provider.strip().lower()
    if provider == "mock":
        return MockNewsSearchProvider()
    raise ConnectorError(
        f"新闻搜索服务未配置或不支持: {provider}. 请将 NEWS_SEARCH_PROVIDER 配置为 mock 或接入合规新闻 API。"
    )
