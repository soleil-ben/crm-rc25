"""The Phase 9 migration: from empty, from a populated Phase 8 database, and back again.

`IMPLEMENTATION_PLAN.md` section 2 calls this migration "the riskiest thing in the whole
plan" and asks for the Phase 7 treatment: a downgrade that is **tested rather than
asserted**, and a rehearsal against a populated database rather than an empty one. That is
what this module is.

The claim being tested is narrower and stronger than "the migration runs". It is:

* nine tables appear, with the columns, uniqueness, foreign keys and indexes the data model
  requires -- checked by name, so a column silently dropped from a model fails here;
* **nothing else changes.** Every pre-existing table keeps its columns, its indexes and its
  row count, through an upgrade, a downgrade *and* a re-upgrade. A populated fixture is used
  because an empty database cannot detect data loss;
* ``role_merge_provenance`` survives all three steps with its rows and its shape, because it
  is owned by ``a1c7f4d92b30`` and this migration has no business touching it (DEC-0089);
* the downgrade genuinely reverses: the schema after ``upgrade`` and after
  ``downgrade`` then ``upgrade`` again is identical, table for table and index for index.

Everything runs the real CLI in a subprocess, like the other migration tests, because what
is being asserted is the behaviour of ``env.py`` as Alembic actually loads it.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

PHASE_7_REVISION = "a1c7f4d92b30"
PHASE_9_REVISION = "b1047733d0e9"
#: Where the row-comparison tests upgrade to. Head moved on (Phase 13A, then the customer
#: prefix rename a7c3e1d9b2f4, which rewrites public_id by design); the Phase 10 revision is
#: the last one that leaves every Phase 9 value untouched.
PHASE_10_REVISION = "6af30fcdd3a8"

#: The nine tables this migration creates. Nine, not the eight `DATA_MODEL.md` proposes:
#: `customer_registration_attempts` is the registration idempotency claim, reconciled in
#: `PROJECT_STATUS.md` section 17.4 and recorded as DEC-0098.
PHASE_9_TABLES = {
    "customer_identities",
    "customer_identity_links",
    "customer_sessions",
    "customer_auth_tokens",
    "customer_terms_acknowledgements",
    "customer_notification_preferences",
    "customer_data_proposals",
    "customer_data_proposal_fields",
    "customer_registration_attempts",
}

#: Tables this migration must not touch. A change to any of them means it has stopped being
#: additive and an existing deployment is at risk.
PRESERVED_TABLES = {
    "users",
    "user_sessions",
    "audit_events",
    "organization_settings",
    "counters",
    "customers",
    "customer_addresses",
    "customer_id_aliases",
    "customer_route_interests",
    "customer_tags",
    "tags",
    "referrals",
    "consent_events",
    "contact_suppressions",
    "interactions",
    "follow_up_tasks",
    "service_issues",
    "saved_segments",
    "shipments",
    "shipment_packages",
    "shipment_legs",
    "shipment_leg_packages",
    "shipment_events",
    "leg_tracking_references",
    "booking_confirmations",
    "label_print_jobs",
    "label_print_job_packages",
    "import_batches",
    "import_batch_rows",
    "integration_connections",
    "integration_webhook_inbox",
    "integration_provider_events",
    "integration_jobs",
    "integration_worker_heartbeats",
    "role_merge_provenance",
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


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("pragma foreign_keys=on")
    return connection


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


def _foreign_keys(path: Path, table: str) -> set[tuple[str, str, str, str]]:
    """``(from_column, referenced_table, to_column, on_delete)`` for one table."""
    connection = sqlite3.connect(path)
    try:
        return {
            (row[3], row[2], row[4], row[6])
            for row in connection.execute(f"pragma foreign_key_list({table})")
        }
    finally:
        connection.close()


def _schema_fingerprint(path: Path) -> dict[str, tuple[frozenset[str], frozenset[str]]]:
    """Every table with its column set and its index set. The comparison a round trip needs."""
    return {
        table: (frozenset(_columns(path, table)), frozenset(_indexes(path, table)))
        for table in sorted(_tables(path))
        if not table.startswith("sqlite_")
    }


def _row_counts(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(path)
    try:
        return {
            table: connection.execute(f"select count(*) from {table}").fetchone()[0]
            for table in sorted(_tables(path))
            if not table.startswith("sqlite_")
        }
    finally:
        connection.close()


def _write_phase_8_rows(path: Path) -> None:
    """The rows a live Phase 8 deployment already holds, in every table this could threaten.

    Raw SQL rather than the services, deliberately: this fixture represents a database
    written by the *previous* revision, and writing it through today's models would be
    writing today's schema.
    """
    connection = _connect(path)
    connection.execute(
        """
        insert into users (
            email, full_name, password_hash, role, is_active, timezone, locale,
            must_change_password, created_at, updated_at
        ) values (
            'ops@demo.example.com', 'Operations Person', 'argon2-placeholder-hash',
            'operations', 1, 'America/Toronto', 'en', 0,
            '2026-01-02 09:00:00', '2026-01-02 09:00:00'
        )
        """
    )
    connection.execute(
        """
        insert into customers (
            public_id, full_name, email_entered, email_normalized, preferred_language,
            category, primary_shipping_purpose, shipping_frequency, do_not_contact,
            is_archived, is_demo_record, created_at, updated_at
        ) values (
            'CUS-000001', 'Nguyễn Thị Bích Hạnh', 'Hanh@Demo.Example.com',
            'hanh@demo.example.com', 'vi', 'individual', 'gifts_family_support',
            'occasional', 0, 0, 0, '2026-01-05 10:00:00', '2026-01-05 10:00:00'
        )
        """
    )
    connection.execute(
        """
        insert into customer_addresses (
            customer_id, role, contact_name, address_line1, city, country_code,
            is_default_sender, is_default_recipient, is_archived, created_at, updated_at
        ) values (1, 'both', 'Tran Quoc Tuan', '4120 Dixie Road', 'Mississauga', 'CA',
                  1, 0, 0, '2026-01-05 10:00:00', '2026-01-05 10:00:00')
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
            'standard_parcel', 'air', 1, 0, 0, 'Tran Quoc Tuan',
            'Nguyễn Thị Bích Hạnh', '2026-01-06 10:00:00', '2026-01-06 10:00:00'
        )
        """
    )
    connection.execute(
        """
        insert into consent_events (
            customer_id, channel, address_value, status, basis, obtained_at, source,
            recorded_at, recorded_by_user_id
        ) values (1, 'email', 'hanh@demo.example.com', 'granted', 'explicit_optin',
                  '2026-01-06 11:00:00', 'staff_entry', '2026-01-06 11:00:00', 1)
        """
    )
    connection.execute(
        """
        insert into audit_events (
            occurred_at, actor_user_id, actor_label, action, entity_type, entity_id,
            summary
        ) values ('2026-01-06 11:00:00', 1, 'ops@demo.example.com', 'customer.create',
                  'customer', '1', 'Created customer CUS-000001')
        """
    )
    connection.execute(
        """
        insert into import_batches (
            public_id, kind, content_sha256, source_system, conflict_policy, row_count,
            created_count, matched_count, skipped_count, rejected_count, committed_at,
            committed_by_user_id, created_at, updated_at
        ) values ('IMP-000001', 'customers', 'a' , 'csv', 'skip', 1, 1, 0, 0, 0,
                  '2026-01-06 12:00:00', 1, '2026-01-06 12:00:00', '2026-01-06 12:00:00')
        """
    )
    connection.execute(
        """
        insert into integration_connections (
            provider_key, connection_key, display_label, state, is_enabled,
            created_at, updated_at
        ) values ('unassigned', 'unassigned', 'Not configured', 'not_configured', 0,
                  '2026-01-06 12:00:00', '2026-01-06 12:00:00')
        """
    )
    # The role-merge bookkeeping a Phase 7 upgrade left behind. Owned by a1c7f4d92b30.
    connection.execute(
        """
        insert into role_merge_provenance (user_id, previous_role, migration_id, recorded_at)
        values (1, 'customer_service', 'a1c7f4d92b30', '2026-09-19 08:00:00')
        """
    )
    connection.commit()
    connection.close()


def _phase_8_database(tmp_path: Path, name: str) -> tuple[Path, str]:
    path = tmp_path / name
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", PHASE_7_REVISION).returncode == 0
    _write_phase_8_rows(path)
    return path, url


# --- From empty --------------------------------------------------------------


def test_migration_runs_on_an_empty_database(tmp_path):
    path = tmp_path / "empty.db"
    result = _alembic(f"sqlite:///{path.as_posix()}", "upgrade", "head")
    assert result.returncode == 0, result.stderr

    tables = _tables(path)
    assert tables >= PHASE_9_TABLES
    assert tables >= PRESERVED_TABLES


def test_this_revision_follows_the_role_merge_and_is_reachable(tmp_path):
    """Phase 9 is no longer head, and this test no longer claims it is.

    As written it upgraded to ``head`` and asserted the result was ``b1047733d0e9``, which
    was true for exactly as long as Phase 9 was the newest migration. Phase 10 added
    ``6af30fcdd3a8``, and a test that says "head is Phase 9" would now be asserting that no
    further migration may ever be written.

    What it should have been saying, and now does: upgrading *to this revision* lands on
    it, and it sits directly on top of the role merge.

    See `docs/customer_account/SUPERSEDED_ASSERTIONS.md`, entry AS-01.
    """
    path = tmp_path / "head.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", PHASE_9_REVISION).returncode == 0
    connection = sqlite3.connect(path)
    try:
        version = connection.execute("select version_num from alembic_version").fetchone()[0]
    finally:
        connection.close()
    assert version == PHASE_9_REVISION

    revision = next(
        path
        for path in (BACKEND_ROOT / "alembic" / "versions").glob("*.py")
        if PHASE_9_REVISION in path.name
    ).read_text(encoding="utf-8")
    assert f'down_revision: str | None = "{PHASE_7_REVISION}"' in revision


# --- The nine tables, column by column ---------------------------------------


def test_identity_table_has_the_columns_the_data_model_requires(tmp_path):
    path = tmp_path / "identity.db"
    assert _alembic(f"sqlite:///{path.as_posix()}", "upgrade", "head").returncode == 0
    columns = _columns(path, "customer_identities")
    assert {
        "id",
        "public_id",
        "email_entered",
        "email_normalized",
        "password_hash",
        "status",
        "email_verified_at",
        "approved_at",
        "approved_by_user_id",
        "rejected_at",
        "rejected_by_user_id",
        "suspended_at",
        "suspended_by_user_id",
        "deactivated_at",
        "deactivated_by_user_id",
        "status_reason_code",
        "failed_sign_in_count",
        "locked_until",
        "last_sign_in_at",
        "preferred_language",
        "created_at",
        "updated_at",
    } <= columns


def test_the_identity_table_holds_no_role_permission_or_customer_column(tmp_path):
    """The one-sentence rule of `IDENTITY_AND_AUTHORIZATION.md`, asserted as a schema fact.

    A ``role`` column here would be the first half of a permission lookup, and a
    ``customer_id`` column would be the link OD-25 requires to live in its own table. Both
    are absent, and this fails if either is ever added by reflex.
    """
    path = tmp_path / "norole.db"
    assert _alembic(f"sqlite:///{path.as_posix()}", "upgrade", "head").returncode == 0
    columns = _columns(path, "customer_identities")
    assert "role" not in columns
    assert "permissions" not in columns
    assert "is_staff" not in columns
    assert "customer_id" not in columns


def test_token_and_session_tables_store_digests_and_not_tokens(tmp_path):
    """No column may hold a plaintext credential, and the column names say so."""
    path = tmp_path / "digests.db"
    assert _alembic(f"sqlite:///{path.as_posix()}", "upgrade", "head").returncode == 0

    sessions = _columns(path, "customer_sessions")
    assert "session_token_hash" in sessions
    assert "csrf_token_hash" in sessions
    assert "session_token" not in sessions
    assert "csrf_token" not in sessions

    tokens = _columns(path, "customer_auth_tokens")
    assert "token_digest" in tokens
    assert "token" not in tokens
    assert "token_plaintext" not in tokens
    assert {"purpose", "issued_at", "expires_at", "consumed_at", "invalidated_at"} <= tokens


def test_proposal_fields_are_typed_and_not_a_json_blob(tmp_path):
    path = tmp_path / "proposal.db"
    assert _alembic(f"sqlite:///{path.as_posix()}", "upgrade", "head").returncode == 0
    columns = _columns(path, "customer_data_proposal_fields")
    assert {
        "proposal_id",
        "field_key",
        "value_type",
        "proposed_value",
        "proposed_value_normalized",
        "current_value_at_submission",
        "applied",
    } <= columns
    # A blob column would make the allowlist decorative.
    assert "payload_json" not in columns
    assert "data_json" not in columns


def test_the_link_table_carries_the_two_partial_unique_indexes(tmp_path):
    """OD-25's release-1 rule is an index, not a comment in a service."""
    path = tmp_path / "links.db"
    assert _alembic(f"sqlite:///{path.as_posix()}", "upgrade", "head").returncode == 0

    assert {
        "uq_customer_identity_links_active_identity",
        "uq_customer_identity_links_active_customer",
    } <= _indexes(path, "customer_identity_links")

    connection = sqlite3.connect(path)
    try:
        definitions = {
            row[0]: row[1]
            for row in connection.execute(
                "select name, sql from sqlite_master where type='index' "
                "and tbl_name='customer_identity_links' and sql is not null"
            )
        }
    finally:
        connection.close()

    for name in (
        "uq_customer_identity_links_active_identity",
        "uq_customer_identity_links_active_customer",
    ):
        sql = definitions[name]
        assert "UNIQUE" in sql.upper()
        # Partial: a revoked link must be free to repeat, or unlink-and-relink is impossible.
        assert "WHERE" in sql.upper()
        assert "active" in sql


