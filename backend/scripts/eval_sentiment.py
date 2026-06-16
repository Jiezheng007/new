"""Sentiment analysis evaluation pipeline.

Benchmarks the available NLP providers (currently ``keyword_nlp`` and
``jieba_nlp``) against a labeled jsonl dataset and reports:

  - accuracy
  - per-class precision / recall / F1
  - macro F1
  - 3x3 confusion matrix (expected × predicted)
  - latency: avg / p50 / p95 / p99 / max
  - cold-start latency (first call only, to surface jieba dict loading cost)
  - disagreement samples (first 20 predicted != expected)
  - when run with ``--provider all``: side-by-side comparison with
    accuracy_uplift, macro_f1_uplift, latency_p95_ratio

Run from repo root:

    cd backend && python -m scripts.eval_sentiment --provider all

Or as a module invocation:

    python -m scripts.eval_sentiment --dataset scripts/data/sentiment_eval.jsonl

The output JSON report is intended to be committed alongside the dataset so
regressions across PRs are easy to spot.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# IMPORTANT: jieba prints to stderr on first import (loading its default dict).
# Silence that — the eval report would otherwise look messy.
import os
os.environ.setdefault("JIEBA_LOG_LEVEL", "20")

from app.services.nlp import SUPPORTED_LANGUAGES, get_nlp_provider, reset_nlp_provider_cache  # noqa: E402
from app.services.nlp.base import BaseNlpProvider  # noqa: E402

LABELS = ("positive", "neutral", "negative")
VALID_PROVIDERS = ("keyword_nlp", "jieba_nlp")


# ---------- configuration ----------------------------------------------------


@dataclass
class EvalConfig:
    provider: str           # one of "keyword_nlp" | "jieba_nlp" | "all"
    dataset: Path
    limit: Optional[int]
    output: Optional[Path]
    fail_below: Optional[float]
    language: str           # forced language for analyze() (default "zh")


# ---------- metrics ----------------------------------------------------------


@dataclass
class EvalReport:
    provider: str
    n: int = 0
    correct: int = 0
    skipped: int = 0
    accuracy: float = 0.0
    macro_f1: float = 0.0
    per_class: dict = field(default_factory=dict)
    confusion: dict = field(default_factory=dict)
    latency_ms: dict = field(default_factory=dict)
    cold_start_ms: float = 0.0
    errors: dict = field(default_factory=dict)
    disagreements: list = field(default_factory=list)
    rows: list = field(default_factory=list)  # full row-level results for debugging

    def to_json(self) -> dict:
        return {
            "provider": self.provider,
            "n": self.n,
            "correct": self.correct,
            "skipped": self.skipped,
            "accuracy": self.accuracy,
            "macro_f1": self.macro_f1,
            "per_class": self.per_class,
            "confusion": self.confusion,
            "latency_ms": self.latency_ms,
            "cold_start_ms": self.cold_start_ms,
            "errors": self.errors,
            "disagreement_total": sum(
                1 for r in self.rows if r.get("expected") != r.get("predicted")
            ),
            "disagreements_sample": self.disagreements,
        }


def _compute_metrics(report: EvalReport) -> None:
    rows = [r for r in report.rows if not r.get("skipped")]
    n = len(rows)
    report.n = n
    if n == 0:
        return

    report.correct = sum(1 for r in rows if r["expected"] == r["predicted"])
    report.accuracy = report.correct / n

    # per-class precision/recall/F1
    per_class = {}
    for lbl in LABELS:
        tp = sum(1 for r in rows if r["predicted"] == lbl and r["expected"] == lbl)
        fp = sum(1 for r in rows if r["predicted"] == lbl and r["expected"] != lbl)
        fn = sum(1 for r in rows if r["predicted"] != lbl and r["expected"] == lbl)
        support = sum(1 for r in rows if r["expected"] == lbl)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_class[lbl] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }
    report.per_class = per_class
    report.macro_f1 = statistics.mean(per_class[lbl]["f1"] for lbl in LABELS)

    # confusion matrix: rows=expected, cols=predicted
    cm = defaultdict(lambda: Counter())
    for r in rows:
        cm[r["expected"]][r["predicted"]] += 1
    report.confusion = {e: dict(cm[e]) for e in LABELS}

    # latency
    lats = sorted(r["latency_ms"] for r in rows)
    if lats:
        report.latency_ms = {
            "avg": statistics.mean(lats),
            "p50": lats[max(0, int(len(lats) * 0.50) - 1)],
            "p95": lats[max(0, int(len(lats) * 0.95) - 1)],
            "p99": lats[max(0, int(len(lats) * 0.99) - 1)],
            "max": lats[-1],
            "min": lats[0],
        }

    # error_message histogram
    err_counter = Counter(r.get("error_message") for r in rows if r.get("error_message"))
    report.errors = dict(err_counter)

    # disagreement sample (up to 20)
    report.disagreements = [
        {k: r[k] for k in ("id", "text", "expected", "predicted", "confidence", "error_message")}
        for r in rows
        if r["expected"] != r["predicted"]
    ][:20]


# ---------- dataset ----------------------------------------------------------


def _load_dataset(path: Path, limit: Optional[int]) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"dataset not found: {path}")
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as e:
                print(f"  warn: skipping malformed line {lineno}: {e}", file=sys.stderr)
                continue
            if not {"text", "label"} <= obj.keys():
                print(f"  warn: line {lineno} missing required keys", file=sys.stderr)
                continue
            if obj["label"] not in LABELS:
                print(f"  warn: line {lineno} invalid label {obj['label']!r}", file=sys.stderr)
                continue
            rows.append(obj)
            if limit is not None and len(rows) >= limit:
                break
    return rows


# ---------- run --------------------------------------------------------------


def _resolve_provider(name: str) -> BaseNlpProvider:
    """Switch the active provider, clear cache, and return a fresh instance."""
    if name not in VALID_PROVIDERS:
        raise ValueError(f"unknown provider: {name!r}; valid: {VALID_PROVIDERS}")
    os.environ["NLP_PROVIDER"] = name
    # Settings is cached, clear so it picks up the new env var.
    from app.core.config import get_settings
    get_settings.cache_clear()
    reset_nlp_provider_cache()
    return get_nlp_provider()


def run_one(cfg: EvalConfig, provider_name: str) -> EvalReport:
    print(f"\n=== Provider: {provider_name} ===")
    provider = _resolve_provider(provider_name)
    print(f"  class:    {type(provider).__name__}")
    print(f"  dataset:  {cfg.dataset}")

    rows = _load_dataset(cfg.dataset, cfg.limit)
    print(f"  rows:     {len(rows)}")

    report = EvalReport(provider=provider_name)
    first_call_done = False
    for row in rows:
        text = row["text"]
        expected = row["label"]
        # The dataset has no language field; all rows are zh by construction.
        language = cfg.language
        if language not in SUPPORTED_LANGUAGES:
            report.rows.append({
                "id": row.get("id"),
                "text": text,
                "expected": expected,
                "predicted": None,
                "confidence": None,
                "error_message": f"dataset row language not in SUPPORTED_LANGUAGES: {language}",
                "skipped": True,
                "latency_ms": 0.0,
            })
            report.skipped += 1
            continue

        # Cold start timing: include the first call's full cost (which may
        # include jieba dict loading).
        t0 = time.perf_counter()
        try:
            result = provider.analyze(text, language=language)
        except Exception as e:  # noqa: BLE001
            t1 = time.perf_counter()
            report.rows.append({
                "id": row.get("id"),
                "text": text,
                "expected": expected,
                "predicted": None,
                "confidence": None,
                "error_message": f"provider_exception: {e}",
                "skipped": True,
                "latency_ms": (t1 - t0) * 1000,
            })
            report.skipped += 1
            continue
        t1 = time.perf_counter()

        latency_ms = (t1 - t0) * 1000
        if not first_call_done:
            report.cold_start_ms = latency_ms
            first_call_done = True

        report.rows.append({
            "id": row.get("id"),
            "text": text,
            "expected": expected,
            "predicted": result.sentiment,
            "confidence": result.confidence,
            "error_message": result.error_message,
            "latency_ms": latency_ms,
            "skipped": False,
        })

    _compute_metrics(report)
    return report


def run_eval(cfg: EvalConfig) -> dict:
    if cfg.provider == "all":
        runs = {
            name: run_one(cfg, name)
            for name in VALID_PROVIDERS
        }
        # Comparison block.
        a = runs["keyword_nlp"]
        b = runs["jieba_nlp"]
        comparison = {
            "accuracy_uplift": b.accuracy - a.accuracy,
            "macro_f1_uplift": b.macro_f1 - a.macro_f1,
            "latency_p95_ratio": (
                b.latency_ms["p95"] / a.latency_ms["p95"]
                if a.latency_ms.get("p95") else None
            ),
            "verdict": (
                "jieba_better" if b.accuracy > a.accuracy else
                "keyword_better" if a.accuracy > b.accuracy else
                "tie"
            ),
        }
        return {
            "dataset": str(cfg.dataset),
            "limit": cfg.limit,
            "language": cfg.language,
            "runs": {name: r.to_json() for name, r in runs.items()},
            "comparison": comparison,
        }

    report = run_one(cfg, cfg.provider)
    return {
        "dataset": str(cfg.dataset),
        "limit": cfg.limit,
        "language": cfg.language,
        "runs": {cfg.provider: report.to_json()},
    }


# ---------- pretty-print -----------------------------------------------------


def _fmt_pct(x: float) -> str:
    return f"{x * 100:6.2f}%"


def _print_report(report: EvalReport) -> None:
    print(f"\n  provider: {report.provider}")
    print(f"  n:        {report.n}  (skipped: {report.skipped}, correct: {report.correct})")
    print(f"  accuracy: {_fmt_pct(report.accuracy)}")
    print(f"  macro_f1: {_fmt_pct(report.macro_f1)}")
    print()
    print(f"  per-class (precision / recall / F1 / support):")
    print(f"    {'label':<10} {'P':>8} {'R':>8} {'F1':>8} {'support':>8}")
    for lbl in LABELS:
        pc = report.per_class.get(lbl, {})
        if not pc:
            continue
        print(
            f"    {lbl:<10} "
            f"{_fmt_pct(pc['precision'])} "
            f"{_fmt_pct(pc['recall'])} "
            f"{_fmt_pct(pc['f1'])} "
            f"{pc['support']:>8}"
        )
    print()
    print(f"  confusion matrix (rows=expected, cols=predicted):")
    print(f"    {'':12} " + "  ".join(f"{c:>10}" for c in LABELS))
    for e in LABELS:
        cm = report.confusion.get(e, {})
        cells = "  ".join(f"{cm.get(p, 0):>10}" for p in LABELS)
        print(f"    {e:<12} {cells}")
    print()
    print(f"  latency (ms): avg={report.latency_ms.get('avg', 0):.2f}  "
          f"p50={report.latency_ms.get('p50', 0):.2f}  "
          f"p95={report.latency_ms.get('p95', 0):.2f}  "
          f"p99={report.latency_ms.get('p99', 0):.2f}  "
          f"max={report.latency_ms.get('max', 0):.2f}  "
          f"cold={report.cold_start_ms:.2f}")
    if report.errors:
        print()
        print(f"  error_message histogram: {report.errors}")
    if report.disagreements:
        print()
        total = getattr(report, "_total_disagreements", len(report.disagreements))
        print(f"  disagreement sample ({len(report.disagreements)} of {total}):")
        for d in report.disagreements[:5]:
            text_preview = (d["text"][:40] + "…") if len(d["text"]) > 40 else d["text"]
            print(f"    [{d['expected']:>8} -> {d['predicted']:<8}] {text_preview}")


def _print_full(payload: dict) -> None:
    for name, rj in payload["runs"].items():
        # Reconstruct minimal report for printing
        r = EvalReport(provider=name)
        r.n = rj["n"]
        r.correct = rj["correct"]
        r.skipped = rj["skipped"]
        r.accuracy = rj["accuracy"]
        r.macro_f1 = rj["macro_f1"]
        r.per_class = rj["per_class"]
        r.confusion = rj["confusion"]
        r.latency_ms = rj["latency_ms"]
        r.cold_start_ms = rj["cold_start_ms"]
        r.errors = rj["errors"]
        r.disagreements = rj.get("disagreements_sample", [])
        # Stash disagreement total so the printer can show "20 of N".
        r._total_disagreements = rj.get("disagreement_total", len(r.disagreements))
        _print_report(r)
    if "comparison" in payload:
        c = payload["comparison"]
        print(f"\n=== Comparison ===")
        print(f"  accuracy_uplift (jieba - keyword): "
              f"{c['accuracy_uplift'] * 100:+.2f} pp")
        print(f"  macro_f1_uplift (jieba - keyword): "
              f"{c['macro_f1_uplift'] * 100:+.2f} pp")
        if c["latency_p95_ratio"] is not None:
            print(f"  latency p95 ratio (jieba / keyword): "
                  f"{c['latency_p95_ratio']:.2f}x")
        print(f"  verdict: {c['verdict']}")


# ---------- CLI --------------------------------------------------------------


def _default_dataset() -> Path:
    return BACKEND_DIR / "scripts" / "data" / "sentiment_eval.jsonl"


def _default_sample() -> Path:
    return BACKEND_DIR / "scripts" / "data" / "sentiment_eval.sample.jsonl"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark NLP sentiment providers against a labeled dataset.",
    )
    parser.add_argument(
        "--provider",
        default="all",
        choices=("keyword_nlp", "jieba_nlp", "all"),
        help="Which provider to evaluate (default: all).",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Path to the jsonl dataset. Defaults to scripts/data/sentiment_eval.jsonl.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap on rows to evaluate (useful for quick smoke tests).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the JSON report here (in addition to stdout).",
    )
    parser.add_argument(
        "--fail-below",
        type=float,
        default=None,
        help="Exit 1 if accuracy (or accuracy_uplift when --provider all) "
             "drops below this value (0..1).",
    )
    parser.add_argument(
        "--language",
        default="zh",
        help="Language to pass to provider.analyze() (default: zh).",
    )
    args = parser.parse_args(argv)

    # Pick the dataset: explicit > SENTIMENT_EVAL_DATASET env > default.
    dataset = args.dataset
    if dataset is None:
        env_path = os.environ.get("SENTIMENT_EVAL_DATASET")
        dataset = Path(env_path) if env_path else _default_dataset()
    if not dataset.is_file() and dataset == _default_dataset():
        # Fall back to the 10-row sample if the full set is missing.
        sample = _default_sample()
        if sample.is_file():
            print(f"warn: full dataset missing, falling back to {sample}")
            dataset = sample

    cfg = EvalConfig(
        provider=args.provider,
        dataset=dataset,
        limit=args.limit or (int(os.environ["SENTIMENT_EVAL_LIMIT"]) if os.environ.get("SENTIMENT_EVAL_LIMIT") else None),
        output=args.output,
        fail_below=args.fail_below,
        language=args.language,
    )

    payload = run_eval(cfg)
    _print_full(payload)

    if cfg.output is not None:
        cfg.output.parent.mkdir(parents=True, exist_ok=True)
        with cfg.output.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"\nwrote report -> {cfg.output}")

    # Exit-code logic.
    if cfg.fail_below is not None:
        if cfg.provider == "all":
            uplift = payload["comparison"]["accuracy_uplift"]
            if uplift < cfg.fail_below:
                print(f"FAIL: accuracy_uplift {uplift:.4f} < --fail-below {cfg.fail_below:.4f}")
                return 1
        else:
            run = payload["runs"][cfg.provider]
            if run["accuracy"] < cfg.fail_below:
                print(f"FAIL: accuracy {run['accuracy']:.4f} < --fail-below {cfg.fail_below:.4f}")
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())