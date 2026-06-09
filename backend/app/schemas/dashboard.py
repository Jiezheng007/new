"""Pydantic schemas for the workbench dashboard (Phase 7 / Issue 9).

The summary endpoint returns a single response that the Web UI can
render as cards + a small trend chart + a latest-alerts feed. Fields
the calling role cannot see are returned as ``None`` (not omitted) so
the contract is stable and the UI can branch on presence rather than
key existence.

Why nullable instead of a polymorphic response shape:
  * The Web UI already hides cards by role (per the existing pattern in
    alerts.js / tickets.js). Branching on ``value === null`` is the
    same shape of code.
  * Optional fields are common in Pydantic / FastAPI; tests can
    assert ``"opinion_total" in body`` regardless of role.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class DashboardTrendPoint(BaseModel):
    """One bucket in the seven-day trend.

    ``date`` is the ISO calendar day (``YYYY-MM-DD``). Counts are
    computed against the union of ``published_at`` and ``created_at``
    (latter as a fallback) so the trend stays populated even if a
    source forgot to publish a timestamp.
    """

    date: date
    total: int = 0
    negative: int = 0
    high_or_severe: int = 0


class DashboardLatestAlert(BaseModel):
    """Narrow alert row for the workbench feed.

    We include the opinion title and source name inline so the workbench
    can render a useful card without a follow-up request to
    ``/api/opinions/{id}`` or ``/api/alerts/{id}``.
    """

    id: int
    opinion_item_id: int
    risk_level: str
    risk_score: int
    status: str
    created_at: datetime
    opinion_title: str = ""
    opinion_source_id: int = 0
    opinion_source_code: str = ""
    opinion_source_name: str = ""


class DashboardSummaryOut(BaseModel):
    """Workbench summary.

    Field naming uses snake_case to match the other Phase 3-6 schemas
    (``alert.confirm`` audit details etc. are already snake_case).
    """

    # Scope marker for the UI to render an "as <role>" hint or hide
    # action buttons that are unavailable to the calling role.
    role_scope: str

    # Opinion aggregate. Shown to admin / risk_control / auditor / viewer.
    opinion_total: Optional[int] = None
    opinion_analyzed_total: Optional[int] = None
    opinion_negative_total: Optional[int] = None
    opinion_negative_ratio: Optional[float] = None

    # Alert aggregate. Shown to admin / risk_control / auditor.
    alerts_high_or_severe_total: Optional[int] = None
    alerts_pending: Optional[int] = None
    alerts_confirmed: Optional[int] = None
    alerts_ignored: Optional[int] = None

    # Ticket aggregate. Shown to admin / risk_control / handler (scoped)
    # / auditor.
    tickets_unassigned: Optional[int] = None
    tickets_in_progress: Optional[int] = None
    tickets_completed: Optional[int] = None
    tickets_archived: Optional[int] = None

    # Seven-day opinion / risk trend. Always returned (it is aggregate
    # data, not personal data) so handlers / viewers get a meaningful
    # overview card even when individual counts are masked. We still
    # honor the opinion:read permission: handlers do not see the trend.
    trend: list[DashboardTrendPoint] = Field(default_factory=list)

    # Latest alerts feed. Shown to admin / risk_control / auditor.
    latest_alerts: list[DashboardLatestAlert] = Field(default_factory=list)

    # Timestamp the summary was assembled; useful when polling.
    generated_at: datetime