def test_the_partial_index_permits_repeated_revoked_links_and_refuses_a_second_active_one(
    tmp_path,
):
    """The predicate does what it says, exercised against the real database."""
    path, _ = _phase_8_database(tmp_path, "linkrules.db")
    assert _alembic(f"sqlite:///{path.as_posix()}", "upgrade", "head").returncode == 0

    connection = _connect(path)
    try:
        connection.execute(
            """
            insert into customer_identities (
                public_id, email_entered, email_normalized, password_hash, status,
                failed_sign_in_count, preferred_language, created_at, updated_at
            ) values ('CA-000001', 'a@example.com', 'a@example.com', 'h',
                      'pending_approval', 0, 'en', '2026-02-01 09:00:00',
                      '2026-02-01 09:00:00')
            """
        )
        for _ in range(3):
            connection.execute(
                "insert into customer_identity_links "
                "(identity_id, customer_id, link_role, status, linked_at) "
                "values (1, 1, 'owner', 'revoked', '2026-02-01 09:00:00')"
            )
        connection.execute(
            "insert into customer_identity_links "
            "(identity_id, customer_id, link_role, status, linked_at) "
            "values (1, 1, 'owner', 'active', '2026-02-01 09:00:00')"
        )
        connection.commit()

        try:
            connection.execute(
                "insert into customer_identity_links "
                "(identity_id, customer_id, link_role, status, linked_at) "
                "values (1, 1, 'owner', 'active', '2026-02-01 10:00:00')"
            )
        except sqlite3.IntegrityError:
            pass
        else:  # pragma: no cover - only reached if the index is missing
            raise AssertionError("a second active link was accepted")
    finally:
        connection.close()


