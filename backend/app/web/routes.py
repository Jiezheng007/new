"""Server-rendered Web UI: login page, layout shell, role-aware navigation.

This intentionally uses Jinja2 templates rather than a JS SPA - the Web UI is
a backend-management style interface, not a marketing site. The shell is fully
server-rendered for phase 1; later phases will fill in the per-page features
without changing the navigation or layout.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.role_codes import ROLE_NAV_ITEMS
from app.models.user import User
from pathlib import Path


_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))

web_router = APIRouter(prefix="/web", tags=["web"], include_in_schema=False)
pages_router = APIRouter(tags=["pages"], include_in_schema=False)


def _current_user_from_cookie_or_none(request: Request, db: Session) -> User | None:
    token = request.cookies.get("access_token")
    if not token:
        return None
    from app.core.security import decode_access_token

    payload = decode_access_token(token)
    if not payload:
        return None
    user_id = payload.get("uid")
    if not user_id:
        return None
    user = db.get(User, int(user_id))
    if not user or not user.is_active:
        return None
    return user


def _require_web_user(request: Request, db: Session) -> User:
    user = _current_user_from_cookie_or_none(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


@pages_router.get("/", response_class=HTMLResponse)
def root(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    user = _current_user_from_cookie_or_none(request, db)
    if user:
        return RedirectResponse(url="/web/workbench", status_code=302)
    return RedirectResponse(url="/login", status_code=302)


@web_router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    user = _current_user_from_cookie_or_none(request, db)
    if user:
        return RedirectResponse(url="/web/workbench", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": None, "username": ""})


@pages_router.get("/login", response_class=HTMLResponse)
def login_alias(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return login_page(request, db)


_PAGE_KEY_TO_PATH = {
    "workbench": "workbench.html",
    "datasources": "datasources.html",
    "rules": "rules.html",
    "import": "import.html",
    "opinions": "opinions.html",
    "alerts": "alerts.html",
    "tickets": "tickets.html",
    "reports": "placeholder.html",
    "users": "users.html",
    "audit": "placeholder.html",
}


@web_router.get("/{page_key}", response_class=HTMLResponse)
def render_page(page_key: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    user = _require_web_user(request, db)
    if page_key not in _PAGE_KEY_TO_PATH:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")
    nav_items = ROLE_NAV_ITEMS.get(user.role.code, [])
    allowed_keys = {item["key"] for item in nav_items}
    if page_key not in allowed_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.code}' cannot access page '{page_key}'",
        )
    template_name = _PAGE_KEY_TO_PATH[page_key]
    context = {
        "user": {
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role.code,
            "role_name": user.role.name,
        },
        "nav_items": nav_items,
        "active_key": page_key,
        "page_title": _page_title(page_key),
    }
    response = templates.TemplateResponse(request, template_name, context)
    # Expose the current role to the page-level JS so per-page scripts
    # (e.g. alerts.js) can hide write actions for read-only roles without
    # an extra roundtrip to /api/auth/me.
    response.headers["X-User-Role"] = user.role.code
    return response


def _page_title(key: str) -> str:
    titles = {
        "workbench": "工作台",
        "datasources": "数据源管理",
        "rules": "风险规则",
        "import": "数据导入",
        "opinions": "舆情列表",
        "alerts": "预警中心",
        "tickets": "工单管理",
        "reports": "报告中心",
        "users": "用户与角色",
        "audit": "审计日志",
    }
    return titles.get(key, key)
