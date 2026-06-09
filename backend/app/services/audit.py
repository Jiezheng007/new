"""Audit logging service: append-only records of important system operations.

Every call commits the audit row inside the caller's transaction so the audit
log and the business change commit or roll back together. Caller must
``db.commit()`` after both the business change and the audit record are added.
"""
from __future__ import annotations

import json
from typing import Any, Optional

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