def test_deletion_behaviour_is_declared_on_every_foreign_key(tmp_path):
    """Cascade where the child is meaningless alone; restrict where a parent must survive."""
    path = tmp_path / "fks.db"
    assert _alembic(f"sqlite:///{path.as_posix()}", "upgrade", "head").returncode == 0

    def rule(table: str, column: str) -> str:
        return next(
            on_delete
            for from_column, _, _, on_delete in _foreign_keys(path, table)
            if from_column == column
        )

    assert rule("customer_sessions", "identity_id") == "CASCADE"
    assert rule("customer_auth_tokens", "identity_id") == "CASCADE"
    assert rule("customer_terms_acknowledgements", "identity_id") == "CASCADE"
    assert rule("customer_notification_preferences", "identity_id") == "CASCADE"
    assert rule("customer_data_proposals", "identity_id") == "CASCADE"
    assert rule("customer_data_proposal_fields", "proposal_id") == "CASCADE"
    assert rule("customer_identity_links", "identity_id") == "CASCADE"
    # A linked customer is not deleted out from under an account.
    assert rule("customer_identity_links", "customer_id") == "RESTRICT"
    # Staff history survives the staff row.
    assert rule("customer_identities", "approved_by_user_id") == "SET NULL"
    assert rule("customer_identities", "suspended_by_user_id") == "SET NULL"
    # A registration attempt is a record of a request and outlives what it created.
    assert rule("customer_registration_attempts", "identity_id") == "SET NULL"


