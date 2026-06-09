"""Pydantic schemas for the opinion-item list/detail API (Phase 3 / Issue 4)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


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


class OpinionListOut(BaseModel):
    total: int
    items: list[OpinionItemOut]
