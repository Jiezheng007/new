"""Sample protected business endpoints to demonstrate RBAC enforcement.

These are intentionally minimal placeholders that later phases will replace
with real features (data sources, opinion lists, alerts, tickets, reports,
audit logs). They exist now so Phase 1 can prove that:
  - unauthenticated requests are rejected (401)
  - authenticated requests with the wrong role are rejected (403)
  - authenticated requests with the right role succeed (200)
"""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.role_codes import RoleCode
from app.models.user import User


router = APIRouter(prefix="/api/protected", tags=["protected"])


@router.get("/risk-control")
def risk_control_area(user: User = Depends(get_current_user)) -> dict:
    if user.role.code not in (RoleCode.ADMIN, RoleCode.RISK_CONTROL):
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.code}' is not permitted for this action",
        )
    return {"area": "risk-control", "user": user.username, "role": user.role.code}


@router.get("/handler")
def handler_area(user: User = Depends(get_current_user)) -> dict:
    if user.role.code not in (RoleCode.ADMIN, RoleCode.HANDLER):
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.code}' is not permitted for this action",
        )
    return {"area": "handler", "user": user.username, "role": user.role.code}


@router.get("/auditor")
def auditor_area(user: User = Depends(get_current_user)) -> dict:
    if user.role.code not in (RoleCode.ADMIN, RoleCode.AUDITOR):
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.code}' is not permitted for this action",
        )
    return {"area": "auditor", "user": user.username, "role": user.role.code}


@router.get("/dashboard")
def dashboard_area(user: User = Depends(get_current_user)) -> dict:
    return {"area": "dashboard", "user": user.username, "role": user.role.code}


@router.get("/admin")
def admin_area(user: User = Depends(get_current_user)) -> dict:
    if user.role.code != RoleCode.ADMIN:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.code}' is not permitted for this action",
        )
    return {"area": "admin", "user": user.username, "role": user.role.code}
