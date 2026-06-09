"""JSON-URL connector (Phase 3 / Issue 4).

Accepts a URL that returns a JSON array of records, where each record is
either already in normalized form (``title``/``content``/``url``/...) or uses
the same field names as the CSV import. This lets the demo pull demo data
from a small public JSON host (or a local file served by FastAPI's static
mount) without requiring RSS infrastructure.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.models.datasource import DataSource
from app.services.connectors import BaseConnector, ConnectorError, RawRecord


class JsonUrlConnector(BaseConnector):
    source_type = "json_url"

    def fetch(self, source: DataSource) -> list[RawRecord]:
        if not source.url:
            raise ConnectorError(f"Data source '{source.code}' has no URL configured")
        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                resp = client.get(source.url)
                resp.raise_for_status()
                payload = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ConnectorError(f"Failed to fetch JSON feed '{source.url}': {e}") from e

        if not isinstance(payload, list):
            raise ConnectorError(
                f"JSON feed '{source.url}' must be a JSON array, got {type(payload).__name__}"
            )
        return [_coerce(item) for item in payload]


def _coerce(item: Any) -> RawRecord:
    if not isinstance(item, dict):
        raise ConnectorError("JSON record must be an object")
    return RawRecord(
        external_id=str(item.get("external_id") or item.get("id") or "")[:256],
        title=str(item.get("title", ""))[:512],
        content=str(item.get("content", "")),
        url=str(item.get("url", ""))[:512],
        author=str(item.get("author", ""))[:128],
        language=str(item.get("language", "zh") or "zh")[:16],
        published_at=item.get("published_at"),
        raw_payload=item,
    )
