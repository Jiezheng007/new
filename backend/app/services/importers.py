"""CSV / JSON import parsers (Phase 3 / Issue 5).

Both parsers emit a stream of :class:`RawRecord` so the rest of the
ingestion pipeline (cleaning, hashing, dedup, persistence) stays identical
to the RSS / static-demo path. Required fields are ``title`` and ``content``;
missing required fields raise :class:`ImportParseError` with the offending
row index, which the API surfaces back to the caller.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import IO, Any, Iterable

from app.services.connectors import RawRecord


class ImportParseError(Exception):
    """Raised when the import payload is structurally invalid.

    ``errors`` carries per-row reasons; ``fatal`` distinguishes a
    payload-wide failure (no records could be parsed) from a partial failure.
    """

    def __init__(self, message: str, *, errors: list[dict[str, Any]] | None = None, fatal: bool = False) -> None:
        super().__init__(message)
        self.errors = errors or []
        self.fatal = fatal


def parse_csv(payload: str) -> tuple[list[RawRecord], list[dict[str, Any]]]:
    """Parse a CSV string into (records, row_errors).

    Required columns: ``title`` and ``content``. A BOM is stripped; an empty
    file or a missing required column raises ``ImportParseError`` with
    ``fatal=True`` because the caller cannot recover. Per-row validation
    failures (missing title, etc.) are returned alongside the records so the
    API can report them in the result payload.
    """
    if payload is None:
        raise ImportParseError("CSV payload is empty", fatal=True)
    text = payload.lstrip("﻿")
    if not text.strip():
        raise ImportParseError("CSV payload is empty", fatal=True)
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ImportParseError("CSV header is missing", fatal=True)
    headers = {h.strip().lower(): h for h in reader.fieldnames if h}
    if "title" not in headers:
        raise ImportParseError("CSV is missing required 'title' column", fatal=True)
    if "content" not in headers:
        raise ImportParseError("CSV is missing required 'content' column", fatal=True)

    records: list[RawRecord] = []
    errors: list[dict[str, Any]] = []
    for index, row in enumerate(reader):
        title = (row.get(headers["title"]) or "").strip()
        if not title:
            errors.append({"index": index, "reason": "title_required"})
            continue
        records.append(RawRecord(
            external_id=(row.get(headers.get("external_id", "")) or "").strip(),
            title=title,
            content=(row.get(headers["content"]) or "").strip(),
            url=(row.get(headers.get("url", "")) or "").strip(),
            author=(row.get(headers.get("author", "")) or "").strip(),
            language=(row.get(headers.get("language", "")) or "zh").strip() or "zh",
            published_at=_coerce_datetime(row.get(headers.get("published_at", ""))),
            raw_payload={k: v for k, v in row.items() if v not in (None, "")},
        ))
    return records, errors


def parse_json(payload: str) -> tuple[list[RawRecord], list[dict[str, Any]]]:
    """Parse a JSON string into (records, record_errors).

    Accepts either a top-level array of objects or an object with a
    ``records`` / ``items`` / ``data`` array. Per-record validation failures
    (missing title, non-object) are returned alongside the records; only
    structural issues (invalid JSON, missing array wrapper) raise
    ``ImportParseError`` with ``fatal=True``.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        raise ImportParseError(f"Invalid JSON: {e}", fatal=True) from e

    if isinstance(data, dict):
        for key in ("records", "items", "data"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
        else:
            raise ImportParseError(
                "JSON object must contain a 'records', 'items', or 'data' array",
                fatal=True,
            )

    if not isinstance(data, list):
        raise ImportParseError("JSON must be an array of records", fatal=True)

    records: list[RawRecord] = []
    errors: list[dict[str, Any]] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append({"index": index, "reason": "not_an_object"})
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            errors.append({"index": index, "reason": "title_required"})
            continue
        records.append(RawRecord(
            external_id=str(item.get("external_id") or item.get("id") or "").strip(),
            title=title,
            content=str(item.get("content", "")).strip(),
            url=str(item.get("url", "")).strip(),
            author=str(item.get("author", "")).strip(),
            language=str(item.get("language", "zh") or "zh").strip() or "zh",
            published_at=_coerce_datetime(item.get("published_at")),
            raw_payload=item,
        ))
    return records, errors


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        # Python 3.11+ understands the common ISO-8601 shapes natively.
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
