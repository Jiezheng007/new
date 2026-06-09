"""User management API: admin-only CRUD over users, password reset, role listing.

All endpoints require an authenticated admin. Every state change writes an
audit log row with actor, action, target, result, IP, and timestamp.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, role_permissions, user_to_dict
from app.core.security import hash_password, random_token
from app.db.session import get_db
from app.models.audit import AuditLog  # noqa: F401 - ensure table registration
from app.models.role_codes import RoleCode
from app.models.user import Role, User
from app.schemas.users import (
    PasswordResetRequest,
    PasswordResetResponse,
    RoleInfo,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.services.audit import get_client_ip, record_audit


router = APIRouter(prefix="/api", tags=["user-management"])


def _require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role.code != RoleCode.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only system administrators can manage users",
        )
    return user


def _serialize_user(user: User) -> dict[str, Any]:
    base = user_to_dict(user)
    base["role_id"] = user.role_id
    base["updated_at"] = user.updated_at
    return base


def _role_id_for_code(db: Session, code: str) -> int:
    role = db.query(Role).filter(Role.code == code).one_or_none()
    if role is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Role '{code}' is missing")
    return role.id


@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> list[UserOut]:
    users = db.query(User).order_by(User.id.asc()).all()
    return [UserOut(**_serialize_user(u)) for u in users]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> UserOut:
    ip = get_client_ip(request)
    if db.query(User).filter(User.username == payload.username).first():
        record_audit(
            db,
            actor=admin,
            action="user.create",
            target_type="user",
            target_id=payload.username,
            result="failure",
            detail={"reason": "username_taken", "username": payload.username},
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    role = db.get(Role, payload.role_id)
    if role is None:
        record_audit(
            db,
            actor=admin,
            action="user.create",
            target_type="user",
            target_id=payload.username,
            result="failure",
            detail={"reason": "invalid_role", "role_id": payload.role_id},
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role not found")

    user = User(
        username=payload.username,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        is_active=payload.is_active,
        role_id=role.id,
    )
    db.add(user)
    db.flush()

    record_audit(
        db,
        actor=admin,
        action="user.create",
        target_type="user",
        target_id=str(user.id),
        result="success",
        detail={
            "username": user.username,
            "role": role.code,
            "is_active": user.is_active,
        },
        ip_address=ip,
    )
    db.commit()
    db.refresh(user)
    return UserOut(**_serialize_user(user))


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> UserOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserOut(**_serialize_user(user))


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> UserOut:
    ip = get_client_ip(request)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    changes: dict[str, Any] = {}
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}

    if payload.full_name is not None and payload.full_name != user.full_name:
        before["full_name"] = user.full_name
        after["full_name"] = payload.full_name
        changes["full_name"] = payload.full_name
        user.full_name = payload.full_name

    if payload.role_id is not None and payload.role_id != user.role_id:
        new_role = db.get(Role, payload.role_id)
        if new_role is None:
            record_audit(
                db,
                actor=admin,
                action="user.update",
                target_type="user",
                target_id=str(user.id),
                result="failure",
                detail={"reason": "invalid_role", "role_id": payload.role_id},
                ip_address=ip,
            )
            db.commit()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role not found")
        if user.id == admin.id and new_role.code != RoleCode.ADMIN:
            record_audit(
                db,
                actor=admin,
                action="user.update",
                target_type="user",
                target_id=str(user.id),
                result="failure",
                detail={"reason": "self_demote_blocked", "from": user.role.code, "to": new_role.code},
                ip_address=ip,
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Administrators cannot remove their own admin role",
            )
        before["role"] = user.role.code
        after["role"] = new_role.code
        changes["role"] = new_role.code
        user.role_id = new_role.id

    if payload.is_active is not None and payload.is_active != user.is_active:
        if user.id == admin.id and payload.is_active is False:
            record_audit(
                db,
                actor=admin,
                action="user.update",
                target_type="user",
                target_id=str(user.id),
                result="failure",
                detail={"reason": "self_disable_blocked"},
                ip_address=ip,
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Administrators cannot disable their own account",
            )
        before["is_active"] = user.is_active
        after["is_active"] = payload.is_active
        changes["is_active"] = payload.is_active
        user.is_active = payload.is_active

    if not changes:
        return UserOut(**_serialize_user(user))

    record_audit(
        db,
        actor=admin,
        action="user.update",
        target_type="user",
        target_id=str(user.id),
        result="success",
        detail={"username": user.username, "changes": changes, "before": before, "after": after},
        ip_address=ip,
    )
    db.commit()
    db.refresh(user)
    return UserOut(**_serialize_user(user))


@router.post("/users/{user_id}/reset-password", response_model=PasswordResetResponse)
def reset_password(
    user_id: int,
    payload: PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> PasswordResetResponse:
    ip = get_client_ip(request)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if payload.new_password:
        new_plain = payload.new_password
        generated = False
    else:
        new_plain = random_token()[:12]
        generated = True

    user.password_hash = hash_password(new_plain)
    record_audit(
        db,
        actor=admin,
        action="user.reset_password",
        target_type="user",
        target_id=str(user.id),
        result="success",
        detail={"username": user.username, "generated": generated},
        ip_address=ip,
    )
    db.commit()
    return PasswordResetResponse(new_password=new_plain, generated=generated)


@router.get("/roles", response_model=list[RoleInfo])
def list_roles(
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> list[RoleInfo]:
    roles = db.query(Role).order_by(Role.id.asc()).all()
    out: list[RoleInfo] = []
    for r in roles:
        perms = role_permissions(r.code)
        out.append(RoleInfo(
            id=r.id,
            code=r.code,
            name=r.name,
            description=r.description,
            permissions=perms,
        ))
    return out
