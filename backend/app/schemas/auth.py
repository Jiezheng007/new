from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    is_active: bool
    role: str
    role_name: str
    permissions: list[str]
    nav_items: list[dict]
    created_at: datetime
