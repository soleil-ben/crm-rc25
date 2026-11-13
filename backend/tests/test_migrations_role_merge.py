"""The role-merge migration (DEC-0088): reversible, and proven so rather than asserted.

The claim under test is narrow and total: after ``upgrade`` then ``downgrade``, every row
of ``users.role`` holds exactly the value it held before the upgrade. Not "roughly", not
"for the accounts we remembered" — the whole column, compared as a mapping.

That claim is what the first version of this migration could not make. It remapped
``customer_service`` to ``operations`` and then had no way to tell the two populations
apart again, so its downgrade printed a warning and changed nothing. A warning is not a
rollback. The provenance table is what turns the warning into a restore, and every test
here exists because some way of getting that wrong would otherwise pass.

The one case that is *not* exact restoration is an account created after the upgrade. It
never had a pre-merge role, so there is nothing to restore it to, and the migration's
contract is that it stays Operations. That is tested as explicitly as the rest, because a
silent choice there is how a rollback quietly invents a role for somebody.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]

#: The revision immediately before the merge: a database at this point still has both
#: roles as independent values.
PRE_MERGE_REVISION = "e5623fcf8018"
ROLE_MERGE_REVISION = "a1c7f4d92b30"

PROVENANCE_TABLE = "role_merge_provenance"

#: Columns the provenance table is allowed to have. The point of the assertion is the
#: absence of everything else: a rollback needs an id and a role, and a table holding a
#: password hash or an email would be a second copy of the staff table living outside the
#: access controls that protect the first one.
PERMITTED_PROVENANCE_COLUMNS = {"id", "user_id", "previous_role", "migration_id", "recorded_at"}

FORBIDDEN_PROVENANCE_COLUMNS = {
    "password_hash",
    "password",
    "email",
    "full_name",
    "session_token",
    "token",
    "timezone",
    "locale",
    "last_login_at",
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


def _url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("pragma foreign_keys=on")
    return connection


def _roles(path: Path) -> dict[int, str]:
    """The whole role column, as a mapping. The unit of comparison for reversibility."""
    connection = sqlite3.connect(path)
    try:
        return {row[0]: row[1] for row in connection.execute("select id, role from users")}
    finally:
        connection.close()


def _tables(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in connection.execute("select name from sqlite_master where type='table'")
        }
    finally:
        connection.close()


def _add_user(connection: sqlite3.Connection, user_id: int, role: str) -> None:
    connection.execute(
        """
        insert into users (
            id, email, full_name, password_hash, role, is_active, timezone, locale,
            must_change_password, created_at, updated_at
        ) values (?, ?, ?, 'argon2-placeholder-not-a-real-hash', ?, 1,
                  'America/Toronto', 'en', 0, '2026-01-01 00:00:00', '2026-01-01 00:00:00')
        """,
        (user_id, f"user{user_id}@demo.example.com", f"User {user_id}", role),
    )


def _database_at_pre_merge(path: Path, roles: list[str]) -> dict[int, str]:
    """A database one revision before the merge, holding ``roles`` in order from id 1."""
    result = _alembic(_url(path), "upgrade", PRE_MERGE_REVISION)
    assert result.returncode == 0, result.stderr
    connection = _connect(path)
    try:
        for index, role in enumerate(roles, start=1):
            _add_user(connection, index, role)
        connection.commit()
    finally:
        connection.close()
    return _roles(path)


def _upgrade(path: Path) -> subprocess.CompletedProcess:
    result = _alembic(_url(path), "upgrade", ROLE_MERGE_REVISION)
    assert result.returncode == 0, result.stderr
    return result


def _downgrade(path: Path) -> subprocess.CompletedProcess:
    result = _alembic(_url(path), "downgrade", PRE_MERGE_REVISION)
    assert result.returncode == 0, result.stderr
    return result


# --- Population shapes ------------------------------------------------------
#
# Each of these is a database a real deployment could be. The parametrisation is the point:
# a downgrade that special-cases "there was at least one of each" passes the mixed case and
# fails here.


@pytest.mark.parametrize(
    ("label", "roles"),
    [
        ("only former customer service", ["customer_service"]),
        ("only former operations", ["operations"]),
        ("both, one each", ["customer_service", "operations"]),
        (
            "multiple accounts of each role",
            [
                "customer_service",
                "customer_service",
                "customer_service",
                "operations",
                "operations",
            ],
        ),
        ("no affected accounts", ["admin", "marketing", "read_only_manager"]),
        ("empty user table", []),
        (
            "every role at once",
            [
                "admin",
                "customer_service",
                "customer_service",
                "operations",
                "operations",
                "marketing",
                "read_only_manager",
            ],
        ),
    ],
)
def test_upgrade_then_downgrade_restores_every_role_exactly(tmp_path, label, roles):
    """The central claim. Compared as a whole mapping, not per interesting account."""
    path = tmp_path / "role_merge.db"
    before = _database_at_pre_merge(path, roles)

    _upgrade(path)
    _downgrade(path)

    assert _roles(path) == before, label


@pytest.mark.parametrize(
    ("label", "roles"),
    [
        ("only former customer service", ["customer_service", "customer_service"]),
        ("only former operations", ["operations", "operations"]),
        ("both", ["customer_service", "operations"]),
        ("no affected accounts", ["admin", "marketing"]),
    ],
)
def test_upgrade_leaves_nobody_on_the_retired_role(tmp_path, label, roles):
    path = tmp_path / "role_merge.db"
    _database_at_pre_merge(path, roles)

    _upgrade(path)

    after = _roles(path)
    assert "customer_service" not in after.values(), label


def test_upgrade_maps_customer_service_and_leaves_operations_alone(tmp_path):
    path = tmp_path / "role_merge.db"
    _database_at_pre_merge(path, ["customer_service", "operations", "marketing", "admin"])

    _upgrade(path)

    assert _roles(path) == {1: "operations", 2: "operations", 3: "marketing", 4: "admin"}


def test_upgrade_captures_provenance_for_both_populations(tmp_path):
    """Former Operations accounts are recorded too, not only the ones that change.

    Recording only the rows the ``UPDATE`` touched would look sufficient and would make the
    downgrade unable to prove it left the others alone on purpose rather than by omission.
    """
    path = tmp_path / "role_merge.db"
    _database_at_pre_merge(path, ["admin", "customer_service", "operations", "marketing"])

    _upgrade(path)

    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            f"select user_id, previous_role, migration_id from {PROVENANCE_TABLE} order by user_id"
        ).fetchall()
    finally:
        connection.close()

    assert rows == [
        (2, "customer_service", ROLE_MERGE_REVISION),
        (3, "operations", ROLE_MERGE_REVISION),
    ]


# --- What the provenance table may hold -------------------------------------


def test_provenance_table_holds_no_credential_or_profile_data(tmp_path):
    path = tmp_path / "role_merge.db"
    _database_at_pre_merge(path, ["customer_service"])

    _upgrade(path)

    connection = sqlite3.connect(path)
    try:
        columns = {row[1] for row in connection.execute(f"pragma table_info({PROVENANCE_TABLE})")}
    finally:
        connection.close()

    assert columns == PERMITTED_PROVENANCE_COLUMNS
    assert not (columns & FORBIDDEN_PROVENANCE_COLUMNS)


def test_provenance_uniqueness_is_enforced(tmp_path):
    """One opinion per account per migration, enforced by the database, not by the query."""
    path = tmp_path / "role_merge.db"
    _database_at_pre_merge(path, ["customer_service"])
    _upgrade(path)

    connection = _connect(path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                f"""
                insert into {PROVENANCE_TABLE} (user_id, previous_role, migration_id, recorded_at)
                values (1, 'operations', ?, '2026-01-01 00:00:00')
                """,
                (ROLE_MERGE_REVISION,),
            )
    finally:
        connection.close()


def test_provenance_foreign_key_cascades_when_a_user_is_deleted(tmp_path):
    """A row whose user is gone has nothing left to restore and must not dangle."""
    path = tmp_path / "role_merge.db"
    _database_at_pre_merge(path, ["customer_service", "operations"])
    _upgrade(path)

    connection = _connect(path)
    try:
        connection.execute("delete from users where id = 1")
        connection.commit()
        remaining = connection.execute(f"select user_id from {PROVENANCE_TABLE}").fetchall()
        violations = connection.execute("pragma foreign_key_check").fetchall()
    finally:
        connection.close()

    assert remaining == [(2,)]
    assert violations == []


def test_provenance_table_is_gone_after_downgrade(tmp_path):
    path = tmp_path / "role_merge.db"
    _database_at_pre_merge(path, ["customer_service", "operations"])

    _upgrade(path)
    assert PROVENANCE_TABLE in _tables(path)

    _downgrade(path)
    assert PROVENANCE_TABLE not in _tables(path)


def test_downgrade_removes_only_rows_this_migration_owns(tmp_path):
    """A foreign row survives, and the table survives with it.

    Nothing writes such a row today. The test fixes the behaviour now so that a later
    migration reusing this table does not discover that its rows were silently dropped.
    """
    path = tmp_path / "role_merge.db"
    _database_at_pre_merge(path, ["customer_service", "operations"])
    _upgrade(path)

    connection = _connect(path)
    try:
        connection.execute(
            f"""
            insert into {PROVENANCE_TABLE} (user_id, previous_role, migration_id, recorded_at)
            values (2, 'marketing', 'some0ther0rev', '2026-01-01 00:00:00')
            """
        )
        connection.commit()
    finally:
        connection.close()

    _downgrade(path)

    assert PROVENANCE_TABLE in _tables(path)
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(f"select migration_id from {PROVENANCE_TABLE}").fetchall()
    finally:
        connection.close()
    assert rows == [("some0ther0rev",)]


# --- The account created after the upgrade ----------------------------------


def test_an_account_created_after_the_upgrade_stays_operations(tmp_path):
    """It never had a pre-merge role, so the downgrade must not invent one for it."""
    path = tmp_path / "role_merge.db"
    _database_at_pre_merge(path, ["customer_service", "operations"])
    _upgrade(path)

    connection = _connect(path)
    try:
        _add_user(connection, 99, "operations")
        connection.commit()
    finally:
        connection.close()

    _downgrade(path)

    after = _roles(path)
    assert after[99] == "operations"
    # ...and the accounts that did have a pre-merge role are still restored exactly.
    assert after[1] == "customer_service"
    assert after[2] == "operations"


def test_downgrade_reports_accounts_created_after_the_upgrade(tmp_path):
    """The count is surfaced, so an operator sees the case rather than inferring it."""
    path = tmp_path / "role_merge.db"
    _database_at_pre_merge(path, ["customer_service"])
    _upgrade(path)

    connection = _connect(path)
    try:
        _add_user(connection, 50, "operations")
        _add_user(connection, 51, "operations")
        connection.commit()
    finally:
        connection.close()

    result = _downgrade(path)

    assert "2 account(s) created after the upgrade keep 'operations'" in result.stdout


# --- Repetition and determinism ---------------------------------------------


def test_repeated_upgrade_downgrade_cycles_are_deterministic(tmp_path):
    path = tmp_path / "role_merge.db"
    before = _database_at_pre_merge(
        path, ["admin", "customer_service", "customer_service", "operations", "marketing"]
    )

    for _ in range(3):
        _upgrade(path)
        merged = _roles(path)
        _downgrade(path)
        assert _roles(path) == before
        # The merged state is identical on every pass too, not only the restored one.
        assert merged == {
            1: "admin",
            2: "operations",
            3: "operations",
            4: "operations",
            5: "marketing",
        }


def test_downgrade_then_upgrade_reaches_the_same_merged_state(tmp_path):
    path = tmp_path / "role_merge.db"
    _database_at_pre_merge(path, ["customer_service", "operations", "marketing"])

    _upgrade(path)
    first = _roles(path)

    _downgrade(path)
    _upgrade(path)

    assert _roles(path) == first


# --- From empty, and against the real seeded database -----------------------


def test_migration_runs_on_an_empty_database(tmp_path):
    path = tmp_path / "empty.db"
    result = _alembic(_url(path), "upgrade", "head")
    assert result.returncode == 0, result.stderr
    assert _roles(path) == {}
    assert PROVENANCE_TABLE in _tables(path)

    result = _alembic(_url(path), "downgrade", PRE_MERGE_REVISION)
    assert result.returncode == 0, result.stderr
    assert _roles(path) == {}


def test_upgrade_from_empty_captures_nothing(tmp_path):
    path = tmp_path / "empty.db"
    _alembic(_url(path), "upgrade", PRE_MERGE_REVISION)

    result = _upgrade(path)

    assert "captured pre-merge role for 0 account(s)" in result.stdout


# --- Integrity --------------------------------------------------------------


@pytest.mark.parametrize("stage", ["after_upgrade", "after_downgrade"])
def test_integrity_and_foreign_keys_hold(tmp_path, stage):
    path = tmp_path / "role_merge.db"
    _database_at_pre_merge(
        path, ["admin", "customer_service", "operations", "marketing", "read_only_manager"]
    )

    _upgrade(path)
    if stage == "after_downgrade":
        _downgrade(path)

    connection = sqlite3.connect(path)
    try:
        integrity = [row[0] for row in connection.execute("pragma integrity_check")]
        violations = connection.execute("pragma foreign_key_check").fetchall()
    finally:
        connection.close()

    assert integrity == ["ok"]
    assert violations == []


# --- A populated pre-merge deployment ---------------------------------------


def _write_populated_rows(path: Path) -> None:
    """The rows a live pre-merge deployment holds, written as raw SQL.

    Deliberately not built through the services: this fixture represents a database
    written by the *previous* revision, and going through today's models would be writing
    today's roles back into it.
    """
    connection = _connect(path)
    try:
        connection.execute(
            """
            insert into customers (
                public_id, full_name, email_normalized, preferred_language, category,
                primary_shipping_purpose, shipping_frequency, do_not_contact, is_archived,
                is_demo_record, owner_user_id, created_at, updated_at
            ) values (
                'CUS-000001', 'Nguyễn Thị Bích Hạnh', 'hanh@demo.example.com', 'vi',
                'individual', 'gifts_family_support', 'occasional', 0, 0, 0, 2,
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
                'standard_parcel', 'air', 1, 0, 0, 'Tran Quoc Tuan',
                'Nguyễn Thị Bích Hạnh', '2026-01-06 10:00:00', '2026-01-06 10:00:00'
            )
            """
        )
        connection.execute(
            """
            insert into audit_events (
                occurred_at, actor_user_id, actor_label, action, entity_type, entity_id, summary
            ) values (
                '2026-01-06 10:00:00', 2, 'cs@demo.example.com', 'shipment.confirm',
                'shipment', '1', 'Confirmed SX-CAV-7K9D2M4R8T6W'
            )
            """
        )
        connection.commit()
    finally:
        connection.close()


def test_migration_upgrades_a_populated_pre_merge_database(tmp_path):
    """Customer, shipment and audit rows survive, and the audit actor still resolves.

    The audit row names user 2 by id. The merge changes that user's role, never its id, so
    the history keeps pointing at the same person — which is the property that makes the
    audit trail survive a role change at all.
    """
    path = tmp_path / "populated.db"
    before = _database_at_pre_merge(
        path, ["admin", "customer_service", "operations", "marketing", "read_only_manager"]
    )
    _write_populated_rows(path)

    _upgrade(path)

    connection = sqlite3.connect(path)
    try:
        assert connection.execute("select count(*) from customers").fetchone() == (1,)
        assert connection.execute("select full_name from customers").fetchone() == (
            "Nguyễn Thị Bích Hạnh",
        )
        assert connection.execute("select public_id from shipments").fetchone() == (
            "SX-CAV-7K9D2M4R8T6W",
        )
        assert connection.execute("select actor_user_id from audit_events").fetchone() == (2,)
        assert connection.execute("select role from users where id = 2").fetchone() == (
            "operations",
        )
        violations = connection.execute("pragma foreign_key_check").fetchall()
    finally:
        connection.close()
    assert violations == []

    _downgrade(path)
    assert _roles(path) == before

    connection = sqlite3.connect(path)
    try:
        assert connection.execute("select count(*) from customers").fetchone() == (1,)
        assert connection.execute("select count(*) from shipments").fetchone() == (1,)
        assert connection.execute("select count(*) from audit_events").fetchone() == (1,)
    finally:
        connection.close()


def test_the_merge_touches_no_column_of_users_but_role(tmp_path):
    path = tmp_path / "populated.db"
    _database_at_pre_merge(path, ["customer_service", "operations"])

    connection = sqlite3.connect(path)
    try:
        before = connection.execute(
            "select id, email, full_name, password_hash, is_active, timezone, locale,"
            " must_change_password, created_at, updated_at from users order by id"
        ).fetchall()
    finally:
        connection.close()

    _upgrade(path)

    connection = sqlite3.connect(path)
    try:
        after = connection.execute(
            "select id, email, full_name, password_hash, is_active, timezone, locale,"
            " must_change_password, created_at, updated_at from users order by id"
        ).fetchall()
    finally:
        connection.close()

    assert after == before
