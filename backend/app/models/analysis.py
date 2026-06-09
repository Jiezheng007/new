"""Analysis + risk-score ORM model (Phase 4 / Issue 6).

A single ``AnalysisResult`` row per ``OpinionItem`` records the outcome of
the NLP provider plus the rule-based risk scoring. Re-analyses upsert the
same row (one-to-one), keeping retry history simple and avoiding duplicate
risk rows. The status, sentiment, score, and level are nullable because a
freshly persisted opinion has no analysis yet; on a provider failure the
row is still created with ``status='failed'`` and an error message so the
failure is observable in the UI and the audit log can be linked.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, backref, mapped_column, relationship

from app.db.session import Base
from app.models.user import utcnow


# Status / sentiment / level constants. Imported from services / schemas.
ANALYSIS_STATUS_PENDING = "pending"
ANALYSIS_STATUS_SUCCESS = "success"
ANALYSIS_STATUS_FAILED = "failed"

ANALYSIS_SENTIMENT_POSITIVE = "positive"
ANALYSIS_SENTIMENT_NEUTRAL = "neutral"
ANALYSIS_SENTIMENT_NEGATIVE = "negative"


class AnalysisResult(Base):
    __tablename__ = "analysis_results"
    __table_args__ = (
        UniqueConstraint("opinion_item_id", name="uq_analysis_opinion_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opinion_item_id: Mapped[int] = mapped_column(
        ForeignKey("opinion_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16), default=ANALYSIS_STATUS_PENDING, nullable=False, index=True
    )
    sentiment: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    provider: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    level: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    factors: Mapped[str] = mapped_column(Text, default="", nullable=False)
    explanation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    opinion_item: Mapped["OpinionItem"] = relationship(  # type: ignore[name-defined]
        "OpinionItem", backref=backref("analysis_result", uselist=False, lazy="joined")
    )
