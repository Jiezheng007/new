"""Opinion-item ingestion pipeline (Phase 3 / Issues 4 and 5).

Single funnel for any source - RSS, JSON URL, built-in static demo, CSV
upload, JSON upload. Steps:

  1. Pull normalized ``RawRecord`` objects from a connector / parser.
  2. Clean + validate each record (reject blank titles, etc).
  3. Compute a stable ``content_hash`` and reject duplicates already stored
     for the same source.
  4. Persist the surviving records as ``OpinionItem`` rows.
  5. Return per-batch counts so callers can surface them in the UI/audit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session

from app.models.datasource import DataSource, OpinionItem
from app.services.connectors import BaseConnector, RawRecord


@dataclass
class IngestionResult:
    accepted: int = 0
    rejected: int = 0
    duplicate: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    sample_ids: list[int] = field(default_factory=list)


class IngestionError(Exception):
    """Raised when the entire fetch failed (network, parse, unsupported source)."""


def ingest_records(
    db: Session,
    source: DataSource,
    records: Iterable[RawRecord],
    origin: str,
) -> IngestionResult:
    """Persist a stream of records under the given source. Caller commits."""
    result = IngestionResult()
    # Pre-load existing hashes for this source so we can detect duplicates in
    # one query rather than per-record.
    existing_hashes: set[str] = {
        row[0]
        for row in db.query(OpinionItem.content_hash)
        .filter(OpinionItem.source_id == source.id)
        .all()
    }

    for index, record in enumerate(records):
        try:
            cleaned = _clean_record(record, index)
        except _RecordRejected as e:
            result.rejected += 1
            result.errors.append({"index": index, "reason": str(e)})
            continue

        if not cleaned.title:
            result.rejected += 1
            result.errors.append({"index": index, "reason": "empty_title"})
            continue

        content_hash = BaseConnector.compute_content_hash(source.code, cleaned.title, cleaned.content)
        if content_hash in existing_hashes:
            result.duplicate += 1
            result.errors.append({"index": index, "reason": "duplicate", "content_hash": content_hash})
            continue

        item = OpinionItem(
            source_id=source.id,
            source_code=source.code,
            source_type=source.source_type,
            external_id=cleaned.external_id,
            title=cleaned.title,
            content=cleaned.content,
            url=cleaned.url,
            author=cleaned.author,
            language=cleaned.language,
            published_at=cleaned.published_at,
            content_hash=content_hash,
            origin=origin,
            raw_payload=_serialize_payload(cleaned.raw_payload),
        )
        db.add(item)
        db.flush()
        result.accepted += 1
        result.sample_ids.append(item.id)
        existing_hashes.add(content_hash)
    return result


def ingest_via_connector(
    db: Session,
    source: DataSource,
    connector: BaseConnector,
    origin: str,
) -> IngestionResult:
    """Run a connector, then funnel its records through ``ingest_records``."""
    records = connector.fetch(source)
    return ingest_records(db, source, records, origin)


class _RecordRejected(Exception):
    pass


def _clean_record(record: RawRecord, index: int) -> RawRecord:
    if not isinstance(record, RawRecord):
        raise _RecordRejected("not_a_raw_record")
    title = (record.title or "").strip()
    content = (record.content or "").strip()
    if not title:
        raise _RecordRejected("empty_title")
    return RawRecord(
        external_id=(record.external_id or "").strip()[:256] or f"row-{index}",
        title=title[:512],
        content=content,
        url=(record.url or "").strip()[:512],
        author=(record.author or "").strip()[:128],
        language=(record.language or "zh")[:16] or "zh",
        published_at=record.published_at,
        raw_payload=record.raw_payload or {},
    )


def _serialize_payload(payload: Any) -> str:
    import json

    try:
        return json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(payload)
