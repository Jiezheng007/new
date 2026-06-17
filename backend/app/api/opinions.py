"""Opinion-item read + analysis API (Phase 3 / Issue 4 + Phase 4 / Issue 6).

Any role that holds ``opinion:read`` permission (admin / risk_control /
auditor / viewer) can list and view details; handler is blocked. The
list supports keyword, source, time-range, sentiment, risk-level, and
analysis-status filters. Phase 4 added the analysis summary on every
opinion and the manual retry endpoints.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.analysis import AnalysisResult
from app.models.datasource import OpinionItem
from app.models.role_codes import RoleCode
from app.models.user import User
from app.schemas.analysis import (
    AnalyzeActionResultOut,
    AnalyzePendingResultOut,
    AnalysisResultOut,
)
from app.schemas.opinions import (
    OPINION_ANALYSIS_STATUS_FILTER,
    OPINION_RISK_LEVEL_FILTER,
    OPINION_SENTIMENT_FILTER,
    OpinionItemOut,
    OpinionListOut,
)
from app.services.analysis import (
    DEFAULT_PENDING_BATCH,
    MAX_PENDING_BATCH,
    analyze_opinion,
    pending_opinions,
)
from app.services.audit import get_client_ip, record_audit
from app.services.opinion_search import search_opinion_ids


router = APIRouter(prefix="/api/opinions", tags=["opinions"])


_OPINION_READ_ROLES = {RoleCode.ADMIN, RoleCode.RISK_CONTROL, RoleCode.AUDITOR, RoleCode.VIEWER}
_OPINION_ANALYZE_ROLES = {RoleCode.ADMIN, RoleCode.RISK_CONTROL}


def _require_opinion_reader(user: User = Depends(get_current_user)) -> User:
    if user.role.code not in _OPINION_READ_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.code}' cannot read opinion items",
        )
    return user


def _require_opinion_analyzer(user: User = Depends(get_current_user)) -> User:
    if user.role.code not in _OPINION_ANALYZE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.code}' cannot trigger opinion analysis",
        )
    return user


def _decode_json(value: str, *, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _analysis_to_out(row: AnalysisResult | None) -> AnalysisResultOut:
    if row is None:
        return AnalysisResultOut(status="pending")
    return AnalysisResultOut(
        status=row.status,
        sentiment=row.sentiment,
        confidence=row.confidence,
        provider=row.provider or "",
        score=row.score,
        level=row.level,
        error_message=row.error_message,
        factors=_decode_json(row.factors, default={}),
        explanation=_decode_json(row.explanation, default=[]),
        analyzed_at=row.analyzed_at,
    )


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
        "analysis": _analysis_to_out(getattr(item, "analysis_result", None)),
    }


@router.get("", response_model=OpinionListOut)
def list_opinions(
    q: Optional[str] = Query(None, description="关键词,匹配标题或正文"),
    source_id: Optional[int] = Query(None),
    source_code: Optional[str] = Query(None),
    start_at: Optional[datetime] = Query(None, description="按发布时间下界过滤 (ISO-8601)"),
    end_at: Optional[datetime] = Query(None, description="按发布时间上界过滤 (ISO-8601)"),
    sentiment: Optional[str] = Query(None, description="情感倾向过滤"),
    risk_level: Optional[str] = Query(None, description="风险等级过滤"),
    analysis_status: Optional[str] = Query(None, description="分析状态过滤"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(_require_opinion_reader),
) -> OpinionListOut:
    if sentiment is not None and sentiment not in OPINION_SENTIMENT_FILTER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"sentiment 必须是 {sorted(OPINION_SENTIMENT_FILTER)}")
    if risk_level is not None and risk_level not in OPINION_RISK_LEVEL_FILTER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"risk_level 必须是 {sorted(OPINION_RISK_LEVEL_FILTER)}")
    if analysis_status is not None and analysis_status not in OPINION_ANALYSIS_STATUS_FILTER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"analysis_status 必须是 {sorted(OPINION_ANALYSIS_STATUS_FILTER)}")

    query = db.query(OpinionItem)
    if q:
        fts_ids = search_opinion_ids(db, q)
        if fts_ids is None:
            like = f"%{q}%"
            query = query.filter(or_(OpinionItem.title.like(like), OpinionItem.content.like(like)))
        else:
            query = query.filter(OpinionItem.id.in_(fts_ids if fts_ids else [-1]))
    if source_id is not None:
        query = query.filter(OpinionItem.source_id == source_id)
    if source_code:
        query = query.filter(OpinionItem.source_code == source_code)
    if start_at is not None:
        query = query.filter(OpinionItem.published_at >= start_at)
    if end_at is not None:
        query = query.filter(OpinionItem.published_at <= end_at)
    if sentiment is not None or risk_level is not None or analysis_status is not None:
        query = query.join(AnalysisResult, AnalysisResult.opinion_item_id == OpinionItem.id)
        if sentiment is not None:
            query = query.filter(AnalysisResult.sentiment == sentiment)
        if risk_level is not None:
            query = query.filter(AnalysisResult.level == risk_level)
        if analysis_status is not None:
            query = query.filter(AnalysisResult.status == analysis_status)

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


@router.post("/{item_id}/analyze", response_model=AnalyzeActionResultOut)
def analyze_one_opinion(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(_require_opinion_analyzer),
) -> AnalyzeActionResultOut:
    ip = get_client_ip(request)
    opinion = db.get(OpinionItem, item_id)
    if opinion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="舆情不存在")
    result = analyze_opinion(db, opinion)
    db.commit()
    db.refresh(result)
    record_audit(
        db,
        actor=actor,
        action="opinion.analyze",
        target_type="opinion",
        target_id=str(opinion.id),
        result="success" if result.status == "success" else "failure",
        detail={
            "status": result.status,
            "sentiment": result.sentiment,
            "risk_level": result.level,
            "risk_score": result.score,
            "error_message": result.error_message,
        },
        ip_address=ip,
    )
    db.commit()
    return AnalyzeActionResultOut(
        opinion_id=opinion.id,
        status=result.status,
        sentiment=result.sentiment,
        risk_level=result.level,
        risk_score=result.score,
        analyzed_at=result.analyzed_at,
        error_message=result.error_message,
    )


@router.post("/analyze-pending", response_model=AnalyzePendingResultOut)
def analyze_pending_opinions(
    request: Request,
    limit: int = Query(DEFAULT_PENDING_BATCH, ge=1, le=MAX_PENDING_BATCH),
    db: Session = Depends(get_db),
    actor: User = Depends(_require_opinion_analyzer),
) -> AnalyzePendingResultOut:
    ip = get_client_ip(request)
    pending = pending_opinions(db, limit=limit)
    analyzed_ids: list[int] = []
    succeeded = 0
    failed = 0
    for opinion in pending:
        result = analyze_opinion(db, opinion)
        if result.status == "success":
            succeeded += 1
        else:
            failed += 1
        analyzed_ids.append(opinion.id)
    db.commit()
    record_audit(
        db,
        actor=actor,
        action="opinion.analyze_pending",
        target_type="opinion_batch",
        target_id="pending",
        result="success" if failed == 0 else ("partial" if succeeded else "failure"),
        detail={
            "requested": len(pending),
            "succeeded": succeeded,
            "failed": failed,
            "limit": limit,
            "analyzed_ids": analyzed_ids,
        },
        ip_address=ip,
    )
    db.commit()
    return AnalyzePendingResultOut(
        requested=len(pending),
        succeeded=succeeded,
        failed=failed,
        analyzed_ids=analyzed_ids,
    )
