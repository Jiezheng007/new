from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, user_to_dict
from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, UserOut
from app.services.audit import get_client_ip, record_audit


router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key="access_token",
        value=token,
        max_age=settings.access_token_ttl_minutes * 60,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie("access_token", path="/")


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    user = db.query(User).filter(User.username == payload.username).one_or_none()
    settings = get_settings()
    ip = get_client_ip(request)

    if user is None:
        record_audit(
            db,
            actor=None,
            action="auth.login",
            target_type="user",
            target_id=payload.username,
            result="failure",
            detail={"reason": "unknown_user", "username": payload.username},
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    if not user.is_active:
        record_audit(
            db,
            actor=user,
            action="auth.login",
            target_type="user",
            target_id=str(user.id),
            result="failure",
            detail={"reason": "user_disabled", "username": user.username},
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    from app.core.security import verify_password

    if not verify_password(payload.password, user.password_hash):
        record_audit(
            db,
            actor=user,
            action="auth.login",
            target_type="user",
            target_id=str(user.id),
            result="failure",
            detail={"reason": "bad_password", "username": user.username},
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    token = create_access_token(subject=user.username, extra_claims={"uid": user.id, "role": user.role.code})
    record_audit(
        db,
        actor=user,
        action="auth.login",
        target_type="user",
        target_id=str(user.id),
        result="success",
        detail={"username": user.username, "role": user.role.code},
        ip_address=ip,
    )
    db.commit()
    _set_cookie(response, token)
    return TokenResponse(access_token=token, expires_in=settings.access_token_ttl_minutes * 60)


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    # Logout is fire-and-forget so we record only if we can identify the
    # caller. Anonymous logout (already-expired cookie) is silently
    # ignored - there is nothing meaningful to audit.
    token = request.cookies.get("access_token")
    if token:
        from app.core.security import decode_access_token

        payload = decode_access_token(token)
        if payload and payload.get("uid"):
            actor = db.get(User, int(payload["uid"]))
            if actor is not None:
                record_audit(
                    db,
                    actor=actor,
                    action="auth.logout",
                    target_type="user",
                    target_id=str(actor.id),
                    result="success",
                    detail={"username": actor.username},
                    ip_address=get_client_ip(request),
                )
                db.commit()
    _clear_cookie(response)
    return {"detail": "logged out"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    data = user_to_dict(user)
    return UserOut(**data)
