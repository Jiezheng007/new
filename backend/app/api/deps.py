"""Reusable FastAPI dependencies: current user resolution, role enforcement."""
from __future__ import annotations

from typing import Iterable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.role_codes import ROLE_NAV_ITEMS, ROLE_PERMISSIONS
from app.models.user import User


bearer_scheme = HTTPBearer(auto_error=False)


def _token_from_request(request: Request, creds: HTTPAuthorizationCredentials | None) -> str | None:
    if creds and creds.scheme.lower() == "bearer" and creds.credentials:
        return creds.credentials
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        return cookie_token
    return None


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = _token_from_request(request, creds)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user_id = payload.get("uid")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    user = db.get(User, int(user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or disabled")
    return user


def require_roles(*role_codes: str):
    allowed = set(role_codes)

    def _checker(user: User = Depends(get_current_user)) -> User:
        if not allowed:
            return user
        if user.role.code not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role.code}' is not permitted for this action",
            )
        return user

    return _checker


def role_permissions(role_code: str) -> list[str]:
    return ROLE_PERMISSIONS.get(role_code, [])


def role_nav_items(role_code: str) -> list[dict]:
    return ROLE_NAV_ITEMS.get(role_code, [])


def user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "role": user.role.code,
        "role_name": user.role.name,
        "permissions": role_permissions(user.role.code),
        "nav_items": role_nav_items(user.role.code),
        "created_at": user.created_at,
    }


def ensure_allowed(role_codes: Iterable[str], user: User) -> None:
    if user.role.code not in set(role_codes):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.code}' is not permitted for this action",
        )
