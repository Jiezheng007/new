"""Pydantic schemas for the risk-rule API (Phase 3 / Issue 3)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


SEVERITY_VALUES = {"low", "medium", "high", "severe"}
RISK_LEVELS = ("low", "medium", "high", "severe")


class SensitiveKeywordCreate(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=128)
    category: str = Field("", max_length=64)
    severity: str = Field("medium")
    is_active: bool = True
    remark: str = Field("", max_length=512)

    @field_validator("keyword")
    @classmethod
    def _strip_keyword(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("keyword must not be blank")
        return v

    @field_validator("severity")
    @classmethod
    def _valid_severity(cls, v: str) -> str:
        v = (v or "").strip().lower() or "medium"
        if v not in SEVERITY_VALUES:
            raise ValueError(f"severity must be one of {sorted(SEVERITY_VALUES)}")
        return v


class SensitiveKeywordUpdate(BaseModel):
    category: Optional[str] = Field(default=None, max_length=64)
    severity: Optional[str] = Field(default=None)
    is_active: Optional[bool] = None
    remark: Optional[str] = Field(default=None, max_length=512)

    @field_validator("severity")
    @classmethod
    def _valid_severity(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().lower()
        if v not in SEVERITY_VALUES:
            raise ValueError(f"severity must be one of {sorted(SEVERITY_VALUES)}")
        return v


class SensitiveKeywordOut(BaseModel):
    id: int
    keyword: str
    category: str
    severity: str
    is_active: bool
    remark: str
    created_at: datetime
    updated_at: datetime


class SubjectKeywordCreate(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=128)
    category: str = Field("", max_length=64)
    is_active: bool = True
    remark: str = Field("", max_length=512)

    @field_validator("keyword")
    @classmethod
    def _strip_keyword(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("keyword must not be blank")
        return v


class SubjectKeywordUpdate(BaseModel):
    category: Optional[str] = Field(default=None, max_length=64)
    is_active: Optional[bool] = None
    remark: Optional[str] = Field(default=None, max_length=512)


class SubjectKeywordOut(BaseModel):
    id: int
    keyword: str
    category: str
    is_active: bool
    remark: str
    created_at: datetime
    updated_at: datetime


class RiskThresholdItem(BaseModel):
    level: str
    min_score: int = Field(..., ge=0, le=100)

    @field_validator("level")
    @classmethod
    def _valid_level(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in RISK_LEVELS:
            raise ValueError(f"level must be one of {RISK_LEVELS}")
        return v


class RiskThresholdUpdate(BaseModel):
    thresholds: list[RiskThresholdItem] = Field(..., min_length=1)


class RiskThresholdOut(BaseModel):
    level: str
    min_score: int
    updated_at: datetime
