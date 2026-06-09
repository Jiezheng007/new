from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, user_to_dict
from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, UserOut


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
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.username == payload.username).one_or_none()
    settings = get_settings()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    from app.core.security import verify_password

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    token = create_access_token(subject=user.username, extra_claims={"uid": user.id, "role": user.role.code})
    _set_cookie(response, token)
    return TokenResponse(access_token=token, expires_in=settings.access_token_ttl_minutes * 60)


@router.post("/logout")
def logout(response: Response) -> dict:
    _clear_cookie(response)
    return {"detail": "logged out"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    data = user_to_dict(user)
    return UserOut(**data)
