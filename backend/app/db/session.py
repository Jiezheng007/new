"""SQLAlchemy engine + session factory.

Notes
-----
SQLite is the supported database for the MVP. Without explicit PRAGMAs the
default journal mode is ``DELETE`` and ``busy_timeout`` is 0, so a long-running
ingestion transaction (e.g. a 100k-record fetch) holds the exclusive write
lock and every concurrent reader/scheduler query fails with
``sqlite3.OperationalError: database is locked`` once it exceeds the 5s
default timeout.

We therefore:

* switch to WAL (Write-Ahead Logging) so readers do not block on the writer
  and vice versa;
* set ``synchronous=NORMAL`` (durable enough for our use case, much faster
  than FULL);
* raise ``busy_timeout`` to 30s so a brief contention surfaces as a wait
  rather than a hard error;
* raise the engine's ``connect_args["timeout"]`` to 30s as a second safety
  net for the Python ``sqlite3`` driver.

The PRAGMA application lives in a tiny helper
(``register_sqlite_pragmas``) so test fixtures that build their own
``Engine`` (see ``backend/tests/conftest.py``) can reuse it and exercise the
same configuration.
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


# Busy-timeout (ms) applied to every SQLite connection opened by an engine
# that we manage. 30s gives ingestion enough headroom to finish long
# batches while still surfacing real failures quickly.
SQLITE_BUSY_TIMEOUT_MS = 30_000
# Engine-level connect timeout (seconds) for the ``sqlite3`` driver itself.
SQLITE_CONNECT_TIMEOUT_S = 30.0


def register_sqlite_pragmas(target_engine: Engine) -> None:
    """Attach the standard SQLite PRAGMA listener to ``target_engine``.

    Idempotent w.r.t. URL — non-sqlite engines are a no-op. Safe to call on
    engines that already have a connect listener; SQLAlchemy will fire both.
    """
    if not str(target_engine.url).startswith("sqlite"):
        return

    @event.listens_for(target_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        finally:
            cursor.close()


_settings = get_settings()
_is_sqlite = _settings.database_url.startswith("sqlite")
_connect_args: dict = {}
if _is_sqlite:
    _connect_args = {
        "check_same_thread": False,
        "timeout": SQLITE_CONNECT_TIMEOUT_S,
    }

engine = create_engine(
    _settings.database_url,
    connect_args=_connect_args,
    future=True,
)
register_sqlite_pragmas(engine)


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
