"""Opinion-item read API (Phase 3 / Issue 4).

Read-only endpoints for browsing collected opinion items. Any role that
holds ``opinion:read`` permission (admin / risk_control / auditor / viewer)
can list and view details; handler is blocked. The list supports a few
filters; sentiment and risk-level filters will be wired in Phase 6 once
analysis results exist.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.datasource import OpinionItem
from app.models.role_codes import RoleCode
from app.models.user import User
from app.schemas.opinions import OpinionItemOut, OpinionListOut


router = APIRouter(prefix="/api/opinions", tags=["opinions"])


_OPINION_READ_ROLES = {RoleCode.ADMIN, RoleCode.RISK_CONTROL, RoleCode.AUDITOR, RoleCode.VIEWER}


def _require_opinion_reader(user: User = Depends(get_current_user)) -> User:
    if user.role.code not in _OPINION_READ_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.code}' cannot read opinion items",
        )
    return user


def _serialize(item: OpinionItem) -> dict:
    return {
        "id": item.id,
        "source_id": item.source_id,
        "source_code": item.source_code,
        "source_type": item.source_type,
        "external_id": item.external_id,
        "title": item.title,
        "content": item.content,
        "url": item.url,
        "author": item.author,
        "language": item.language,
        "published_at": item.published_at,
        "fetched_at": item.fetched_at,
        "content_hash": item.content_hash,
        "origin": item.origin,
        "created_at": item.created_at,
    }


@router.get("", response_model=OpinionListOut)
def list_opinions(
    q: Optional[str] = Query(None, description="关键词,匹配标题或正文"),
    source_id: Optional[int] = Query(None),
    source_code: Optional[str] = Query(None),
    start_at: Optional[datetime] = Query(None, description="按发布时间下界过滤 (ISO-8601)"),
    end_at: Optional[datetime] = Query(None, description="按发布时间上界过滤 (ISO-8601)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(_require_opinion_reader),
) -> OpinionListOut:
    query = db.query(OpinionItem)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(OpinionItem.title.like(like), OpinionItem.content.like(like)))
    if source_id is not None:
        query = query.filter(OpinionItem.source_id == source_id)
    if source_code:
        query = query.filter(OpinionItem.source_code == source_code)
    if start_at is not None:
        query = query.filter(OpinionItem.published_at >= start_at)
    if end_at is not None:
        query = query.filter(OpinionItem.published_at <= end_at)

    total = query.count()
    items = (
        query.order_by(OpinionItem.published_at.desc().nulls_last(), OpinionItem.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return OpinionListOut(
        total=total,
        items=[OpinionItemOut(**_serialize(i)) for i in items],
    )


@router.get("/{item_id}", response_model=OpinionItemOut)
def get_opinion(
    item_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(_require_opinion_reader),
) -> OpinionItemOut:
    item = db.get(OpinionItem, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="舆情不存在")
    return OpinionItemOut(**_serialize(item))
