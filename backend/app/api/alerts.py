"""Alert lifecycle API (Phase 5 / Issue 7).

Endpoints:
  - GET    /api/alerts                list with filters (read)
  - GET    /api/alerts/{id}           detail of one alert (read)
  - POST   /api/alerts/{id}/confirm   pending -> confirmed (write)
  - POST   /api/alerts/{id}/ignore    pending -> ignored (write)
  - GET    /api/alerts/summary        count by status (read)

Read access: admin, risk_control, auditor.
Write access: admin, risk_control. Handlers and viewers are blocked
from every endpoint, matching the role permissions defined in
``app/models/role_codes.py``.

Every state change writes an ``AuditLog`` row with actor, action,
target_id, result, IP address, and timestamp - same shape as
Phase 2-4 used for the other write paths.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.alert import (
    ALERT_STATUS_CONFIRMED,
    ALERT_STATUS_IGNORED,
    ALERT_STATUS_PENDING,
    Alert,
)
from app.models.role_codes import RoleCode
from app.models.user import User
from app.schemas.alerts import (
    ALERT_LEVEL_VALUES,
    ALERT_STATUS_VALUES,
    AlertConfirmResultOut,
    AlertIgnoreRequest,
    AlertIgnoreResultOut,
    AlertListOut,
    AlertOut,
    AlertSummaryOut,
)
from app.services.alerts import (
    AlertStateError,
    IGNORE_REASON_MIN,
    alert_to_dict,
    confirm_alert,
    count_alerts_by_status,
    get_alert,
    ignore_alert,
    list_alerts,
)
from app.services.audit import get_client_ip, record_audit


router = APIRouter(prefix="/api/alerts", tags=["alerts"])


_ALERT_READ_ROLES = {RoleCode.ADMIN, RoleCode.RISK_CONTROL, RoleCode.AUDITOR}
_ALERT_WRITE_ROLES = {RoleCode.ADMIN, RoleCode.RISK_CONTROL}


def _require_alert_reader(user: User = Depends(get_current_user)) -> User:
    if user.role.code not in _ALERT_READ_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.code}' cannot read alerts",
        )
    return user


def _require_alert_writer(user: User = Depends(get_current_user)) -> User:
    if user.role.code not in _ALERT_WRITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.code}' cannot confirm or ignore alerts",
        )
    return user


@router.get("", response_model=AlertListOut)
def list_alerts_endpoint(
    status_filter: Optional[str] = Query(None, alias="status", description="状态过滤"),
    risk_level: Optional[str] = Query(None, description="风险等级过滤"),
    source_id: Optional[int] = Query(None, description="数据源 ID 过滤"),
    q: Optional[str] = Query(None, description="关键词,匹配标题或正文"),
    start_at: Optional[datetime] = Query(None, description="创建时间下界 (ISO-8601)"),
    end_at: Optional[datetime] = Query(None, description="创建时间上界 (ISO-8601)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(_require_alert_reader),
) -> AlertListOut:
    if status_filter is not None and status_filter not in ALERT_STATUS_VALUES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status 必须是 {sorted(ALERT_STATUS_VALUES)}",
        )
    if risk_level is not None and risk_level not in ALERT_LEVEL_VALUES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"risk_level 必须是 {sorted(ALERT_LEVEL_VALUES)}",
        )

    rows, total = list_alerts(
        db,
        status_filter=status_filter,
        level_filter=risk_level,
        source_id=source_id,
        keyword=q,
        start_at=start_at,
        end_at=end_at,
        limit=limit,
        offset=offset,
    )
    return AlertListOut(
        total=total,
        items=[AlertOut(**alert_to_dict(r)) for r in rows],
    )


@router.get("/summary", response_model=AlertSummaryOut)
def alert_summary_endpoint(
    db: Session = Depends(get_db),
    _: User = Depends(_require_alert_reader),
) -> AlertSummaryOut:
    counts = count_alerts_by_status(db)
    return AlertSummaryOut(
        pending=counts[ALERT_STATUS_PENDING],
        confirmed=counts[ALERT_STATUS_CONFIRMED],
        ignored=counts[ALERT_STATUS_IGNORED],
        total=counts["total"],
    )


@router.get("/{alert_id}", response_model=AlertOut)
def get_alert_endpoint(
    alert_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(_require_alert_reader),
) -> AlertOut:
    alert = get_alert(db, alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预警不存在")
    return AlertOut(**alert_to_dict(alert))


@router.post("/{alert_id}/confirm", response_model=AlertConfirmResultOut)
def confirm_alert_endpoint(
    alert_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(_require_alert_writer),
) -> AlertConfirmResultOut:
    ip = get_client_ip(request)
    alert = get_alert(db, alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预警不存在")
    try:
        confirm_alert(db, alert, actor=actor, ip_address=ip)
    except AlertStateError as e:
        record_audit(
            db,
            actor=actor,
            action="alert.confirm",
            target_type="alert",
            target_id=str(alert.id),
            result="failure",
            detail={
                "reason": "invalid_state",
                "current_status": e.current_status,
            },
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"预警当前状态为 {e.current_status},无法确认",
        )

    record_audit(
        db,
        actor=actor,
        action="alert.confirm",
        target_type="alert",
        target_id=str(alert.id),
        result="success",
        detail={
            "opinion_item_id": alert.opinion_item_id,
            "risk_level": alert.risk_level,
            "risk_score": alert.risk_score,
        },
        ip_address=ip,
    )
    db.commit()
    db.refresh(alert)
    return AlertConfirmResultOut(
        id=alert.id,
        status=alert.status,
        confirmed_by_username=alert.confirmed_by_username,
        confirmed_at=alert.confirmed_at,
    )


@router.post("/{alert_id}/ignore", response_model=AlertIgnoreResultOut)
def ignore_alert_endpoint(
    alert_id: int,
    payload: AlertIgnoreRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(_require_alert_writer),
) -> AlertIgnoreResultOut:
    ip = get_client_ip(request)
    alert = get_alert(db, alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预警不存在")

    # The schema validator already rejects blank reasons, but we re-check
    # the lower bound the service enforces (so direct service calls from
    # other code paths stay protected too).
    reason_clean = (payload.reason or "").strip()
    if len(reason_clean) < IGNORE_REASON_MIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"忽略原因至少 {IGNORE_REASON_MIN} 个字符",
        )

    try:
        ignore_alert(db, alert, actor=actor, reason=reason_clean, ip_address=ip)
    except AlertStateError as e:
        record_audit(
            db,
            actor=actor,
            action="alert.ignore",
            target_type="alert",
            target_id=str(alert.id),
            result="failure",
            detail={
                "reason": "invalid_state",
                "current_status": e.current_status,
            },
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"预警当前状态为 {e.current_status},无法忽略",
        )

    record_audit(
        db,
        actor=actor,
        action="alert.ignore",
        target_type="alert",
        target_id=str(alert.id),
        result="success",
        detail={
            "opinion_item_id": alert.opinion_item_id,
            "risk_level": alert.risk_level,
            "risk_score": alert.risk_score,
            "ignore_reason": alert.ignore_reason,
        },
        ip_address=ip,
    )
    db.commit()
    db.refresh(alert)
    return AlertIgnoreResultOut(
        id=alert.id,
        status=alert.status,
        ignored_by_username=alert.ignored_by_username,
        ignored_at=alert.ignored_at,
        ignore_reason=alert.ignore_reason,
    )
