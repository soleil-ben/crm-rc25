"""The Phase 13B migration: six new tables and nothing else, from empty and from a populated database."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.test_migrations_phase10 import _write_phase_9_rows

BACKEND_ROOT = Path(__file__).resolve().parents[1]

PREFIX_REVISION = "a7c3e1d9b2f4"
PHASE_13B_REVISION = "b8d4f2a6c1e7"

PHASE_13B_TABLES = {
    "consolidations",
    "consolidation_memberships",
    "shipment_items",
    "service_vendor_products",
    "shipment_payers",
    "consolidation_event_links",
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
            r[0] for r in connection.execute("select name from sqlite_master where type='table'")
        }
    finally:
        connection.close()


def _columns(path: Path, table: str) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        return [r[1] for r in connection.execute(f"pragma table_info({table})")]
    finally:
        connection.close()


def _existing_schema(path: Path) -> dict[str, str]:
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            "select name, sql from sqlite_master where sql is not null"
        ).fetchall()
    finally:
        connection.close()
    return {
        name: sql
        for name, sql in rows
        if not any(name == t or name.startswith((f"ix_{t}", f"uq_{t}")) for t in PHASE_13B_TABLES)
    }


def _row_counts(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(path)
    try:
        return {
            t: connection.execute(f"select count(*) from {t}").fetchone()[0]
            for t in sorted(_tables(path) - PHASE_13B_TABLES)
            if t != "alembic_version"
        }
    finally:
        connection.close()


def test_runs_from_empty_is_the_head_and_checks_clean(tmp_path):
    """Head moved past 13B (Phase 13C pricing tables); this upgrades to 13B by revision and
    checks the schema at head separately below."""
    path = tmp_path / "empty.db"
    url = f"sqlite:///{path.as_posix()}"
    result = _alembic(url, "upgrade", PHASE_13B_REVISION)
    assert result.returncode == 0, result.stderr
    assert _tables(path) >= PHASE_13B_TABLES
    assert PHASE_13B_REVISION in _alembic(url, "current").stdout
    assert _alembic(url, "upgrade", "head").returncode == 0
    check = _alembic(url, "check")
    assert check.returncode == 0, check.stdout + check.stderr


def test_the_partial_unique_index_allows_history_but_one_active_membership(tmp_path):
    path = tmp_path / "partial.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", PHASE_13B_REVISION).returncode == 0
    connection = sqlite3.connect(path)
    try:
        sql = connection.execute(
            "select sql from sqlite_master where name='uq_consolidation_memberships_active_shipment'"
        ).fetchone()[0]
        assert "removed_at IS NULL" in sql and "UNIQUE" in sql.upper()
        connection.execute("pragma foreign_keys=off")
        connection.execute(
            "insert into consolidation_memberships (consolidation_id, shipment_id, added_at, removed_at) "
            "values (1, 7, '2026-10-01', '2026-10-02')"
        )
        connection.execute(
            "insert into consolidation_memberships (consolidation_id, shipment_id, added_at, removed_at) "
            "values (2, 7, '2026-10-02', NULL)"
        )
        try:
            connection.execute(
                "insert into consolidation_memberships (consolidation_id, shipment_id, added_at, removed_at) "
                "values (3, 7, '2026-10-03', NULL)"
            )
        except sqlite3.IntegrityError as error:
            assert "UNIQUE" in str(error).upper()
        else:
            raise AssertionError("a second active membership for one shipment was accepted")
    finally:
        connection.close()


def test_a_populated_database_upgrades_in_place_and_downgrades_back(tmp_path):
    path = tmp_path / "populated.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", PREFIX_REVISION).returncode == 0
    _write_phase_9_rows(path)
    counts_before = _row_counts(path)
    schema_before = _existing_schema(path)

    upgraded = _alembic(url, "upgrade", PHASE_13B_REVISION)
    assert upgraded.returncode == 0, upgraded.stderr
    assert _row_counts(path) == counts_before
    assert _existing_schema(path) == schema_before, "the migration altered an existing table"
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("pragma integrity_check").fetchone()[0] == "ok"
        assert connection.execute("pragma foreign_key_check").fetchall() == []
    finally:
        connection.close()

    down = _alembic(url, "downgrade", PREFIX_REVISION)
    assert down.returncode == 0, down.stderr
    assert PHASE_13B_TABLES.isdisjoint(_tables(path))
    assert _existing_schema(path) == schema_before
    assert _row_counts(path) == counts_before
    assert _alembic(url, "upgrade", PHASE_13B_REVISION).returncode == 0


def test_every_new_foreign_key_declares_its_deletion_behaviour(tmp_path):
    path = tmp_path / "fk.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", PHASE_13B_REVISION).returncode == 0
    connection = sqlite3.connect(path)
    try:
        for table in PHASE_13B_TABLES:
            for row in connection.execute(f"pragma foreign_key_list({table})"):
                target, on_delete = row[2], row[6]
                if target == "vendors":
                    assert on_delete == "RESTRICT", (table, target)
                elif (
                    target in {"users", "tariff_versions", "tariff_products", "shipment_packages"}
                    and table != "service_vendor_products"
                ):
                    assert on_delete == "SET NULL", (table, target)
                else:
                    assert on_delete == "CASCADE", (table, target)
    finally:
        connection.close()


def test_the_upgrade_backfills_the_service_mapping_for_existing_tariff_versions(tmp_path):
    """A tariff imported under Phase 13A has no mapping rows; the migration writes them."""
    path = tmp_path / "backfill.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", PREFIX_REVISION).returncode == 0
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "insert into vendors (key, name, is_active, created_at, updated_at) "
            "values ('kango', 'Kango', 1, '2026-10-12', '2026-10-12')"
        )
        connection.execute(
            "insert into tariff_versions (public_id, vendor_id, label, source_sha256, effective_from, "
            "status, imported_at, dim_divisor_default, cost_currency, import_report_json, created_at, updated_at) "
            "values ('TRF-000001', 1, 'v1', 'abc', '2026-10-12', 'active', '2026-10-12', 6000, 'VND', '{}', "
            "'2026-10-12', '2026-10-12')"
        )
        for origin, code, last_mile in (
            ("HCM", "AIR-CAD", "purolator_ground"),
            ("HCM", "AIR-CAD EXPRESS", "purolator_express"),
            ("HAN", "AIR-CAD", "purolator_ground"),
            ("HAN", "KSN-SEA-CAD-PURO", "purolator_ground"),
        ):
            connection.execute(
                "insert into tariff_products (version_id, code, origin, mode, last_mile, dim_divisor, "
                "customs_surcharges_waived, source_sheet, created_at, updated_at) values "
                "(1, ?, ?, 'air', ?, 6000, 0, 'x', '2026-10-12', '2026-10-12')",
                (code, origin, last_mile),
            )
        connection.commit()
    finally:
        connection.close()

    upgraded = _alembic(url, "upgrade", PHASE_13B_REVISION)
    assert upgraded.returncode == 0, upgraded.stderr
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            "select solaris_service, origin from service_vendor_products order by 1, 2"
        ).fetchall()
    finally:
        connection.close()
    # Express exists for HCM only in this fixture; sea is never mapped.
    assert rows == [("air_express", "HCM"), ("air_standard", "HAN"), ("air_standard", "HCM")]
