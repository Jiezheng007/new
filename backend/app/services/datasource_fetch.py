"""Unified data-source fetch service (Phase 11 / Issue 14).

Both the manual ``POST /api/datasources/{id}/fetch`` endpoint and the
background scheduler call :func:`fetch_datasource`. The function:

  1. Resolves the connector for ``source.source_type``.
  2. Runs the connector and funnels the records through
     :func:`ingest_via_connector` so dedup / persistence stay in one place.
  3. Kicks off :func:`analyze_batch` for the freshly inserted opinions so
     new items enter the analysis + alert pipeline.
  4. Updates ``DataSource.latest_fetch_*`` status fields and writes an
     ``AuditLog`` row.

The function never raises for fetch/connector problems: those are
recorded as ``status="failure"`` on the source and an audit row. The
caller (manual API or scheduler) decides whether to surface the error
to the operator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.datasource import DataSource
from app.models.user import User
from app.services.analysis import analyze_batch, opinions_by_ids
from app.services.audit import record_audit
from app.services.connectors import (
    ALL_SOURCE_TYPES,
    ConnectorError,
    SOURCE_TYPE_CSV,
    SOURCE_TYPE_JSON_IMPORT,
    SOURCE_TYPE_STATIC_DEMO,
    get_connector,
)
from app.services.ingestion import IngestionResult, ingest_via_connector


# Source types that the background scheduler is allowed to auto-fetch.
# CSV / JSON imports are upload-driven, never auto-pulled.
AUTO_FETCH_TYPES: frozenset[str] = frozenset(
    t for t in ALL_SOURCE_TYPES if t not in {SOURCE_TYPE_CSV, SOURCE_TYPE_JSON_IMPORT}
)


ORIGIN_MANUAL = "manual"
ORIGIN_SCHEDULED = "scheduled"

# ``origin`` is what gets persisted on OpinionItem. We pass the same string
# the audit log uses so the two views stay aligned.
_VALID_ORIGINS = {ORIGIN_MANUAL, ORIGIN_SCHEDULED}


@dataclass
class FetchOutcome:
    """Result of one fetch attempt.

    Mirrors the fields the manual endpoint exposes so callers can decide
    what to do with the result without re-querying the database.
    """

    source: DataSource
    status: str
    accepted: int = 0
    rejected: int = 0
    duplicate: int = 0
    analyzed: int = 0
    failed_analysis: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""
    error: Optional[ConnectorError] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def fetch_datasource(
    db: Session,
    source: DataSource,
    *,
    actor: Optional[User] = None,
    origin: str = ORIGIN_MANUAL,
) -> FetchOutcome:
    """Run the connector for ``source`` and persist the result.

    ``actor`` is the user (admin) for manual fetches; the scheduler passes
    ``None``. ``origin`` is persisted on every ``OpinionItem`` and on the
    audit log so manual vs scheduled runs are visible in the review UI.
    """
    if origin not in _VALID_ORIGINS:
        raise ValueError(f"Invalid origin: {origin!r}")

    outcome = FetchOutcome(source=source, status="failure")

    try:
        connector = get_connector(source.source_type)
    except ConnectorError as e:
        outcome.message = str(e)
        outcome.error = e
        _write_status(db, source, "failure", message=outcome.message, items=0)
        record_audit(
            db,
            actor=actor,
            action="datasource.fetch",
            target_type="datasource",
            target_id=str(source.id),
            result="failure",
            detail={
                "code": source.code,
                "origin": origin,
                "reason": "unsupported_source_type",
                "error": str(e),
            },
        )
        return outcome

    try:
        result: IngestionResult = ingest_via_connector(db, source, connector, origin=origin)
    except ConnectorError as e:
        outcome.message = str(e)
        outcome.error = e
        _write_status(db, source, "failure", message=outcome.message, items=0)
        record_audit(
            db,
            actor=actor,
            action="datasource.fetch",
            target_type="datasource",
            target_id=str(source.id),
            result="failure",
            detail={
                "code": source.code,
                "origin": origin,
                "reason": "fetch_error",
                "error": str(e),
            },
        )
        return outcome

    outcome.accepted = result.accepted
    outcome.rejected = result.rejected
    outcome.duplicate = result.duplicate
    outcome.errors = list(result.errors)

    if result.sample_ids:
        opinions = opinions_by_ids(db, result.sample_ids)
        analyzed = analyze_batch(db, opinions)
        outcome.analyzed = sum(1 for r in analyzed if r.status == "success")
        outcome.failed_analysis = len(analyzed) - outcome.analyzed

    status = _classify_status(result, outcome.failed_analysis)
    message = (
        f"accepted={result.accepted} rejected={result.rejected} "
        f"duplicate={result.duplicate} "
        f"analyzed={outcome.analyzed} failed={outcome.failed_analysis}"
    )
    _write_status(db, source, status, message=message, items=result.accepted)
    outcome.status = status
    outcome.message = message

    audit_result = "success" if status == "success" else "partial"
    record_audit(
        db,
        actor=actor,
        action="datasource.fetch",
        target_type="datasource",
        target_id=str(source.id),
        result=audit_result,
        detail={
            "code": source.code,
            "origin": origin,
            "accepted": result.accepted,
            "rejected": result.rejected,
            "duplicate": result.duplicate,
            "analyzed": outcome.analyzed,
            "failed_analysis": outcome.failed_analysis,
        },
    )
    return outcome


def _classify_status(result: IngestionResult, failed_analysis: int) -> str:
    """Translate an IngestionResult + analysis counts into a status string."""
    if result.accepted == 0 and result.rejected == 0 and result.duplicate == 0:
        # Connector returned no records and no errors - this is the
        # "healthy empty feed" case. We still call it success.
        return "success"
    if result.rejected == 0 and failed_analysis == 0:
        return "success"
    if result.accepted > 0:
        return "partial"
    return "failure"


def _write_status(
    db: Session,
    source: DataSource,
    status: str,
    *,
    message: str,
    items: int,
) -> None:
    source.latest_fetch_at = datetime.now(timezone.utc)
    source.latest_fetch_status = status
    source.latest_fetch_message = (message or "")[:1000]
    source.latest_items_count = items
    db.flush()
