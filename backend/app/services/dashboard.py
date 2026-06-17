"""Workbench dashboard aggregation service (Phase 7 / Issue 9).

This module owns the read-only queries that feed ``/api/dashboard/summary``.
The dashboard is a thin role-aware projection over the existing
opinion / alert / ticket tables, so the implementation is mostly
``COUNT(*) GROUP BY ...`` and a few joins.

Public entry point:

  * :func:`build_dashboard_summary` - run the queries and return a
    Pydantic-ready dict shaped like
    :class:`app.schemas.dashboard.DashboardSummaryOut`.

Why a separate module:
  * The aggregation has different permission rules from the CRUD APIs:
    every authenticated role can hit it, but the *fields* they see are
    gated by the same per-resource permissions used elsewhere
    (``opinion:read``, ``alert:read``, ``ticket:read``). The role
    matrix lives here so the API layer stays a one-liner.
  * The seven-day trend padding (zeros for days with no data) is
    presentation logic that does not belong in the route handler.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.alert import (
    ALERT_STATUS_CONFIRMED,
    ALERT_STATUS_IGNORED,
    ALERT_STATUS_PENDING,
    ALERT_TRIGGER_LEVELS,
    Alert,
)
from app.models.analysis import (
    ANALYSIS_STATUS_SUCCESS,
    AnalysisResult,
)
from app.models.datasource import OpinionItem
from app.models.role_codes import RoleCode
from app.models.ticket import (
    TICKET_STATUSES,
    Ticket,
)
from app.models.user import User
from app.schemas.dashboard import (
    DashboardLatestAlert,
    DashboardSummaryOut,
    DashboardTrendPoint,
)


# Number of days to show in the workbench trend. The PRD says
# "seven-day trends"; this is the one place that constant lives.
TREND_WINDOW_DAYS = 7

# Cap on the latest-alerts feed. The PRD only requires "latest
# alerts"; five is a comfortable default that fits the workbench card
# without scrolling.
LATEST_ALERTS_LIMIT = 5

_DashboardCacheKey = tuple[str, str, int]
_dashboard_summary_cache: dict[_DashboardCacheKey, tuple[float, DashboardSummaryOut]] = {}


# ---------- permission predicates ----------


def _has_opinion_read(role_code: str) -> bool:
    if role_code == RoleCode.ADMIN:
        return True
    return role_code in {
        RoleCode.RISK_CONTROL,
        RoleCode.AUDITOR,
        RoleCode.VIEWER,
    }


def _has_alert_read(role_code: str) -> bool:
    if role_code == RoleCode.ADMIN:
        return True
    return role_code in {RoleCode.RISK_CONTROL, RoleCode.AUDITOR}


def _has_ticket_read(role_code: str) -> bool:
    if role_code == RoleCode.ADMIN:
        return True
    return role_code in {
        RoleCode.RISK_CONTROL,
        RoleCode.HANDLER,
        RoleCode.AUDITOR,
    }


# ---------- trend helpers ----------


def _trend_window_end(today_utc: date) -> list[date]:
    """Return the seven calendar dates ending at ``today_utc`` (inclusive)."""
    return [today_utc - timedelta(days=offset) for offset in range(TREND_WINDOW_DAYS - 1, -1, -1)]


def _opinion_event_dates(db: Session, start_window: datetime) -> list[date]:
    """Return the bucketing date for every opinion published on/after
    ``start_window``. Bucketing happens in Python (after the SQL
    fetch) so we can use a single, timezone-stable rule regardless
    of the database engine: ``published_at`` is stored as UTC; the
    Python ``.date()`` call returns the UTC calendar date.

    The fallback to ``created_at`` is also Python-side to keep the
    rule in one place.
    """
    published_rows = (
        db.query(
            OpinionItem.published_at.label("published_at"),
            OpinionItem.created_at.label("created_at"),
        )
        .filter(OpinionItem.published_at >= start_window)
        .all()
    )
    fallback_rows = (
        db.query(
            OpinionItem.published_at.label("published_at"),
            OpinionItem.created_at.label("created_at"),
        )
        .filter(OpinionItem.published_at.is_(None))
        .filter(OpinionItem.created_at >= start_window)
        .all()
    )
    out: list[date] = []
    for row in [*published_rows, *fallback_rows]:
        ts = row.published_at or row.created_at
        if ts is None:
            continue
        out.append(ts.date())
    return out


def _opinion_trend(db: Session, today_utc: date) -> list[DashboardTrendPoint]:
    """Compute the seven-day opinion trend (total / negative / high+severe).

    We use Python-side bucketing (see :func:`_opinion_event_dates`)
    to stay portable across SQLite (tests) and PostgreSQL (prod).
    The :func:`_opinion_date_bucket` helper is retained so the
    compatibility story is documented; the trend itself does not
    lean on it.
    """
    start_window = datetime.combine(
        today_utc - timedelta(days=TREND_WINDOW_DAYS - 1),
        datetime.min.time(),
        tzinfo=timezone.utc,
    )
    event_dates = _opinion_event_dates(db, start_window)

    # Negative-sentiment / high+severity counts require joining to the
    # analysis table. We restrict to successful analyses so a row
    # still in ``pending`` state is not counted as negative just
    # because its default label is unset.
    analyzed_query = (
        db.query(
            OpinionItem.published_at.label("published_at"),
            OpinionItem.created_at.label("created_at"),
            AnalysisResult.sentiment.label("sentiment"),
            AnalysisResult.level.label("level"),
        )
        .join(AnalysisResult, AnalysisResult.opinion_item_id == OpinionItem.id)
        .filter(AnalysisResult.status == ANALYSIS_STATUS_SUCCESS)
    )
    analyzed_rows = [
        *analyzed_query.filter(OpinionItem.published_at >= start_window).all(),
        *analyzed_query.filter(OpinionItem.published_at.is_(None))
        .filter(OpinionItem.created_at >= start_window)
        .all(),
    ]

    totals: dict[date, int] = {}
    negatives: dict[date, int] = {}
    high_severe: dict[date, int] = {}
    trigger_levels = set(ALERT_TRIGGER_LEVELS)
    for row in analyzed_rows:
        ts = row.published_at or row.created_at
        if ts is None:
            continue
        d = ts.date()
        if row.sentiment == "negative":
            negatives[d] = negatives.get(d, 0) + 1
        if row.level in trigger_levels:
            high_severe[d] = high_severe.get(d, 0) + 1
    for d in event_dates:
        totals[d] = totals.get(d, 0) + 1

    return [
        DashboardTrendPoint(
            date=d,
            total=totals.get(d, 0),
            negative=negatives.get(d, 0),
            high_or_severe=high_severe.get(d, 0),
        )
        for d in _trend_window_end(today_utc)
    ]


# ---------- alert helpers ----------


def _alert_status_counts(db: Session) -> dict[str, int]:
    """Group-by count of alerts by status. Returns zero for any
    status with no rows so the UI does not have to special-case."""
    rows = db.query(Alert.status, func.count(Alert.id)).group_by(Alert.status).all()
    counts = {ALERT_STATUS_PENDING: 0, ALERT_STATUS_CONFIRMED: 0, ALERT_STATUS_IGNORED: 0}
    for status, count in rows:
        if status in counts:
            counts[status] = int(count)
    return counts


def _alert_high_or_severe_total(db: Session) -> int:
    return (
        db.query(func.count(Alert.id))
        .filter(Alert.risk_level.in_(ALERT_TRIGGER_LEVELS))
        .scalar()
        or 0
    )


def _latest_alerts(db: Session, limit: int) -> list[DashboardLatestAlert]:
    """Return the most-recent alerts joined with opinion title / source."""
    rows = (
        db.query(Alert)
        .order_by(Alert.created_at.desc(), Alert.id.desc())
        .limit(limit)
        .all()
    )
    out: list[DashboardLatestAlert] = []
    for alert in rows:
        opinion: Optional[OpinionItem] = getattr(alert, "opinion_item", None)
        source = getattr(opinion, "source", None) if opinion is not None else None
        out.append(
            DashboardLatestAlert(
                id=alert.id,
                opinion_item_id=alert.opinion_item_id,
                risk_level=alert.risk_level,
                risk_score=alert.risk_score,
                status=alert.status,
                created_at=alert.created_at,
                opinion_title=opinion.title if opinion is not None else "",
                opinion_source_id=opinion.source_id if opinion is not None else 0,
                opinion_source_code=opinion.source_code if opinion is not None else "",
                opinion_source_name=source.name if source is not None else "",
            )
        )
    return out


# ---------- opinion helpers ----------


def _opinion_aggregate(db: Session) -> dict[str, Any]:
    """Total opinions + analyzed / negative counts for the negative ratio.

    Two small queries: one for the total opinion count, one for the
    analyzed + negative breakdown. Kept separate (instead of a single
    conditional-sum) so the SQL is portable across SQLite (tests) and
    PostgreSQL (production) without leaning on dialect-specific
    helpers like ``iif`` or non-standard CASE.
    """
    total = int(db.query(func.count(OpinionItem.id)).scalar() or 0)
    analyzed = int(
        db.query(func.count(AnalysisResult.id))
        .filter(AnalysisResult.status == ANALYSIS_STATUS_SUCCESS)
        .scalar()
        or 0
    )
    negative = int(
        db.query(func.count(AnalysisResult.id))
        .filter(AnalysisResult.status == ANALYSIS_STATUS_SUCCESS)
        .filter(AnalysisResult.sentiment == "negative")
        .scalar()
        or 0
    )
    ratio = (negative / analyzed) if analyzed > 0 else 0.0
    return {
        "total": total,
        "analyzed": analyzed,
        "negative": negative,
        "negative_ratio": ratio,
    }


# ---------- ticket helpers ----------


def _ticket_status_counts(db: Session, viewer: User) -> dict[str, int]:
    """Group-by count of tickets by status, optionally scoped to the
    calling handler. The service already provides
    :func:`count_tickets_by_status` with the same scoping; we mirror
    it here to keep the dashboard queries in one place."""
    query = db.query(Ticket.status, func.count(Ticket.id))
    if viewer.role.code == RoleCode.HANDLER:
        query = query.filter(Ticket.assignee_id == viewer.id)
    rows = query.group_by(Ticket.status).all()
    counts = {status: 0 for status in TICKET_STATUSES}
    for status, count in rows:
        if status in counts:
            counts[status] = int(count)
    return counts


# ---------- public entry point ----------


def _dashboard_cache_key(db: Session, viewer: User) -> _DashboardCacheKey:
    bind = db.get_bind()
    db_scope = str(getattr(bind, "url", ""))
    return (db_scope, viewer.role.code, int(viewer.id))


def _get_cached_dashboard_summary(key: _DashboardCacheKey, now_monotonic: float) -> DashboardSummaryOut | None:
    cached = _dashboard_summary_cache.get(key)
    if cached is None:
        return None
    expires_at, summary = cached
    if expires_at <= now_monotonic:
        _dashboard_summary_cache.pop(key, None)
        return None
    return summary


def build_dashboard_summary(db: Session, viewer: User) -> DashboardSummaryOut:
    """Assemble the workbench summary for the calling user.

    The role permission checks here mirror those used by the per-resource
    CRUD APIs (``opinion:read``, ``alert:read``, ``ticket:read``). A
    field the calling role cannot see is returned as ``None`` rather
    than a 403; the dashboard endpoint itself is open to all
    authenticated roles so the workbench page never 403s for a user
    who is allowed to see it in the nav.
    """
    settings = get_settings()
    cache_ttl = max(0, int(settings.dashboard_summary_cache_ttl_seconds))
    cache_key = _dashboard_cache_key(db, viewer)
    now_monotonic = time.monotonic()
    if cache_ttl > 0:
        cached = _get_cached_dashboard_summary(cache_key, now_monotonic)
        if cached is not None:
            return cached

    now = datetime.now(timezone.utc)
    today_utc = now.date()
    role_code = viewer.role.code

    out_kwargs: dict[str, Any] = {
        "role_scope": role_code,
        "generated_at": now,
    }

    # Opinion aggregate.
    if _has_opinion_read(role_code):
        agg = _opinion_aggregate(db)
        out_kwargs.update(
            opinion_total=agg["total"],
            opinion_analyzed_total=agg["analyzed"],
            opinion_negative_total=agg["negative"],
            opinion_negative_ratio=round(agg["negative_ratio"], 4),
            trend=_opinion_trend(db, today_utc),
        )
    else:
        out_kwargs.update(
            opinion_total=None,
            opinion_analyzed_total=None,
            opinion_negative_total=None,
            opinion_negative_ratio=None,
            trend=[],
        )

    # Alert aggregate.
    if _has_alert_read(role_code):
        status_counts = _alert_status_counts(db)
        out_kwargs.update(
            alerts_high_or_severe_total=_alert_high_or_severe_total(db),
            alerts_pending=status_counts[ALERT_STATUS_PENDING],
            alerts_confirmed=status_counts[ALERT_STATUS_CONFIRMED],
            alerts_ignored=status_counts[ALERT_STATUS_IGNORED],
            latest_alerts=_latest_alerts(db, LATEST_ALERTS_LIMIT),
        )
    else:
        out_kwargs.update(
            alerts_high_or_severe_total=None,
            alerts_pending=None,
            alerts_confirmed=None,
            alerts_ignored=None,
            latest_alerts=[],
        )

    # Ticket aggregate.
    if _has_ticket_read(role_code):
        ticket_counts = _ticket_status_counts(db, viewer)
        out_kwargs.update(
            tickets_unassigned=ticket_counts.get("unassigned", 0),
            tickets_in_progress=ticket_counts.get("in_progress", 0),
            tickets_completed=ticket_counts.get("completed", 0),
            tickets_archived=ticket_counts.get("archived", 0),
        )
    else:
        out_kwargs.update(
            tickets_unassigned=None,
            tickets_in_progress=None,
            tickets_completed=None,
            tickets_archived=None,
        )

    summary = DashboardSummaryOut(**out_kwargs)
    if cache_ttl > 0:
        _dashboard_summary_cache[cache_key] = (now_monotonic + cache_ttl, summary)
    return summary
