"""Pydantic schemas for the ticket lifecycle API (Phase 6 / Issue 8)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.ticket import HANDLING_RESULT_MAX, TICKET_STATUSES


# Allowed filter / request values mirrored here so the API contract is
# explicit. Statuses follow the lifecycle, levels mirror alert risk
# levels (the ticket only spawns from high / severe anyway).
TICKET_STATUS_VALUES = set(TICKET_STATUSES)
TICKET_LEVEL_VALUES = {"high", "severe"}


class TicketOpinionSummary(BaseModel):
    """Narrow view of the underlying opinion so the UI can render a
    ticket row without a second roundtrip to ``/api/opinions``."""

    id: int
    title: str
    content: str
    url: str
    author: str
    language: str
    published_at: Optional[datetime] = None
    source_id: int
    source_code: str
    source_name: str = ""
    source_type: str
    sentiment: Optional[str] = None
    analysis_score: Optional[int] = None
    analysis_level: Optional[str] = None
    analysis_status: Optional[str] = None


class TicketAlertSummary(BaseModel):
    """Narrow view of the parent alert so the ticket detail can show
    who confirmed it and when."""

    id: int
    status: str
    risk_level: str
    risk_score: int
    confirmed_by_username: str = ""
    confirmed_at: Optional[datetime] = None


class TicketOut(BaseModel):
    id: int
    alert_id: int
    opinion_item_id: int
    risk_level: str
    risk_score: int
    title: str
    description: str
    status: str

    assignee_id: Optional[int] = None
    assignee_username: str = ""
    assigned_by_id: Optional[int] = None
    assigned_by_username: str = ""
    assigned_at: Optional[datetime] = None

    started_at: Optional[datetime] = None
    handling_result: str = ""
    completed_by_id: Optional[int] = None
    completed_by_username: str = ""
    completed_at: Optional[datetime] = None

    archived_by_id: Optional[int] = None
    archived_by_username: str = ""
    archived_at: Optional[datetime] = None

    created_by_id: Optional[int] = None
    created_by_username: str = ""
    created_at: datetime
    updated_at: datetime

    opinion: TicketOpinionSummary
    alert_summary: TicketAlertSummary

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: str) -> str:
        if v not in TICKET_STATUS_VALUES:
            raise ValueError(f"status must be one of {sorted(TICKET_STATUS_VALUES)}")
        return v

    @field_validator("risk_level")
    @classmethod
    def _check_level(cls, v: str) -> str:
        if v not in TICKET_LEVEL_VALUES:
            raise ValueError(f"risk_level must be one of {sorted(TICKET_LEVEL_VALUES)}")
        return v


class TicketListOut(BaseModel):
    total: int
    items: list[TicketOut]


class TicketCreateRequest(BaseModel):
    """Body for ``POST /api/tickets/from-alert``.

    All fields are optional - if ``assignee_id`` is provided the ticket
    is created directly in ``in_progress`` (and assigned). Otherwise it
    is created in ``unassigned`` and can be assigned later.
    """

    alert_id: int = Field(..., ge=1)
    title: str = Field("", max_length=255)
    description: str = Field("", max_length=2000)
    assignee_id: Optional[int] = Field(None, ge=1)


class TicketAssignRequest(BaseModel):
    """Body for ``POST /api/tickets/{id}/assign``."""

    assignee_id: int = Field(..., ge=1)
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)


class TicketCompleteRequest(BaseModel):
    """Body for ``POST /api/tickets/{id}/complete``."""

    handling_result: str = Field("", max_length=HANDLING_RESULT_MAX)

    @field_validator("handling_result")
    @classmethod
    def _check_result_nonblank(cls, v: str) -> str:
        cleaned = (v or "").strip()
        if len(cleaned) < 2:
            raise ValueError("handling_result must be at least 2 non-whitespace characters")
        return v


class TicketCreateResultOut(BaseModel):
    id: int
    status: str
    assignee_username: str = ""
    created_at: datetime


class TicketAssignResultOut(BaseModel):
    id: int
    status: str
    assignee_username: str = ""
    assigned_by_username: str = ""
    assigned_at: Optional[datetime] = None
    started_at: Optional[datetime] = None


class TicketStartResultOut(BaseModel):
    id: int
    status: str
    started_at: Optional[datetime] = None


class TicketCompleteResultOut(BaseModel):
    id: int
    status: str
    completed_by_username: str = ""
    completed_at: Optional[datetime] = None


class TicketArchiveResultOut(BaseModel):
    id: int
    status: str
    archived_by_username: str = ""
    archived_at: Optional[datetime] = None


class TicketSummaryOut(BaseModel):
    """Dashboard / sidebar counter - unassigned / in_progress / completed / archived / total."""

    unassigned: int
    in_progress: int
    completed: int
    archived: int
    total: int
