"""Audit-log review API (Phase 9 / Issue 11).

Endpoints:
  - GET /api/audit-logs          paginated list with filters
  - GET /api/audit-logs/facets   distinct action / target / result / actor
  - GET /api/audit-logs/{id}     detail for a single row

Role rules:
  * Read: ``admin`` (catch-all) and ``auditor`` (the role whose whole
    purpose is reviewing audit trails). Every other role - including
    risk_control, handler, and viewer - gets a 403.

This router is read-only on purpose. The audit log is append-only and
the only writer is :func:`services.audit.record_audit`, which is called
from inside the transaction of the business action that produced it.
A delete or update endpoint here would defeat the point of the log.

Listing the audit log is *itself* a sensitive operation but we do not
audit a successful list - that would produce an unbounded recursion of
``audit.list`` entries every time an auditor opens the page. The
service-side query is bounded by ``limit`` (``<=`` 200), so the page
cannot be used to exfiltrate the whole table in one call.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.role_codes import RoleCode
from app.models.user import User
from app.schemas.audit import (
    AUDIT_RESULT_VALUES,
    AuditLogFacetsOut,
    AuditLogListOut,
    AuditLogOut,
)
from app.services.audit import (
    audit_log_facets,
    audit_log_to_dict,
    get_audit_log,
    list_audit_logs,
)


router = APIRouter(prefix="/api/audit-logs", tags=["audit"])


_AUDIT_READ_ROLES = {RoleCode.ADMIN, RoleCode.AUDITOR}


def _require_audit_reader(user: User = Depends(get_current_user)) -> User:
    if user.role.code not in _AUDIT_READ_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.code}' cannot read audit logs",
        )
    return user


@router.get("", response_model=AuditLogListOut)
def list_audit_logs_endpoint(
    action: Optional[str] = Query(None, description="操作类型,例如 alert.confirm"),
    target_type: Optional[str] = Query(None, description="目标实体类型,例如 ticket / user"),
    target_id: Optional[str] = Query(None, description="目标实体 ID 精确匹配"),
    actor: Optional[str] = Query(None, description="操作人用户名或 ID"),
    result: Optional[str] = Query(None, description="success 或 failure"),
    start_at: Optional[datetime] = Query(None, description="开始时间 (ISO-8601)"),
    end_at: Optional[datetime] = Query(None, description="结束时间 (ISO-8601)"),
    q: Optional[str] = Query(None, description="在 detail JSON 中做子串查询"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(_require_audit_reader),
) -> AuditLogListOut:
    if result is not None and result not in AUDIT_RESULT_VALUES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"result 必须是 {sorted(AUDIT_RESULT_VALUES)}",
        )
    rows, total = list_audit_logs(
        db,
        action=action,
        target_type=target_type,
        target_id=target_id,
        actor=actor,
        result=result,
        start_at=start_at,
        end_at=end_at,
        keyword=q,
        limit=limit,
        offset=offset,
    )
    return AuditLogListOut(
        total=total,
        items=[AuditLogOut(**audit_log_to_dict(r)) for r in rows],
    )


@router.get("/facets", response_model=AuditLogFacetsOut)
def audit_log_facets_endpoint(
    db: Session = Depends(get_db),
    _: User = Depends(_require_audit_reader),
) -> AuditLogFacetsOut:
    data = audit_log_facets(db)
    return AuditLogFacetsOut(**data)


@router.get("/{log_id}", response_model=AuditLogOut)
def get_audit_log_endpoint(
    log_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(_require_audit_reader),
) -> AuditLogOut:
    entry = get_audit_log(db, log_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="审计日志不存在")
    return AuditLogOut(**audit_log_to_dict(entry))
