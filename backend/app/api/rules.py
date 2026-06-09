"""Risk-rule API (Phase 3 / Issue 3).

All write endpoints require an authenticated admin. Every state change writes
an ``AuditLog`` row with actor, action, target, result, IP, and timestamp -
same shape as Phase 2 used for user management.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.role_codes import RoleCode
from app.models.rule import RiskThreshold, SensitiveKeyword, SubjectKeyword
from app.models.user import User
from app.schemas.rules import (
    RISK_LEVELS,
    RiskThresholdItem,
    RiskThresholdOut,
    RiskThresholdUpdate,
    SensitiveKeywordCreate,
    SensitiveKeywordOut,
    SensitiveKeywordUpdate,
    SubjectKeywordCreate,
    SubjectKeywordOut,
    SubjectKeywordUpdate,
)
from app.services.audit import get_client_ip, record_audit


router = APIRouter(prefix="/api/rules", tags=["rules"])


def _require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role.code != RoleCode.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only system administrators can manage risk rules",
        )
    return user


def _serialize_sensitive(row: SensitiveKeyword) -> dict[str, Any]:
    return {
        "id": row.id,
        "keyword": row.keyword,
        "category": row.category,
        "severity": row.severity,
        "is_active": row.is_active,
        "remark": row.remark,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _serialize_subject(row: SubjectKeyword) -> dict[str, Any]:
    return {
        "id": row.id,
        "keyword": row.keyword,
        "category": row.category,
        "is_active": row.is_active,
        "remark": row.remark,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


# ---------- sensitive keywords ----------

@router.get("/sensitive-keywords", response_model=list[SensitiveKeywordOut])
def list_sensitive_keywords(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[SensitiveKeywordOut]:
    rows = db.query(SensitiveKeyword).order_by(SensitiveKeyword.id.asc()).all()
    return [SensitiveKeywordOut(**_serialize_sensitive(r)) for r in rows]


@router.post(
    "/sensitive-keywords",
    response_model=SensitiveKeywordOut,
    status_code=status.HTTP_201_CREATED,
)
def create_sensitive_keyword(
    payload: SensitiveKeywordCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> SensitiveKeywordOut:
    ip = get_client_ip(request)
    if db.query(SensitiveKeyword).filter(SensitiveKeyword.keyword == payload.keyword).first():
        record_audit(
            db,
            actor=admin,
            action="rule.sensitive.create",
            target_type="sensitive_keyword",
            target_id=payload.keyword,
            result="failure",
            detail={"reason": "duplicate", "keyword": payload.keyword},
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="敏感词已存在")

    row = SensitiveKeyword(
        keyword=payload.keyword,
        category=payload.category,
        severity=payload.severity,
        is_active=payload.is_active,
        remark=payload.remark,
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        actor=admin,
        action="rule.sensitive.create",
        target_type="sensitive_keyword",
        target_id=str(row.id),
        result="success",
        detail={"keyword": row.keyword, "severity": row.severity, "category": row.category, "is_active": row.is_active},
        ip_address=ip,
    )
    db.commit()
    db.refresh(row)
    return SensitiveKeywordOut(**_serialize_sensitive(row))


@router.patch("/sensitive-keywords/{keyword_id}", response_model=SensitiveKeywordOut)
def update_sensitive_keyword(
    keyword_id: int,
    payload: SensitiveKeywordUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> SensitiveKeywordOut:
    ip = get_client_ip(request)
    row = db.get(SensitiveKeyword, keyword_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="敏感词不存在")

    changes: dict[str, Any] = {}
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}

    if payload.category is not None and payload.category != row.category:
        before["category"] = row.category
        after["category"] = payload.category
        changes["category"] = payload.category
        row.category = payload.category
    if payload.severity is not None and payload.severity != row.severity:
        before["severity"] = row.severity
        after["severity"] = payload.severity
        changes["severity"] = payload.severity
        row.severity = payload.severity
    if payload.is_active is not None and payload.is_active != row.is_active:
        before["is_active"] = row.is_active
        after["is_active"] = payload.is_active
        changes["is_active"] = payload.is_active
        row.is_active = payload.is_active
    if payload.remark is not None and payload.remark != row.remark:
        before["remark"] = row.remark
        after["remark"] = payload.remark
        changes["remark"] = payload.remark
        row.remark = payload.remark

    if changes:
        record_audit(
            db,
            actor=admin,
            action="rule.sensitive.update",
            target_type="sensitive_keyword",
            target_id=str(row.id),
            result="success",
            detail={"keyword": row.keyword, "changes": changes, "before": before, "after": after},
            ip_address=ip,
        )
        db.commit()
        db.refresh(row)
    return SensitiveKeywordOut(**_serialize_sensitive(row))


# ---------- subject keywords ----------

@router.get("/subject-keywords", response_model=list[SubjectKeywordOut])
def list_subject_keywords(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[SubjectKeywordOut]:
    rows = db.query(SubjectKeyword).order_by(SubjectKeyword.id.asc()).all()
    return [SubjectKeywordOut(**_serialize_subject(r)) for r in rows]


@router.post(
    "/subject-keywords",
    response_model=SubjectKeywordOut,
    status_code=status.HTTP_201_CREATED,
)
def create_subject_keyword(
    payload: SubjectKeywordCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> SubjectKeywordOut:
    ip = get_client_ip(request)
    if db.query(SubjectKeyword).filter(SubjectKeyword.keyword == payload.keyword).first():
        record_audit(
            db,
            actor=admin,
            action="rule.subject.create",
            target_type="subject_keyword",
            target_id=payload.keyword,
            result="failure",
            detail={"reason": "duplicate", "keyword": payload.keyword},
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="主体词已存在")

    row = SubjectKeyword(
        keyword=payload.keyword,
        category=payload.category,
        is_active=payload.is_active,
        remark=payload.remark,
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        actor=admin,
        action="rule.subject.create",
        target_type="subject_keyword",
        target_id=str(row.id),
        result="success",
        detail={"keyword": row.keyword, "category": row.category, "is_active": row.is_active},
        ip_address=ip,
    )
    db.commit()
    db.refresh(row)
    return SubjectKeywordOut(**_serialize_subject(row))


@router.patch("/subject-keywords/{keyword_id}", response_model=SubjectKeywordOut)
def update_subject_keyword(
    keyword_id: int,
    payload: SubjectKeywordUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> SubjectKeywordOut:
    ip = get_client_ip(request)
    row = db.get(SubjectKeyword, keyword_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主体词不存在")

    changes: dict[str, Any] = {}
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    if payload.category is not None and payload.category != row.category:
        before["category"] = row.category
        after["category"] = payload.category
        changes["category"] = payload.category
        row.category = payload.category
    if payload.is_active is not None and payload.is_active != row.is_active:
        before["is_active"] = row.is_active
        after["is_active"] = payload.is_active
        changes["is_active"] = payload.is_active
        row.is_active = payload.is_active
    if payload.remark is not None and payload.remark != row.remark:
        before["remark"] = row.remark
        after["remark"] = payload.remark
        changes["remark"] = payload.remark
        row.remark = payload.remark

    if changes:
        record_audit(
            db,
            actor=admin,
            action="rule.subject.update",
            target_type="subject_keyword",
            target_id=str(row.id),
            result="success",
            detail={"keyword": row.keyword, "changes": changes, "before": before, "after": after},
            ip_address=ip,
        )
        db.commit()
        db.refresh(row)
    return SubjectKeywordOut(**_serialize_subject(row))


# ---------- risk thresholds ----------

@router.get("/thresholds", response_model=list[RiskThresholdOut])
def list_risk_thresholds(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[RiskThresholdOut]:
    rows = db.query(RiskThreshold).order_by(RiskThreshold.min_score.asc()).all()
    return [RiskThresholdOut(level=r.level, min_score=r.min_score, updated_at=r.updated_at) for r in rows]


@router.put("/thresholds", response_model=list[RiskThresholdOut])
def replace_risk_thresholds(
    payload: RiskThresholdUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> list[RiskThresholdOut]:
    ip = get_client_ip(request)
    levels = [t.level for t in payload.thresholds]
    if sorted(levels) != sorted(RISK_LEVELS):
        record_audit(
            db,
            actor=admin,
            action="rule.threshold.update",
            target_type="risk_threshold",
            target_id="thresholds",
            result="failure",
            detail={"reason": "missing_or_extra_levels", "provided": levels, "expected": list(RISK_LEVELS)},
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"必须同时提供 {list(RISK_LEVELS)} 四个等级",
        )

    sorted_items = sorted(payload.thresholds, key=lambda t: t.min_score)
    for index in range(1, len(sorted_items)):
        if sorted_items[index].min_score <= sorted_items[index - 1].min_score:
            record_audit(
                db,
                actor=admin,
                action="rule.threshold.update",
                target_type="risk_threshold",
                target_id="thresholds",
                result="failure",
                detail={"reason": "non_strictly_increasing", "values": [t.min_score for t in sorted_items]},
                ip_address=ip,
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="阈值必须严格递增 (low < medium < high < severe)",
            )

    before_rows = {r.level: r.min_score for r in db.query(RiskThreshold).all()}
    for item in payload.thresholds:
        row = db.query(RiskThreshold).filter(RiskThreshold.level == item.level).one_or_none()
        if row is None:
            row = RiskThreshold(level=item.level, min_score=item.min_score)
            db.add(row)
        else:
            row.min_score = item.min_score

    record_audit(
        db,
        actor=admin,
        action="rule.threshold.update",
        target_type="risk_threshold",
        target_id="thresholds",
        result="success",
        detail={"before": before_rows, "after": {t.level: t.min_score for t in payload.thresholds}},
        ip_address=ip,
    )
    db.commit()
    rows = db.query(RiskThreshold).order_by(RiskThreshold.min_score.asc()).all()
    return [RiskThresholdOut(level=r.level, min_score=r.min_score, updated_at=r.updated_at) for r in rows]
