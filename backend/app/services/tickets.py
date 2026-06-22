"""Ticket lifecycle service (Phase 6 / Issue 8).

This module owns the ticket state machine and the small amount of
business logic that sits behind the API. Public entry points:

  * :func:`create_ticket_from_alert` - convert a confirmed alert into a
    ticket. If ``assignee_id`` is provided the ticket starts in
    ``in_progress``; otherwise it starts in ``unassigned``. The
    uniqueness constraint on ``alert_id`` makes the operation idempotent
    (re-calling with the same alert raises :class:`TicketStateError`).

  * :func:`assign_ticket` - choose a handler. Allowed from ``unassigned``
    (transitions to ``in_progress``) and from ``in_progress`` /
    ``completed`` (reassignment, status unchanged). Cannot reassign an
    archived ticket.

  * :func:`start_ticket` - handler accepts the work. Allowed from
    ``unassigned`` or ``in_progress`` when the caller is the assignee.
    No-op for ``completed`` / ``archived``.

  * :func:`complete_ticket` - handler submits result. Allowed from
    ``in_progress`` only. Requires a non-blank ``handling_result``.

  * :func:`archive_ticket` - risk-control closes the loop. Allowed from
    ``completed`` only.

  * :func:`list_tickets` - paginated, filterable listing used by the
    :class:`TicketListOut` schema and the Web UI. The ``handler``
    role is automatically constrained to ``assignee_id == current_user``
    so the API layer does not need a second query for that.

The audit trail is written by the API layer (same pattern as alerts)
so each HTTP path can capture action-specific details (e.g. ignore
reason) without complicating the service signatures.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, contains_eager, joinedload

from app.models.alert import (
    ALERT_STATUS_CONFIRMED,
    Alert,
)
from app.models.analysis import AnalysisResult
from app.models.datasource import OpinionItem
from app.models.role_codes import RoleCode
from app.models.ticket import (
    HANDLING_RESULT_MAX,
    TICKET_STATUS_ARCHIVED,
    TICKET_STATUS_COMPLETED,
    TICKET_STATUS_IN_PROGRESS,
    TICKET_STATUS_UNASSIGNED,
    TICKET_STATUSES,
    Ticket,
)
from app.models.user import User


@dataclass
class TicketStateError(Exception):
    """Raised when a ticket state transition is not legal (e.g. start
    a completed ticket). The API layer maps this to HTTP 409."""

    ticket_id: int
    current_status: str
    attempted: str

    def __str__(self) -> str:  # pragma: no cover - debug only
        return (
            f"Ticket {self.ticket_id} is in state '{self.current_status}'; "
            f"cannot transition via '{self.attempted}'"
        )


@dataclass
class TicketInputError(Exception):
    """Raised when the input data is invalid (e.g. handler not a
    handler, alert not confirmed). The API layer maps this to HTTP 400."""

    reason: str


# ---------- creation ----------


def _resolve_handler(db: Session, user_id: int) -> User:
    """Return the user with the given id, or raise ``TicketInputError``."""
    user = db.get(User, user_id)
    if user is None:
        raise TicketInputError(f"assignee {user_id} not found")
    if not user.is_active:
        raise TicketInputError(f"assignee {user.username} is disabled")
    if user.role.code != RoleCode.HANDLER:
        raise TicketInputError(
            f"user {user.username} does not have the handler role"
        )
    return user


def create_ticket_from_alert(
    db: Session,
    *,
    alert: Alert,
    actor: User,
    title: str = "",
    description: str = "",
    assignee_id: Optional[int] = None,
    ip_address: str = "",
) -> Ticket:
    """Convert a confirmed alert into a ticket.

    The alert must be in state ``confirmed``; this is the input the
    issue spec describes (``Risk-control user can convert a confirmed
    alert into a ticket``). Pending and ignored alerts are rejected.

    Idempotency: the ``uq_ticket_alert`` unique constraint prevents
    duplicate tickets for the same alert. We pre-check for a friendlier
    error path but the unique constraint is the safety net.
    """
    if alert.status != ALERT_STATUS_CONFIRMED:
        raise TicketStateError(alert.id, alert.status, "create_ticket")

    existing = (
        db.query(Ticket).filter(Ticket.alert_id == alert.id).one_or_none()
    )
    if existing is not None:
        raise TicketStateError(alert.id, alert.status, "create_ticket")
        # The state string is approximate; the caller will re-read.

    handler: Optional[User] = None
    if assignee_id is not None:
        handler = _resolve_handler(db, assignee_id)

    opinion: OpinionItem = alert.opinion_item
    snapshot_title = (title or "").strip() or (opinion.title or "")[:255]
    snapshot_description = (description or "").strip()

    now = datetime.utcnow()
    ticket = Ticket(
        alert_id=alert.id,
        opinion_item_id=alert.opinion_item_id,
        risk_level=alert.risk_level,
        risk_score=int(alert.risk_score),
        title=snapshot_title,
        description=snapshot_description,
        status=TICKET_STATUS_IN_PROGRESS if handler is not None else TICKET_STATUS_UNASSIGNED,
        assignee_id=handler.id if handler is not None else None,
        assignee_username=handler.username if handler is not None else "",
        assigned_by_id=actor.id,
        assigned_by_username=actor.username,
        assigned_at=now if handler is not None else None,
        started_at=now if handler is not None else None,
        created_by_id=actor.id,
        created_by_username=actor.username,
    )
    db.add(ticket)
    # Flush so the unique constraint surfaces here, not at commit time.
    db.flush()
    return ticket


# ---------- assignment ----------


def assign_ticket(
    db: Session,
    ticket: Ticket,
    *,
    actor: User,
    assignee_id: int,
    title: Optional[str] = None,
    description: Optional[str] = None,
    ip_address: str = "",
) -> Ticket:
    """Assign (or reassign) a ticket to a handler.

    Legal source states: ``unassigned`` (transitions to ``in_progress``),
    ``in_progress`` and ``completed`` (status unchanged, fields
    updated). ``archived`` is rejected - the work is closed.
    """
    if ticket.status == TICKET_STATUS_ARCHIVED:
        raise TicketStateError(ticket.id, ticket.status, "assign")

    handler = _resolve_handler(db, assignee_id)
    now = datetime.utcnow()
    was_unassigned = ticket.status == TICKET_STATUS_UNASSIGNED

    ticket.assignee_id = handler.id
    ticket.assignee_username = handler.username
    ticket.assigned_by_id = actor.id
    ticket.assigned_by_username = actor.username
    ticket.assigned_at = now
    if was_unassigned:
        ticket.status = TICKET_STATUS_IN_PROGRESS
        ticket.started_at = now
    if title is not None:
        cleaned = (title or "").strip()
        if cleaned:
            ticket.title = cleaned[:255]
    if description is not None:
        ticket.description = (description or "").strip()[:2000]
    db.flush()
    return ticket


# ---------- start (handler accept) ----------


def start_ticket(
    db: Session,
    ticket: Ticket,
    *,
    actor: User,
    ip_address: str = "",
) -> Ticket:
    """Handler marks the ticket in-progress.

    Legal from ``unassigned`` (transitions to ``in_progress``) and
    from ``in_progress`` (no-op, but refreshes ``started_at`` only if
    it was missing). ``completed`` / ``archived`` are rejected.
    """
    if ticket.status in {TICKET_STATUS_COMPLETED, TICKET_STATUS_ARCHIVED}:
        raise TicketStateError(ticket.id, ticket.status, "start")

    if ticket.assignee_id is None or ticket.assignee_id != actor.id:
        # The API layer catches this earlier for a cleaner 403, but
        # defending here keeps the service safe for direct callers.
        raise TicketInputError("only the assigned handler can start this ticket")

    now = datetime.utcnow()
    if ticket.status == TICKET_STATUS_UNASSIGNED:
        ticket.status = TICKET_STATUS_IN_PROGRESS
    if ticket.started_at is None:
        ticket.started_at = now
    db.flush()
    return ticket


# ---------- complete ----------


def complete_ticket(
    db: Session,
    ticket: Ticket,
    *,
    actor: User,
    handling_result: str,
    ip_address: str = "",
) -> Ticket:
    """Handler submits the result and marks the ticket completed.

    Legal from ``in_progress`` only. Requires a non-blank result of at
    least 2 characters. Re-completing a completed ticket is a 409.
    """
    if ticket.status != TICKET_STATUS_IN_PROGRESS:
        raise TicketStateError(ticket.id, ticket.status, "complete")

    if ticket.assignee_id is None or ticket.assignee_id != actor.id:
        raise TicketInputError("only the assigned handler can complete this ticket")

    cleaned = (handling_result or "").strip()
    if len(cleaned) < 2:
        raise TicketInputError("handling_result must be at least 2 non-whitespace characters")
    if len(cleaned) > HANDLING_RESULT_MAX:
        cleaned = cleaned[:HANDLING_RESULT_MAX]

    now = datetime.utcnow()
    ticket.status = TICKET_STATUS_COMPLETED
    ticket.handling_result = cleaned
    ticket.completed_by_id = actor.id
    ticket.completed_by_username = actor.username
    ticket.completed_at = now
    db.flush()
    return ticket


# ---------- archive ----------


def archive_ticket(
    db: Session,
    ticket: Ticket,
    *,
    actor: User,
    ip_address: str = "",
) -> Ticket:
    """Risk-control user archives a completed ticket. Idempotent on
    archived (returns the same row without writing new timestamps)."""
    if ticket.status == TICKET_STATUS_ARCHIVED:
        return ticket
    if ticket.status != TICKET_STATUS_COMPLETED:
        raise TicketStateError(ticket.id, ticket.status, "archive")

    now = datetime.utcnow()
    ticket.status = TICKET_STATUS_ARCHIVED
    ticket.archived_by_id = actor.id
    ticket.archived_by_username = actor.username
    ticket.archived_at = now
    db.flush()
    return ticket


# ---------- listing / fetch ----------


def _base_query(db: Session):
    return db.query(Ticket)


def list_tickets(
    db: Session,
    *,
    status_filter: Optional[str] = None,
    level_filter: Optional[str] = None,
    assignee_id: Optional[int] = None,
    keyword: Optional[str] = None,
    start_at: Optional[datetime] = None,
    end_at: Optional[datetime] = None,
    viewer: Optional[User] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Ticket], int]:
    """Return a filtered, paginated list of tickets plus the unfiltered total.

    If ``viewer`` is a handler, the result is automatically restricted
    to tickets they own - matching the ``ticket:read:assigned``
    permission. Admin / risk-control / auditor / viewer keep the full
    list (viewer should rarely reach this endpoint, but if they do
    they get a 403 upstream anyway).
    """
    query = (
        _base_query(db)
        .join(OpinionItem, OpinionItem.id == Ticket.opinion_item_id)
        .options(
            contains_eager(Ticket.opinion_item).joinedload(OpinionItem.source),
            contains_eager(Ticket.opinion_item).joinedload(OpinionItem.analysis_result),
            joinedload(Ticket.alert),
        )
    )
    count_query = db.query(func.count(Ticket.id)).join(
        OpinionItem, OpinionItem.id == Ticket.opinion_item_id
    )

    if viewer is not None and viewer.role.code == RoleCode.HANDLER:
        query = query.filter(Ticket.assignee_id == viewer.id)
        count_query = count_query.filter(Ticket.assignee_id == viewer.id)

    if status_filter:
        query = query.filter(Ticket.status == status_filter)
        count_query = count_query.filter(Ticket.status == status_filter)
    if level_filter:
        query = query.filter(Ticket.risk_level == level_filter)
        count_query = count_query.filter(Ticket.risk_level == level_filter)
    if assignee_id is not None:
        query = query.filter(Ticket.assignee_id == assignee_id)
        count_query = count_query.filter(Ticket.assignee_id == assignee_id)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            (OpinionItem.title.like(like)) | (OpinionItem.content.like(like))
        )
        count_query = count_query.filter(
            (OpinionItem.title.like(like)) | (OpinionItem.content.like(like))
        )
    if start_at is not None:
        query = query.filter(Ticket.created_at >= start_at)
        count_query = count_query.filter(Ticket.created_at >= start_at)
    if end_at is not None:
        query = query.filter(Ticket.created_at <= end_at)
        count_query = count_query.filter(Ticket.created_at <= end_at)

    total = int(count_query.scalar() or 0)
    rows = (
        query.order_by(Ticket.created_at.desc(), Ticket.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return rows, total


def get_ticket(db: Session, ticket_id: int) -> Optional[Ticket]:
    return db.get(Ticket, ticket_id)


def count_tickets_by_status(
    db: Session,
    *,
    viewer: Optional[User] = None,
) -> dict[str, int]:
    """Group-by count helper for the dashboard.

    Returns ``{"unassigned": N, "in_progress": N, "completed": N,
    "archived": N, "total": N}``. Handlers get the same shape but
    scoped to their own tickets.
    """
    query = db.query(Ticket.status, func.count(Ticket.id))
    if viewer is not None and viewer.role.code == RoleCode.HANDLER:
        query = query.filter(Ticket.assignee_id == viewer.id)
    rows = query.group_by(Ticket.status).all()
    out: dict[str, int] = {s: 0 for s in TICKET_STATUSES}
    for status, count in rows:
        if status in out:
            out[status] = int(count)
    out["total"] = sum(out[s] for s in TICKET_STATUSES)
    return out


# ---------- serialization helpers (used by the API + UI) ----------


def ticket_to_dict(ticket: Ticket) -> dict[str, Any]:
    """Flatten the ticket row into a JSON-friendly dict.

    The nested opinion summary is intentionally narrow (title / source /
    published_at / author / url / risk-level / score) so the UI can
    render a useful row without a second roundtrip to ``/api/opinions``.
    """
    opinion: OpinionItem = ticket.opinion_item
    source = getattr(opinion, "source", None)
    analysis: Optional[AnalysisResult] = getattr(opinion, "analysis_result", None)
    alert: Alert = ticket.alert

    return {
        "id": ticket.id,
        "alert_id": ticket.alert_id,
        "opinion_item_id": ticket.opinion_item_id,
        "risk_level": ticket.risk_level,
        "risk_score": ticket.risk_score,
        "title": ticket.title,
        "description": ticket.description,
        "status": ticket.status,
        "assignee_id": ticket.assignee_id,
        "assignee_username": ticket.assignee_username,
        "assigned_by_id": ticket.assigned_by_id,
        "assigned_by_username": ticket.assigned_by_username,
        "assigned_at": ticket.assigned_at,
        "started_at": ticket.started_at,
        "handling_result": ticket.handling_result,
        "completed_by_id": ticket.completed_by_id,
        "completed_by_username": ticket.completed_by_username,
        "completed_at": ticket.completed_at,
        "archived_by_id": ticket.archived_by_id,
        "archived_by_username": ticket.archived_by_username,
        "archived_at": ticket.archived_at,
        "created_by_id": ticket.created_by_id,
        "created_by_username": ticket.created_by_username,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
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
        "alert_summary": {
            "id": alert.id,
            "status": alert.status,
            "risk_level": alert.risk_level,
            "risk_score": alert.risk_score,
            "confirmed_by_username": alert.confirmed_by_username,
            "confirmed_at": alert.confirmed_at,
        },
    }
