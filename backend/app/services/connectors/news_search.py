"""Connector for keyword-driven news monitoring."""
from __future__ import annotations

import json
from typing import Any

from app.models.datasource import DataSource
from app.services.connectors import BaseConnector, ConnectorError, RawRecord
from app.services.news_search import NewsSearchResult, get_news_search_provider


class NewsSearchConnector(BaseConnector):
    source_type = "news_search"

    def fetch(self, source: DataSource) -> list[RawRecord]:
        query = (source.query or "").strip()
        if not query:
            raise ConnectorError(f"Data source '{source.code}' has no query configured")

        config = _load_config(source.config_json)
        provider = get_news_search_provider()
        results = provider.search(
            query=query,
            language=str(config.get("language") or "zh"),
            region=str(config.get("region") or "CN"),
            limit=source.max_items_per_fetch,
        )
        return [_coerce(item) for item in results]


def _load_config(value: str) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        raise ConnectorError(f"news_search config_json is not valid JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise ConnectorError("news_search config_json must be a JSON object")
    return parsed


def _coerce(item: NewsSearchResult) -> RawRecord:
    return RawRecord(
        external_id=str(item.external_id or item.url)[:256],
        title=str(item.title or "")[:512],
        content=str(item.content or item.title or ""),
        url=str(item.url or "")[:512],
        author=str(item.author or "")[:128],
        language="zh",
        published_at=item.published_at,
        raw_payload=item.raw,
    )
