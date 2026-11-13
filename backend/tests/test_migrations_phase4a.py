"""The Phase 4A migration: from empty, from a populated Phase 3 database, and back.

AC-20 and the Phase 4A requirement that Phases 1 to 3 are *extended*, never rewritten. The
baseline and Phase 2 migrations are untouched, so an existing deployment upgrades in place
and its rows survive.

The interesting one is ``test_migration_upgrades_a_populated_phase_3_database``. A Phase 3
database is a Phase 2 database -- Phase 3 added no migration, because the public surface is
a read path over the existing schema -- so the fixture writes the rows a live deployment
would already hold and checks they are intact afterwards, identifiers included.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

PHASE_1_REVISION = "b39203a50b1e"
PHASE_2_REVISION = "6b767a8a58fe"
PHASE_4A_REVISION = "9d7dc78dd25c"

PHASE_4A_TABLES = {
    "integration_connections",
    "integration_webhook_inbox",
    "integration_provider_events",
    "integration_jobs",
    "integration_worker_heartbeats",
}

#: Tables Phase 4A must not touch. If any of these changes, the migration has stopped
#: being additive and an existing deployment is at risk.
PRESERVED_TABLES = {
    "customers",
    "shipments",
    "shipment_packages",
    "shipment_legs",
    "shipment_events",
    "leg_tracking_references",
    "booking_confirmations",
    "label_print_jobs",
    "saved_segments",
    "consent_events",
    "contact_suppressions",
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


def _indexes(path: Path, table: str) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {row[1] for row in connection.execute(f"pragma index_list({table})")}
    finally:
        connection.close()


def _write_phase_3_rows(path: Path) -> None:
    """The rows a live Phase 3 deployment would already hold.

    Written as raw SQL rather than through the services, deliberately: this fixture has to
    represent a database written by the *previous* revision, and going through today's
    models would be writing today's schema.
    """
    connection = sqlite3.connect(path)
    connection.execute("pragma foreign_keys=on")
    connection.execute(
        """
        insert into customers (
            public_id, full_name, email_normalized, preferred_language, category,
            primary_shipping_purpose, shipping_frequency, do_not_contact, is_archived,
            is_demo_record, created_at, updated_at
        ) values (
            'CUS-000001', 'Nguyễn Thị Bích Hạnh', 'hanh@demo.example.com', 'vi',
            'individual', 'gifts_family_support', 'occasional', 0, 0, 0,
            '2026-01-05 10:00:00', '2026-01-05 10:00:00'
        )
        """
    )
    connection.execute(
        """
        insert into shipments (
            public_id, customer_id, route_group, booking_state, operational_state,
            payment_state, service_type, transport_mode, package_count, is_return,
            is_demo_record, sender_name, recipient_name, created_at, updated_at
        ) values (
            'SX-CAV-7K9D2M4R8T6W', 1, 'CAV', 'confirmed', 'in_transit', 'unrecorded',
            'standard_parcel', 'air', 2, 0, 0, 'Tran Quoc Tuan',
            'Nguyễn Thị Bích Hạnh', '2026-01-06 10:00:00', '2026-01-06 10:00:00'
        )
        """
    )
    for sequence in (1, 2):
        connection.execute(
            """
            insert into shipment_packages (
                shipment_id, sequence, package_reference, is_active, dimension_unit,
                weight_unit, operational_state, created_at, updated_at
            ) values (?, ?, ?, 1, 'cm', 'kg', 'in_transit',
                      '2026-01-06 10:00:00', '2026-01-06 10:00:00')
            """,
            (1, sequence, f"SX-CAV-7K9D2M4R8T6W-0{sequence}"),
        )
    connection.execute(
        """
        insert into shipment_legs (
            shipment_id, sequence, leg_type, is_final_recipient_delivery, status,
            created_at, updated_at
        ) values (1, 1, 'final_delivery', 1, 'planned',
                  '2026-01-06 10:00:00', '2026-01-06 10:00:00')
        """
    )
    connection.execute(
        """
        insert into leg_tracking_references (
            leg_id, carrier_name, tracking_number, source_mode, is_active,
            created_at, updated_at
        ) values (1, 'Other', 'LEGACY-TRACK-1', 'manual', 1,
                  '2026-01-06 10:00:00', '2026-01-06 10:00:00')
        """
    )
    connection.execute(
        """
        insert into shipment_events (
            shipment_id, package_id, event_type, operational_state, occurred_at,
            recorded_at, is_public_update, public_update_text,
            is_final_recipient_delivery, source, is_voided
        ) values (1, 1, 'in_transit', 'in_transit', '2026-01-07 09:00:00',
                  '2026-01-07 09:05:00', 1, 'On its way to Vietnam', 0, 'manual', 0)
        """
    )
    connection.commit()
    connection.close()


# --- From empty -------------------------------------------------------------


def test_migration_runs_on_an_empty_database(tmp_path):
    path = tmp_path / "empty.db"
    result = _alembic(f"sqlite:///{path.as_posix()}", "upgrade", "head")
    assert result.returncode == 0, result.stderr

    tables = _tables(path)
    assert tables >= PHASE_4A_TABLES
    assert tables >= PRESERVED_TABLES


def test_the_new_tables_carry_the_columns_the_design_requires(tmp_path):
    """A checklist against the schema, so a missing column fails here rather than later."""
    path = tmp_path / "columns.db"
    assert _alembic(f"sqlite:///{path.as_posix()}", "upgrade", "head").returncode == 0

    inbox = _columns(path, "integration_webhook_inbox")
    assert {
        "provider_key",
        "provider_api_version",
        "connection_key",
        "received_at",
        "content_type",
        "payload_bytes",
        "payload_text",
        "payload_omitted",
        "payload_sha256",
        "provider_event_id",
        "payload_fingerprint",
        "dedupe_key",
        "dedupe_basis",
        "verification_state",
        "processing_state",
        "attempt_count",
        "next_attempt_at",
        "processed_at",
        "rejected_at",
        "failed_at",
        "error_code",
        "error_summary",
        "lease_owner",
        "lease_token",
        "lease_expires_at",
        "created_at",
        "updated_at",
    } <= inbox

    job = _columns(path, "integration_jobs")
    assert {
        "job_type",
        "provider_key",
        "connection_key",
        "tracking_assignment_id",
        "inbox_item_id",
        "shipment_id",
        "status",
        "available_at",
        "attempt_count",
        "max_attempts",
        "priority",
        "dedupe_key",
        "active_dedupe_key",
        "lease_owner",
        "lease_token",
        "lease_expires_at",
        "last_attempt_at",
        "next_retry_at",
        "provider_retry_after_seconds",
        "error_code",
        "error_summary",
        "completed_at",
        "failed_at",
        "requires_review",
        "created_at",
        "updated_at",
    } <= job

    event = _columns(path, "integration_provider_events")
    assert {
        "provider_key",
        "provider_api_version",
        "provider_event_id",
        "provider_event_fingerprint",
        "tracking_assignment_id",
        "shipment_id",
        "package_id",
        "leg_id",
        "raw_status",
        "raw_status_detail",
        "normalized_event_type",
        "normalized_state",
        "occurred_at",
        "occurred_at_timezone",
        "occurred_time_provenance",
        "received_at",
        "verification_source",
        "mapping_version",
        "inbox_item_id",
        "applied_shipment_event_id",
        "corrects_event_id",
        "is_voided",
    } <= event


def test_no_new_table_carries_a_credential_column(tmp_path):
    """Structural, in the schema itself rather than only in the model.

    ``credential_ref`` is the one name that survives, and it holds the *name* of an
    environment variable rather than its value.
    """
    path = tmp_path / "secrets.db"
    assert _alembic(f"sqlite:///{path.as_posix()}", "upgrade", "head").returncode == 0

    allowed = {"credential_ref", "lease_token", "lease_owner", "lease_expires_at"}
    for table in PHASE_4A_TABLES:
        for column in _columns(path, table) - allowed:
            for forbidden in (
                "api_key",
                "apikey",
                "password",
                "authorization",
                "cookie",
                "secret",
                "token",
                "signature",
            ):
                assert forbidden not in column, f"{table}.{column}"


def _table_sql(path: Path, table: str) -> str:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute(
            "select sql from sqlite_master where type='table' and name=?", (table,)
        ).fetchone()
        return row[0] if row else ""
    finally:
        connection.close()


def test_the_deduplication_constraints_are_named_in_the_schema(tmp_path):
    """Deduplication is a database guarantee, so it has to be a database object.

    Checked in the ``CREATE TABLE`` text rather than through ``pragma index_list``: SQLite
    renders a table-level ``UNIQUE`` declared inline as an *auto-index*
    (``sqlite_autoindex_...``), so the constraint is enforced but its name never appears in
    the index list. Reading the DDL is what makes the name assertable, and the test below
    is what makes the enforcement assertable.
    """
    path = tmp_path / "constraints.db"
    assert _alembic(f"sqlite:///{path.as_posix()}", "upgrade", "head").returncode == 0

    assert "uq_integration_webhook_inbox_dedupe" in _table_sql(path, "integration_webhook_inbox")
    assert "uq_integration_jobs_active_dedupe_key" in _table_sql(path, "integration_jobs")
    assert "uq_integration_provider_events_fingerprint" in _table_sql(
        path, "integration_provider_events"
    )


def test_the_deduplication_constraints_are_enforced(tmp_path):
    """The behaviour, which is what actually matters. Two identical keys, one row."""
    path = tmp_path / "enforced.db"
    assert _alembic(f"sqlite:///{path.as_posix()}", "upgrade", "head").returncode == 0

    connection = sqlite3.connect(path)
    try:
        insert = """
            insert into integration_webhook_inbox (
                provider_key, connection_key, received_at, payload_bytes, payload_omitted,
                payload_sha256, payload_fingerprint, dedupe_key, dedupe_basis,
                verification_state, processing_state, attempt_count, created_at, updated_at
            ) values ('fake', 'unassigned', '2026-09-01 09:00:00', 10, 0,
                      'a' , 'f', 'event-1', 'provider_event_id', 'pending', 'pending', 0,
                      '2026-09-01 09:00:00', '2026-09-01 09:00:00')
        """
        connection.execute(insert)
        connection.commit()

        try:
            connection.execute(insert)
            connection.commit()
            raise AssertionError("a duplicate dedupe_key was accepted")
        except sqlite3.IntegrityError:
            pass

        # A NULL active_dedupe_key must not collide, or completed jobs would block
        # every later refresh.
        job_insert = """
            insert into integration_jobs (
                job_type, provider_key, connection_key, status, available_at,
                attempt_count, max_attempts, priority, active_dedupe_key,
                requires_review, manual_retry_count, created_at, updated_at
            ) values ('refresh_tracking_assignment', 'fake', 'unassigned', 'succeeded',
                      '2026-09-01 09:00:00', 1, 5, 100, NULL, 0, 0,
                      '2026-09-01 09:00:00', '2026-09-01 09:00:00')
        """
        connection.execute(job_insert)
        connection.execute(job_insert)
        connection.commit()
        completed = connection.execute(
            "select count(*) from integration_jobs where active_dedupe_key is null"
        ).fetchone()[0]
        assert completed == 2
    finally:
        connection.close()


def test_foreign_keys_are_enforced_on_the_new_tables(tmp_path):
    """SQLite enforces foreign keys per connection, so this checks a live one."""
    path = tmp_path / "fk.db"
    assert _alembic(f"sqlite:///{path.as_posix()}", "upgrade", "head").returncode == 0

    connection = sqlite3.connect(path)
    try:
        connection.execute("pragma foreign_keys=on")
        assert connection.execute("pragma foreign_keys").fetchone()[0] == 1

        try:
            connection.execute(
                """
                insert into integration_jobs (
                    job_type, provider_key, connection_key, tracking_assignment_id,
                    status, available_at, attempt_count, max_attempts, priority,
                    requires_review, manual_retry_count, created_at, updated_at
                ) values ('refresh_tracking_assignment', 'fake', 'unassigned', 999999,
                          'pending', '2026-09-01 09:00:00', 0, 5, 100, 0, 0,
                          '2026-09-01 09:00:00', '2026-09-01 09:00:00')
                """
            )
            connection.commit()
            raise AssertionError("a job naming a missing tracking assignment was accepted")
        except sqlite3.IntegrityError:
            pass
    finally:
        connection.close()


# --- From a populated Phase 3 database ---------------------------------------


def test_migration_upgrades_a_populated_phase_3_database_and_keeps_its_rows(tmp_path):
    """The upgrade an existing deployment would actually perform.

    Phase 3 added no migration, so a Phase 3 database is at the Phase 2 revision. Its rows
    -- customer, shipment, packages, leg, tracking reference, and a published event -- must
    all survive, with every identifier unchanged.
    """
    path = tmp_path / "phase3.db"
    url = f"sqlite:///{path.as_posix()}"

    assert _alembic(url, "upgrade", PHASE_2_REVISION).returncode == 0
    assert PHASE_4A_TABLES.isdisjoint(_tables(path))
    _write_phase_3_rows(path)

    upgraded = _alembic(url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    assert _tables(path) >= PHASE_4A_TABLES

    connection = sqlite3.connect(path)
    try:
        shipment = connection.execute(
            "select public_id, route_group, operational_state, package_count from shipments"
        ).fetchone()
        packages = [
            row[0]
            for row in connection.execute(
                "select package_reference from shipment_packages order by sequence"
            )
        ]
        customer = connection.execute("select public_id, full_name from customers").fetchone()
        reference = connection.execute(
            "select tracking_number, source_mode, is_active from leg_tracking_references"
        ).fetchone()
        event = connection.execute(
            "select event_type, source, public_update_text from shipment_events"
        ).fetchone()
        integrity = connection.execute("pragma integrity_check").fetchone()[0]
        foreign_keys = connection.execute("pragma foreign_key_check").fetchall()
    finally:
        connection.close()

    # Identifiers never change (CRM.md section 6) -- with one recorded exception: the customer
    # prefix was renamed CUS- -> STCA- by a7c3e1d9b2f4 (OD-42, DEC-0174) while no production
    # customer existed, and the former identifier is kept as an alias.
    assert shipment == ("SX-CAV-7K9D2M4R8T6W", "CAV", "in_transit", 2)
    assert packages == ["SX-CAV-7K9D2M4R8T6W-01", "SX-CAV-7K9D2M4R8T6W-02"]
    assert customer == ("STCA-000001", "Nguyễn Thị Bích Hạnh")
    assert reference == ("LEGACY-TRACK-1", "manual", 1)
    assert event == ("in_transit", "manual", "On its way to Vietnam")
    assert integrity == "ok"
    assert foreign_keys == []


#: Columns added to a pre-existing table since Phase 2, each one a decision somebody had to
#: argue for. The guard below allows exactly these and nothing else, so a column added by
#: accident -- or a "small" schema change nobody reviewed -- still fails the build.
INTENTIONAL_COLUMN_ADDITIONS = {
    # Phase 5A1: a public milestone stores an approved template key instead of a typed
    # sentence, so the tracking page can render it in the customer's own language
    # (DEC-0084). Nullable, no backfill, dropped cleanly on downgrade.
    "shipment_events": {"public_update_template_key"},
    # Phase 10. The two of the three gaps `FIELD_MATRIX.md` section 6 names that needed a
    # column: the registered name and the preferred name, both nullable, both undefaulted,
    # both unbackfilled, and neither feeding a match key. The third gap needed no column at
    # all -- a billing address is a fourth `AddressRole` member (DEC-0101).
    "customers": {"legal_name", "display_name"},
}


def test_the_upgrade_adds_no_unplanned_column_to_an_existing_table(tmp_path):
    """Additive means additive.

    Phase 4A added no column to any Phase 2 table at all. Phase 5A1 adds exactly one, and
    it is named here rather than waved through: the value of this test is that the set of
    changes to established tables stays small enough to enumerate.
    """
    before_path = tmp_path / "before.db"
    after_path = tmp_path / "after.db"
    assert (
        _alembic(f"sqlite:///{before_path.as_posix()}", "upgrade", PHASE_2_REVISION).returncode == 0
    )
    assert _alembic(f"sqlite:///{after_path.as_posix()}", "upgrade", "head").returncode == 0

    for table in sorted(PRESERVED_TABLES):
        before = _columns(before_path, table)
        after = _columns(after_path, table)
        allowed = INTENTIONAL_COLUMN_ADDITIONS.get(table, set())

        assert set(after) - set(before) == allowed, f"{table} gained an unplanned column"
        # Nothing is ever removed from or reordered within an established table.
        assert [name for name in after if name not in allowed] == list(before), table


def test_the_new_tables_start_empty(tmp_path):
    """No connection row, so the health service can only say ``not configured``."""
    path = tmp_path / "counts.db"
    assert _alembic(f"sqlite:///{path.as_posix()}", "upgrade", "head").returncode == 0

    connection = sqlite3.connect(path)
    try:
        for table in sorted(PHASE_4A_TABLES):
            count = connection.execute(f"select count(*) from {table}").fetchone()[0]
            assert count == 0, table
    finally:
        connection.close()


# --- Round trip -------------------------------------------------------------


def test_the_migration_downgrades_and_upgrades_cleanly(tmp_path):
    path = tmp_path / "roundtrip.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", "head").returncode == 0
    assert _tables(path) >= PHASE_4A_TABLES

    down = _alembic(url, "downgrade", PHASE_2_REVISION)
    assert down.returncode == 0, down.stderr
    assert PHASE_4A_TABLES.isdisjoint(_tables(path))
    # And the Phase 2 schema is intact, so a downgrade is a genuine rollback.
    assert _tables(path) >= PRESERVED_TABLES

    up = _alembic(url, "upgrade", "head")
    assert up.returncode == 0, up.stderr
    assert _tables(path) >= PHASE_4A_TABLES


def test_a_downgrade_preserves_phase_3_data(tmp_path):
    """Rolling Phase 4A back must not cost a deployment its shipments."""
    path = tmp_path / "downgrade-data.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", PHASE_2_REVISION).returncode == 0
    _write_phase_3_rows(path)
    assert _alembic(url, "upgrade", "head").returncode == 0

    assert _alembic(url, "downgrade", PHASE_2_REVISION).returncode == 0

    connection = sqlite3.connect(path)
    try:
        shipment = connection.execute("select public_id from shipments").fetchone()
        integrity = connection.execute("pragma integrity_check").fetchone()[0]
    finally:
        connection.close()

    assert shipment == ("SX-CAV-7K9D2M4R8T6W",)
    assert integrity == "ok"


# --- The revision chain -----------------------------------------------------


def test_the_phase_4a_migration_chains_onto_phase_2(tmp_path):
    revision = next((BACKEND_ROOT / "alembic" / "versions").glob(f"{PHASE_4A_REVISION}_*.py"))
    source = revision.read_text(encoding="utf-8")

    assert f'revision: str = "{PHASE_4A_REVISION}"' in source
    assert f'down_revision: str | None = "{PHASE_2_REVISION}"' in source


def test_the_earlier_migrations_are_unmodified():
    """Phase 4A extends the schema through a new revision; it never edits an old one."""
    versions = BACKEND_ROOT / "alembic" / "versions"

    baseline = (versions / f"{PHASE_1_REVISION}_phase_1_baseline_schema.py").read_text(
        encoding="utf-8"
    )
    assert "down_revision: str | None = None" in baseline

    phase_2 = next(versions.glob(f"{PHASE_2_REVISION}_*.py")).read_text(encoding="utf-8")
    assert f'down_revision: str | None = "{PHASE_1_REVISION}"' in phase_2

    # No Phase 4A table may appear in an earlier revision.
    for table in PHASE_4A_TABLES:
        assert f'"{table}"' not in baseline, table
        assert f'"{table}"' not in phase_2, table


def test_the_migration_touches_no_existing_table(tmp_path):
    """Read from the migration source, so an added ALTER is caught at review time."""
    revision = next((BACKEND_ROOT / "alembic" / "versions").glob(f"{PHASE_4A_REVISION}_*.py"))
    source = revision.read_text(encoding="utf-8")

    for table in sorted(PRESERVED_TABLES):
        assert f'batch_alter_table("{table}"' not in source, table
        assert f'op.drop_table("{table}")' not in source, table
