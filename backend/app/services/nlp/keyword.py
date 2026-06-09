"""Deterministic Chinese-keyword NLP provider (Phase 4 / Issue 6 default).

Counts positive and negative Chinese tokens inside the supplied text,
then labels the result by whichever side is ahead (tie -> neutral).
The dictionary is small but covers the categories the demo data and the
risk-rule examples actually exercise, so the provider can drive a real
risk-scoring demo without depending on an external model or network.

Confidence is a coarse, deterministic function of the score gap:
``min(1.0, 0.5 + gap * 0.1)`` clamped to ``[0.5, 0.95]``. The exact
shape is not part of the contract - tests only assert the *direction*
(positive vs. negative vs. neutral) and the monotonicity in the gap.
"""
from __future__ import annotations

import re

from app.services.nlp.base import (
    BaseNlpProvider,
    NlpResult,
    SENTIMENT_NEGATIVE,
    SENTIMENT_NEUTRAL,
    SENTIMENT_POSITIVE,
    SUPPORTED_LANGUAGES,
)
from app.services.nlp.exceptions import NlpProviderError


# Negative-leaning Chinese tokens. Strings, not patterns - simple
# ``in`` matching keeps the implementation easy to audit and explain.
_NEGATIVE_TOKENS: tuple[str, ...] = (
    "问题", "严重", "重大", "安全", "事故", "投诉", "违规", "违法", "整改",
    "下架", "召回", "曝光", "批评", "质疑", "担忧", "焦虑", "失望", "不满",
    "失败", "下滑", "亏损", "暴跌", "危机", "风险", "紧急", "突发", "召回",
    "封锁", "中断", "影响恶劣", "强烈不满", "强制", "查处", "处罚", "罚款",
    "通报", "调查中", "涉嫌", "造假", "欺诈", "泄露", "投诉", "维权",
)

# Positive-leaning Chinese tokens.
_POSITIVE_TOKENS: tuple[str, ...] = (
    "增长", "提升", "改善", "优化", "创新", "突破", "稳健", "积极", "升级",
    "好评", "满意", "推荐", "达成", "签署", "合作", "发布", "落地", "试点",
    "规范", "合规", "透明", "高效", "及时", "回应", "解决", "推动", "促进",
    "利好", "上行", "新高", "扩大", "拓展", "领先", "认可", "通过", "批准",
)

# Severity multipliers used to scale the negative count. Not directly
# used by the score (sensitive keywords are counted separately in
# scoring.py); kept here for future tuning of provider confidence.
_NEGATIVE_WEIGHTS: dict[str, float] = {tok: 1.0 for tok in _NEGATIVE_TOKENS}
_NEGATIVE_WEIGHTS.update({
    "严重": 2.0, "重大": 2.0, "事故": 2.0, "危机": 2.5, "暴跌": 2.0,
    "曝光": 1.8, "强制": 1.5, "处罚": 1.6, "查处": 1.6, "罚款": 1.6,
    "造假": 2.0, "欺诈": 2.0, "泄露": 1.8, "违规": 1.5, "违法": 2.0,
})


def _token_count(text: str, tokens: tuple[str, ...]) -> float:
    if not text:
        return 0.0
    total = 0.0
    for tok in tokens:
        weight = _NEGATIVE_WEIGHTS.get(tok, 1.0) if tokens is _NEGATIVE_TOKENS else 1.0
        total += weight * text.count(tok)
    return total


def _confidence(gap: int) -> float:
    """Map an integer count gap to a [0.5, 0.95] confidence value."""
    if gap <= 0:
        return 0.5
    return min(0.95, 0.5 + gap * 0.1)


class KeywordNlpProvider(BaseNlpProvider):
    name = "keyword_nlp"

    def analyze(self, text: str, language: str = "zh") -> NlpResult:
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
        normalized = re.sub(r"\s+", " ", text)
        pos = _token_count(normalized, _POSITIVE_TOKENS)
        neg = _token_count(normalized, _NEGATIVE_TOKENS)
        # Ties or empty text -> neutral. The threshold of 0 keeps the
        # output deterministic regardless of dictionary size.
        if pos == 0 and neg == 0:
            return NlpResult(sentiment=SENTIMENT_NEUTRAL, confidence=0.5)
        if neg > pos:
            return NlpResult(sentiment=SENTIMENT_NEGATIVE, confidence=_confidence(int(neg - pos)))
        if pos > neg:
            return NlpResult(sentiment=SENTIMENT_POSITIVE, confidence=_confidence(int(pos - neg)))
        return NlpResult(sentiment=SENTIMENT_NEUTRAL, confidence=0.5)


__all__ = ["KeywordNlpProvider", "NlpProviderError"]
