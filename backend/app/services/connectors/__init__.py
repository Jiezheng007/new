"""Connector framework for opinion-item ingestion (Phase 3 / Issues 4-5).

Every adapter normalizes the records it pulls out of the wild into the same
``RawRecord`` shape so the downstream ingestion pipeline can stay source-
agnostic. New public sources plug in by adding an entry to ``CONNECTOR_REGISTRY``
and implementing the :class:`BaseConnector` interface.

Static demo data and CSV/JSON import both feed through the same pipeline,
which keeps dedup / persistence / audit behaviour consistent.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Type

from app.models.datasource import DataSource


SOURCE_TYPE_RSS = "rss"
SOURCE_TYPE_JSON_URL = "json_url"
SOURCE_TYPE_STATIC_DEMO = "static_demo"
SOURCE_TYPE_CSV = "csv"
SOURCE_TYPE_JSON_IMPORT = "json_import"

ALL_SOURCE_TYPES: tuple[str, ...] = (
    SOURCE_TYPE_RSS,
    SOURCE_TYPE_JSON_URL,
    SOURCE_TYPE_STATIC_DEMO,
    SOURCE_TYPE_CSV,
    SOURCE_TYPE_JSON_IMPORT,
)


@dataclass
class RawRecord:
    """A single opinion item after connector-level normalization.

    ``raw_payload`` is the original dict/text the connector pulled out of the
    source so it can be stored alongside the normalized record for debugging
    and later full-text search.
    """

    external_id: str = ""
    title: str = ""
    content: str = ""
    url: str = ""
    author: str = ""
    language: str = "zh"
    published_at: Optional[datetime] = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


class ConnectorError(Exception):
    """Raised when a connector cannot complete a fetch."""


class BaseConnector:
    """Source-agnostic ingestion adapter.

    Subclasses implement :meth:`fetch` and return normalized records. The
    ingestion service handles hashing, dedup, and persistence.
    """

    source_type: str = ""

    def fetch(self, source: DataSource) -> list[RawRecord]:
        raise NotImplementedError

    @staticmethod
    def compute_content_hash(source_code: str, title: str, content: str) -> str:
        """SHA-256 hex of (source_code, title, content) - first 32 hex chars.

        The hash is the dedup fingerprint: re-fetching the same article from
        the same source produces the same hash, so duplicates are rejected
        even if external_id changes.
        """
        payload = f"{source_code}\x00{title.strip()}\x00{content.strip()}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:32]


def _get_connector_registry() -> dict[str, Type[BaseConnector]]:
    # Local import to avoid a circular dependency: connectors import models
    # only, and the registry is resolved at first use.
    from app.services.connectors import json_url, rss, static_demo  # noqa: F401

    return {
        SOURCE_TYPE_RSS: rss.RssConnector,
        SOURCE_TYPE_JSON_URL: json_url.JsonUrlConnector,
        SOURCE_TYPE_STATIC_DEMO: static_demo.StaticDemoConnector,
    }


def get_connector(source_type: str) -> BaseConnector:
    """Return a fresh connector instance for the given source type."""
    registry = _get_connector_registry()
    cls = registry.get(source_type)
    if cls is None:
        raise ConnectorError(f"Unsupported source type: {source_type!r}")
    return cls()
