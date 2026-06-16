"""jieba + HowNet simplified lexicon NLP provider (Phase 5 / Issue 11).

Upgrades the deterministic-keyword baseline in :mod:`keyword` to a
real Chinese sentiment analyzer:

  1. jieba.cut() for word segmentation (avoids substring-in-word bugs
     like "下滑" matching inside "不下滑").
  2. Token-level polarity lookup against a vendored HowNet simplified
     lexicon (~600 positive + ~500 negative single tokens).
  3. Negation window: looks back up to ``_WINDOW`` tokens for any
     negation word (不/没/非/未/并非/毫无/绝不/无) and flips the sign.
  4. Degree-adverb weighting (极其/非常 ×1.5, 稍微/有点 ×0.5) scales
     the contribution of the following sentiment word.
  5. A neutral dead-zone keeps borderline / mixed texts as ``neutral``
     so the downstream risk scorer does not mis-fire on uncertainty.

Confidence is ``min(0.95, 0.5 + gap * 0.1)`` where ``gap`` is the
absolute score difference, matching the keyword provider's scale.

The lexicon files live under ``backend/app/services/nlp/data/`` and
are loaded lazily on first call (module-global cached ``frozenset``).

Provider is deterministic for the same input and language, satisfying
the :class:`BaseNlpProvider` contract relied on by ``analyze_opinion``.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import FrozenSet

from app.services.nlp.base import (
    SUPPORTED_LANGUAGES,
    BaseNlpProvider,
    NlpResult,
    SENTIMENT_NEGATIVE,
    SENTIMENT_NEUTRAL,
    SENTIMENT_POSITIVE,
)
from app.services.nlp.exceptions import NlpProviderError

import jieba  # third-party; declared in backend/requirements.txt


# --- lexicon loading ---------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parent / "data"


def _load_lexicon(filename: str) -> FrozenSet[str]:
    """Load a one-token-per-line UTF-8 lexicon file.

    Lines that are blank or start with ``#`` are skipped. Anything left
    after ``.strip()`` is taken verbatim; no normalization is applied so
    that the lexicon author stays in full control of what tokens are
    matched.
    """
    path = _DATA_DIR / filename
    if not path.is_file():
        raise NlpProviderError(f"lexicon file missing: {path}")
    tokens: set[str] = set()
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            tokens.add(line)
    if not tokens:
        raise NlpProviderError(f"lexicon file is empty: {path}")
    return frozenset(tokens)


@lru_cache(maxsize=1)
def _get_positive_tokens() -> FrozenSet[str]:
    return _load_lexicon("hownet_simplified.pos.txt")


@lru_cache(maxsize=1)
def _get_negative_tokens() -> FrozenSet[str]:
    return _load_lexicon("hownet_simplified.neg.txt")


# --- negation / degree dictionaries (intentionally small but high-precision) -

_NEGATION_WORDS: FrozenSet[str] = frozenset({
    # Single-char negations (always tokenized separately by jieba).
    "不", "没", "非", "未", "无", "别", "莫", "勿", "毋", "弗",
    # Multi-char negations that jieba keeps as single tokens in its default dict.
    "没有", "不会", "不能", "不可", "不是", "不行", "没法", "不要",
    "并未", "并非", "毫无", "绝不", "决不", "毫不", "无从", "未",
    "未曾", "不曾", "尚未", "无法", "难以", "难以", "无须", "不必",
    "不宜", "不许", "不准", "不可", "不可不", "不敢", "不能不",
})

_DEGREE_WORDS: dict[str, float] = {
    # strong intensifiers — push score up
    "极其": 1.8, "极度": 1.8, "极端": 1.8, "最为": 1.5, "最为": 1.5,
    "非常": 1.5, "异常": 1.5, "异常": 1.5, "特别": 1.4, "格外": 1.4,
    "十分": 1.4, "尤其": 1.4, "尤为": 1.4, "更": 1.2, "更加": 1.3,
    "更显": 1.3, "更是": 1.3, "愈加": 1.3, "愈发": 1.3, "越加": 1.3,
    "颇": 1.2, "颇为": 1.3, "深": 1.2, "深感": 1.2, "深感": 1.2,
    # weak / hedging — push score down
    "稍微": 0.5, "稍": 0.5, "略": 0.5, "略微": 0.5, "有点": 0.5,
    "有些": 0.6, "些许": 0.6, "一点": 0.6, "一点儿": 0.6,
    "不怎么": 0.4, "不太": 0.4, "不够": 0.4,
}

# --- algorithm constants -----------------------------------------------------

_WINDOW = 3              # tokens looked back for negation / degree
_NEUTRAL_DEAD_ZONE = 0.3 # gap ratio below which we report "neutral"


# --- provider ----------------------------------------------------------------


class JiebaNlpProvider(BaseNlpProvider):
    name = "jieba_nlp"

    def analyze(self, text: str, language: str = "zh") -> NlpResult:
        # --- guards (mirror KeywordNlpProvider semantics) ---
        if language not in SUPPORTED_LANGUAGES:
            return NlpResult(
                sentiment=SENTIMENT_NEUTRAL,
                confidence=0.0,
                error_message=f"unsupported_language:{language}",
            )
        if text is None:
            return NlpResult(
                sentiment=SENTIMENT_NEUTRAL,
                confidence=0.0,
                error_message="empty_text",
            )

        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return NlpResult(
                sentiment=SENTIMENT_NEUTRAL,
                confidence=0.5,
                error_message="empty_text",
            )

        pos_set = _get_positive_tokens()
        neg_set = _get_negative_tokens()

        # --- segmentation ---
        # jieba.cut() returns a generator; list() materializes for windowing.
        # cut_all=False gives precise mode (matches jieba's default dict).
        try:
            tokens = list(jieba.cut(normalized, cut_all=False))
        except Exception as e:  # noqa: BLE001 - any segmentation failure is fatal
            raise NlpProviderError(f"jieba segmentation failed: {e}") from e

        pos_score = 0.0
        neg_score = 0.0

        for i, tok in enumerate(tokens):
            polarity = 0
            if tok in pos_set:
                polarity = +1
            elif tok in neg_set:
                polarity = -1
            else:
                continue

            # Build the window of preceding tokens (skip punctuation / whitespace).
            window_start = max(0, i - _WINDOW)
            window = [t for t in tokens[window_start:i] if t.strip()]

            # Negation: any negation word in the window flips the sign.
            # Negation is amplified (×1.2) instead of mere inversion because
            # the speaker usually expresses stronger feeling when negating.
            negated = any(w in _NEGATION_WORDS for w in window)
            magnitude = 1.0
            if negated:
                magnitude = 1.2
                polarity = -polarity

            # Degree adverb: take the maximum multiplier found in the window.
            for w in window:
                m = _DEGREE_WORDS.get(w)
                if m is not None and m > magnitude:
                    magnitude = m

            contribution = magnitude
            if polarity > 0:
                pos_score += contribution
            else:
                neg_score += contribution

        # --- decision ---
        total = pos_score + neg_score
        if total == 0.0:
            return NlpResult(sentiment=SENTIMENT_NEUTRAL, confidence=0.5)

        diff = pos_score - neg_score  # signed
        gap = abs(diff)
        # Confidence is the same shape as the keyword provider's so downstream
        # callers see comparable numbers.
        confidence = min(0.95, 0.5 + gap * 0.1)

        # Neutral dead-zone: when pos and neg are close in magnitude, report
        # neutral rather than guessing — the舆情 scorer prefers "uncertain"
        # over "wrong side".
        if gap / total <= _NEUTRAL_DEAD_ZONE:
            return NlpResult(
                sentiment=SENTIMENT_NEUTRAL,
                confidence=min(0.75, 0.5 + gap * 0.1),
            )

        if diff > 0:
            return NlpResult(sentiment=SENTIMENT_POSITIVE, confidence=confidence)
        return NlpResult(sentiment=SENTIMENT_NEGATIVE, confidence=confidence)


__all__ = ["JiebaNlpProvider"]