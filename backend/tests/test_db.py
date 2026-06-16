"""Regression tests for the SQLite WAL / busy_timeout configuration.

These guard the fix for issue #5 — a long-running ingestion transaction
used to hold the exclusive write lock and every concurrent reader (web
pages, scheduler tick) failed with
``sqlite3.OperationalError: database is locked``.

We verify two things:

1. The PRAGMAs we apply at engine-create time actually take effect on
   the underlying DB-API connection.
2. A long write transaction no longer blocks concurrent readers once
   WAL is on (readers see the last committed snapshot, do not wait on
   the writer).
"""
from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import text

from app.db import session as session_module


def _read_pragma(name: str) -> str:
    with session_module.engine.connect() as conn:
        return conn.execute(text(f"PRAGMA {name}")).scalar()


def test_journal_mode_is_wal(app):
    assert _read_pragma("journal_mode").lower() == "wal"


def test_synchronous_is_normal(app):
    # ``synchronous=NORMAL`` reports as ``1`` (1=NORMAL, 2=FULL, 0=OFF).
    assert _read_pragma("synchronous") == 1


def test_busy_timeout_is_30s(app):
    # PRAGMA busy_timeout reports the value in milliseconds.
    assert _read_pragma("busy_timeout") == 30_000


def test_concurrent_read_during_write_does_not_block_or_error(app):
    """Long writer + concurrent reader must not raise ``database is locked``.

    We open a writer that holds a transaction open for ~1.5s. With WAL +
    a sane busy_timeout, a reader opened on a separate connection should
    return immediately (it sees the snapshot from before the writer
    started) and never raise ``OperationalError``.
    """
    started_at = time.monotonic()
    barrier = threading.Event()
    writer_done = threading.Event()
    errors: list[BaseException] = []
    reader_latency: list[float] = []

    def writer() -> None:
        try:
            with session_module.engine.begin() as conn:
                # Touch a real table so the writer takes a real lock.
                conn.execute(text("CREATE TABLE IF NOT EXISTS _lock_probe (n INTEGER)"))
                conn.execute(text("INSERT INTO _lock_probe (n) VALUES (1)"))
                # Hold the transaction open so concurrent code paths see
                # the writer is active.
                barrier.set()
                time.sleep(1.5)
        except BaseException as exc:  # pragma: no cover - propagated below
            errors.append(exc)
        finally:
            writer_done.set()

    t_writer = threading.Thread(target=writer)
    t_writer.start()
    barrier.wait(timeout=2.0)

    def reader() -> None:
        t0 = time.monotonic()
        try:
            with session_module.engine.connect() as conn:
                conn.execute(text("SELECT 1")).scalar()
        except BaseException as exc:
            errors.append(exc)
        finally:
            reader_latency.append(time.monotonic() - t0)

    t_reader = threading.Thread(target=reader)
    t_reader.start()
    t_reader.join(timeout=5.0)
    t_writer.join(timeout=5.0)

    assert not errors, f"unexpected errors during concurrent access: {errors!r}"
    # Reader should have returned in well under the writer's sleep — WAL
    # means readers do not block on writers.
    assert reader_latency, "reader did not record a latency"
    assert reader_latency[0] < 1.0, (
        f"reader took {reader_latency[0]:.2f}s — WAL is not effective"
    )
    assert writer_done.is_set(), "writer thread did not finish in time"
    # Sanity: the whole test should be bounded by the writer's sleep.
    assert time.monotonic() - started_at < 5.0


def test_register_sqlite_pragmas_is_safe_on_non_sqlite():
    """Helper must be a no-op on non-SQLite engines."""
    class _FakeEngine:
        url = type("U", (), {"__str__": lambda self: "postgresql://x"})()

    # Should not raise even though we never actually open the connection.
    session_module.register_sqlite_pragmas(_FakeEngine())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "name", ["register_sqlite_pragmas", "SQLITE_BUSY_TIMEOUT_MS", "SQLITE_CONNECT_TIMEOUT_S"]
)
def test_public_helpers_are_exported(name):
    assert hasattr(session_module, name), f"missing public symbol: {name}"
