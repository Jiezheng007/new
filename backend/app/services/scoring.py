"""Rule-based risk scoring (Phase 4 / Issue 6).

Combines the NLP sentiment result with the active sensitive-keyword
hits, monitored subject-keyword hits, source weight, and a recency heat
proxy into a 0-100 integer score. The score is then mapped to a
risk level (``low``/``medium``/``high``/``severe``) using the
``RiskThreshold`` table - changing thresholds re-runs the mapping
without touching the stored factors.

The factors dict and the explanation list are persisted alongside the
score so the UI can show *why* an opinion ended up in a given bucket.
The math is intentionally simple and easy to defend in a course
demo: every factor is an integer, the total is capped at 100, and every
line of the explanation is a single Chinese sentence.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.models.analysis import (
    ANALYSIS_SENTIMENT_NEGATIVE,
    ANALYSIS_SENTIMENT_NEUTRAL,
    ANALYSIS_SENTIMENT_POSITIVE,
)
from app.models.datasource import DataSource, OpinionItem
from app.models.rule import RiskThreshold, SensitiveKeyword, SubjectKeyword
from app.services.nlp.base import NlpResult


# Per-sentiment contribution. Kept as a constant table so tests and
# the UI agree on the mapping.
SENTIMENT_CONTRIB: dict[str, int] = {
    ANALYSIS_SENTIMENT_NEGATIVE: 25,
    ANALYSIS_SENTIMENT_NEUTRAL: 5,
    ANALYSIS_SENTIMENT_POSITIVE: 0,
}

# Per-severity contribution per *unique* active sensitive-keyword hit.
SENSITIVE_SEVERITY_CONTRIB: dict[str, int] = {
    "low": 5,
    "medium": 10,
    "high": 20,
    "severe": 35,
}

# Per-unique subject-keyword hit. Less aggressive than sensitive because
# subjects are *monitored*, not *risky* on their own.
SUBJECT_HIT_CONTRIB = 8

# Caps for each factor so a single factor cannot push the score
# arbitrarily high (low / medium / high / severe thresholds are fixed).
SENSITIVE_HIT_CAP = 40
SUBJECT_HIT_CAP = 24
SOURCE_WEIGHT_CAP = 16

# Heat proxy windows: more recent => more heat.
HEAT_WINDOW_24H = 6
HEAT_WINDOW_7D = 3

# Hard ceiling for the total score, regardless of factor counts.
TOTAL_CAP = 100

# Cap on the number of distinct lines the explanation keeps so a giant
# keyword list does not blow up the persisted Text column.
EXPLANATION_MAX_LINES = 24


@dataclass
class ScoreResult:
    score: int
    level: str
    factors: dict[str, Any] = field(default_factory=dict)
    explanation: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScoringRules:
    sensitive_rows: list[SensitiveKeyword]
    subject_rows: list[SubjectKeyword]
    thresholds: list[RiskThreshold]


def load_scoring_rules(db: Session) -> ScoringRules:
    """Load the rule tables used by risk scoring once for a batch."""
    return ScoringRules(
        sensitive_rows=_active_keywords(db.query(SensitiveKeyword).all()),
        subject_rows=_active_keywords(db.query(SubjectKeyword).all()),
        thresholds=db.query(RiskThreshold).all(),
    )


def _active_keywords(rows: Iterable[SensitiveKeyword]) -> list[SensitiveKeyword]:
    return [r for r in rows if r.is_active]


def _match_keywords(
    text: str,
    rows: Iterable[SensitiveKeyword],
) -> list[SensitiveKeyword]:
    if not text:
        return []
    return [r for r in rows if r.keyword and r.keyword in text]


def _match_subject_keywords(
    text: str,
    rows: Iterable[SubjectKeyword],
) -> list[SubjectKeyword]:
    if not text:
        return []
    return [r for r in rows if r.keyword and r.keyword in text]


def _heat_for_published_at(published_at: datetime | None) -> int:
    if published_at is None:
        return 0
    now = datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        # Defensive: some legacy rows may be naive. Treat as UTC.
        published_at = published_at.replace(tzinfo=timezone.utc)
    delta = now - published_at
    if delta <= timedelta(hours=24):
        return HEAT_WINDOW_24H
    if delta <= timedelta(days=7):
        return HEAT_WINDOW_7D
    return 0


def _level_for_score(score: int, thresholds: list[RiskThreshold]) -> str:
    """Find the lowest band whose ``min_score <= score``. Default severe."""
    if not thresholds:
        return "severe"
    ordered = sorted(thresholds, key=lambda t: t.min_score)
    chosen = ordered[-1].level
    for row in ordered:
        if score >= row.min_score:
            chosen = row.level
    return chosen


def compute_risk(
    db: Session,
    opinion: OpinionItem,
    nlp_result: NlpResult,
    rules: ScoringRules | None = None,
) -> ScoreResult:
    """Combine NLP output with the current rule set into a ScoreResult.

    The function is pure: it reads from the DB but does not commit. The
    caller is responsible for persisting the result. The DB read is
    kept narrow (active sensitive + subject keywords, all risk
    thresholds) so the call fits in the request's transaction.
    """
    text = f"{opinion.title or ''}\n{opinion.content or ''}"
    sentiment_contrib = SENTIMENT_CONTRIB.get(nlp_result.sentiment, 0)

    if rules is None:
        rules = load_scoring_rules(db)

    sensitive_hits = _match_keywords(text, rules.sensitive_rows)
    subject_hits = _match_subject_keywords(text, rules.subject_rows)

    sensitive_contrib = 0
    sensitive_breakdown: list[dict[str, Any]] = []
    for hit in sensitive_hits:
        add = SENSITIVE_SEVERITY_CONTRIB.get(hit.severity, 0)
        sensitive_contrib += add
        sensitive_breakdown.append(
            {
                "keyword": hit.keyword,
                "severity": hit.severity,
                "category": hit.category,
                "contribution": add,
            }
        )
    sensitive_contrib = min(sensitive_contrib, SENSITIVE_HIT_CAP)

    subject_contrib = min(len(subject_hits) * SUBJECT_HIT_CONTRIB, SUBJECT_HIT_CAP)
    subject_breakdown = [
        {"keyword": h.keyword, "category": h.category, "contribution": SUBJECT_HIT_CONTRIB}
        for h in subject_hits
    ]

    source: DataSource = opinion.source
    source_weight = float(getattr(source, "weight", 1.0) or 0.0)
    source_weight_contrib = int(min(round(source_weight * 4), SOURCE_WEIGHT_CAP))

    heat = _heat_for_published_at(opinion.published_at)

    raw_total = (
        sentiment_contrib
        + sensitive_contrib
        + subject_contrib
        + source_weight_contrib
        + heat
    )
    total = min(raw_total, TOTAL_CAP)

    level = _level_for_score(total, rules.thresholds)

    factors: dict[str, Any] = {
        "sentiment": {
            "label": nlp_result.sentiment,
            "contribution": sentiment_contrib,
        },
        "sensitive_keywords": {
            "hits": sensitive_breakdown,
            "raw_contribution": sum(item["contribution"] for item in sensitive_breakdown),
            "contribution": sensitive_contrib,
            "cap": SENSITIVE_HIT_CAP,
        },
        "subject_keywords": {
            "hits": subject_breakdown,
            "raw_contribution": sum(item["contribution"] for item in subject_breakdown),
            "contribution": subject_contrib,
            "cap": SUBJECT_HIT_CAP,
        },
        "source_weight": {
            "weight": source_weight,
            "contribution": source_weight_contrib,
            "cap": SOURCE_WEIGHT_CAP,
        },
        "heat": {
            "published_at": opinion.published_at.isoformat() if opinion.published_at else None,
            "contribution": heat,
        },
        "total": total,
        "raw_total": raw_total,
        "cap": TOTAL_CAP,
        "level": level,
    }

    explanation = _build_explanation(
        nlp_result=nlp_result,
        sentiment_contrib=sentiment_contrib,
        sensitive_hits=sensitive_breakdown,
        sensitive_contrib=sensitive_contrib,
        subject_hits=subject_breakdown,
        subject_contrib=subject_contrib,
        source_weight=source_weight,
        source_weight_contrib=source_weight_contrib,
        heat=heat,
        total=total,
        level=level,
    )

    return ScoreResult(score=total, level=level, factors=factors, explanation=explanation)


def _build_explanation(
    *,
    nlp_result: NlpResult,
    sentiment_contrib: int,
    sensitive_hits: list[dict[str, Any]],
    sensitive_contrib: int,
    subject_hits: list[dict[str, Any]],
    subject_contrib: int,
    source_weight: float,
    source_weight_contrib: int,
    heat: int,
    total: int,
    level: str,
) -> list[str]:
    lines: list[str] = []
    label = {
        ANALYSIS_SENTIMENT_NEGATIVE: "负面",
        ANALYSIS_SENTIMENT_NEUTRAL: "中性",
        ANALYSIS_SENTIMENT_POSITIVE: "正面",
    }.get(nlp_result.sentiment, nlp_result.sentiment)
    lines.append(f"情感倾向 {label} (+{sentiment_contrib})")
    for hit in sensitive_hits:
        lines.append(
            f"命中敏感词『{hit['keyword']}』[{hit['severity']},+{hit['contribution']}]"
        )
    if sensitive_hits and sensitive_contrib < sum(h["contribution"] for h in sensitive_hits):
        lines.append(f"敏感词累计 {sensitive_contrib}/{SENSITIVE_HIT_CAP} (已封顶)")
    for hit in subject_hits:
        lines.append(f"命中主体词『{hit['keyword']}』(+{hit['contribution']})")
    if subject_hits and subject_contrib < len(subject_hits) * SUBJECT_HIT_CONTRIB:
        lines.append(f"主体词累计 {subject_contrib}/{SUBJECT_HIT_CAP} (已封顶)")
    if source_weight_contrib > 0:
        lines.append(f"数据源权重 {source_weight:.2f} → +{source_weight_contrib}")
    if heat > 0:
        window = "24h 内" if heat == HEAT_WINDOW_24H else "7d 内"
        lines.append(f"热度: {window} (+{heat})")
    lines.append(f"合计 {total}/{TOTAL_CAP} → 风险等级 {level}")
    return lines[:EXPLANATION_MAX_LINES]


def factors_to_json(factors: dict[str, Any]) -> str:
    return json.dumps(factors, ensure_ascii=False, default=str)


def explanation_to_json(lines: list[str]) -> str:
    return json.dumps(lines, ensure_ascii=False)
