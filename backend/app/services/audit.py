"""Audit logging service: append-only records of important system operations.

Every call commits the audit row inside the caller's transaction so the audit
log and the business change commit or roll back together. Caller must
``db.commit()`` after both the business change and the audit record are added.

This module also exposes the read-side helpers used by the audit-review
API (Phase 9 / Issue 11): paginated list, distinct-value facets, and a
to-dict serializer. The read helpers do not authorize - the API layer
does that.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.user import User


def _coerce_detail(detail: Any) -> str:
    if detail is None:
        return ""
    if isinstance(detail, str):
        return detail
    try:
        return json.dumps(detail, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(detail)


def record_audit(
    db: Session,
    *,
    actor: Optional[User],
    action: str,
    target_type: str = "",
    target_id: Any = "",
    result: str = "success",
    detail: Any = None,
    ip_address: str = "",
) -> AuditLog:
    """Append an audit row. Does not commit - caller's transaction owns it."""
    actor_id = actor.id if actor is not None else None
    actor_username = actor.username if actor is not None else ""
    entry = AuditLog(
        actor_id=actor_id,
        actor_username=actor_username,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else "",
        result=result,
        detail=_coerce_detail(detail),
        ip_address=ip_address or "",
    )
    db.add(entry)
    db.flush()
    return entry


def get_client_ip(request) -> str:
    """Best-effort client IP, honouring X-Forwarded-For for proxy deployments."""
    if request is None:
        return ""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    if request.client is not None:
        return request.client.host or ""
    return ""


# ---------- read-side helpers used by the audit-review API ----------


def audit_log_to_dict(entry: AuditLog) -> dict[str, Any]:
    """Serialize one row in the shape the API contract expects."""
    return {
        "id": entry.id,
        "actor_id": entry.actor_id,
        "actor_username": entry.actor_username or "",
        "action": entry.action,
        "target_type": entry.target_type or "",
        "target_id": entry.target_id or "",
        "result": entry.result or "",
        "detail": entry.detail or "",
        "ip_address": entry.ip_address or "",
        "created_at": entry.created_at,
    }


def list_audit_logs(
    db: Session,
    *,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    actor: Optional[str] = None,
    result: Optional[str] = None,
    start_at: Optional[datetime] = None,
    end_at: Optional[datetime] = None,
    keyword: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AuditLog], int]:
    """Return ``(rows, total)``.

    All filters are AND-combined. ``actor`` matches either the
    ``actor_username`` column or, if numeric, the ``actor_id`` column.
    ``keyword`` is a substring match against ``detail`` so an operator
    can search the JSON payload for an opinion id, username, or other
    inline value.
    """
    q = db.query(AuditLog)

    if action:
        q = q.filter(AuditLog.action == action)
    if target_type:
        q = q.filter(AuditLog.target_type == target_type)
    if target_id:
        q = q.filter(AuditLog.target_id == str(target_id))
    if result:
        q = q.filter(AuditLog.result == result)
    if actor:
        stripped = actor.strip()
        if stripped:
            if stripped.isdigit():
                q = q.filter(
                    or_(
                        AuditLog.actor_username == stripped,
                        AuditLog.actor_id == int(stripped),
                    )
                )
            else:
                q = q.filter(AuditLog.actor_username == stripped)
    if start_at is not None:
        q = q.filter(AuditLog.created_at >= start_at)
    if end_at is not None:
        q = q.filter(AuditLog.created_at <= end_at)
    if keyword:
        like = f"%{keyword.strip()}%"
        if like.strip("% "):
            q = q.filter(AuditLog.detail.ilike(like))

    total = q.count()
    rows = (
        q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return rows, total


def get_audit_log(db: Session, log_id: int) -> Optional[AuditLog]:
    return db.get(AuditLog, log_id)


def audit_log_facets(db: Session) -> dict[str, list[str]]:
    """Distinct ``action``, ``target_type``, ``result``, and actor values.

    Used by the UI to render filter dropdowns. The lists are sorted
    alphabetically; empty strings are dropped so the UI never renders
    a blank option.
    """
    actions = sorted(
        {a for (a,) in db.query(AuditLog.action).distinct().all() if a}
    )
    target_types = sorted(
        {t for (t,) in db.query(AuditLog.target_type).distinct().all() if t}
    )
    results = sorted(
        {r for (r,) in db.query(AuditLog.result).distinct().all() if r}
    )
    actors = sorted(
        {u for (u,) in db.query(AuditLog.actor_username).distinct().all() if u}
    )
    return {
        "actions": actions,
        "target_types": target_types,
        "results": results,
        "actors": actors,
    }
