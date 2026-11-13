"""``alembic check`` must be green, and must still fail for anything that is real drift.

The exclusion under test is one table wide. ``role_merge_provenance`` is created and dropped
by migration ``a1c7f4d92b30`` and mapped by no model, so autogeneration used to propose
dropping it on every run -- which made ``alembic check`` fail permanently and therefore
useless as a drift check: a real difference would have arrived as a third line in a message
that was already red.

Silencing it is only safe if the silence is narrow, so both halves are tested here and the
second half is the important one. Every test below that ends in ``still_fails`` exists to
prove the check did not become a check that passes. They deliberately introduce differences
of several shapes -- another unmapped table, a near-miss name, an extra column on a mapped
table, a missing column -- because "ignore unmapped tables" and "ignore tables whose name
starts with role_merge" would both pass a test that only looked at the green case.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]

#: The table the exclusion names, and the migration that owns it.
EXCLUDED_TABLE = "role_merge_provenance"

#: The second excluded table, owned by the end-to-end harness rather than by a migration.
#: It exists only inside a throwaway `.e2e.db`, never in a real database.
HARNESS_TABLE = "e2e_run_marker"
ROLE_MERGE_REVISION = "a1c7f4d92b30"
PRE_MERGE_REVISION = "e5623fcf8018"


def _load_policy():
    """Import the policy module the way nothing else can: it lives beside ``env.py``.

    Alembic loads ``env.py`` from a file path, so its neighbours are not importable by name
    from here. Loading it explicitly is what lets the hook be tested as a function, in the
    cases the CLI cannot reach -- most of all the case where the table *is* mapped.
    """
    path = BACKEND_ROOT / "alembic" / "autogenerate_policy.py"
    spec = importlib.util.spec_from_file_location("autogenerate_policy_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


policy = _load_policy()


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess:
    """Run the real CLI against a throwaway database.

    A subprocess, not an in-process API call, because the thing being asserted is the
    behaviour of ``env.py`` as Alembic actually loads it -- including the path handling that
    makes the policy module importable at all.
    """
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


@pytest.fixture
def database_at_head(tmp_path: Path) -> Path:
    """An empty database migrated to head: schema only, no seed, no rows that matter."""
    path = tmp_path / "check.db"
    result = _alembic(_url(path), "upgrade", "head")
    assert result.returncode == 0, result.stderr
    return path


def _execute(path: Path, statement: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(statement)
        connection.commit()
    finally:
        connection.close()


def _check(path: Path) -> subprocess.CompletedProcess:
    return _alembic(_url(path), "check")


def _tables(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute("select name from sqlite_master where type='table'")
        return {row[0] for row in rows}
    finally:
        connection.close()


# --- The green case ---------------------------------------------------------


def test_check_is_green_at_head(database_at_head: Path) -> None:
    """A database at head with the migration-owned table present has no drift to report."""
    result = _check(database_at_head)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "No new upgrade operations detected" in result.stdout


def test_the_excluded_table_really_is_present_while_the_check_passes(
    database_at_head: Path,
) -> None:
    """Otherwise the green result above would prove only that the table was missing."""
    assert EXCLUDED_TABLE in _tables(database_at_head)


# --- Drift that must still fail ---------------------------------------------


def test_another_unmapped_table_still_fails(database_at_head: Path) -> None:
    """The exclusion is one name, not the rule "ignore tables no model maps"."""
    _execute(database_at_head, "create table stray_unmapped_table (id integer primary key)")

    result = _check(database_at_head)

    assert result.returncode != 0
    assert "stray_unmapped_table" in result.stdout + result.stderr


@pytest.mark.parametrize(
    "near_miss",
    [
        "role_merge_provenance_backup",
        "role_merge_provenance_old",
        "role_merge",
        "provenance",
    ],
)
def test_a_near_miss_name_still_fails(database_at_head: Path, near_miss: str) -> None:
    """Matched literally and whole. A copy of the table left behind by hand is drift."""
    _execute(database_at_head, f"create table {near_miss} (id integer primary key)")

    result = _check(database_at_head)

    assert result.returncode != 0
    assert near_miss in result.stdout + result.stderr


def test_an_extra_column_on_a_mapped_table_still_fails(database_at_head: Path) -> None:
    """Column-level drift on the tables the application does own is untouched by this."""
    _execute(database_at_head, "alter table customers add column unexpected_drift varchar(10)")

    result = _check(database_at_head)

    assert result.returncode != 0
    assert "unexpected_drift" in result.stdout + result.stderr


def test_a_missing_column_on_a_mapped_table_still_fails(database_at_head: Path) -> None:
    """The other direction: the database holding *less* than the models is drift too."""
    _execute(database_at_head, "alter table customers drop column preferred_language")

    result = _check(database_at_head)

    assert result.returncode != 0
    assert "preferred_language" in result.stdout + result.stderr


def test_drift_is_reported_even_while_the_excluded_table_is_present(
    database_at_head: Path,
) -> None:
    """The failure mode this guards against: an exclusion that swallows the whole run."""
    _execute(database_at_head, "create table stray_unmapped_table (id integer primary key)")

    result = _check(database_at_head)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "stray_unmapped_table" in output
    assert EXCLUDED_TABLE in _tables(database_at_head)
    assert f"Detected removed table '{EXCLUDED_TABLE}'" not in output


# --- The migration still owns the table -------------------------------------


def test_upgrade_creates_the_table_and_downgrade_drops_it(tmp_path: Path) -> None:
    """Excluding it from autogeneration must not change what the migration does with it."""
    path = tmp_path / "ownership.db"

    assert _alembic(_url(path), "upgrade", ROLE_MERGE_REVISION).returncode == 0
    assert EXCLUDED_TABLE in _tables(path)

    assert _alembic(_url(path), "downgrade", PRE_MERGE_REVISION).returncode == 0
    assert EXCLUDED_TABLE not in _tables(path)


def test_check_is_green_again_after_a_downgrade_and_re_upgrade(tmp_path: Path) -> None:
    """The exclusion holds across a round trip, not only on a database built once."""
    path = tmp_path / "roundtrip.db"

    assert _alembic(_url(path), "upgrade", "head").returncode == 0
    assert _alembic(_url(path), "downgrade", PRE_MERGE_REVISION).returncode == 0
    assert _alembic(_url(path), "upgrade", "head").returncode == 0

    result = _check(path)

    assert result.returncode == 0, result.stdout + result.stderr


# --- The hook itself, in the cases the CLI cannot reach ----------------------


def test_the_migration_owned_set_names_exactly_one_table() -> None:
    """A second entry is a decision. This test is the thing that makes it one."""
    assert set(policy.MIGRATION_OWNED_TABLES) == {EXCLUDED_TABLE}


def test_the_harness_owned_set_names_exactly_one_table() -> None:
    """Same rule for the other set, and the same reason.

    The two are kept apart because the arguments for them are different: one table is
    created by a migration and must survive autogeneration, the other is created by the
    test harness and cannot appear in a real database at all.
    """
    assert set(policy.HARNESS_OWNED_TABLES) == {HARNESS_TABLE}


def test_the_two_sets_are_the_whole_exclusion() -> None:
    """Nothing is excluded that is not in one of the two named sets."""
    assert set(policy.EXCLUDED_TABLES) == {EXCLUDED_TABLE, HARNESS_TABLE}


def test_the_hook_excludes_the_harness_table() -> None:
    assert policy.include_object(object(), HARNESS_TABLE, "table", True, None) is False


@pytest.mark.parametrize(
    "near_miss", ["e2e_run_markers", "e2e_run", "run_marker", "e2e_run_marker_old"]
)
def test_a_near_miss_of_the_harness_table_is_not_excluded(near_miss: str) -> None:
    """Matched literally and whole, exactly as the other name is."""
    assert policy.include_object(object(), near_miss, "table", True, None) is True


def test_the_harness_table_is_absent_from_a_migrated_database(database_at_head: Path) -> None:
    """The exclusion cannot be hiding anything in a real database, because it is not there.

    Nothing in the migrations creates it. Only `scripts/e2e_env.py` does, and
    `app.core.e2e_guard` refuses to let that script touch the development, UAT or
    production database -- so the exclusion changes nothing about a check run against one.
    """
    assert HARNESS_TABLE not in _tables(database_at_head)


def test_a_database_carrying_the_harness_table_still_passes(database_at_head: Path) -> None:
    """The case the exclusion exists for: `alembic check` against a scratch E2E database."""
    _execute(
        database_at_head,
        f"create table {HARNESS_TABLE} (run_id text not null, created_at text not null)",
    )

    result = _check(database_at_head)

    assert result.returncode == 0, result.stdout + result.stderr
    assert HARNESS_TABLE in _tables(database_at_head)


def test_real_drift_is_still_reported_beside_the_harness_table(database_at_head: Path) -> None:
    """Adding the second name must not turn the check into one that passes."""
    _execute(
        database_at_head,
        f"create table {HARNESS_TABLE} (run_id text not null, created_at text not null)",
    )
    _execute(database_at_head, "create table stray_unmapped_table (id integer primary key)")

    result = _check(database_at_head)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "stray_unmapped_table" in output
    assert f"Detected removed table '{HARNESS_TABLE}'" not in output


def test_the_hook_excludes_the_reflected_unmapped_table() -> None:
    assert policy.include_object(object(), EXCLUDED_TABLE, "table", True, None) is False


def test_the_hook_stops_applying_the_moment_the_table_is_mapped() -> None:
    """If a model is ever added for it, it is compared like anything else, from that commit.

    This is the branch that keeps the exclusion from outliving its reason, and no CLI run
    can exercise it while the table is unmapped.
    """
    mapped_counterpart = object()

    assert (
        policy.include_object(object(), EXCLUDED_TABLE, "table", True, mapped_counterpart) is True
    )


def test_the_hook_covers_tables_only() -> None:
    """A column or index that happens to share the name is not what was excluded."""
    assert policy.include_object(object(), EXCLUDED_TABLE, "column", True, None) is True
    assert policy.include_object(object(), EXCLUDED_TABLE, "index", True, None) is True


def test_the_hook_includes_everything_else() -> None:
    assert policy.include_object(object(), "customers", "table", True, None) is True
    assert policy.include_object(object(), "users", "table", False, None) is True
