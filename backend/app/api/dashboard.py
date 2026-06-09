"""Workbench dashboard read-only API (Phase 7 / Issue 9).

Single endpoint:

  - GET /api/dashboard/summary

Returns a role-aware summary suitable for the workbench card grid
(opinion totals, alert counts, ticket counts, seven-day trend, latest
alerts). All authenticated roles can call it; fields the role cannot
see are returned as ``None`` (or an empty list) so the page renders
without 403s.

The endpoint is intentionally read-only - the dashboard is a
projection, not a write path. ``normal viewer`` is the canonical
proof: a viewer can render the page, but cannot mutate any source
data behind the cards.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.dashboard import DashboardSummaryOut
from app.services.dashboard import build_dashboard_summary


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummaryOut)
def dashboard_summary(
    db: Session = Depends(get_db),
    viewer: User = Depends(get_current_user),
) -> DashboardSummaryOut:
    return build_dashboard_summary(db, viewer)
