"""Pydantic schemas for the analysis + risk-score API (Phase 4 / Issue 6)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


SENTIMENT_VALUES = {"positive", "neutral", "negative"}
RISK_LEVEL_VALUES = {"low", "medium", "high", "severe"}
ANALYSIS_STATUS_VALUES = {"pending", "success", "failed"}


class RiskScoreOut(BaseModel):
    score: Optional[int] = None
    level: Optional[str] = None
    factors: dict[str, Any] = Field(default_factory=dict)
    explanation: list[str] = Field(default_factory=list)


class AnalysisResultOut(BaseModel):
    status: str
    sentiment: Optional[str] = None
    confidence: Optional[float] = None
    provider: str = ""
    score: Optional[int] = None
    level: Optional[str] = None
    error_message: Optional[str] = None
    factors: dict[str, Any] = Field(default_factory=dict)
    explanation: list[str] = Field(default_factory=list)
    analyzed_at: Optional[datetime] = None

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: str) -> str:
        if v not in ANALYSIS_STATUS_VALUES:
            raise ValueError(f"status must be one of {sorted(ANALYSIS_STATUS_VALUES)}")
        return v

    @field_validator("sentiment")
    @classmethod
    def _check_sentiment(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v not in SENTIMENT_VALUES:
            raise ValueError(f"sentiment must be one of {sorted(SENTIMENT_VALUES)}")
        return v

    @field_validator("level")
    @classmethod
    def _check_level(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v not in RISK_LEVEL_VALUES:
            raise ValueError(f"level must be one of {sorted(RISK_LEVEL_VALUES)}")
        return v


class AnalyzeActionResultOut(BaseModel):
    opinion_id: int
    status: str
    sentiment: Optional[str] = None
    risk_level: Optional[str] = None
    risk_score: Optional[int] = None
    analyzed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class AnalyzePendingResultOut(BaseModel):
    requested: int
    succeeded: int
    failed: int
    analyzed_ids: list[int] = Field(default_factory=list)
