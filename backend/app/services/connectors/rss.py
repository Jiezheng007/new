"""RSS/Atom connector (Phase 3 / Issue 4).

Pulls an RSS or Atom feed over HTTP and normalizes entries into ``RawRecord``
shape. Requires the optional ``feedparser`` dependency; if it is not installed
the connector raises a clear ``ConnectorError`` rather than crashing the
request. This keeps the runtime lean for tests and the demo while still
letting real RSS sources work when feedparser is present.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from app.models.datasource import DataSource
from app.services.connectors import BaseConnector, ConnectorError, RawRecord


def _parse_dt(value: Any) -> object:
    """Best-effort datetime parsing - returns the original value if feedparser
    already produced a struct_time/datetime; otherwise returns ``None``."""
    if value is None:
        return None
    # feedparser returns time.struct_time for published/updated; we don't need
    # to import struct explicitly because callers accept datetime or string.
    return value


class RssConnector(BaseConnector):
    source_type = "rss"

    def fetch(self, source: DataSource) -> list[RawRecord]:
        if not source.url:
            raise ConnectorError(f"Data source '{source.code}' has no URL configured")
        try:
            import feedparser  # type: ignore
        except ImportError as e:
            raise ConnectorError(
                "RSS ingestion requires the optional 'feedparser' dependency. "
                "Install it with `pip install feedparser`."
            ) from e

        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                resp = client.get(source.url)
                resp.raise_for_status()
                content = resp.content
        except httpx.HTTPError as e:
            raise ConnectorError(f"Failed to fetch RSS feed '{source.url}': {e}") from e

        try:
            parsed = feedparser.parse(content)
        except Exception as e:  # feedparser is permissive but guard anyway
            raise ConnectorError(f"Failed to parse RSS feed '{source.url}': {e}") from e

        if getattr(parsed, "bozo", False) and not parsed.entries:
            raise ConnectorError(
                f"RSS feed '{source.url}' could not be parsed: {getattr(parsed, 'bozo_exception', 'unknown')}"
            )

        records: list[RawRecord] = []
        for entry in parsed.entries:
            external_id = (
                entry.get("id")
                or entry.get("link")
                or entry.get("title", "")
            )
            published = _parse_dt(entry.get("published_parsed") or entry.get("updated_parsed"))
            raw_payload = {
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "summary": entry.get("summary", ""),
            }
            records.append(RawRecord(
                external_id=str(external_id)[:256],
                title=str(entry.get("title", ""))[:512],
                content=str(entry.get("summary", "")),
                url=str(entry.get("link", ""))[:512],
                author=str(entry.get("author", ""))[:128],
                language=str(entry.get("language", "zh") or "zh")[:16],
                published_at=published,
                raw_payload=raw_payload,
            ))
        return records
