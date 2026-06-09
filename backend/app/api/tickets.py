"""Ticket lifecycle API (Phase 6 / Issue 8).

Endpoints:
  - GET    /api/tickets                 list with filters (read)
  - GET    /api/tickets/summary         count by status (read)
  - GET    /api/tickets/{id}            detail of one ticket (read)
  - POST   /api/tickets/from-alert      create from confirmed alert (write)
  - POST   /api/tickets/{id}/assign     pick a handler (write)
  - POST   /api/tickets/{id}/start      handler accepts (write)
  - POST   /api/tickets/{id}/complete   handler submits result (write)
  - POST   /api/tickets/{id}/archive    risk-control closes (write)

Role rules:
  * Read: admin, risk_control, handler (only their own), auditor.
  * Create / assign / archive: admin, risk_control.
  * Start / complete: admin or the assigned handler.

Every state change writes an ``AuditLog`` row with actor, action,
target_id, result, IP address, and timestamp - same shape as
Phase 5 used for the alert lifecycle.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.role_codes import RoleCode
from app.models.user import User
from app.schemas.tickets import (
    TICKET_LEVEL_VALUES,
    TICKET_STATUS_VALUES,
    TicketArchiveResultOut,
    TicketAssignRequest,
    TicketAssignResultOut,
    TicketCompleteRequest,
    TicketCompleteResultOut,
    TicketCreateRequest,
    TicketCreateResultOut,
    TicketListOut,
    TicketOut,
    TicketStartResultOut,
    TicketSummaryOut,
)
from app.services.alerts import get_alert
from app.services.audit import get_client_ip, record_audit
from app.services.tickets import (
    TicketInputError,
    TicketStateError,
    archive_ticket,
    assign_ticket,
    complete_ticket,
    count_tickets_by_status,
    create_ticket_from_alert,
    get_ticket,
    list_tickets,
    start_ticket,
    ticket_to_dict,
)


router = APIRouter(prefix="/api/tickets", tags=["tickets"])


_TICKET_READ_ROLES = {RoleCode.ADMIN, RoleCode.RISK_CONTROL, RoleCode.HANDLER, RoleCode.AUDITOR}
_TICKET_MANAGE_ROLES = {RoleCode.ADMIN, RoleCode.RISK_CONTROL}


def _require_ticket_reader(user: User = Depends(get_current_user)) -> User:
    if user.role.code not in _TICKET_READ_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.code}' cannot read tickets",
        )
    return user


def _require_ticket_manager(user: User = Depends(get_current_user)) -> User:
    if user.role.code not in _TICKET_MANAGE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.code}' cannot manage tickets",
        )
    return user


def _audit_and_commit(
    db: Session,
    *,
    actor: User,
    action: str,
    target_id: str,
    result: str,
    detail: dict,
    ip: str,
) -> None:
    record_audit(
        db,
        actor=actor,
        action=action,
        target_type="ticket",
        target_id=target_id,
        result=result,
        detail=detail,
        ip_address=ip,
    )
    db.commit()


# ---------- list / detail / summary ----------


@router.get("", response_model=TicketListOut)
def list_tickets_endpoint(
    status_filter: Optional[str] = Query(None, alias="status", description="状态过滤"),
    risk_level: Optional[str] = Query(None, description="风险等级过滤"),
    assignee_id: Optional[int] = Query(None, description="处置人 ID 过滤"),
    q: Optional[str] = Query(None, description="关键词,匹配标题或正文"),
    start_at: Optional[datetime] = Query(None, description="创建时间下界 (ISO-8601)"),
    end_at: Optional[datetime] = Query(None, description="创建时间上界 (ISO-8601)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    viewer: User = Depends(_require_ticket_reader),
) -> TicketListOut:
    if status_filter is not None and status_filter not in TICKET_STATUS_VALUES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status 必须是 {sorted(TICKET_STATUS_VALUES)}",
        )
    if risk_level is not None and risk_level not in TICKET_LEVEL_VALUES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"risk_level 必须是 {sorted(TICKET_LEVEL_VALUES)}",
        )

    rows, total = list_tickets(
        db,
        status_filter=status_filter,
        level_filter=risk_level,
        assignee_id=assignee_id,
        keyword=q,
        start_at=start_at,
        end_at=end_at,
        viewer=viewer,
        limit=limit,
        offset=offset,
    )
    return TicketListOut(
        total=total,
        items=[TicketOut(**ticket_to_dict(r)) for r in rows],
    )


@router.get("/summary", response_model=TicketSummaryOut)
def ticket_summary_endpoint(
    db: Session = Depends(get_db),
    viewer: User = Depends(_require_ticket_reader),
) -> TicketSummaryOut:
    counts = count_tickets_by_status(db, viewer=viewer)
    return TicketSummaryOut(
        unassigned=counts["unassigned"],
        in_progress=counts["in_progress"],
        completed=counts["completed"],
        archived=counts["archived"],
        total=counts["total"],
    )


@router.get("/{ticket_id}", response_model=TicketOut)
def get_ticket_endpoint(
    ticket_id: int,
    db: Session = Depends(get_db),
    viewer: User = Depends(_require_ticket_reader),
) -> TicketOut:
    ticket = get_ticket(db, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="工单不存在")
    if viewer.role.code == RoleCode.HANDLER and ticket.assignee_id != viewer.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Handlers can only see their own tickets",
        )
    return TicketOut(**ticket_to_dict(ticket))


# ---------- creation ----------


@router.post(
    "/from-alert",
    response_model=TicketCreateResultOut,
    status_code=status.HTTP_201_CREATED,
)
def create_ticket_from_alert_endpoint(
    payload: TicketCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(_require_ticket_manager),
) -> TicketCreateResultOut:
    ip = get_client_ip(request)
    alert = get_alert(db, payload.alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预警不存在")
    try:
        ticket = create_ticket_from_alert(
            db,
            alert=alert,
            actor=actor,
            title=payload.title,
            description=payload.description,
            assignee_id=payload.assignee_id,
            ip_address=ip,
        )
    except TicketStateError as e:
        _audit_and_commit(
            db,
            actor=actor,
            action="ticket.create",
            target_id=str(alert.id),
            result="failure",
            detail={"reason": "invalid_alert_state", "current_status": e.current_status},
            ip=ip,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"预警当前状态为 {e.current_status},无法转为工单",
        )
    except TicketInputError as e:
        _audit_and_commit(
            db,
            actor=actor,
            action="ticket.create",
            target_id=str(alert.id),
            result="failure",
            detail={"reason": e.reason},
            ip=ip,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.reason)

    _audit_and_commit(
        db,
        actor=actor,
        action="ticket.create",
        target_id=str(ticket.id),
        result="success",
        detail={
            "alert_id": ticket.alert_id,
            "opinion_item_id": ticket.opinion_item_id,
            "risk_level": ticket.risk_level,
            "risk_score": ticket.risk_score,
            "assignee_id": ticket.assignee_id,
            "assignee_username": ticket.assignee_username,
            "status": ticket.status,
        },
        ip=ip,
    )
    db.refresh(ticket)
    return TicketCreateResultOut(
        id=ticket.id,
        status=ticket.status,
        assignee_username=ticket.assignee_username,
        created_at=ticket.created_at,
    )


# ---------- assignment ----------


@router.post("/{ticket_id}/assign", response_model=TicketAssignResultOut)
def assign_ticket_endpoint(
    ticket_id: int,
    payload: TicketAssignRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(_require_ticket_manager),
) -> TicketAssignResultOut:
    ip = get_client_ip(request)
    ticket = get_ticket(db, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="工单不存在")
    try:
        assign_ticket(
            db,
            ticket,
            actor=actor,
            assignee_id=payload.assignee_id,
            title=payload.title,
            description=payload.description,
            ip_address=ip,
        )
    except TicketStateError as e:
        _audit_and_commit(
            db,
            actor=actor,
            action="ticket.assign",
            target_id=str(ticket.id),
            result="failure",
            detail={"reason": "invalid_state", "current_status": e.current_status},
            ip=ip,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"工单当前状态为 {e.current_status},无法重新指派",
        )
    except TicketInputError as e:
        _audit_and_commit(
            db,
            actor=actor,
            action="ticket.assign",
            target_id=str(ticket.id),
            result="failure",
            detail={"reason": e.reason},
            ip=ip,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.reason)

    _audit_and_commit(
        db,
        actor=actor,
        action="ticket.assign",
        target_id=str(ticket.id),
        result="success",
        detail={
            "assignee_id": ticket.assignee_id,
            "assignee_username": ticket.assignee_username,
            "status": ticket.status,
        },
        ip=ip,
    )
    db.refresh(ticket)
    return TicketAssignResultOut(
        id=ticket.id,
        status=ticket.status,
        assignee_username=ticket.assignee_username,
        assigned_by_username=ticket.assigned_by_username,
        assigned_at=ticket.assigned_at,
        started_at=ticket.started_at,
    )


# ---------- start (handler accept) ----------


@router.post("/{ticket_id}/start", response_model=TicketStartResultOut)
def start_ticket_endpoint(
    ticket_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(_require_ticket_reader),
) -> TicketStartResultOut:
    ip = get_client_ip(request)
    ticket = get_ticket(db, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="工单不存在")

    # Only the assigned handler (or an admin override) can start. Auditors
    # and risk-control get a 403 here even though they can read the list.
    if (
        actor.role.code != RoleCode.ADMIN
        and ticket.assignee_id != actor.id
    ):
        _audit_and_commit(
            db,
            actor=actor,
            action="ticket.start",
            target_id=str(ticket.id),
            result="failure",
            detail={"reason": "not_assignee"},
            ip=ip,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the assigned handler can start this ticket",
        )

    try:
        start_ticket(db, ticket, actor=actor, ip_address=ip)
    except TicketStateError as e:
        _audit_and_commit(
            db,
            actor=actor,
            action="ticket.start",
            target_id=str(ticket.id),
            result="failure",
            detail={"reason": "invalid_state", "current_status": e.current_status},
            ip=ip,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"工单当前状态为 {e.current_status},无法开始",
        )

    _audit_and_commit(
        db,
        actor=actor,
        action="ticket.start",
        target_id=str(ticket.id),
        result="success",
        detail={"status": ticket.status, "started_at": str(ticket.started_at)},
        ip=ip,
    )
    db.refresh(ticket)
    return TicketStartResultOut(
        id=ticket.id,
        status=ticket.status,
        started_at=ticket.started_at,
    )


# ---------- complete ----------


@router.post("/{ticket_id}/complete", response_model=TicketCompleteResultOut)
def complete_ticket_endpoint(
    ticket_id: int,
    payload: TicketCompleteRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(_require_ticket_reader),
) -> TicketCompleteResultOut:
    ip = get_client_ip(request)
    ticket = get_ticket(db, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="工单不存在")

    if (
        actor.role.code != RoleCode.ADMIN
        and ticket.assignee_id != actor.id
    ):
        _audit_and_commit(
            db,
            actor=actor,
            action="ticket.complete",
            target_id=str(ticket.id),
            result="failure",
            detail={"reason": "not_assignee"},
            ip=ip,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the assigned handler can complete this ticket",
        )

    try:
        complete_ticket(db, ticket, actor=actor, handling_result=payload.handling_result, ip_address=ip)
    except TicketStateError as e:
        _audit_and_commit(
            db,
            actor=actor,
            action="ticket.complete",
            target_id=str(ticket.id),
            result="failure",
            detail={"reason": "invalid_state", "current_status": e.current_status},
            ip=ip,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"工单当前状态为 {e.current_status},无法完成",
        )
    except TicketInputError as e:
        _audit_and_commit(
            db,
            actor=actor,
            action="ticket.complete",
            target_id=str(ticket.id),
            result="failure",
            detail={"reason": e.reason},
            ip=ip,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.reason)

    _audit_and_commit(
        db,
        actor=actor,
        action="ticket.complete",
        target_id=str(ticket.id),
        result="success",
        detail={
            "status": ticket.status,
            "completed_at": str(ticket.completed_at),
            "handling_result_length": len(ticket.handling_result),
        },
        ip=ip,
    )
    db.refresh(ticket)
    return TicketCompleteResultOut(
        id=ticket.id,
        status=ticket.status,
        completed_by_username=ticket.completed_by_username,
        completed_at=ticket.completed_at,
    )


# ---------- archive ----------


@router.post("/{ticket_id}/archive", response_model=TicketArchiveResultOut)
def archive_ticket_endpoint(
    ticket_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(_require_ticket_manager),
) -> TicketArchiveResultOut:
    ip = get_client_ip(request)
    ticket = get_ticket(db, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="工单不存在")
    try:
        archive_ticket(db, ticket, actor=actor, ip_address=ip)
    except TicketStateError as e:
        _audit_and_commit(
            db,
            actor=actor,
            action="ticket.archive",
            target_id=str(ticket.id),
            result="failure",
            detail={"reason": "invalid_state", "current_status": e.current_status},
            ip=ip,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"工单当前状态为 {e.current_status},无法归档",
        )

    _audit_and_commit(
        db,
        actor=actor,
        action="ticket.archive",
        target_id=str(ticket.id),
        result="success",
        detail={"status": ticket.status, "archived_at": str(ticket.archived_at)},
        ip=ip,
    )
    db.refresh(ticket)
    return TicketArchiveResultOut(
        id=ticket.id,
        status=ticket.status,
        archived_by_username=ticket.archived_by_username,
        archived_at=ticket.archived_at,
    )
