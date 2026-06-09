"""Data-source management API (Phase 3 / Issue 4).

Admin-only CRUD for RSS / JSON / static-demo sources. Manual ``POST .../fetch``
runs the configured connector and persists normalized records as
``OpinionItem`` rows. Every state change writes an audit row.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

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
from app.services.connectors import ConnectorError, get_connector
from app.services.ingestion import IngestionError, ingest_via_connector
from app.services.analysis import analyze_batch, opinions_by_ids


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
            detail={"reason": "disabled", "code": source.code},
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="数据源已停用,无法触发抓取")

    try:
        connector = get_connector(source.source_type)
    except ConnectorError as e:
        record_audit(
            db,
            actor=admin,
            action="datasource.fetch",
            target_type="datasource",
            target_id=str(source.id),
            result="failure",
            detail={"reason": "unsupported_source_type", "code": source.code, "error": str(e)},
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    try:
        result = ingest_via_connector(db, source, connector, origin="ingest")
    except ConnectorError as e:
        source.latest_fetch_at = datetime.now(timezone.utc)
        source.latest_fetch_status = "failure"
        source.latest_fetch_message = str(e)[:500]
        source.latest_items_count = 0
        record_audit(
            db,
            actor=admin,
            action="datasource.fetch",
            target_type="datasource",
            target_id=str(source.id),
            result="failure",
            detail={"reason": "fetch_error", "code": source.code, "error": str(e)},
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except IngestionError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e

    source.latest_fetch_at = datetime.now(timezone.utc)
    source.latest_fetch_status = "success" if result.rejected == 0 and not result.errors else "partial"
    source.latest_fetch_message = (
        f"accepted={result.accepted} rejected={result.rejected} duplicate={result.duplicate}"
    )
    source.latest_items_count = result.accepted

    # Run analysis on the freshly inserted items. analyze_batch never
    # raises on provider failure (it records status='failed'), so the
    # fetch response is unaffected by an unhappy NLP service.
    analyzed_count = 0
    if result.sample_ids:
        opinions = opinions_by_ids(db, result.sample_ids)
        analyzed = analyze_batch(db, opinions)
        analyzed_count = sum(1 for r in analyzed if r.status == "success")
        failed_count = len(analyzed) - analyzed_count
        if failed_count:
            source.latest_fetch_message += f" analyzed={analyzed_count} failed={failed_count}"

    record_audit(
        db,
        actor=admin,
        action="datasource.fetch",
        target_type="datasource",
        target_id=str(source.id),
        result="success" if result.rejected == 0 else "partial",
        detail={
            "code": source.code,
            "accepted": result.accepted,
            "rejected": result.rejected,
            "duplicate": result.duplicate,
            "analyzed": analyzed_count,
        },
        ip_address=ip,
    )
    db.commit()
    return FetchResult(
        source_id=source.id,
        source_code=source.code,
        status=source.latest_fetch_status,
        accepted=result.accepted,
        rejected=result.rejected,
        duplicate=result.duplicate,
        errors=result.errors,
        message=source.latest_fetch_message,
        fetched_at=source.latest_fetch_at,
    )
