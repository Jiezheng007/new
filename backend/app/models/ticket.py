"""Ticket ORM model (Phase 6 / Issue 8).

A ``Ticket`` is the work unit created from a confirmed alert. Lifecycle:

  unassigned -> in_progress -> completed -> archived

  * ``unassigned``: a risk-control user just converted a confirmed alert
    into a ticket but has not chosen a handler yet. The row can be
    created in this state (e.g. bulk-convert flow) or jump straight to
    ``in_progress`` if a handler is picked at create time.
  * ``in_progress``: a handler has accepted the work and is operating
    on it. Only the assigned handler (or an admin) can mark completed.
  * ``completed``: the handler submitted a result; awaiting risk-control
    review. Only risk-control users / admin can archive from here.
  * ``archived``: closed work separated from the active list. Visible
    for read-only audit purposes but no further transitions.

A ticket is bound 1:1 to a confirmed alert (uniqueness on ``alert_id``)
so the same alert cannot spawn multiple tickets even if the conversion
endpoint is retried.
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
TICKET_STATUS_UNASSIGNED = "unassigned"
TICKET_STATUS_IN_PROGRESS = "in_progress"
TICKET_STATUS_COMPLETED = "completed"
TICKET_STATUS_ARCHIVED = "archived"

TICKET_STATUSES: tuple[str, ...] = (
    TICKET_STATUS_UNASSIGNED,
    TICKET_STATUS_IN_PROGRESS,
    TICKET_STATUS_COMPLETED,
    TICKET_STATUS_ARCHIVED,
)

# A "completed" ticket MUST have a non-empty handling_result; an
# in_progress ticket may have one (handler updates the result before
# completion) but it is not required.
HANDLING_RESULT_MAX = 2000


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("alert_id", name="uq_ticket_alert"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[int] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Snapshot of the underlying opinion + analysis so the ticket still
    # tells a coherent story even if the alert is later re-computed.
    opinion_item_id: Mapped[int] = mapped_column(
        ForeignKey("opinion_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), default=TICKET_STATUS_UNASSIGNED, nullable=False, index=True
    )

    # Assignment can be null (unassigned bucket) or point at a user.
    # We use SET NULL on user delete so the ticket itself survives.
    assignee_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assignee_username: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    assigned_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    assigned_by_username: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    assigned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    handling_result: Mapped[str] = mapped_column(Text, default="", nullable=False)
    completed_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    completed_by_username: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    archived_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    archived_by_username: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_username: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    alert: Mapped["Alert"] = relationship(  # type: ignore[name-defined]
        "Alert",
        backref=backref("ticket", uselist=False, lazy="joined"),
    )
    opinion_item: Mapped["OpinionItem"] = relationship(  # type: ignore[name-defined]
        "OpinionItem",
        backref=backref("tickets", lazy="select"),
        foreign_keys=[opinion_item_id],
    )
    assignee: Mapped[Optional["User"]] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[assignee_id]
    )
