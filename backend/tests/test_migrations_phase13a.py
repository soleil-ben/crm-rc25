"""The Phase 13A migration: from empty, from a populated Phase 10 database, and back.

The migration adds twelve tables and touches nothing else. The populated-database test
builds a Phase 10 database with a customer, a shipment and its packages, upgrades it, and
checks every identifier is still there; the downgrade test checks the twelve tables are
gone and nothing else moved.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.test_migrations_phase10 import _write_phase_9_rows

BACKEND_ROOT = Path(__file__).resolve().parents[1]

PHASE_10_REVISION = "6af30fcdd3a8"
PHASE_13A_REVISION = "f53efaa7773e"

PHASE_13A_TABLES = {
    "vendors",
    "tariff_versions",
    "tariff_products",
    "tariff_rate_brackets",
    "tariff_zone_fsas",
    "tariff_beyond_postal_codes",
    "tariff_beyond_rates",
    "tariff_accessorials",
    "tariff_surcharge_rules",
    "tariff_surcharge_rule_tiers",
    "fx_rate_snapshots",
    "fx_sync_attempts",
}


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        env={
            "PATH": "",
            "SYSTEMROOT": "C:\\Windows",
            "DATABASE_URL": database_url,
            "SECRET_KEY": "test-only-secret",
            "ENVIRONMENT": "test",
        },
        capture_output=True,
        text=True,
    )


def _tables(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in connection.execute("select name from sqlite_master where type='table'")
        }
    finally:
        connection.close()


def _schema(path: Path) -> dict[str, str]:
    """Every table's and index's CREATE statement, except the twelve new ones."""
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            "select name, sql from sqlite_master where sql is not null order by name"
        ).fetchall()
    finally:
        connection.close()
    return {
        name: sql
        for name, sql in rows
        if not any(
            name == t or name.startswith(f"ix_{t}") or name.startswith(f"uq_{t}")
            for t in PHASE_13A_TABLES
        )
    }


def _row_counts(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(path)
    try:
        return {
            table: connection.execute(f"select count(*) from {table}").fetchone()[0]
            for table in sorted(_tables(path) - PHASE_13A_TABLES)
            if table != "alembic_version"
        }
    finally:
        connection.close()


def test_migration_runs_on_an_empty_database_and_is_in_the_chain(tmp_path):
    """Head moved past 13A (the customer-prefix migration a7c3e1d9b2f4), so this asserts the
    revision is reachable and that the schema at head still checks clean."""
    path = tmp_path / "empty.db"
    url = f"sqlite:///{path.as_posix()}"
    result = _alembic(url, "upgrade", PHASE_13A_REVISION)
    assert result.returncode == 0, result.stderr
    assert _tables(path) >= PHASE_13A_TABLES
    assert PHASE_13A_REVISION in _alembic(url, "current").stdout
    assert _alembic(url, "upgrade", "head").returncode == 0
    check = _alembic(url, "check")
    assert check.returncode == 0, check.stdout + check.stderr


def test_upgrading_a_populated_phase_10_database_keeps_its_rows_and_schema(tmp_path):
    path = tmp_path / "phase10.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", PHASE_10_REVISION).returncode == 0
    assert PHASE_13A_TABLES.isdisjoint(_tables(path))
    _write_phase_9_rows(path)  # the Phase 10 schema is the Phase 9 schema plus two tables
    before = _schema(path)
    counts_before = _row_counts(path)
    assert counts_before["customers"] >= 1 and counts_before["shipments"] >= 1

    upgraded = _alembic(url, "upgrade", PHASE_13A_REVISION)
    assert upgraded.returncode == 0, upgraded.stderr

    assert _tables(path) >= PHASE_13A_TABLES
    assert _schema(path) == before, "the migration changed a pre-existing table or index"
    assert _row_counts(path) == counts_before, "a pre-existing row was lost or added"
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("pragma integrity_check").fetchone()[0] == "ok"
        assert connection.execute("pragma foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_downgrade_removes_exactly_the_twelve_tables(tmp_path):
    path = tmp_path / "down.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", PHASE_13A_REVISION).returncode == 0
    with_tables = _tables(path)
    down = _alembic(url, "downgrade", PHASE_10_REVISION)
    assert down.returncode == 0, down.stderr
    assert _tables(path) == with_tables - PHASE_13A_TABLES
    assert PHASE_10_REVISION in _alembic(url, "current").stdout
    up = _alembic(url, "upgrade", PHASE_13A_REVISION)
    assert up.returncode == 0, up.stderr
    assert _tables(path) == with_tables


def test_every_new_foreign_key_declares_its_target_and_deletion_behaviour(tmp_path):
    path = tmp_path / "fk.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", "head").returncode == 0
    connection = sqlite3.connect(path)
    try:
        for table in PHASE_13A_TABLES:
            for row in connection.execute(f"pragma foreign_key_list({table})"):
                target, on_delete = row[2], row[6]
                assert target in PHASE_13A_TABLES or target == "users", (table, target)
                # Declared on every key, as in Phase 10: a version's children cascade, a
                # user or snapshot reference is set to NULL, a vendor is protected.
                assert on_delete in {"CASCADE", "SET NULL", "RESTRICT"}, (table, target, on_delete)
                if target in {"users", "fx_rate_snapshots"}:
                    assert on_delete == "SET NULL", (table, target)
                elif target == "vendors":
                    assert on_delete == "RESTRICT", (table, target)
                else:
                    assert on_delete == "CASCADE", (table, target)
    finally:
        connection.close()
