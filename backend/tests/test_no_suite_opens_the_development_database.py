"""The test suite must not open the development database. Asserted, not assumed.

Found on 2026-09-21, while confirming that it did not.

``app/core/db.py`` builds its module-level engine from ``settings.database_url`` at import
time. ``conftest.py`` set ``ENVIRONMENT=test`` and left ``DATABASE_URL`` alone, so that
default was ``data/solaris_crm.db`` -- and every ``TestClient(app)`` runs the lifespan,
whose readiness check queries that engine. The suite connected to the real development
database once per app startup, several thousand times a run.

Nothing was ever written: two ``SELECT``s and a ``PRAGMA journal_mode=WAL`` against a
database already in WAL, and the file's SHA-256 was byte-identical before and after a full
validation pass. It was still an automated suite opening the development database, which is
the shape of the incident that produced ``app.core.e2e_guard`` in the first place --
and ``test_e2e_safety.py`` was asserting the file did not *change* while this quietly made
it the thing being read.

What makes it worth a file of its own is how it hid. ``test_phase5b_startup_and_health.py``
asserts ``/health/ready`` reports ready, and that assertion passed *because* the engine was
reading a database that really was migrated. The health check was being proved correct
against production-shaped data nobody meant to involve. Point the engine at an empty file
and that test fails -- which is why ``conftest.module_engine_database`` creates a schema and
stamps the head, so the check answers for a real reason.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import event

from app.core import e2e_guard
from app.core.config import settings
from app.core.db import engine


def _resolved(url: str) -> Path | None:
    path = e2e_guard.sqlite_path_from_url(url)
    return e2e_guard.canonical(path) if path else None


DEV_DB = e2e_guard.canonical(e2e_guard.DEV_DB)
UAT_DB = e2e_guard.canonical(e2e_guard.UAT_DIR / "solaris_uat.uat.db")


class TestWhereTheModuleEngineIsPointed:
    def test_it_is_not_the_development_database(self):
        assert _resolved(str(engine.url)) != DEV_DB

    def test_it_is_not_the_uat_database(self):
        assert _resolved(str(engine.url)) != UAT_DB

    def test_the_settings_agree(self):
        assert _resolved(settings.database_url) != DEV_DB

    def test_it_is_outside_the_repository(self):
        """A temporary directory, so a stray file cannot land in the working tree."""
        resolved = _resolved(str(engine.url))
        assert resolved is not None
        assert not e2e_guard.is_within(resolved, e2e_guard.canonical(e2e_guard.REPO_ROOT))

    def test_the_environment_variable_is_what_does_it(self):
        """Set in `conftest.py` before any app import, because the engine is built then."""
        assert os.environ.get("DATABASE_URL")
        assert _resolved(os.environ["DATABASE_URL"]) == _resolved(str(engine.url))


class TestNothingReachesTheDevelopmentDatabase:
    def test_starting_the_app_opens_no_connection_to_it(self, client):
        """The `client` fixture runs the lifespan; nothing it does may touch the real file.

        Asserted by listening on the engine rather than by inspecting its URL, so a future
        change that opened a *second* connection to the development database would fail
        here even if the configured URL still looked right.
        """
        opened: list[str] = []

        @event.listens_for(engine, "connect")
        def _record(dbapi_connection, _record):  # noqa: ANN001
            url = str(engine.url)
            if _resolved(url) == DEV_DB:
                opened.append(url)

        try:
            assert client.get("/health/ready").status_code == 200
        finally:
            event.remove(engine, "connect", _record)

        assert opened == []

    def test_readiness_still_answers_for_a_real_reason(self, client):
        """It reports ready because *this* database is reachable and at head, not the real one."""
        body = client.get("/health/ready").json()
        assert body["status"] == "ready"
        assert body["checks"]["database"] == "ok"
        assert body["checks"]["migrations"] == "ok"


class TestTheDevelopmentDatabaseIsUntouched:
    """Belt and braces: the file's modification time must not move during the run."""

    def test_its_mtime_has_not_changed(self):
        """Holds whether or not the file exists: absent at import, absent now."""
        assert _mtime_or_none(DEV_DB) == _DEV_DB_MTIME_AT_IMPORT


def _mtime_or_none(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


_DEV_DB_MTIME_AT_IMPORT = _mtime_or_none(DEV_DB)
