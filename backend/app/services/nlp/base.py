"""NLP provider interface (Phase 4 / Issue 6).

A thin abstraction over the actual sentiment analyzer so the business
logic never depends on a specific model or remote API. The default
implementation is ``KeywordNlpProvider`` (see ``keyword.py``); future
implementations can plug in a local model or third-party API by adding
an entry to the registry in ``__init__.py`` and selecting it through the
``NLP_PROVIDER`` setting.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Sentiment labels shared with AnalysisResult. Keep them in sync with
# app.models.analysis constants.
SENTIMENT_POSITIVE = "positive"
SENTIMENT_NEUTRAL = "neutral"
SENTIMENT_NEGATIVE = "negative"

SUPPORTED_LANGUAGES: tuple[str, ...] = ("zh", "en")


@dataclass
class NlpResult:
    """Outcome of a single ``analyze()`` call.

    ``error_message`` is set only when the provider could not complete
    the request; the orchestration layer treats such a result as
    ``status='failed'`` even though the provider itself returned.
    """

    sentiment: str = SENTIMENT_NEUTRAL
    confidence: float = 0.0
    error_message: Optional[str] = None


class BaseNlpProvider:
    """Replaceable sentiment-analysis adapter.

    Implementations must be deterministic-enough that the same input
    produces the same output - tests rely on this. They may use a
    dictionary, a local model, or a remote API; the orchestration layer
    only ever sees :class:`NlpResult`.
    """

    name: str = "base"

    def analyze(self, text: str, language: str = "zh") -> NlpResult:  # pragma: no cover - interface
        raise NotImplementedError
