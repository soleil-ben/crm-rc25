"""The Phase 13C migration: five new tables, nothing else, from empty and from a populated database."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.test_migrations_phase10 import _write_phase_9_rows

BACKEND_ROOT = Path(__file__).resolve().parents[1]

PHASE_13B_REVISION = "b8d4f2a6c1e7"
PHASE_13C_REVISION = "c9e5a3b7d2f8"
PHASE_13C_TABLES = {
    "pricing_settings",
    "surcharge_rule_policies",
    "shipment_fee_lines",
    "quote_versions",
    "quote_lines",
    "consolidation_cartons",
}


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        env={
            "PATH": "",
            "SYSTEMROOT": r"C:\Windows",
            "DATABASE_URL": database_url,
            "SECRET_KEY": "test-only-secret",
            "ENVIRONMENT": "test",
        },
        capture_output=True,
        text=True,
    )


def _tables(path: Path) -> set[str]:
    with sqlite3.connect(path) as c:
        return {r[0] for r in c.execute("select name from sqlite_master where type='table'")}


def _existing_schema(path: Path) -> dict[str, str]:
    with sqlite3.connect(path) as c:
        rows = c.execute("select name, sql from sqlite_master where sql is not null").fetchall()
    return {
        name: sql
        for name, sql in rows
        if not any(name == t or name.startswith((f"ix_{t}", f"uq_{t}")) for t in PHASE_13C_TABLES)
    }


def _row_counts(path: Path) -> dict[str, int]:
    with sqlite3.connect(path) as c:
        return {
            t: c.execute(f"select count(*) from {t}").fetchone()[0]
            for t in sorted(_tables(path) - PHASE_13C_TABLES)
            if t != "alembic_version"
        }


def test_upgrades_an_empty_database_to_phase_13c(tmp_path):
    # Phase 13E moved the head on; `alembic check` at head lives in its own test.
    url = f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"
    assert _alembic(url, "upgrade", PHASE_13C_REVISION).returncode == 0
    assert PHASE_13C_REVISION in _alembic(url, "current").stdout
    assert _tables(tmp_path / "empty.db") >= PHASE_13C_TABLES


def test_a_populated_database_upgrades_in_place_and_downgrades_back(tmp_path):
    path = tmp_path / "populated.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", PHASE_13B_REVISION).returncode == 0
    _write_phase_9_rows(path)
    counts, schema = _row_counts(path), _existing_schema(path)
    upgraded = _alembic(url, "upgrade", PHASE_13C_REVISION)
    assert upgraded.returncode == 0, upgraded.stderr
    assert _row_counts(path) == counts
    assert _existing_schema(path) == schema, "the migration altered an existing table"
    with sqlite3.connect(path) as c:
        assert c.execute("pragma integrity_check").fetchone()[0] == "ok"
        assert c.execute("pragma foreign_key_check").fetchall() == []
    assert _alembic(url, "downgrade", PHASE_13B_REVISION).returncode == 0
    assert PHASE_13C_TABLES.isdisjoint(_tables(path))
    assert _row_counts(path) == counts and _existing_schema(path) == schema


def test_deletion_behaviour_and_the_two_partial_indexes(tmp_path):
    path = tmp_path / "fk.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", PHASE_13C_REVISION).returncode == 0
    with sqlite3.connect(path) as c:
        fks = {
            (t, r[3]): (r[2], r[6])
            for t in PHASE_13C_TABLES
            for r in c.execute(f"pragma foreign_key_list({t})")
        }
        for name in ("uq_shipment_fee_lines_active_item_rule", "uq_quote_versions_open_draft"):
            sql = c.execute("select sql from sqlite_master where name = ?", (name,)).fetchone()[0]
            assert "UNIQUE" in sql.upper() and "WHERE" in sql.upper(), name
    assert fks[("quote_versions", "shipment_id")] == ("shipments", "RESTRICT")
    assert fks[("quote_lines", "version_id")] == ("quote_versions", "CASCADE")
    assert fks[("shipment_fee_lines", "shipment_id")] == ("shipments", "CASCADE")
    assert fks[("consolidation_cartons", "consolidation_id")] == ("consolidations", "CASCADE")
    assert all(on_delete in {"CASCADE", "SET NULL", "RESTRICT"} for _t, on_delete in fks.values())
