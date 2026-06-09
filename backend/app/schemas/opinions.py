"""Pydantic schemas for the opinion-item list/detail API (Phase 3 / Issue 4)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.analysis import (
    RISK_LEVEL_VALUES,
    SENTIMENT_VALUES,
    AnalysisResultOut,
)


class OpinionItemOut(BaseModel):
    id: int
    source_id: int
    source_code: str
    source_type: str
    external_id: str
    title: str
    content: str
    url: str
    author: str
    language: str
    published_at: Optional[datetime]
    fetched_at: datetime
    content_hash: str
    origin: str
    created_at: datetime
    # Phase 4: nested analysis summary so the UI can show sentiment,
    # risk level, score, and status without a second request.
    analysis: AnalysisResultOut = Field(default_factory=AnalysisResultOut)


class OpinionListOut(BaseModel):
    total: int
    items: list[OpinionItemOut]


# Allowed filter values mirrored here so the API contract is explicit.
OPINION_SENTIMENT_FILTER = SENTIMENT_VALUES
OPINION_RISK_LEVEL_FILTER = RISK_LEVEL_VALUES
OPINION_ANALYSIS_STATUS_FILTER = {"pending", "success", "failed"}
