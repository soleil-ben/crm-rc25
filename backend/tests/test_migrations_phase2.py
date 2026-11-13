"""The Phase 2 migration must apply to a clean database *and* to a Phase 1 database.

AC-20. The Phase 1 baseline migration is never edited, so an existing deployment upgrades
in place rather than being rebuilt, and rows written under Phase 1 survive the upgrade.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PHASE_1_REVISION = "b39203a50b1e"
PHASE_2_REVISION = "6b767a8a58fe"

PHASE_2_TABLES = {
    "booking_confirmations",
    "shipment_packages",
    "shipment_legs",
    "shipment_leg_packages",
    "leg_tracking_references",
    "shipment_events",
    "label_print_jobs",
    "label_print_job_packages",
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


def _columns(path: Path, table: str) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {row[1] for row in connection.execute(f"pragma table_info({table})")}
    finally:
        connection.close()


def test_migration_runs_on_a_clean_database(tmp_path):
    path = tmp_path / "clean.db"
    result = _alembic(f"sqlite:///{path.as_posix()}", "upgrade", "head")
    assert result.returncode == 0, result.stderr

    tables = _tables(path)
    assert tables >= PHASE_2_TABLES
    assert {"customers", "shipments", "saved_segments"} <= tables

    shipment_columns = _columns(path, "shipments")
    assert {
        "booking_reference",
        "sender_name",
        "sender_country_code",
        "recipient_name",
        "recipient_country_code",
        "recipient_delivery_note",
        "declared_value",
        "declared_value_currency",
        "rebooked_to_shipment_id",
        "cancelled_by_user_id",
        "confirmed_by_user_id",
    } <= shipment_columns


def test_migration_upgrades_a_phase_1_database_and_keeps_its_rows(tmp_path):
    path = tmp_path / "phase1.db"
    url = f"sqlite:///{path.as_posix()}"

    stepped = _alembic(url, "upgrade", PHASE_1_REVISION)
    assert stepped.returncode == 0, stepped.stderr
    assert PHASE_2_TABLES.isdisjoint(_tables(path))

    # Write a Phase 1 shaped row, exactly as a live deployment would already hold.
    connection = sqlite3.connect(path)
    connection.execute("pragma foreign_keys=on")
    connection.execute(
        """
        insert into customers (
            public_id, full_name, email_normalized, preferred_language, category,
            primary_shipping_purpose, shipping_frequency, do_not_contact, is_archived,
            is_demo_record, created_at, updated_at
        ) values (
            'CUS-000001', 'Nguyễn Thị Bích Hạnh', 'legacy@demo.example.com', 'vi',
            'individual', 'gifts_family_support', 'occasional', 0, 0, 0,
            '2026-01-05 10:00:00', '2026-01-05 10:00:00'
        )
        """
    )
    connection.execute(
        """
        insert into shipments (
            public_id, customer_id, route_group, booking_state, operational_state,
            payment_state, service_type, transport_mode, package_count,
            packages_delivered_count, is_return, is_demo_record, created_at, updated_at
        ) values (
            'SX-CAV-LEGACY123456', 1, 'CAV', 'confirmed', 'in_transit', 'unrecorded',
            'standard_parcel', 'air', 2, 1, 0, 0,
            '2026-01-06 10:00:00', '2026-01-06 10:00:00'
        )
        """
    )
    connection.commit()
    connection.close()

    upgraded = _alembic(url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    assert _tables(path) >= PHASE_2_TABLES
    columns = _columns(path, "shipments")
    assert "sender_name" in columns
    # The unused Phase 1 counter is replaced by a value derived from package rows.
    assert "packages_delivered_count" not in columns

    connection = sqlite3.connect(path)
    try:
        row = connection.execute(
            "select public_id, route_group, package_count, sender_name from shipments"
        ).fetchone()
        name = connection.execute("select full_name from customers").fetchone()[0]
    finally:
        connection.close()

    # The Phase 1 row survived, its identifier is unchanged, and the new columns are
    # simply empty rather than defaulted to something untrue.
    assert row == ("SX-CAV-LEGACY123456", "CAV", 2, None)
    assert name == "Nguyễn Thị Bích Hạnh"


def test_the_phase_1_baseline_migration_is_unmodified():
    """Phase 2 extends the schema through a new revision; it never edits the baseline."""
    baseline = (
        BACKEND_ROOT / "alembic" / "versions" / f"{PHASE_1_REVISION}_phase_1_baseline_schema.py"
    )
    assert baseline.exists()
    source = baseline.read_text(encoding="utf-8")
    assert f'revision: str = "{PHASE_1_REVISION}"' in source
    assert "down_revision: str | None = None" in source
    # None of the Phase 2 tables may appear in the Phase 1 baseline.
    for table in PHASE_2_TABLES:
        assert f'"{table}"' not in source


def test_the_phase_2_migration_chains_onto_phase_1():
    phase2 = next((BACKEND_ROOT / "alembic" / "versions").glob(f"{PHASE_2_REVISION}_*.py"))
    source = phase2.read_text(encoding="utf-8")
    assert f'down_revision: str | None = "{PHASE_1_REVISION}"' in source


def test_the_migration_downgrades_cleanly(tmp_path):
    path = tmp_path / "roundtrip.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", "head").returncode == 0

    # Downgrade to the Phase 1 revision by name rather than by ``-1``.
    #
    # This assertion is unchanged; only how the target is named. ``-1`` meant "the Phase 2
    # migration" for as long as Phase 2 was head, and stopped meaning it the moment
    # Phase 4A added a revision on top. Naming the revision says what this test is about
    # -- the Phase 2 migration reverses cleanly -- rather than depending on where the head
    # happens to be.
    down = _alembic(url, "downgrade", PHASE_1_REVISION)
    assert down.returncode == 0, down.stderr
    assert PHASE_2_TABLES.isdisjoint(_tables(path))
    assert "packages_delivered_count" in _columns(path, "shipments")

    up = _alembic(url, "upgrade", "head")
    assert up.returncode == 0, up.stderr
    assert _tables(path) >= PHASE_2_TABLES
