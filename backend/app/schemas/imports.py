"""Pydantic schemas for the CSV / JSON import API (Phase 3 / Issue 5)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ImportResultOut(BaseModel):
    format: str
    accepted: int
    rejected: int
    duplicate: int
    errors: list[dict[str, Any]]
    sample_ids: list[int]
    message: str
