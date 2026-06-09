"""Database initialization: create tables, seed roles, create bootstrap admin and demo users."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import Base, engine
from app.models.role_codes import ROLE_SEEDS, RoleCode
from app.models.user import Role, User


_DEMO_USERS: list[tuple[str, str, str, str]] = [
    (RoleCode.RISK_CONTROL, "risk", "风控演示账号", "risk123"),
    (RoleCode.HANDLER, "handler", "处置演示账号", "handler123"),
    (RoleCode.AUDITOR, "auditor", "审计演示账号", "auditor123"),
    (RoleCode.VIEWER, "viewer", "查看演示账号", "viewer123"),
]


def init_db() -> None:
    """Create tables, seed roles, and ensure a bootstrap admin + demo users exist."""
    from app.models import user  # noqa: F401 - ensure model registration

    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        _seed_roles(db)
        db.commit()
        _seed_admin(db)
        db.commit()
        _seed_demo_users(db)
        db.commit()


def _seed_roles(db: Session) -> None:
    existing = {role.code for role in db.query(Role).all()}
    for code, name, description in ROLE_SEEDS:
        if code in existing:
            continue
        db.add(Role(code=code, name=name, description=description))


def _seed_admin(db: Session) -> None:
    settings = get_settings()
    username = settings.bootstrap_admin_username
    password = settings.bootstrap_admin_password
    if not username or not password:
        return
    user = db.query(User).filter(User.username == username).one_or_none()
    if user is not None:
        return
    admin_role = db.query(Role).filter(Role.code == RoleCode.ADMIN).one_or_none()
    if admin_role is None:
        return
    db.add(
        User(
            username=username,
            full_name="Bootstrap Admin",
            password_hash=hash_password(password),
            is_active=True,
            role_id=admin_role.id,
        )
    )


def _seed_demo_users(db: Session) -> None:
    """Create one demo account per non-admin role so the Web UI is fully demoable."""
    for role_code, username, full_name, password in _DEMO_USERS:
        if db.query(User).filter(User.username == username).first():
            continue
        role = db.query(Role).filter(Role.code == role_code).one_or_none()
        if role is None:
            continue
        db.add(
            User(
                username=username,
                full_name=full_name,
                password_hash=hash_password(password),
                is_active=True,
                role_id=role.id,
            )
        )
