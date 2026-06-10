"""Weibo JSON connector.

This adapter intentionally consumes a JSON endpoint instead of scraping Weibo
HTML directly. Real Weibo access often depends on login cookies, rate limits,
or an internal collection service, so the stable contract for this app is:
provide a URL that returns Weibo-like JSON and normalize it into RawRecord.
"""
from __future__ import annotations

import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any

import httpx

from app.models.datasource import DataSource
from app.services.connectors import BaseConnector, ConnectorError, RawRecord


class WeiboConnector(BaseConnector):
    source_type = "weibo"

    def fetch(self, source: DataSource) -> list[RawRecord]:
        if not source.url:
            raise ConnectorError(f"Data source '{source.code}' has no URL configured")

        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                resp = client.get(source.url)
                resp.raise_for_status()
                payload = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ConnectorError(f"Failed to fetch Weibo feed '{source.url}': {e}") from e

        items = _extract_items(payload)
        return [_coerce(item) for item in items]


def _extract_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise ConnectorError(
            f"Weibo feed must be a JSON object or array, got {type(payload).__name__}"
        )

    for key in ("statuses", "items", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return value

    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("statuses", "items", "records", "list"):
            value = data.get(key)
            if isinstance(value, list):
                return value

    raise ConnectorError("Weibo feed JSON must contain a list of statuses/items/records")


def _coerce(item: Any) -> RawRecord:
    if not isinstance(item, dict):
        raise ConnectorError("Weibo record must be an object")

    status = item.get("mblog") if isinstance(item.get("mblog"), dict) else item
    user = status.get("user") if isinstance(status.get("user"), dict) else {}
    text = _clean_text(
        status.get("text_raw")
        or status.get("text")
        or status.get("content")
        or status.get("title")
        or ""
    )
    title = _clean_text(status.get("title") or text[:80])
    external_id = status.get("idstr") or status.get("mid") or status.get("id") or ""
    url = (
        status.get("url")
        or status.get("scheme")
        or status.get("source_url")
        or _build_weibo_url(user, external_id)
    )

    return RawRecord(
        external_id=str(external_id)[:256],
        title=title[:512],
        content=text,
        url=str(url or "")[:512],
        author=str(user.get("screen_name") or status.get("author") or "")[:128],
        language="zh",
        published_at=_parse_datetime(status.get("created_at") or status.get("published_at")),
        raw_payload=item,
    )


def _clean_text(value: Any) -> str:
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None


def _build_weibo_url(user: dict[str, Any], external_id: Any) -> str:
    user_id = user.get("id") or user.get("idstr")
    if not user_id or not external_id:
        return ""
    return f"https://weibo.com/{user_id}/{external_id}"
