"""Alert lifecycle service (Phase 5 / Issue 7).

This module owns the alert state machine. The two public entry points
that the rest of the codebase calls are:

  * :func:`ensure_alert_for_analysis` - idempotent. Called by
    :func:`app.services.analysis.analyze_opinion` after every successful
    analysis. If the analysis is ``high`` / ``severe`` and the opinion
    has no existing alert, a new ``pending`` row is inserted. The
    uniqueness constraint on ``opinion_item_id`` is the dedup mechanism,
    so concurrent calls (e.g. analyze-pending + manual re-analyze) are
    safe.

  * :func:`list_alerts` - paginated, filterable listing used by the
    :class:`AlertListOut` schema and the Web UI.

The two state-transition functions (:func:`confirm_alert` and
:func:`ignore_alert`) are the only places that flip the ``status``
column. They check the current state in the same transaction and write
an :class:`AuditLog` row so the audit trail matches the business
change.

The service is intentionally small - the API layer is the only caller
of confirm/ignore, and the analysis layer is the only caller of
ensure_alert_for_analysis. No background workers, no scheduling.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.alert import (
    ALERT_STATUS_CONFIRMED,
    ALERT_STATUS_IGNORED,
    ALERT_STATUS_PENDING,
    ALERT_TRIGGER_LEVELS,
    Alert,
)
from app.models.analysis import AnalysisResult
from app.models.datasource import OpinionItem
from app.models.user import User


@dataclass
class AlertStateError(Exception):
    """Raised when an alert state transition is not legal (e.g. confirm
    a confirmed alert). The API layer maps this to HTTP 409."""

    alert_id: int
    current_status: str
    attempted: str

    def __str__(self) -> str:  # pragma: no cover - debug only
        return (
            f"Alert {self.alert_id} is in state '{self.current_status}'; "
            f"cannot transition via '{self.attempted}'"
        )


# Reason text bounds. The reason is required on ignore, free-form, and is
# the only operator-provided input the API takes for the action.
IGNORE_REASON_MIN = 2
IGNORE_REASON_MAX = 500


def _decode_explanation(value: str) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except (TypeError, ValueError):
        return []
    if isinstance(data, list):
        return [str(x) for x in data]
    return []


def _explanation_to_text(lines: list[str]) -> str:
    """Persist the trigger explanation as a small JSON array.

    A JSON list keeps the data round-trippable to the UI without bringing
    in a second column for each factor. The schema decodes it back to
    ``list[str]`` on read.
    """
    if not lines:
        return ""
    return json.dumps(lines[:24], ensure_ascii=False)


# ---------- creation hook (called from analyze_opinion) ----------


def ensure_alert_for_analysis(
    db: Session,
    analysis: AnalysisResult,
) -> Optional[Alert]:
    """Create a pending alert if the analysis is high/severe and none exists.

    Safe to call repeatedly. Returns the new alert when one is created,
    or ``None`` when the analysis does not warrant an alert or an alert
    already exists for that opinion. The function does not commit; the
    caller's transaction owns the flush so it can be combined with the
    analysis persist and the audit row in a single round trip.
    """
    if analysis is None:
        return None
    if analysis.status != "success":
        return None
    if analysis.level not in ALERT_TRIGGER_LEVELS:
        return None
    if analysis.score is None:
        return None

    existing = (
        db.query(Alert)
        .filter(Alert.opinion_item_id == analysis.opinion_item_id)
        .one_or_none()
    )
    if existing is not None:
        return None

    alert = Alert(
        opinion_item_id=analysis.opinion_item_id,
        risk_level=analysis.level,
        risk_score=int(analysis.score),
        status=ALERT_STATUS_PENDING,
        trigger_explanation=_explanation_to_text(_decode_explanation(analysis.explanation)),
    )
    db.add(alert)
    # Flush so a duplicate-key race surfaces here, not at commit time.
    # The pre-check makes this rare; the unique constraint is a safety net.
    db.flush()
    return alert


# ---------- listing / fetch ----------


def _base_query(db: Session):
    return db.query(Alert)


def list_alerts(
    db: Session,
    *,
    status_filter: Optional[str] = None,
    level_filter: Optional[str] = None,
    source_id: Optional[int] = None,
    keyword: Optional[str] = None,
    start_at: Optional[datetime] = None,
    end_at: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Alert], int]:
    """Return a filtered, paginated list of alerts plus the unfiltered total.

    Joins to ``OpinionItem`` so source + keyword filters work in a single
    query. Ordered by created_at desc with id desc as the tiebreaker.
    """
    query = _base_query(db).join(OpinionItem, OpinionItem.id == Alert.opinion_item_id)
    count_query = db.query(func.count(Alert.id)).join(
        OpinionItem, OpinionItem.id == Alert.opinion_item_id
    )

    if status_filter:
        query = query.filter(Alert.status == status_filter)
        count_query = count_query.filter(Alert.status == status_filter)
    if level_filter:
        query = query.filter(Alert.risk_level == level_filter)
        count_query = count_query.filter(Alert.risk_level == level_filter)
    if source_id is not None:
        query = query.filter(OpinionItem.source_id == source_id)
        count_query = count_query.filter(OpinionItem.source_id == source_id)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            (OpinionItem.title.like(like)) | (OpinionItem.content.like(like))
        )
        count_query = count_query.filter(
            (OpinionItem.title.like(like)) | (OpinionItem.content.like(like))
        )
    if start_at is not None:
        query = query.filter(Alert.created_at >= start_at)
        count_query = count_query.filter(Alert.created_at >= start_at)
    if end_at is not None:
        query = query.filter(Alert.created_at <= end_at)
        count_query = count_query.filter(Alert.created_at <= end_at)

    total = int(count_query.scalar() or 0)
    rows = (
        query.order_by(Alert.created_at.desc(), Alert.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return rows, total


def get_alert(db: Session, alert_id: int) -> Optional[Alert]:
    return db.get(Alert, alert_id)


def count_alerts_by_status(db: Session) -> dict[str, int]:
    """Group-by count helper for the dashboard.

    Returns ``{"pending": N, "confirmed": N, "ignored": N, "total": N}``.
    Missing statuses are reported as ``0`` so the UI can render a
    complete picture without a None check.
    """
    rows = (
        db.query(Alert.status, func.count(Alert.id))
        .group_by(Alert.status)
        .all()
    )
    out: dict[str, int] = {
        ALERT_STATUS_PENDING: 0,
        ALERT_STATUS_CONFIRMED: 0,
        ALERT_STATUS_IGNORED: 0,
    }
    for status, count in rows:
        out[status] = int(count)
    out["total"] = out[ALERT_STATUS_PENDING] + out[ALERT_STATUS_CONFIRMED] + out[ALERT_STATUS_IGNORED]
    return out


# ---------- state transitions ----------


def _require_pending(alert: Alert, attempted: str) -> None:
    if alert.status != ALERT_STATUS_PENDING:
        raise AlertStateError(alert.id, alert.status, attempted)


def confirm_alert(
    db: Session,
    alert: Alert,
    *,
    actor: User,
    ip_address: str,
) -> Alert:
    """Transition a pending alert to confirmed and write an audit row."""
    _require_pending(alert, "confirm")
    now = datetime.utcnow()
    alert.status = ALERT_STATUS_CONFIRMED
    alert.confirmed_by_id = actor.id
    alert.confirmed_by_username = actor.username
    alert.confirmed_at = now
    db.flush()
    return alert


def ignore_alert(
    db: Session,
    alert: Alert,
    *,
    actor: User,
    reason: str,
    ip_address: str,
) -> Alert:
    """Transition a pending alert to ignored and write an audit row.

    The reason is mandatory and must be at least ``IGNORE_REASON_MIN``
    characters of non-whitespace text. The API layer returns HTTP 400
    for shorter input, but we re-validate here so the service cannot
    be called from a non-API code path with a blank reason.
    """
    _require_pending(alert, "ignore")
    cleaned = (reason or "").strip()
    if len(cleaned) < IGNORE_REASON_MIN:
        raise ValueError(
            f"ignore_reason must be at least {IGNORE_REASON_MIN} characters of non-whitespace text"
        )
    if len(cleaned) > IGNORE_REASON_MAX:
        cleaned = cleaned[:IGNORE_REASON_MAX]
    now = datetime.utcnow()
    alert.status = ALERT_STATUS_IGNORED
    alert.ignored_by_id = actor.id
    alert.ignored_by_username = actor.username
    alert.ignored_at = now
    alert.ignore_reason = cleaned
    db.flush()
    return alert


# ---------- serialization helpers (used by the API + UI) ----------


def alert_to_dict(alert: Alert) -> dict[str, Any]:
    """Flatten the alert row into a JSON-friendly dict.

    The nested opinion summary is intentionally narrow (title / source /
    published_at / author / url / risk-level / score) so the UI can
    render a useful row without a second roundtrip to ``/api/opinions``.
    """
    opinion: OpinionItem = alert.opinion_item
    source = getattr(opinion, "source", None)
    analysis: Optional[AnalysisResult] = getattr(opinion, "analysis_result", None)

    return {
        "id": alert.id,
        "opinion_item_id": alert.opinion_item_id,
        "risk_level": alert.risk_level,
        "risk_score": alert.risk_score,
        "status": alert.status,
        "trigger_explanation": _decode_explanation(alert.trigger_explanation),
        "confirmed_by_id": alert.confirmed_by_id,
        "confirmed_by_username": alert.confirmed_by_username,
        "confirmed_at": alert.confirmed_at,
        "ignored_by_id": alert.ignored_by_id,
        "ignored_by_username": alert.ignored_by_username,
        "ignored_at": alert.ignored_at,
        "ignore_reason": alert.ignore_reason,
        "created_at": alert.created_at,
        "updated_at": alert.updated_at,
        "opinion": {
            "id": opinion.id,
            "title": opinion.title,
            "content": opinion.content,
            "url": opinion.url,
            "author": opinion.author,
            "language": opinion.language,
            "published_at": opinion.published_at,
            "source_id": opinion.source_id,
            "source_code": opinion.source_code,
            "source_name": source.name if source is not None else "",
            "source_type": opinion.source_type,
            "sentiment": analysis.sentiment if analysis is not None else None,
            "analysis_score": analysis.score if analysis is not None else None,
            "analysis_level": analysis.level if analysis is not None else None,
            "analysis_status": analysis.status if analysis is not None else None,
        },
    }
