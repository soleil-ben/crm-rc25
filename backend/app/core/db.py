"""Database engine and session management.

SQLite hardening required by CRM.md section 3:

* foreign key enforcement is turned on for *every* connection;
* WAL journal mode for single-server concurrency;
* a bounded busy timeout so short writer contention retries instead of failing;
* the database file lives outside the source tree and is git-ignored.

Nothing here is SQLite-specific beyond the PRAGMA listener, which keeps a future
PostgreSQL migration practical.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core import sqlite_codecs
from app.core.config import settings
from app.core.normalization import SEARCH_FOLD_SQL_NAME, search_fold

_IS_SQLITE = settings.database_url.startswith("sqlite")

# Process-wide, before any engine exists: the un-deprecated ``date``/``datetime`` codecs
# that store exactly what Python's deprecated defaults stored. See the module docstring.
sqlite_codecs.register()


def _ensure_sqlite_directory() -> None:
    path = settings.sqlite_path
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)


def build_engine(database_url: str | None = None) -> Engine:
    url = database_url or settings.database_url
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        connect_args["timeout"] = settings.sqlite_busy_timeout_ms / 1000
    engine = create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)
    if url.startswith("sqlite"):
        _register_sqlite_pragmas(engine)
        _register_explicit_transactions(engine)
    return engine


def _register_explicit_transactions(engine: Engine) -> None:
    """Make a transaction begin when SQLAlchemy says it does, not when pysqlite decides.

    **This is the documented pysqlite recipe**, and Phase 10 added it because two things
    that read as guarantees were not ones (DEC-0108).

    Left alone, the driver emits no ``BEGIN`` until it sees an ``INSERT``, ``UPDATE`` or
    ``DELETE``. Two consequences follow, and neither is visible from the code that suffers
    them:

    1. **A ``SAVEPOINT`` becomes the outermost transaction.** ``Session.begin_nested()`` on
       a session that has so far only read emits ``SAVEPOINT`` with no ``BEGIN`` in front
       of it, and in SQLite releasing the outermost savepoint *commits*. So a block written
       to be rolled back with its transaction was committing on release instead -- which in
       the Customer Account approval meant the idempotency claim, and then the link row and
       the proposal's decision, landing in three separate transactions, with the identity's
       activation outside all of them. A refusal after any of those left exactly the
       partial state the whole module is written to make impossible.
    2. **A read taken before the first write belongs to no transaction**, so
       check-then-write across two connections is unprotected: one connection can commit
       between another's check and its write, and neither sees a conflict. That is write
       skew, and it is the shape of "a merge checks for an account link while an approval
       creates one" (OD-40).

    With the two listeners below, ``BEGIN`` is emitted when SQLAlchemy begins a
    transaction. Savepoints nest properly, a rollback rolls the whole thing back, and a
    connection that has read holds its snapshot -- so a later write against a database that
    moved underneath it is refused rather than silently applied.

    **What it costs.** Transactions now hold their read snapshot from the first statement,
    so a writer that races a long reader meets ``database is locked`` sooner than before.
    That is a refusal rather than a corruption, ``PRAGMA busy_timeout`` absorbs the short
    cases, and ``commit_with_retry`` absorbs the rest. Reversible: deleting this function
    and its call restores the previous behaviour exactly.
    """

    @event.listens_for(engine, "connect")
    def _disable_implicit_begin(dbapi_connection, _connection_record):  # noqa: ANN001
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _emit_begin(connection):  # noqa: ANN001
        connection.exec_driver_sql("BEGIN")


def _register_sqlite_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={settings.sqlite_busy_timeout_ms}")
            # In-memory databases do not support WAL.
            if ":memory:" not in str(engine.url):
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA temp_store=MEMORY")
        finally:
            cursor.close()
        # SQLite's own lower() folds ASCII only, so "Đà Nẵng" would not match "đà nẵng".
        # The Customer Account keyword search folds both sides with this (DEC-0156).
        dbapi_connection.create_function(SEARCH_FOLD_SQL_NAME, 1, search_fold, deterministic=True)


if _IS_SQLITE:
    _ensure_sqlite_directory()

engine: Engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a short-lived session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for scripts and services outside the request cycle."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def commit_with_retry(session: Session, attempts: int = 4, base_delay: float = 0.05) -> None:
    """Commit, retrying briefly on SQLite ``database is locked`` (CRM.md section 3).

    The commit itself is retried while the transaction is still pending; the session is
    only rolled back once the bounded retries are exhausted. Any other OperationalError
    propagates immediately so genuine failures are not masked.

    **A failed flush ends the retries.** ``session.commit()`` flushes first, and a flush
    that hits ``database is locked`` leaves SQLAlchemy's transaction *deactivated*: every
    further statement on that session, including the next ``commit()``, is refused with
    ``PendingRollbackError``. The loop used to retry anyway, and because
    ``PendingRollbackError`` is not an ``OperationalError`` it escaped this ``except``
    entirely -- so a transient lock surfaced as an exception naming SQLAlchemy internals
    rather than as the lock it was. Found by the Phase 12 browser suite, where three
    audit-writing reads arrived at once (`PROJECT_STATUS.md` §27).

    Rolling back and retrying is **not** the alternative: the rollback discards the work
    the caller was committing, so the retry would succeed and write nothing. When the
    transaction is deactivated the honest answer is the original error.
    """
    for attempt in range(attempts):
        try:
            session.commit()
            return
        except OperationalError as exc:  # pragma: no cover - timing dependent
            locked = "database is locked" in str(exc).lower()
            # `is_active` is false once a flush has failed. Nothing further can be done
            # with this session but roll it back.
            deactivated = not session.is_active
            if not locked or deactivated or attempt == attempts - 1:
                session.rollback()
                raise
            time.sleep(base_delay * (2**attempt))


def run_unit_with_retry(session: Session, work, attempts: int = 4, base_delay: float = 0.05):
    """Run ``work()`` and commit it, re-running **the whole unit** on a SQLite lock.

    For writes that read a lot first (re-pricing a quote, issuing an invoice, approving a
    vendor bill). With explicit transactions (DEC-0108) such a unit holds its read snapshot
    from its first statement; if any other request commits meanwhile -- and every signed-in
    request records its session's last-seen time -- the unit's first write is refused with
    ``database is locked`` and the busy timeout cannot help, because the snapshot itself is
    stale. ``commit_with_retry`` cannot recover that: the failed flush has deactivated the
    session. Here the whole unit is rolled back and run again from the start, so it re-reads
    the current state and nothing half-done is ever committed. Any other error propagates
    unchanged (DEC-0204).
    """
    for attempt in range(attempts):
        try:
            result = work()
            session.commit()
            return result
        except OperationalError as exc:
            session.rollback()
            if "database is locked" not in str(exc).lower() or attempt == attempts - 1:
                raise
            time.sleep(base_delay * (2**attempt))
    raise RuntimeError("unreachable")  # pragma: no cover


#: The attribute a refusal carries when it wants a record of itself kept.
REFUSAL_AUDIT_ATTRIBUTE = "audit_refusal"


def persist_refusal_audit(session: Session, error: Exception) -> None:
    """Write a refused operation's audit row **after** its transaction has been discarded.

    The problem this solves. A service that audits a refusal by writing the row and then
    raising writes it into the transaction that is about to be rolled back, so the record
    of the refusal goes the same way the refusal's non-existent changes do. Every refusal
    audit in the Customer Account surface was doing this: the rows were written, and none
    of them survived (DEC-0111).

    Committing instead would be worse. A refusal raised halfway through an operation sits
    in a transaction that holds real work -- an idempotency claim, a proposal decision --
    and committing to save the audit row would commit that too.

    So the order here is **roll back, then write, then commit**, on the same session:

    1. ``rollback()`` discards every change the refused operation made and releases the
       writer lock, which is what makes the audit row the only thing in the transaction;
    2. the hook the exception carries writes exactly one row;
    3. ``commit_with_retry`` lands it.

    A refusal that carries no hook is left alone, which keeps this to the refusals somebody
    decided were worth a record rather than making it the default for every 409.
    """
    hook = getattr(error, REFUSAL_AUDIT_ATTRIBUTE, None)
    if hook is None:
        return
    session.rollback()
    hook(session)
    commit_with_retry(session)


def database_file() -> Path | None:
    return settings.sqlite_path
