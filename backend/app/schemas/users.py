"""Schemas for the user management API (Phase 2 / Issue 2)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    full_name: str = Field("", max_length=128)
    password: str = Field(..., min_length=6, max_length=128)
    role_id: int = Field(..., ge=1)
    is_active: bool = True

    @field_validator("username")
    @classmethod
    def _username_no_spaces(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("username must not be blank")
        if any(ch.isspace() for ch in v):
            raise ValueError("username must not contain whitespace")
        return v


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=128)
    role_id: Optional[int] = Field(default=None, ge=1)
    is_active: Optional[bool] = None


class PasswordResetRequest(BaseModel):
    new_password: Optional[str] = Field(default=None, min_length=6, max_length=128)


class PasswordResetResponse(BaseModel):
    new_password: str
    generated: bool


class RoleInfo(BaseModel):
    id: int
    code: str
    name: str
    description: str
    permissions: list[str]


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    is_active: bool
    role_id: int
    role: str
    role_name: str
    permissions: list[str]
    nav_items: list[dict]
    created_at: datetime
    updated_at: datetime
