"""Pydantic schemas for data-source management (Phase 3 / Issue 4)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.connectors import (
    ALL_SOURCE_TYPES,
    SOURCE_TYPE_NEWS_SEARCH,
    SOURCE_TYPE_JSON_URL,
    SOURCE_TYPE_RSS,
    SOURCE_TYPE_WEIBO,
)


class DataSourceCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    source_type: str = Field(...)
    url: str = Field("", max_length=512)
    query: str = Field("", max_length=1024)
    fetch_interval_minutes: int = Field(60, ge=5, le=1440)
    max_items_per_fetch: int = Field(50, ge=1, le=100)
    config: dict[str, Any] = Field(default_factory=dict)
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
        network_types = (SOURCE_TYPE_RSS, SOURCE_TYPE_JSON_URL, SOURCE_TYPE_WEIBO)
        if self.source_type in network_types and not (self.url or "").strip():
            raise ValueError("url is required for RSS / json_url / weibo data sources")
        if self.source_type == SOURCE_TYPE_NEWS_SEARCH and not (self.query or "").strip():
            raise ValueError("query is required for news_search data sources")
        return self


class DataSourceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    url: Optional[str] = Field(default=None, max_length=512)
    query: Optional[str] = Field(default=None, max_length=1024)
    fetch_interval_minutes: Optional[int] = Field(default=None, ge=5, le=1440)
    max_items_per_fetch: Optional[int] = Field(default=None, ge=1, le=100)
    config: Optional[dict[str, Any]] = None
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
    query: str
    fetch_interval_minutes: int
    max_items_per_fetch: int
    config: dict[str, Any]
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


class DataSourceTestRequest(BaseModel):
    source_type: str = Field(...)
    url: str = Field("", max_length=512)
    query: str = Field("", max_length=1024)
    max_items_per_fetch: int = Field(5, ge=1, le=100)
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in ALL_SOURCE_TYPES:
            raise ValueError(f"source_type must be one of {ALL_SOURCE_TYPES}")
        return v

    @model_validator(mode="after")
    def _required_input_for_type(self) -> "DataSourceTestRequest":
        network_types = (SOURCE_TYPE_RSS, SOURCE_TYPE_JSON_URL, SOURCE_TYPE_WEIBO)
        if self.source_type in network_types and not (self.url or "").strip():
            raise ValueError("url is required for RSS / json_url / weibo data sources")
        if self.source_type == SOURCE_TYPE_NEWS_SEARCH and not (self.query or "").strip():
            raise ValueError("query is required for news_search data sources")
        return self


class DataSourceTestSample(BaseModel):
    title: str
    content: str
    url: str
    author: str
    published_at: Optional[datetime]


class DataSourceTestResult(BaseModel):
    ok: bool
    sample_count: int
    samples: list[DataSourceTestSample]
    message: str
    error_code: str = ""
