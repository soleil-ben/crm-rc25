"""The Phase 13F migration: two new tables, nothing else; the head, and it checks clean."""

from __future__ import annotations

import sqlite3

from tests.test_migrations_phase10 import _write_phase_9_rows
from tests.test_migrations_phase13c import _alembic, _tables

OWNER_ANSWERS_REVISION = "e4a7c2d9f1b3"
PHASE_13F_REVISION = "f2b8d5a1c7e4"
PHASE_13F_TABLES = {"notification_preferences", "notification_outbox"}


MARKUP_REVISION = "a3c9e7f1b5d2"
#: RC-UAT-20 (owner answers of 2026-10-23: GST/HST by route, the costume-jewellery customer
#: price) revises RC-UAT-19's e6b1c4a8d2f3. RC-UAT-22's orphaned-account re-link table
#: (B-13) revises RC-UAT-21's c3e5a7b9d2f4; RC-UAT-24's legal-entity rename (data only) revises it;
#: RC-UAT-25's two new tables (Admin sign-in email changes, timeline event edits) revise that and
#: are followed by the method v0.5 pricing tables (b8d1f3a5c7e9), v0.5 on by default
#: (c2e4a6b8d0f1), method v0.6 (d4f6a8c0e2b4), method v0.7 (e6a8c0e2b4d6) and the
#: version-neutral switch (f8b0d2e4a6c8), then the tariff approver grant (a1b3c5d7e9f2), the head.
HEAD_REVISION = "b2c4d6e8f0a1"


def test_is_the_head_and_checks_clean(tmp_path):
    url = f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"
    assert _alembic(url, "upgrade", "head").returncode == 0
    assert HEAD_REVISION in _alembic(url, "current").stdout
    assert "markup_defaults" in _tables(tmp_path / "empty.db")
    assert _tables(tmp_path / "empty.db") >= PHASE_13F_TABLES
    check = _alembic(url, "check")
    assert check.returncode == 0, check.stdout + check.stderr


def test_a_populated_database_upgrades_and_downgrades_without_touching_existing_rows(tmp_path):
    path = tmp_path / "populated.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", OWNER_ANSWERS_REVISION).returncode == 0
    _write_phase_9_rows(path)
    with sqlite3.connect(path) as c:
        before = {
            t: c.execute(f"select count(*) from {t}").fetchone()[0]  # noqa: S608
            for t in _tables(path)
            if t != "alembic_version"
        }
    assert _alembic(url, "upgrade", PHASE_13F_REVISION).returncode == 0
    with sqlite3.connect(path) as c:
        assert c.execute("pragma integrity_check").fetchone()[0] == "ok"
        for table, count in before.items():
            assert c.execute(f"select count(*) from {table}").fetchone()[0] == count  # noqa: S608
        fks = {
            r[3]: (r[2], r[6]) for r in c.execute("pragma foreign_key_list(notification_outbox)")
        }
    assert fks["shipment_id"] == ("shipments", "CASCADE")
    assert fks["customer_id"] == ("customers", "SET NULL")
    assert _alembic(url, "downgrade", OWNER_ANSWERS_REVISION).returncode == 0
    assert PHASE_13F_TABLES.isdisjoint(_tables(path))
