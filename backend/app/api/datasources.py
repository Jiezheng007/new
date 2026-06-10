"""Data-source management API (Phase 3 / Issue 4, Phase 11 / Issue 14).

Admin-only CRUD for RSS / JSON / static-demo / Weibo sources. Manual
``POST .../fetch`` delegates to :func:`app.services.datasource_fetch.fetch_datasource`,
the same routine the background scheduler uses, so the two code paths
cannot drift apart. Every state change writes an audit row.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.datasource import DataSource
from app.models.role_codes import RoleCode
from app.models.user import User
from app.schemas.datasources import (
    DataSourceCreate,
    DataSourceOut,
    DataSourceUpdate,
    FetchResult,
)
from app.services.audit import get_client_ip, record_audit
from app.services.datasource_fetch import ORIGIN_MANUAL, fetch_datasource


router = APIRouter(prefix="/api/datasources", tags=["datasources"])


def _require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role.code != RoleCode.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only system administrators can manage data sources",
        )
    return user


def _serialize(row: DataSource) -> dict[str, Any]:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "source_type": row.source_type,
        "url": row.url,
        "weight": row.weight,
        "is_enabled": row.is_enabled,
        "description": row.description,
        "latest_fetch_at": row.latest_fetch_at,
        "latest_fetch_status": row.latest_fetch_status,
        "latest_fetch_message": row.latest_fetch_message,
        "latest_items_count": row.latest_items_count,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("", response_model=list[DataSourceOut])
def list_datasources(
    db: Session = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[DataSourceOut]:
    rows = db.query(DataSource).order_by(DataSource.id.asc()).all()
    return [DataSourceOut(**_serialize(r)) for r in rows]


@router.post("", response_model=DataSourceOut, status_code=status.HTTP_201_CREATED)
def create_datasource(
    payload: DataSourceCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> DataSourceOut:
    ip = get_client_ip(request)
    if db.query(DataSource).filter(DataSource.code == payload.code).first():
        record_audit(
            db,
            actor=admin,
            action="datasource.create",
            target_type="datasource",
            target_id=payload.code,
            result="failure",
            detail={"reason": "duplicate_code", "code": payload.code},
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="数据源编码已存在")

    row = DataSource(
        code=payload.code,
        name=payload.name,
        source_type=payload.source_type,
        url=payload.url,
        weight=payload.weight,
        is_enabled=payload.is_enabled,
        description=payload.description,
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        actor=admin,
        action="datasource.create",
        target_type="datasource",
        target_id=str(row.id),
        result="success",
        detail={"code": row.code, "source_type": row.source_type, "weight": row.weight, "is_enabled": row.is_enabled},
        ip_address=ip,
    )
    db.commit()
    db.refresh(row)
    return DataSourceOut(**_serialize(row))


@router.get("/{source_id}", response_model=DataSourceOut)
def get_datasource(
    source_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(_require_admin),
) -> DataSourceOut:
    row = db.get(DataSource, source_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据源不存在")
    return DataSourceOut(**_serialize(row))


@router.patch("/{source_id}", response_model=DataSourceOut)
def update_datasource(
    source_id: int,
    payload: DataSourceUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> DataSourceOut:
    ip = get_client_ip(request)
    row = db.get(DataSource, source_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据源不存在")

    changes: dict[str, Any] = {}
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    if payload.name is not None and payload.name != row.name:
        before["name"] = row.name
        after["name"] = payload.name
        changes["name"] = payload.name
        row.name = payload.name
    if payload.url is not None and payload.url != row.url:
        before["url"] = row.url
        after["url"] = payload.url
        changes["url"] = payload.url
        row.url = payload.url
    if payload.weight is not None and payload.weight != row.weight:
        before["weight"] = row.weight
        after["weight"] = payload.weight
        changes["weight"] = payload.weight
        row.weight = payload.weight
    if payload.is_enabled is not None and payload.is_enabled != row.is_enabled:
        action_name = "datasource.enable" if payload.is_enabled else "datasource.disable"
        before["is_enabled"] = row.is_enabled
        after["is_enabled"] = payload.is_enabled
        changes["is_enabled"] = payload.is_enabled
        row.is_enabled = payload.is_enabled
        record_audit(
            db,
            actor=admin,
            action=action_name,
            target_type="datasource",
            target_id=str(row.id),
            result="success",
            detail={"code": row.code, "before": row.is_enabled, "after": payload.is_enabled},
            ip_address=ip,
        )
    if payload.description is not None and payload.description != row.description:
        before["description"] = row.description
        after["description"] = payload.description
        changes["description"] = payload.description
        row.description = payload.description

    if changes and "is_enabled" not in changes:
        record_audit(
            db,
            actor=admin,
            action="datasource.update",
            target_type="datasource",
            target_id=str(row.id),
            result="success",
            detail={"code": row.code, "changes": changes, "before": before, "after": after},
            ip_address=ip,
        )
    elif "is_enabled" not in changes and not changes:
        # No-op patch, return as-is.
        pass
    db.commit()
    db.refresh(row)
    return DataSourceOut(**_serialize(row))


@router.post("/{source_id}/fetch", response_model=FetchResult)
def manual_fetch(
    source_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> FetchResult:
    ip = get_client_ip(request)
    source = db.get(DataSource, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据源不存在")
    if not source.is_enabled:
        record_audit(
            db,
            actor=admin,
            action="datasource.fetch",
            target_type="datasource",
            target_id=str(source.id),
            result="failure",
            detail={"reason": "disabled", "code": source.code, "origin": ORIGIN_MANUAL},
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="数据源已停用,无法触发抓取")

    outcome = fetch_datasource(db, source, actor=admin, origin=ORIGIN_MANUAL)
    db.commit()
    if outcome.error is not None:
        # Connector/transport errors become a 502 - the upstream is
        # unreachable, malformed, or unsupported. Other failures (e.g.
        # all records rejected) still return 200 with a "partial" status
        # so the operator can read counts from the body.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(outcome.error))

    return FetchResult(
        source_id=source.id,
        source_code=source.code,
        status=outcome.status,
        accepted=outcome.accepted,
        rejected=outcome.rejected,
        duplicate=outcome.duplicate,
        errors=outcome.errors,
        message=outcome.message,
        fetched_at=source.latest_fetch_at,
    )
