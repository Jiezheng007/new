"""Analysis orchestration (Phase 4 / Issue 6).

Glues the NLP provider, the risk scorer, and the ``AnalysisResult``
ORM model together. The two public entry points are:

  * :func:`analyze_opinion` - run a single opinion through the
    pipeline. Upserts the ``AnalysisResult`` row, never raises on
    provider/scorer failure (records ``status='failed'`` instead).
  * :func:`analyze_batch` - run several opinions in sequence. Used
    by the ingestion/import API call sites to score freshly
    persisted items, and by the manual retry endpoint.

A separate helper, :func:`pending_opinions`, returns opinions whose
latest analysis is missing or in a non-success state so the
``/api/opinions/analyze-pending`` endpoint can target them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.analysis import (
    ANALYSIS_STATUS_FAILED,
    ANALYSIS_STATUS_PENDING,
    ANALYSIS_STATUS_SUCCESS,
    AnalysisResult,
)
from app.models.datasource import OpinionItem
from app.services.nlp import NlpProviderError, get_nlp_provider
from app.services.scoring import (
    ScoringRules,
    compute_risk,
    explanation_to_json,
    factors_to_json,
    load_scoring_rules,
)


# Public batch size for /api/opinions/analyze-pending. Kept modest
# because the request is synchronous and we do not want one admin
# click to time out on a large backlog.
DEFAULT_PENDING_BATCH = 50
MAX_PENDING_BATCH = 500


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _existing_result(db: Session, opinion: OpinionItem) -> AnalysisResult | None:
    return (
        db.query(AnalysisResult)
        .filter(AnalysisResult.opinion_item_id == opinion.id)
        .one_or_none()
    )


def analyze_opinion(
    db: Session,
    opinion: OpinionItem,
    rules: ScoringRules | None = None,
) -> AnalysisResult:
    """Run NLP + scoring for one opinion and persist the result.

    Catches provider and scoring exceptions and writes them into the
    ``AnalysisResult`` row with ``status='failed'`` and a descriptive
    ``error_message``. The function never raises; callers can rely on
    the returned row being either ``success`` or ``failed``.
    """
    provider = get_nlp_provider()
    row = _existing_result(db, opinion)
    if row is None:
        row = AnalysisResult(
            opinion_item_id=opinion.id,
            status=ANALYSIS_STATUS_PENDING,
            provider=provider.name,
        )
        db.add(row)

    row.provider = provider.name
    text = f"{opinion.title or ''}\n{opinion.content or ''}"
    language = (opinion.language or "zh")[:16] or "zh"
    try:
        nlp_result = provider.analyze(text, language)
    except NlpProviderError as e:
        row.status = ANALYSIS_STATUS_FAILED
        row.error_message = str(e)
        row.analyzed_at = _utcnow()
        db.flush()
        return row
    except Exception as e:  # noqa: BLE001 - convert any provider crash to a failed row
        row.status = ANALYSIS_STATUS_FAILED
        row.error_message = f"provider_crash: {e}"
        row.analyzed_at = _utcnow()
        db.flush()
        return row

    if nlp_result.error_message:
        row.status = ANALYSIS_STATUS_FAILED
        row.sentiment = None
        row.confidence = None
        row.score = None
        row.level = None
        row.factors = ""
        row.explanation = ""
        row.error_message = nlp_result.error_message
        row.analyzed_at = _utcnow()
        db.flush()
        return row

    try:
        scored = compute_risk(db, opinion, nlp_result, rules=rules)
    except Exception as e:  # noqa: BLE001
        row.status = ANALYSIS_STATUS_FAILED
        row.sentiment = nlp_result.sentiment
        row.confidence = nlp_result.confidence
        row.score = None
        row.level = None
        row.factors = ""
        row.explanation = ""
        row.error_message = f"scoring_error: {e}"
        row.analyzed_at = _utcnow()
        db.flush()
        return row

    row.status = ANALYSIS_STATUS_SUCCESS
    row.sentiment = nlp_result.sentiment
    row.confidence = nlp_result.confidence
    row.score = scored.score
    row.level = scored.level
    row.factors = factors_to_json(scored.factors)
    row.explanation = explanation_to_json(scored.explanation)
    row.error_message = None
    row.analyzed_at = _utcnow()
    db.flush()
    # Phase 5 / Issue 7: a successful high/severe analysis auto-creates a
    # pending alert. Hooked here so every code path that goes through
    # analyze_opinion (manual fetch, CSV / JSON import, retry, pending
    # batch) gets the same behavior. ensure_alert_for_analysis is a
    # no-op for low/medium levels and for re-analyses of an opinion that
    # already has an alert.
    from app.services.alerts import ensure_alert_for_analysis
    ensure_alert_for_analysis(db, row)
    return row


def analyze_batch(
    db: Session,
    opinions: Iterable[OpinionItem],
) -> list[AnalysisResult]:
    """Run :func:`analyze_opinion` for every opinion in ``opinions``."""
    results: list[AnalysisResult] = []
    rules = load_scoring_rules(db)
    for opinion in opinions:
        results.append(analyze_opinion(db, opinion, rules=rules))
    return results


def pending_opinions(db: Session, limit: int = DEFAULT_PENDING_BATCH) -> list[OpinionItem]:
    """Return opinions that have no successful analysis yet.

    An opinion is considered pending if it has no ``AnalysisResult`` row
    at all, or if its row is in a non-success state (``pending`` /
    ``failed``). The result preserves ``OpinionItem.id`` ordering so the
    batch is stable across retries.
    """
    if limit <= 0:
        return []
    limit = min(limit, MAX_PENDING_BATCH)
    # Subquery: ids of opinion items that have a successful analysis.
    from sqlalchemy import select

    success_ids = (
        db.query(AnalysisResult.opinion_item_id)
        .filter(AnalysisResult.status == ANALYSIS_STATUS_SUCCESS)
    )
    rows = (
        db.query(OpinionItem)
        .filter(~OpinionItem.id.in_(select(success_ids.subquery())))
        .order_by(OpinionItem.id.asc())
        .limit(limit)
        .all()
    )
    return rows


def opinions_by_ids(db: Session, ids: list[int]) -> list[OpinionItem]:
    if not ids:
        return []
    return (
        db.query(OpinionItem)
        .filter(OpinionItem.id.in_(ids))
        .all()
    )
