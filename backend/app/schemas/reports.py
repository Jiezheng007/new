"""Pydantic schemas for the report-center API (Phase 8 / Issue 10).

The contract covers:
  - ``ReportTaskCreateRequest`` : filters + optional title / description
  - ``ReportTaskOut``          : full task representation for list / detail
  - ``ReportTaskListOut``      : paginated list envelope
  - ``ReportTaskSummaryOut``   : counts by status (mirrors the dashboard pattern)
  - ``ReportTaskCreateResultOut`` : compact result returned by ``POST /api/reports``

The risk-level values are mirrored from the workbench / opinions /
alerts schemas to keep the API contract consistent across the system.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.report import (
    DESCRIPTION_MAX,
    REPORT_RISK_LEVELS,
    REPORT_STATUSES,
    TITLE_MAX,
)


# Allowed filter / status values mirrored here so the API contract is
# explicit. The risk-level set is the same one used by opinions / alerts.
REPORT_RISK_LEVEL_VALUES = set(REPORT_RISK_LEVELS)
REPORT_STATUS_VALUES = set(REPORT_STATUSES)


class ReportTaskCreateRequest(BaseModel):
    """Body for ``POST /api/reports``.

    ``start_at`` and ``end_at`` bound the opinion ``published_at``
    column. ``risk_level`` is a single value, ``subject_keyword`` is a
    free-text match against the title / content of the opinion. All
    filters are optional - an empty filter set means "include
    everything" (capped by the listing logic in the service).
    """

    title: str = Field("", max_length=TITLE_MAX)
    description: str = Field("", max_length=DESCRIPTION_MAX)
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    risk_level: str = Field("", max_length=16)
    subject_keyword: str = Field("", max_length=128)

    @field_validator("risk_level")
    @classmethod
    def _check_risk_level(cls, v: str) -> str:
        if v == "":
            return v
        if v not in REPORT_RISK_LEVEL_VALUES:
            raise ValueError(f"risk_level must be one of {sorted(REPORT_RISK_LEVEL_VALUES)}")
        return v

    @field_validator("start_at", "end_at")
    @classmethod
    def _strip_naive(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return v
        # Pydantic does not enforce tzinfo on datetime - we accept
        # either, the service treats naive values as UTC.
        return v


class ReportTaskOut(BaseModel):
    """Full task representation used by list / detail responses."""

    id: int
    title: str
    description: str
    status: str
    error_message: str
    file_path: str

    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    risk_level: str
    subject_keyword: str

    matched_count: int
    included_count: int
    file_size_bytes: int

    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    created_by_id: Optional[int] = None
    created_by_username: str
    created_at: datetime
    updated_at: datetime

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: str) -> str:
        if v not in REPORT_STATUS_VALUES:
            raise ValueError(f"status must be one of {sorted(REPORT_STATUS_VALUES)}")
        return v


class ReportTaskListOut(BaseModel):
    total: int
    items: list[ReportTaskOut]


class ReportTaskSummaryOut(BaseModel):
    """Counts by status. Mirrors the dashboard summary pattern."""

    pending: int
    generating: int
    completed: int
    failed: int
    total: int


class ReportTaskCreateResultOut(BaseModel):
    """Compact result returned by ``POST /api/reports``.

    The detail endpoint is the canonical way to inspect a freshly
    created task; the create response only needs the new id + status
    so the UI can navigate to the list and poll.
    """

    id: int
    status: str
    created_at: datetime
