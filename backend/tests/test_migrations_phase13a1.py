"""The customer-prefix migration: ``CUS-`` → ``STCA-`` with the former identifier as an alias.

OD-42 / DEC-0174. A Phase 13A database is built with two ``CUS-`` customers, one of them
already carrying a merge alias, plus one alias that collides with the rename; the upgrade must
rename both customers, write exactly one new alias per customer that lacked one, leave the merge
alias alone, and the downgrade must put everything back.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app.core.db import build_engine
from app.services import customer_service
from tests.test_migrations_phase10 import _write_phase_9_rows

BACKEND_ROOT = Path(__file__).resolve().parents[1]

PHASE_13A_REVISION = "f53efaa7773e"
PREFIX_REVISION = "a7c3e1d9b2f4"
REASON = "prefix_change_2026_10_19"


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


def _seed(path: Path) -> None:
    """The project's own Phase 9 row-writer: customers under ``CUS-``, one with a merge alias."""
    _write_phase_9_rows(path)


def _state(path: Path) -> tuple[list[tuple], list[tuple]]:
    connection = sqlite3.connect(path)
    try:
        customers = connection.execute("select id, public_id from customers order by id").fetchall()
        aliases = connection.execute(
            "select customer_id, alias_public_id, reason from customer_id_aliases order by id"
        ).fetchall()
    finally:
        connection.close()
    return customers, aliases


def test_upgrade_renames_and_aliases_and_downgrade_restores(tmp_path):
    path = tmp_path / "prefix.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", PHASE_13A_REVISION).returncode == 0
    _seed(path)

    customers_before, aliases_before = _state(path)
    assert customers_before and all(pid.startswith("CUS-") for _, pid in customers_before)
    assert all(reason == "merge" for _, _, reason in aliases_before)

    upgraded = _alembic(url, "upgrade", PREFIX_REVISION)
    assert upgraded.returncode == 0, upgraded.stderr
    customers, aliases = _state(path)
    assert customers == [(cid, "STCA-" + pid[len("CUS-") :]) for cid, pid in customers_before]
    new_aliases = [a for a in aliases if a[2] == REASON]
    assert aliases[: len(aliases_before)] == aliases_before, "merge aliases must be untouched"
    assert sorted(new_aliases) == sorted((cid, pid, REASON) for cid, pid in customers_before)

    # Down restores every identifier and removes only this revision's aliases; up again is the
    # same result as the first time.
    assert _alembic(url, "downgrade", PHASE_13A_REVISION).returncode == 0
    assert _state(path) == (customers_before, aliases_before)
    assert _alembic(url, "upgrade", PREFIX_REVISION).returncode == 0
    assert _state(path) == (customers, aliases)
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("pragma integrity_check").fetchone()[0] == "ok"
        assert connection.execute("pragma foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_a_former_identifier_still_resolves_through_the_alias(tmp_path):
    path = tmp_path / "resolve.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", PHASE_13A_REVISION).returncode == 0
    _seed(path)
    assert _alembic(url, "upgrade", "head").returncode == 0

    engine = build_engine(url)
    try:
        with sessionmaker(bind=engine, future=True)() as db:
            by_new = customer_service.get_customer_by_public_id(db, "STCA-000001")
            by_old = customer_service.get_customer_by_public_id(db, "CUS-000001")
            by_merge_alias = customer_service.get_customer_by_public_id(db, "CUS-000009")
            assert by_new is not None and by_new.id == 1
            assert by_old is not None and by_old.id == 1
            assert by_merge_alias is not None and by_merge_alias.id == 2
            assert customer_service.get_customer_by_public_id(db, "STCA-000009") is None
    finally:
        engine.dispose()


def test_new_customers_continue_the_sequence_under_the_new_prefix(db):
    from tests.conftest import make_customer  # noqa: PLC0415

    first = make_customer(db, email="first@demo.example.com")
    second = make_customer(db, email="second@demo.example.com")
    assert first.public_id == "STCA-000001"
    assert second.public_id == "STCA-000002"
