"""Pydantic schemas for data-source management (Phase 3 / Issue 4)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.connectors import (
    ALL_SOURCE_TYPES,
    SOURCE_TYPE_RSS,
    SOURCE_TYPE_STATIC_DEMO,
)


class DataSourceCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    source_type: str = Field(...)
    url: str = Field("", max_length=512)
    weight: float = Field(1.0, ge=0.0, le=10.0)
    is_enabled: bool = True
    description: str = Field("", max_length=512)

    @field_validator("code")
    @classmethod
    def _code_no_spaces(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("code must not be blank")
        if any(ch.isspace() for ch in v):
            raise ValueError("code must not contain whitespace")
        return v

    @field_validator("source_type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in ALL_SOURCE_TYPES:
            raise ValueError(f"source_type must be one of {ALL_SOURCE_TYPES}")
        return v

    @model_validator(mode="after")
    def _url_required_for_network(self) -> "DataSourceCreate":
        if self.source_type in (SOURCE_TYPE_RSS, "json_url") and not (self.url or "").strip():
            raise ValueError("url is required for RSS / json_url data sources")
        return self


class DataSourceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    url: Optional[str] = Field(default=None, max_length=512)
    weight: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    is_active: Optional[bool] = None
    is_enabled: Optional[bool] = None
    description: Optional[str] = Field(default=None, max_length=512)


class DataSourceOut(BaseModel):
    id: int
    code: str
    name: str
    source_type: str
    url: str
    weight: float
    is_enabled: bool
    description: str
    latest_fetch_at: Optional[datetime]
    latest_fetch_status: str
    latest_fetch_message: str
    latest_items_count: int
    created_at: datetime
    updated_at: datetime


class FetchResult(BaseModel):
    source_id: int
    source_code: str
    status: str
    accepted: int
    rejected: int
    duplicate: int
    errors: list[dict]
    message: str
    fetched_at: datetime
