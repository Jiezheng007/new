"""Alert ORM model (Phase 5 / Issue 7).

A single ``Alert`` row per high-risk / severe-risk ``OpinionItem``.
The (opinion_item_id) uniqueness constraint is the dedup mechanism: even
if the same opinion is re-analyzed many times (threshold changes,
provider retries, manual re-analyze) it can only ever create one alert,
and re-analysis of an already-pending / confirmed / ignored alert is
a no-op for the alert subsystem.

States are kept intentionally simple for the MVP:
  - ``pending``  : auto-created; awaits risk-control decision
  - ``confirmed``: a risk-control user (or admin) accepted the risk
  - ``ignored``  : a risk-control user rejected the risk with a reason

Transitions are one-way ``pending`` -> ``{confirmed, ignored}``. Confirmed
alerts become the input to the ticket-conversion workflow in Phase 6
(Issue 8), so we never silently move a confirmed alert back to pending.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, backref, mapped_column, relationship

from app.db.session import Base
from app.models.user import utcnow


# Status constants. Mirrored as string literals throughout services /
# schemas / tests to keep the API contract explicit.
ALERT_STATUS_PENDING = "pending"
ALERT_STATUS_CONFIRMED = "confirmed"
ALERT_STATUS_IGNORED = "ignored"

ALERT_STATUSES: tuple[str, ...] = (
    ALERT_STATUS_PENDING,
    ALERT_STATUS_CONFIRMED,
    ALERT_STATUS_IGNORED,
)

# Risk levels that auto-create a pending alert. Kept in sync with
# ``AnalysisResult.level`` values written by the scoring service.
ALERT_TRIGGER_LEVELS: tuple[str, ...] = ("high", "severe")


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("opinion_item_id", name="uq_alert_opinion_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opinion_item_id: Mapped[int] = mapped_column(
        ForeignKey("opinion_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=ALERT_STATUS_PENDING, nullable=False, index=True
    )
    # Snapshot of the analysis.factors / explanation at trigger time so the
    # alert still tells a coherent story if the underlying analysis row is
    # later re-computed.
    trigger_explanation: Mapped[str] = mapped_column(Text, default="", nullable=False)

    confirmed_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    confirmed_by_username: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    ignored_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    ignored_by_username: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    ignored_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ignore_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    opinion_item: Mapped["OpinionItem"] = relationship(  # type: ignore[name-defined]
        "OpinionItem",
        backref=backref("alert", uselist=False, lazy="joined"),
    )

    confirmed_by: Mapped[Optional["User"]] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[confirmed_by_id]
    )
    ignored_by: Mapped[Optional["User"]] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[ignored_by_id]
    )
