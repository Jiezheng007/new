"""Pydantic schemas for the alert lifecycle API (Phase 5 / Issue 7)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.alert import ALERT_STATUSES, ALERT_TRIGGER_LEVELS


# Allowed filter values mirrored here so the API contract is explicit.
ALERT_STATUS_VALUES = set(ALERT_STATUSES)
ALERT_LEVEL_VALUES = set(ALERT_TRIGGER_LEVELS)


class AlertOpinionSummary(BaseModel):
    """Narrow view of the underlying opinion so the UI can render an
    alert row without a second roundtrip to ``/api/opinions``."""

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


class AlertOut(BaseModel):
    id: int
    opinion_item_id: int
    risk_level: str
    risk_score: int
    status: str
    trigger_explanation: list[str] = Field(default_factory=list)
    confirmed_by_id: Optional[int] = None
    confirmed_by_username: str = ""
    confirmed_at: Optional[datetime] = None
    ignored_by_id: Optional[int] = None
    ignored_by_username: str = ""
    ignored_at: Optional[datetime] = None
    ignore_reason: str = ""
    created_at: datetime
    updated_at: datetime
    opinion: AlertOpinionSummary

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: str) -> str:
        if v not in ALERT_STATUS_VALUES:
            raise ValueError(f"status must be one of {sorted(ALERT_STATUS_VALUES)}")
        return v

    @field_validator("risk_level")
    @classmethod
    def _check_level(cls, v: str) -> str:
        if v not in ALERT_LEVEL_VALUES:
            raise ValueError(f"risk_level must be one of {sorted(ALERT_LEVEL_VALUES)}")
        return v


class AlertListOut(BaseModel):
    total: int
    items: list[AlertOut]


class AlertIgnoreRequest(BaseModel):
    """Body for ``POST /api/alerts/{id}/ignore``."""

    reason: str = Field(..., min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def _check_reason_nonblank(cls, v: str) -> str:
        cleaned = (v or "").strip()
        if len(cleaned) < 2:
            raise ValueError("ignore reason must be at least 2 non-whitespace characters")
        return v


class AlertConfirmResultOut(BaseModel):
    id: int
    status: str
    confirmed_by_username: str
    confirmed_at: Optional[datetime] = None


class AlertIgnoreResultOut(BaseModel):
    id: int
    status: str
    ignored_by_username: str
    ignored_at: Optional[datetime] = None
    ignore_reason: str


class AlertSummaryOut(BaseModel):
    """Dashboard / sidebar counter — pending / confirmed / ignored / total."""

    pending: int
    confirmed: int
    ignored: int
    total: int
