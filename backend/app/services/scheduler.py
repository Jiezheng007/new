"""Background scheduler that auto-fetches enabled data sources (Phase 11 / Issue 14).

The scheduler is a simple async loop: every ``scheduler_interval_seconds`` it
walks every enabled data source whose ``source_type`` is in
:data:`app.services.datasource_fetch.AUTO_FETCH_TYPES` and runs
:func:`fetch_datasource` on it. Upload-only types (``csv`` / ``json_import``)
are skipped - they are operator-driven.

Design notes:

  * The loop runs as a FastAPI startup task. Tests opt out by setting
    ``SCHEDULER_ENABLED=false``.
  * ``_running`` acts as a coarse re-entrancy guard: if a previous tick is
    still in progress (slow connector, large backlog) the next tick is a
    no-op rather than stacking up. This matches what the plan document
    asks for.
  * Per-source exceptions are caught and recorded on the source's
    ``latest_fetch_*`` columns; one broken source never kills the loop.
  * The scheduler owns its own short-lived ``Session`` so it does not
    share state with a request handler.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.core.config import get_settings
from app.models.datasource import DataSource
from app.services.datasource_fetch import (
    AUTO_FETCH_TYPES,
    ORIGIN_SCHEDULED,
    fetch_datasource,
)


log = logging.getLogger(__name__)


def _get_session_factory():
    """Return the active ``SessionLocal`` from the db session module.

    The factory is resolved at call time (not import time) so tests that
    swap ``app.db.session.SessionLocal`` after the scheduler module is
    loaded still get the test session.
    """
    from app.db.session import SessionLocal
    return SessionLocal


_running: bool = False
_task: Optional[asyncio.Task[None]] = None
_stop_event: Optional[asyncio.Event] = None


def is_running() -> bool:
    """Whether a scheduler tick is currently executing."""
    return _running


def scheduler_task_is_alive() -> bool:
    """Whether the background loop task exists and has not been cancelled."""
    return _task is not None and not _task.done()


async def start_scheduler_if_enabled() -> None:
    """Start the background loop if the setting allows it.

    Idempotent: calling twice is a no-op. Safe to invoke from the FastAPI
    startup hook because it short-circuits when the feature flag is off
    or when the loop is already running.
    """
    global _task, _stop_event
    settings = get_settings()
    if not settings.scheduler_enabled:
        log.info("scheduler: disabled by configuration")
        return
    if _task is not None and not _task.done():
        return
    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_scheduler_loop(), name="yuqing-scheduler")
    log.info(
        "scheduler: started (interval=%ss, batch_limit=%s)",
        settings.scheduler_interval_seconds,
        settings.scheduler_fetch_batch_limit,
    )


async def stop_scheduler() -> None:
    """Signal the background loop to exit and wait for it to finish.

    Used by tests; production code lets the loop die with the event loop.
    """
    global _task, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _task is not None:
        try:
            await asyncio.wait_for(_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _task.cancel()
        _task = None
    _stop_event = None


async def _scheduler_loop() -> None:
    """Main loop: sleep, then run a single tick."""
    assert _stop_event is not None
    settings = get_settings()
    interval = max(1, int(settings.scheduler_interval_seconds))
    while not _stop_event.is_set():
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=interval)
            # If the event was set, exit without running another tick.
            return
        except asyncio.TimeoutError:
            # Normal cadence - time to run another tick.
            try:
                await run_once()
            except Exception:  # noqa: BLE001 - never let a tick kill the loop
                log.exception("scheduler: tick crashed")


async def run_once() -> dict[str, int]:
    """Run a single scheduler tick. Returns a small summary for tests/logs.

    Re-entrancy is guarded by the module-level ``_running`` flag so a slow
    tick cannot be overtaken by a fresh one. Upload-only types and disabled
    sources are filtered out before any work happens.
    """
    global _running
    if _running:
        log.debug("scheduler: previous tick still running, skipping")
        return {"skipped": 1, "fetched": 0, "failed": 0}
    _running = True
    fetched = 0
    failed = 0
    try:
        with _get_session_factory()() as db:
            settings = get_settings()
            sources = (
                db.query(DataSource)
                .filter(DataSource.is_enabled.is_(True))
                .filter(DataSource.source_type.in_(tuple(AUTO_FETCH_TYPES)))
                .order_by(DataSource.id.asc())
                .limit(settings.scheduler_fetch_batch_limit)
                .all()
            )
            for source in sources:
                try:
                    outcome = fetch_datasource(
                        db, source, actor=None, origin=ORIGIN_SCHEDULED
                    )
                    db.commit()
                    if outcome.ok:
                        fetched += 1
                    else:
                        failed += 1
                except Exception:  # noqa: BLE001 - one bad source must not stop the rest
                    db.rollback()
                    failed += 1
                    log.exception("scheduler: fetch failed for source id=%s", source.id)
    finally:
        _running = False
    return {"skipped": 0, "fetched": fetched, "failed": failed}
