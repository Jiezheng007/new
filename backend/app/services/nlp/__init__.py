"""NLP provider registry (Phase 4 / Issue 6).

The active provider is selected through the ``NLP_PROVIDER`` setting
(default: ``keyword_nlp``). The registry resolves the name to a class
the first time it is needed, then caches the instance for the lifetime
of the process. New providers plug in by:

  1. subclassing :class:`BaseNlpProvider` in a new module
  2. adding an entry to ``_PROVIDER_REGISTRY`` below
  3. (optionally) exposing a new ``NLP_PROVIDER`` setting value

The orchestration layer only sees :class:`BaseNlpProvider` - it does
not care whether the implementation is a keyword dictionary, a local
model, or a remote API.
"""
from __future__ import annotations

from typing import Type

from app.core.config import get_settings
from app.services.nlp.base import (
    SUPPORTED_LANGUAGES,
    BaseNlpProvider,
    NlpResult,
    SENTIMENT_NEGATIVE,
    SENTIMENT_NEUTRAL,
    SENTIMENT_POSITIVE,
)
from app.services.nlp.exceptions import NlpProviderError


_PROVIDER_REGISTRY: dict[str, Type[BaseNlpProvider]] = {}


def _build_registry() -> dict[str, Type[BaseNlpProvider]]:
    if _PROVIDER_REGISTRY:
        return _PROVIDER_REGISTRY
    from app.services.nlp.jieba_provider import JiebaNlpProvider  # noqa: WPS433 - lazy import
    from app.services.nlp.keyword import KeywordNlpProvider  # noqa: WPS433 - lazy import

    _PROVIDER_REGISTRY.update({
        "jieba_nlp": JiebaNlpProvider,
        "keyword_nlp": KeywordNlpProvider,
    })
    return _PROVIDER_REGISTRY


_cached_provider: BaseNlpProvider | None = None


def get_nlp_provider() -> BaseNlpProvider:
    """Return the configured provider instance (cached)."""
    global _cached_provider
    if _cached_provider is not None:
        return _cached_provider
    settings = get_settings()
    name = (settings.nlp_provider or "keyword_nlp").strip()
    registry = _build_registry()
    cls = registry.get(name)
    if cls is None:
        raise NlpProviderError(f"Unknown NLP provider: {name!r}")
    _cached_provider = cls()
    return _cached_provider


def reset_nlp_provider_cache() -> None:
    """Clear the cached provider (used by tests after overriding settings)."""
    global _cached_provider
    _cached_provider = None


__all__ = [
    "BaseNlpProvider",
    "NlpResult",
    "NlpProviderError",
    "SUPPORTED_LANGUAGES",
    "SENTIMENT_POSITIVE",
    "SENTIMENT_NEUTRAL",
    "SENTIMENT_NEGATIVE",
    "get_nlp_provider",
    "reset_nlp_provider_cache",
]