# --- From a populated Phase 8 database ---------------------------------------


def test_migration_upgrades_a_populated_phase_8_database_without_losing_a_row(tmp_path):
    path, url = _phase_8_database(tmp_path, "populated.db")
    before = _row_counts(path)

    result = _alembic(url, "upgrade", PHASE_10_REVISION)
    assert result.returncode == 0, result.stderr

    after = _row_counts(path)
    for table, count in before.items():
        assert after[table] == count, f"{table} changed from {count} to {after[table]}"


def test_pre_existing_tables_keep_their_shape(tmp_path):
    """Pinned to the Phase 9 revision, which is what the assertion message always claimed.

    It upgraded to ``head``, so from Phase 10 onward it was really asserting "no migration
    after Phase 7 alters an established table" -- a claim no phase can promise on behalf of
    the ones that follow it, and one Phase 10 breaks on purpose by adding two columns to
    ``customers`` (DEC-0101).

    The register of every column ever added to an established table lives in
    `tests/test_migrations_phase4a.py`, which enumerates them and is where a new one has to
    be named. This test is about **this** migration, and now upgrades to it.

    See `docs/customer_account/SUPERSEDED_ASSERTIONS.md`, entry AS-02.
    """
    path, url = _phase_8_database(tmp_path, "shape.db")
    before = _schema_fingerprint(path)

    assert _alembic(url, "upgrade", PHASE_9_REVISION).returncode == 0

    after = _schema_fingerprint(path)
    for table, fingerprint in before.items():
        assert after[table] == fingerprint, f"{table} was altered by the Phase 9 migration"


