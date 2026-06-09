"""Report-task ORM model (Phase 8 / Issue 10).

A ``ReportTask`` is the persisted handle for an asynchronous Excel
report job. The state machine has four states:

  pending    -> generating -> completed
                         \\-> failed

  * ``pending``    : row persisted, no work has started yet
  * ``generating`` : the BackgroundTask is actively building the file
  * ``completed``  : the file is on disk and downloadable; ``file_path``
                     points to it
  * ``failed``     : the run blew up; ``error_message`` carries the
                     human-readable reason; no file is exposed

``started_at`` is set when the task flips to ``generating``;
``completed_at`` is set on either terminal state. A second
``pending -> generating`` transition is the one we expect most often;
re-running a completed report is allowed (same filters, new file) and
re-running a failed one is also allowed.

Filters are intentionally simple for the MVP:
  - ``start_at`` / ``end_at`` bound ``OpinionItem.published_at``
  - ``risk_level`` is a single ``low / medium / high / severe`` value
    joined to ``AnalysisResult``
  - ``subject_keyword`` is a free-text match against the
    ``SubjectKeyword.keyword`` set (matches when any active subject
    keyword appears in the title or content - same shape as the
    opinion list keyword search)

The unique constraints on the table are deliberately minimal: the
creator column is a plain snapshot, and we never assume uniqueness on
filters (a user is allowed to re-run the same report to refresh the
Excel against newer data).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.user import utcnow


# Status constants. Mirrored as string literals throughout services /
# schemas / tests to keep the API contract explicit.
REPORT_STATUS_PENDING = "pending"
REPORT_STATUS_GENERATING = "generating"
REPORT_STATUS_COMPLETED = "completed"
REPORT_STATUS_FAILED = "failed"

REPORT_STATUSES: tuple[str, ...] = (
    REPORT_STATUS_PENDING,
    REPORT_STATUS_GENERATING,
    REPORT_STATUS_COMPLETED,
    REPORT_STATUS_FAILED,
)

# Filter helpers. The risk-level set mirrors the workbench; the keyword
# filter is free-text (a single non-blank token matched with LIKE).
REPORT_RISK_LEVELS: tuple[str, ...] = ("low", "medium", "high", "severe")

# Sub-folder under the app's working directory where completed files
# land. The path is created lazily by the service so the test suite
# can run without seeding a real file-system layout.
REPORT_FILE_PREFIX = "report_files"

# Upper bound on the title / description so the persisted row stays
# within reasonable SQLite column widths.
TITLE_MAX = 255
DESCRIPTION_MAX = 500


class ReportTask(Base):
    __tablename__ = "report_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(TITLE_MAX), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), default=REPORT_STATUS_PENDING, nullable=False, index=True
    )
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), default="", nullable=False)

    # Filters
    start_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    end_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    risk_level: Mapped[str] = mapped_column(String(16), default="", nullable=False, index=True)
    subject_keyword: Mapped[str] = mapped_column(String(128), default="", nullable=False)

    # Counters recorded on completion. Persisted so the list endpoint
    # can render "X rows, Y in selection" without re-running the query.
    matched_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    included_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Lifecycle timestamps
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Creator snapshot
    created_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_username: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    created_by: Mapped[Optional["User"]] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[created_by_id]
    )
