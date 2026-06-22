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
from app.services.opinion_search import sync_opinion_fts_rows


HASH_LOOKUP_CHUNK_SIZE = 500
INGEST_FLUSH_BATCH_SIZE = 500


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

    cleaned_records: list[tuple[int, RawRecord, str]] = []
    incoming_hashes: set[str] = set()

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
        cleaned_records.append((index, cleaned, content_hash))
        incoming_hashes.add(content_hash)

    existing_hashes = _existing_hashes_for_batch(db, source.id, incoming_hashes)
    seen_hashes: set[str] = set()
    pending_items: list[OpinionItem] = []

    for index, cleaned, content_hash in cleaned_records:
        if content_hash in existing_hashes:
            result.duplicate += 1
            result.errors.append({"index": index, "reason": "duplicate", "content_hash": content_hash})
            continue
        if content_hash in seen_hashes:
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
        pending_items.append(item)
        result.accepted += 1
        seen_hashes.add(content_hash)
        if len(pending_items) >= INGEST_FLUSH_BATCH_SIZE:
            _flush_items(db, pending_items, result)
            pending_items = []

    if pending_items:
        _flush_items(db, pending_items, result)
    return result


def _flush_items(db: Session, items: list[OpinionItem], result: IngestionResult) -> None:
    db.add_all(items)
    db.flush()
    result.sample_ids.extend(item.id for item in items)
    sync_opinion_fts_rows(db, items)


def _existing_hashes_for_batch(db: Session, source_id: int, incoming_hashes: set[str]) -> set[str]:
    if not incoming_hashes:
        return set()
    out: set[str] = set()
    hashes = list(incoming_hashes)
    for start in range(0, len(hashes), HASH_LOOKUP_CHUNK_SIZE):
        chunk = hashes[start : start + HASH_LOOKUP_CHUNK_SIZE]
        rows = (
            db.query(OpinionItem.content_hash)
            .filter(OpinionItem.source_id == source_id)
            .filter(OpinionItem.content_hash.in_(chunk))
            .all()
        )
        out.update(row[0] for row in rows)
    return out


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