def test_role_merge_provenance_survives_the_whole_round_trip(tmp_path):
    """It is owned by ``a1c7f4d92b30`` and this migration has no business touching it."""
    path, url = _phase_8_database(tmp_path, "provenance.db")
    shape = (_columns(path, "role_merge_provenance"), _row_counts(path)["role_merge_provenance"])

    for step in ("upgrade head", f"downgrade {PHASE_7_REVISION}", "upgrade head"):
        assert _alembic(url, *step.split()).returncode == 0
        assert "role_merge_provenance" in _tables(path)
        assert _columns(path, "role_merge_provenance") == shape[0]
        assert _row_counts(path)["role_merge_provenance"] == shape[1]


# --- Down and back up again --------------------------------------------------


def test_downgrade_removes_exactly_the_nine_tables(tmp_path):
    path, url = _phase_8_database(tmp_path, "down.db")
    assert _alembic(url, "upgrade", "head").returncode == 0
    assert _tables(path) >= PHASE_9_TABLES

    result = _alembic(url, "downgrade", PHASE_7_REVISION)
    assert result.returncode == 0, result.stderr

    remaining = _tables(path)
    assert not (PHASE_9_TABLES & remaining)
    assert remaining >= PRESERVED_TABLES


def test_downgrade_then_reupgrade_restores_the_schema_exactly(tmp_path):
    path, url = _phase_8_database(tmp_path, "roundtrip.db")

    assert _alembic(url, "upgrade", "head").returncode == 0
    after_first_upgrade = _schema_fingerprint(path)

    assert _alembic(url, "downgrade", PHASE_7_REVISION).returncode == 0
    assert _alembic(url, "upgrade", "head").returncode == 0
    after_round_trip = _schema_fingerprint(path)

    assert after_round_trip == after_first_upgrade


def test_existing_data_survives_downgrade_and_reupgrade(tmp_path):
    path, url = _phase_8_database(tmp_path, "survive.db")
    before = _row_counts(path)

    assert _alembic(url, "upgrade", PHASE_10_REVISION).returncode == 0
    assert _alembic(url, "downgrade", PHASE_7_REVISION).returncode == 0
    assert _alembic(url, "upgrade", PHASE_10_REVISION).returncode == 0

    after = _row_counts(path)
    for table, count in before.items():
        assert after[table] == count, f"{table} changed from {count} to {after[table]}"


# --- alembic check, the standing requirement (DEC-0089) ----------------------


def test_alembic_check_is_green_after_upgrade(tmp_path):
    path, url = _phase_8_database(tmp_path, "check-up.db")
    assert _alembic(url, "upgrade", "head").returncode == 0

    result = _alembic(url, "check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No new upgrade operations detected" in result.stdout


def test_alembic_check_is_green_after_a_downgrade_and_reupgrade(tmp_path):
    path, url = _phase_8_database(tmp_path, "check-round.db")
    assert _alembic(url, "upgrade", "head").returncode == 0
    assert _alembic(url, "downgrade", PHASE_7_REVISION).returncode == 0
    assert _alembic(url, "upgrade", "head").returncode == 0

    result = _alembic(url, "check")
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_migration_source_never_mentions_the_migration_owned_table(tmp_path):
    """A textual check, because the cost of getting this wrong is silent irreversibility.

    `README.md` in `docs/customer_account/` states it as a rule: no Customer Account
    migration may drop, rename, map or repurpose ``role_merge_provenance``. A generated
    migration that mentions it was produced against a tree where the autogeneration hook was
    missing, and the correct response is to discard it and regenerate.
    """
    source = (
        BACKEND_ROOT / "alembic" / "versions" / "b1047733d0e9_phase_9_customer_account_identity_.py"
    ).read_text(encoding="utf-8")
    body = source.split('"""', 2)[2]
    assert "role_merge_provenance" not in body
