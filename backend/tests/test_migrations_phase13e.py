"""The Phase 13E migration: eight new tables, nothing else, from empty and populated databases."""

from __future__ import annotations

import sqlite3

from tests.test_migrations_phase10 import _write_phase_9_rows
from tests.test_migrations_phase13c import PHASE_13C_REVISION, _alembic, _tables

PHASE_13E_REVISION = "d1f6b4c8e2a9"
PHASE_13E_TABLES = {
    "finance_settings",
    "customer_invoices",
    "customer_invoice_lines",
    "customer_payments",
    "vendor_invoices",
    "vendor_invoice_lines",
    "cost_allocations",
    "period_closes",
}


def _schema_without_13e(path) -> dict[str, str]:
    with sqlite3.connect(path) as c:
        rows = c.execute("select name, sql from sqlite_master where sql is not null").fetchall()
    return {
        name: sql
        for name, sql in rows
        if not any(name == t or name.startswith((f"ix_{t}", f"uq_{t}")) for t in PHASE_13E_TABLES)
    }


def _counts(path) -> dict[str, int]:
    with sqlite3.connect(path) as c:
        return {
            t: c.execute(f"select count(*) from {t}").fetchone()[0]  # noqa: S608
            for t in sorted(_tables(path) - PHASE_13E_TABLES)
            if t != "alembic_version"
        }


def test_upgrades_an_empty_database_to_phase_13e(tmp_path):
    url = f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"
    assert _alembic(url, "upgrade", PHASE_13E_REVISION).returncode == 0
    assert PHASE_13E_REVISION in _alembic(url, "current").stdout
    assert _tables(tmp_path / "empty.db") >= PHASE_13E_TABLES


OWNER_ANSWERS_REVISION = "e4a7c2d9f1b3"


def test_the_owner_answers_revision_adds_one_table_and_goes_back(tmp_path):
    url = f"sqlite:///{(tmp_path / 'oa.db').as_posix()}"
    assert _alembic(url, "upgrade", OWNER_ANSWERS_REVISION).returncode == 0
    assert OWNER_ANSWERS_REVISION in _alembic(url, "current").stdout
    assert "payment_conversions" in _tables(tmp_path / "oa.db")
    assert _alembic(url, "downgrade", PHASE_13E_REVISION).returncode == 0
    assert "payment_conversions" not in _tables(tmp_path / "oa.db")


def test_a_populated_database_upgrades_in_place_and_downgrades_back(tmp_path):
    path = tmp_path / "populated.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", PHASE_13C_REVISION).returncode == 0
    _write_phase_9_rows(path)
    counts, schema = _counts(path), _schema_without_13e(path)
    upgraded = _alembic(url, "upgrade", PHASE_13E_REVISION)
    assert upgraded.returncode == 0, upgraded.stderr
    assert _counts(path) == counts
    assert _schema_without_13e(path) == schema, "the migration altered an existing table"
    with sqlite3.connect(path) as c:
        assert c.execute("pragma integrity_check").fetchone()[0] == "ok"
        assert c.execute("pragma foreign_key_check").fetchall() == []
    assert _alembic(url, "downgrade", PHASE_13C_REVISION).returncode == 0
    assert PHASE_13E_TABLES.isdisjoint(_tables(path))
    assert _counts(path) == counts and _schema_without_13e(path) == schema


def test_financial_records_hold_what_they_point_at(tmp_path):
    path = tmp_path / "fk.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", PHASE_13E_REVISION).returncode == 0
    with sqlite3.connect(path) as c:
        fks = {
            (t, r[3]): (r[2], r[6])
            for t in PHASE_13E_TABLES
            for r in c.execute(f"pragma foreign_key_list({t})")
        }
        for name in ("uq_customer_invoices_live_shipment", "uq_vendor_invoices_live_consolidation"):
            sql = c.execute("select sql from sqlite_master where name = ?", (name,)).fetchone()[0]
            assert "UNIQUE" in sql.upper() and "WHERE" in sql.upper(), name
    assert fks[("customer_invoices", "shipment_id")] == ("shipments", "RESTRICT")
    assert fks[("customer_invoices", "quote_version_id")] == ("quote_versions", "RESTRICT")
    assert fks[("customer_payments", "invoice_id")] == ("customer_invoices", "RESTRICT")
    assert fks[("vendor_invoices", "consolidation_id")] == ("consolidations", "RESTRICT")
    assert fks[("cost_allocations", "shipment_id")] == ("shipments", "RESTRICT")
