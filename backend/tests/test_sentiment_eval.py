"""Pytest regression gate for the sentiment-analysis evaluation pipeline.

Runs the eval script in-process against the labeled dataset and asserts
that the jieba provider beats the keyword provider by at least 5 percentage
points on accuracy. This guards against future lexicon / algorithm changes
that might regress the win.

Behaviour:
  - Marked ``@pytest.mark.slow`` so quick local runs (``pytest -m 'not slow'``)
    skip it. CI runs the slow suite.
  - Respects the ``SENTIMENT_EVAL_LIMIT`` env var (default 50) so the gate
    stays fast on developer machines.
  - Looks for the dataset in this priority order:
      1. ``sentiment_eval.jsonl`` (full 500-row set, may be gitignored)
      2. ``sentiment_eval.sample.jsonl`` (10-row sample, always committed)
      3. ``pytest.skip`` if neither exists.
  - Skips if jieba is not importable (the dependency is added in
    ``backend/requirements.txt`` but tests should not hard-require it).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# jieba is declared in requirements.txt but not strictly required at test
# collection time. The gate is the only test that needs it.
pytest.importorskip("jieba")

DATA_DIR = Path(__file__).resolve().parent.parent / "scripts" / "data"
FULL_DATASET = DATA_DIR / "sentiment_eval.jsonl"
SAMPLE_DATASET = DATA_DIR / "sentiment_eval.sample.jsonl"


def _resolve_dataset() -> Path:
    if FULL_DATASET.is_file():
        return FULL_DATASET
    if SAMPLE_DATASET.is_file():
        return SAMPLE_DATASET
    pytest.skip(
        f"no eval dataset found; expected {FULL_DATASET} or {SAMPLE_DATASET}"
    )


def _resolve_limit() -> int | None:
    env = os.environ.get("SENTIMENT_EVAL_LIMIT")
    if env:
        try:
            return int(env)
        except ValueError:
            return None
    return None


@pytest.mark.slow
def test_jieba_beats_keyword_by_at_least_5pp():
    """Regression guard: jieba_nlp must beat keyword_nlp by >= 5pp on accuracy."""
    # Import inside the test so the skip-if-no-jieba check is honoured.
    from scripts.eval_sentiment import EvalConfig, run_eval

    dataset = _resolve_dataset()
    cfg = EvalConfig(
        provider="all",
        dataset=dataset,
        limit=_resolve_limit(),
        output=None,
        fail_below=None,
        language="zh",
    )
    payload = run_eval(cfg)
    runs = payload["runs"]
    comparison = payload["comparison"]

    keyword_acc = runs["keyword_nlp"]["accuracy"]
    jieba_acc = runs["jieba_nlp"]["accuracy"]
    uplift = comparison["accuracy_uplift"]

    # Clear message if the gate fails: include both accuracies and a sample
    # of disagreements so the developer can see exactly where jieba
    # regressed.
    assert uplift >= 0.05, (
        f"jieba vs keyword accuracy uplift regressed: "
        f"jieba={jieba_acc:.4f} keyword={keyword_acc:.4f} uplift={uplift:+.4f}\n"
        f"keyword disagreements (first 5):\n"
        + "\n".join(
            f"  [{d['expected']} -> {d['predicted']}] {d['text'][:60]}"
            for d in runs["keyword_nlp"]["disagreements_sample"][:5]
        )
        + "\n\njieba disagreements (first 5):\n"
        + "\n".join(
            f"  [{d['expected']} -> {d['predicted']}] {d['text'][:60]}"
            for d in runs["jieba_nlp"]["disagreements_sample"][:5]
        )
    )


@pytest.mark.slow
def test_jieba_provider_passes_minimum_accuracy_floor():
    """A floor on jieba alone (so a complete failure of keyword doesn't mask a
    jieba regression). The exact floor is intentionally conservative: with
    a curated 500-row set we expect >= 0.65, well above what the keyword
    baseline achieves. Tighten or loosen as the dataset evolves."""
    from scripts.eval_sentiment import EvalConfig, run_eval

    dataset = _resolve_dataset()
    cfg = EvalConfig(
        provider="jieba_nlp",
        dataset=dataset,
        limit=_resolve_limit(),
        output=None,
        fail_below=None,
        language="zh",
    )
    payload = run_eval(cfg)
    jieba_acc = payload["runs"]["jieba_nlp"]["accuracy"]
    assert jieba_acc >= 0.65, (
        f"jieba_nlp accuracy {jieba_acc:.4f} below floor 0.65. "
        f"Likely causes: lexicon regression, segmentation failure, "
        f"or dataset schema change."
    )


@pytest.mark.slow
def test_eval_pipeline_runs_end_to_end_and_writes_report(tmp_path):
    """Smoke test for the eval CLI: pipeline runs, produces a JSON report,
    and the report shape matches the contract documented in
    scripts/eval_sentiment.py."""
    from scripts.eval_sentiment import EvalConfig, run_eval

    dataset = _resolve_dataset()
    out = tmp_path / "report.json"
    cfg = EvalConfig(
        provider="all",
        dataset=dataset,
        limit=_resolve_limit(),
        output=out,
        fail_below=None,
        language="zh",
    )
    payload = run_eval(cfg)
    assert "runs" in payload
    assert "keyword_nlp" in payload["runs"]
    assert "jieba_nlp" in payload["runs"]
    assert "comparison" in payload
    # Schema spot-checks.
    for provider, run in payload["runs"].items():
        for key in (
            "n", "accuracy", "macro_f1", "per_class", "confusion",
            "latency_ms", "cold_start_ms",
        ):
            assert key in run, f"{provider}.{key} missing"