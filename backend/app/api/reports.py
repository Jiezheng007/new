"""Report-center API (Phase 8 / Issue 10).

Endpoints:
  - GET    /api/reports             list with filters (read)
  - GET    /api/reports/summary     count by status (read)
  - GET    /api/reports/{id}        detail of one task (read)
  - POST   /api/reports             create a new task and trigger the
                                    background runner (write)
  - GET    /api/reports/{id}/download  stream the generated .xlsx
                                    (read; requires the task to be in
                                    the ``completed`` state)

Role rules:
  * Read (list, detail, summary, download): admin, risk_control, auditor,
    viewer. The task list is "creator-aware" only in the sense that
    every authenticated user can see every task - reports are not
    private. (The download path requires the file to actually exist on
    disk, so a failed task can never leak a 200 with no body.)
  * Create: admin, risk_control. A handler / viewer / auditor cannot
    create reports.

Every state change writes an ``AuditLog`` row with actor, action,
target_id, result, IP address, and timestamp. The two relevant
actions are ``report.create`` and ``report.download``; failures
(``invalid filters``, ``task not completed``) write a ``failure`` row
before the error response.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.report import REPORT_STATUS_COMPLETED
from app.models.role_codes import RoleCode
from app.models.user import User
from app.schemas.reports import (
    REPORT_RISK_LEVEL_VALUES,
    REPORT_STATUS_VALUES,
    ReportTaskCreateRequest,
    ReportTaskCreateResultOut,
    ReportTaskListOut,
    ReportTaskOut,
    ReportTaskSummaryOut,
)
from app.services.audit import get_client_ip, record_audit
from app.services.reports import (
    ReportInputError,
    count_report_tasks_by_status,
    create_report_task,
    get_report_task,
    list_report_tasks,
    process_report_task,
    report_task_to_dict,
)


router = APIRouter(prefix="/api/reports", tags=["reports"])


_REPORT_READ_ROLES = {
    RoleCode.ADMIN,
    RoleCode.RISK_CONTROL,
    RoleCode.AUDITOR,
    RoleCode.VIEWER,
}
_REPORT_CREATE_ROLES = {RoleCode.ADMIN, RoleCode.RISK_CONTROL}


def _require_report_reader(user: User = Depends(get_current_user)) -> User:
    if user.role.code not in _REPORT_READ_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.code}' cannot read reports",
        )
    return user


def _require_report_creator(user: User = Depends(get_current_user)) -> User:
    if user.role.code not in _REPORT_CREATE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.code}' cannot create reports",
        )
    return user


# ---------- list / detail / summary ----------


@router.get("", response_model=ReportTaskListOut)
def list_reports_endpoint(
    status_filter: Optional[str] = Query(None, alias="status", description="状态过滤"),
    creator_id: Optional[int] = Query(None, description="创建人 ID 过滤"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(_require_report_reader),
) -> ReportTaskListOut:
    if status_filter is not None and status_filter not in REPORT_STATUS_VALUES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status 必须是 {sorted(REPORT_STATUS_VALUES)}",
        )
    rows, total = list_report_tasks(
        db,
        status_filter=status_filter,
        creator_id=creator_id,
        limit=limit,
        offset=offset,
    )
    return ReportTaskListOut(
        total=total,
        items=[ReportTaskOut(**report_task_to_dict(r)) for r in rows],
    )


@router.get("/summary", response_model=ReportTaskSummaryOut)
def report_summary_endpoint(
    db: Session = Depends(get_db),
    _: User = Depends(_require_report_reader),
) -> ReportTaskSummaryOut:
    counts = count_report_tasks_by_status(db)
    return ReportTaskSummaryOut(
        pending=counts["pending"],
        generating=counts["generating"],
        completed=counts["completed"],
        failed=counts["failed"],
        total=counts["total"],
    )


@router.get("/{task_id}", response_model=ReportTaskOut)
def get_report_endpoint(
    task_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(_require_report_reader),
) -> ReportTaskOut:
    task = get_report_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告任务不存在")
    return ReportTaskOut(**report_task_to_dict(task))


# ---------- create ----------


@router.post(
    "",
    response_model=ReportTaskCreateResultOut,
    status_code=status.HTTP_201_CREATED,
)
def create_report_endpoint(
    payload: ReportTaskCreateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: User = Depends(_require_report_creator),
) -> ReportTaskCreateResultOut:
    ip = get_client_ip(request)
    try:
        task = create_report_task(
            db,
            actor=actor,
            title=payload.title,
            description=payload.description,
            start_at=payload.start_at,
            end_at=payload.end_at,
            risk_level=payload.risk_level,
            subject_keyword=payload.subject_keyword,
        )
    except ReportInputError as e:
        record_audit(
            db,
            actor=actor,
            action="report.create",
            target_type="report",
            target_id="new",
            result="failure",
            detail={"reason": "invalid_filters", "error": e.reason},
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.reason,
        )

    db.refresh(task)

    record_audit(
        db,
        actor=actor,
        action="report.create",
        target_type="report",
        target_id=str(task.id),
        result="success",
        detail={
            "title": task.title,
            "risk_level": task.risk_level,
            "subject_keyword": task.subject_keyword,
            "start_at": str(task.start_at) if task.start_at else None,
            "end_at": str(task.end_at) if task.end_at else None,
        },
        ip_address=ip,
    )
    db.commit()

    # Schedule the background runner. We pass only the id so the worker
    # opens its own session - the request session will have been
    # closed by the time the BackgroundTask fires.
    background_tasks.add_task(process_report_task, task.id)

    return ReportTaskCreateResultOut(
        id=task.id,
        status=task.status,
        created_at=task.created_at,
    )


# ---------- download ----------


@router.get("/{task_id}/download")
def download_report_endpoint(
    task_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(_require_report_reader),
):
    """Stream the generated Excel for a completed task.

    A 404 / 409 is returned for a missing / not-yet-completed task;
    both write a ``report.download`` audit row with ``result='failure'``
    so an operator can later trace "who tried to fetch what".
    """
    ip = get_client_ip(request)
    task = get_report_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告任务不存在")

    if task.status != REPORT_STATUS_COMPLETED or not task.file_path:
        record_audit(
            db,
            actor=actor,
            action="report.download",
            target_type="report",
            target_id=str(task.id),
            result="failure",
            detail={"reason": "not_ready", "current_status": task.status},
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"报告任务当前状态为 {task.status},无法下载",
        )

    file_path = Path(task.file_path)
    if not file_path.is_file():
        record_audit(
            db,
            actor=actor,
            action="report.download",
            target_type="report",
            target_id=str(task.id),
            result="failure",
            detail={"reason": "file_missing", "path": str(file_path)},
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="报告文件已丢失,请重新生成",
        )

    record_audit(
        db,
        actor=actor,
        action="report.download",
        target_type="report",
        target_id=str(task.id),
        result="success",
        detail={
            "file_size_bytes": task.file_size_bytes,
            "matched_count": task.matched_count,
        },
        ip_address=ip,
    )
    db.commit()

    # ``download_name`` is sanitized so the response header never
    # leaks a user-supplied string into Content-Disposition.
    safe_name = os.path.basename(str(file_path)) or f"report_{task.id}.xlsx"
    return FileResponse(
        path=str(file_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=safe_name,
    )
