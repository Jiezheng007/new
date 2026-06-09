"""Exceptions raised by the NLP provider abstraction (Phase 4 / Issue 6)."""


class NlpProviderError(Exception):
    """Raised when an NLP provider cannot complete an analyze() call.

    The orchestration layer converts these into a persisted
    ``status='failed'`` ``AnalysisResult`` row rather than bubbling them
    up to the API request - a failing NLP service must never break
    ingestion or import.
    """
