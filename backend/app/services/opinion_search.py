"""SQLite FTS helpers for opinion title/content search.

The project does not use Alembic, so this module owns the small bootstrap
needed for the FTS5 table. Callers can fall back to LIKE when FTS is not
available or when the query is not token-friendly for SQLite's default
tokenizer.
"""
from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.datasource import OpinionItem


_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def fts_supported_for_query(db: Session, query_text: str) -> bool:
    """Return True when SQLite FTS is a safe search backend for ``query_text``."""
    bind = db.get_bind()
    if not str(getattr(bind, "url", "")).startswith("sqlite"):
        return False
    tokens = _ASCII_TOKEN_RE.findall((query_text or "").strip())
    return bool(tokens) and "".join(tokens) == (query_text or "").strip().replace(" ", "")


def ensure_opinion_fts(db: Session) -> None:
    """Create and backfill the opinion FTS table if SQLite FTS5 is available."""
    db.execute(text(
        "CREATE VIRTUAL TABLE IF NOT EXISTS opinion_item_fts "
        "USING fts5(opinion_item_id UNINDEXED, title, content)"
    ))
    db.execute(text(
        "INSERT INTO opinion_item_fts(opinion_item_id, title, content) "
        "SELECT oi.id, oi.title, oi.content "
        "FROM opinion_items oi "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM opinion_item_fts f WHERE f.opinion_item_id = oi.id"
        ")"
    ))


def search_opinion_ids(db: Session, query_text: str) -> list[int] | None:
    """Return matching opinion ids via FTS, or None when caller should use LIKE."""
    if not fts_supported_for_query(db, query_text):
        return None
    try:
        ensure_opinion_fts(db)
        match_query = " ".join(_ASCII_TOKEN_RE.findall(query_text))
        rows = db.execute(
            text(
                "SELECT opinion_item_id "
                "FROM opinion_item_fts "
                "WHERE opinion_item_fts MATCH :query"
            ),
            {"query": match_query},
        ).all()
    except Exception:  # noqa: BLE001 - FTS is an optimization; callers fallback to LIKE.
        return None
    return [int(row[0]) for row in rows]


def sync_opinion_fts_rows(db: Session, items: list[OpinionItem]) -> None:
    """Best-effort FTS sync for newly inserted opinions."""
    if not items:
        return
    bind = db.get_bind()
    if not str(getattr(bind, "url", "")).startswith("sqlite"):
        return
    try:
        ensure_opinion_fts(db)
        db.execute(
            text("DELETE FROM opinion_item_fts WHERE opinion_item_id = :opinion_item_id"),
            [{"opinion_item_id": item.id} for item in items],
        )
        db.execute(
            text(
                "INSERT INTO opinion_item_fts(opinion_item_id, title, content) "
                "VALUES (:opinion_item_id, :title, :content)"
            ),
            [
                {
                    "opinion_item_id": item.id,
                    "title": item.title or "",
                    "content": item.content or "",
                }
                for item in items
            ],
        )
    except Exception:
        # Keep ingestion reliable even if a local SQLite build lacks FTS5.
        return
