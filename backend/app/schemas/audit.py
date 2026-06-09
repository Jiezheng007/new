"""Pydantic schemas for the audit-log review API (Phase 9 / Issue 11).

The audit log is append-only; this contract is read-only by design.
Three response shapes are exposed:

  * ``AuditLogOut``         : a single row (actor, action, target,
                              result, IP address, timestamp, detail).
  * ``AuditLogListOut``     : a paginated list envelope.
  * ``AuditLogFacetsOut``   : distinct action / target_type / result
                              values so the UI can render filter
                              dropdowns from real data instead of
                              hard-coding them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# Result values currently produced by the codebase. We intentionally
# return a string rather than an enum so the API does not need to
# change when a new ``record_audit`` callsite uses a different label.
AUDIT_RESULT_VALUES = {"success", "failure"}


class AuditLogOut(BaseModel):
    """One audit row as returned by the list / detail endpoints.

    ``detail`` is the raw text stored in the database. Most callsites
    write a JSON-serialized dict via :func:`services.audit._coerce_detail`,
    but the schema does not parse it back to a dict because audit rows
    are sometimes plain strings (e.g. legacy entries, or hand-written
    debug rows). Leaving it as a string keeps the contract honest.
    """

    id: int
    actor_id: Optional[int] = None
    actor_username: str
    action: str
    target_type: str
    target_id: str
    result: str
    detail: str
    ip_address: str
    created_at: datetime


class AuditLogListOut(BaseModel):
    total: int
    items: list[AuditLogOut]


class AuditLogFacetsOut(BaseModel):
    """Distinct values for filter dropdowns.

    Returned as plain sorted lists. The UI uses these to render the
    ``action`` and ``target_type`` selects; ``result`` is normally
    rendered with hard-coded labels but is included for completeness.
    """

    actions: list[str]
    target_types: list[str]
    results: list[str]
    actors: list[str]
