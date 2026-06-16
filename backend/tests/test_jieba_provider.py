"""Unit tests for the jieba + HowNet simplified lexicon NLP provider.

Mirrors the structure of ``test_analysis.py::test_keyword_provider_*`` so
the two providers can be diffed side-by-side. Targets:

  1. unsupported language guard
  2. empty text guard
  3. positive sample detection
  4. negative sample detection
  5. negation window: "不推荐" must NOT come out positive
  6. degree adverb: "非常好" scores higher confidence than "好"
  7. word segmentation: "业绩不下滑" must not be flagged strongly negative
  8. determinism: same input -> same output
  9. registry: ``get_nlp_provider()`` resolves ``jieba_nlp`` when configured
"""
from __future__ import annotations

import pytest

from app.services.nlp import (
    BaseNlpProvider,
    NlpProviderError,
    SENTIMENT_NEGATIVE,
    SENTIMENT_NEUTRAL,
    SENTIMENT_POSITIVE,
    get_nlp_provider,
    reset_nlp_provider_cache,
)
from app.services.nlp.jieba_provider import JiebaNlpProvider


# ---------- 1. unsupported language ----------

def test_jieba_provider_unsupported_language_records_error():
    result = JiebaNlpProvider().analyze("anything", language="fr")
    assert result.sentiment == SENTIMENT_NEUTRAL
    assert result.error_message is not None
    assert "unsupported_language" in result.error_message


# ---------- 2. empty text ----------

def test_jieba_provider_empty_text_is_neutral():
    result = JiebaNlpProvider().analyze("", language="zh")
    assert result.sentiment == SENTIMENT_NEUTRAL

    result_none = JiebaNlpProvider().analyze(None, language="zh")  # type: ignore[arg-type]
    assert result_none.sentiment == SENTIMENT_NEUTRAL
    assert result_none.error_message == "empty_text"


def test_jieba_provider_whitespace_only_is_neutral():
    result = JiebaNlpProvider().analyze("   \n\t  ", language="zh")
    assert result.sentiment == SENTIMENT_NEUTRAL


# ---------- 3. positive sample ----------

def test_jieba_provider_detects_positive():
    provider = JiebaNlpProvider()
    result = provider.analyze(
        "公司业绩大幅增长,获得客户高度好评,实现历史新高",
        language="zh",
    )
    assert result.sentiment == SENTIMENT_POSITIVE, result
    assert result.error_message is None
    assert 0.5 <= result.confidence <= 0.95


# ---------- 4. negative sample ----------

def test_jieba_provider_detects_negative():
    provider = JiebaNlpProvider()
    result = provider.analyze(
        "发生安全事故,产品被召回,大量用户投诉,监管部门介入调查",
        language="zh",
    )
    assert result.sentiment == SENTIMENT_NEGATIVE, result
    assert result.error_message is None


# ---------- 5. negation handling (key regression protection) ----------

def test_jieba_provider_handles_negation_not_recommended():
    """The keyword provider wrongly returns 'positive' for '我不推荐'
    because '推荐' is in its positive set. The jieba provider must flip
    that via the negation window."""
    provider = JiebaNlpProvider()
    result = provider.analyze("这个产品我不推荐", language="zh")
    assert result.sentiment == SENTIMENT_NEGATIVE, result


def test_jieba_provider_handles_negation_no_praise():
    result = JiebaNlpProvider().analyze("客户没有明显的好评反馈", language="zh")
    # Should NOT be confidently positive; negation in window dampens it.
    assert result.sentiment != SENTIMENT_POSITIVE


def test_jieba_provider_handles_negation_no_growth():
    """'业绩没有增长' should not be positive."""
    result = JiebaNlpProvider().analyze("这个季度业绩没有增长", language="zh")
    assert result.sentiment != SENTIMENT_POSITIVE


# ---------- 6. degree adverb ----------

def test_jieba_provider_degree_adverb_raises_confidence():
    provider = JiebaNlpProvider()
    weak = provider.analyze("服务质量好", language="zh")
    strong = provider.analyze("服务质量非常好", language="zh")
    # Both should be positive in this setup, and strong should have >= confidence.
    assert weak.sentiment == SENTIMENT_POSITIVE
    assert strong.sentiment == SENTIMENT_POSITIVE
    assert strong.confidence >= weak.confidence


# ---------- 7. word segmentation ----------

def test_jieba_provider_segmentation_handles_not_drop():
    """'不下滑' must NOT trigger a strong negative result. The keyword
    provider's substring matching would flag '下滑' even with '不' in front."""
    result = JiebaNlpProvider().analyze("本季度业绩不下滑", language="zh")
    # Either neutral or weakly positive is acceptable; definitely NOT
    # strongly negative.
    assert result.sentiment != SENTIMENT_NEGATIVE or result.confidence <= 0.6


def test_jieba_provider_segmentation_handles_no_accident():
    """'无事故' must NOT trigger a strongly negative classification.
    '事故' is in the negative lexicon, but '无' should flip the polarity."""
    result = JiebaNlpProvider().analyze("本月无安全事故发生", language="zh")
    assert result.sentiment != SENTIMENT_NEGATIVE or result.confidence <= 0.6


# ---------- 8. determinism ----------

def test_jieba_provider_is_deterministic():
    provider = JiebaNlpProvider()
    text = "公司业绩大幅增长,获得客户高度好评,实现历史新高"
    r1 = provider.analyze(text, language="zh")
    r2 = provider.analyze(text, language="zh")
    assert r1.sentiment == r2.sentiment
    assert r1.confidence == r2.confidence


# ---------- 9. registry wiring ----------

def test_get_nlp_provider_resolves_jieba_when_configured(monkeypatch):
    monkeypatch.setenv("NLP_PROVIDER", "jieba_nlp")
    # Settings is cached; clear and force a reload.
    from app.core.config import get_settings
    get_settings.cache_clear()
    reset_nlp_provider_cache()
    try:
        provider = get_nlp_provider()
        assert isinstance(provider, JiebaNlpProvider)
        assert provider.name == "jieba_nlp"
    finally:
        monkeypatch.delenv("NLP_PROVIDER", raising=False)
        get_settings.cache_clear()
        reset_nlp_provider_cache()


def test_get_nlp_provider_default_is_jieba(monkeypatch):
    """Default in backend/app/core/config.py switched to jieba_nlp in Phase 5."""
    monkeypatch.delenv("NLP_PROVIDER", raising=False)
    from app.core.config import get_settings
    get_settings.cache_clear()
    reset_nlp_provider_cache()
    provider = get_nlp_provider()
    assert isinstance(provider, JiebaNlpProvider)
    assert provider.name == "jieba_nlp"


# ---------- provider name + base class contract ----------

def test_jieba_provider_name():
    assert JiebaNlpProvider.name == "jieba_nlp"


def test_jieba_provider_is_base_nlp_provider():
    assert issubclass(JiebaNlpProvider, BaseNlpProvider)


# ---------- lexicon availability ----------

def test_lexicon_files_load():
    """Smoke test: importing the provider module must successfully load
    both lexicon files (raising NlpProviderError on failure)."""
    # Touch the lru_cache to force load.
    from app.services.nlp.jieba_provider import _get_negative_tokens, _get_positive_tokens

    pos = _get_positive_tokens()
    neg = _get_negative_tokens()
    assert len(pos) >= 100, f"positive lexicon too small: {len(pos)}"
    assert len(neg) >= 100, f"negative lexicon too small: {len(neg)}"
    # Sanity: well-known words should be present.
    assert "增长" in pos
    assert "下滑" in neg