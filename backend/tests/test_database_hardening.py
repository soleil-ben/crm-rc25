"""SQLite hardening required by CRM.md section 3.

Foreign key enforcement in SQLite is per-connection, so it is not enough to switch it on
once at startup; it must hold for every connection the pool hands out. These tests verify
the pragmas and prove that a foreign key is genuinely enforced rather than merely declared.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.db import build_engine
from app.models import Base, Customer, FollowUpTask, Shipment
from tests.conftest import add_shipment, make_customer


def test_pragmas_are_applied_to_every_connection(engine):
    """Check several connections, not just the first one out of the pool."""
    for _ in range(3):
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
            assert connection.execute(text("PRAGMA busy_timeout")).scalar() == (
                settings.sqlite_busy_timeout_ms
            )
            assert connection.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"


def test_foreign_keys_are_actually_enforced(db):
    """A dangling reference must be rejected, not silently accepted."""
    task = FollowUpTask(customer_id=999_999, subject="Orphan", status="not_scheduled")
    db.add(task)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_deleting_a_customer_with_shipments_is_restricted(db):
    """Shipment history is never cascade-deleted with a customer (CRM.md section 15)."""
    customer = make_customer(db, full_name="Has History")
    add_shipment(db, customer, days_ago=10)

    db.delete(customer)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # Both records survive the failed delete.
    assert db.get(Customer, customer.id) is not None
    assert db.scalar(select(Shipment).where(Shipment.customer_id == customer.id)) is not None


def test_child_records_cascade_when_intended(db):
    """Tasks belong to their customer, so an explicit customer delete removes them."""
    customer = make_customer(db, full_name="No History", email="nohistory@demo.example.com")
    db.add(FollowUpTask(customer_id=customer.id, subject="Call", status="not_scheduled"))
    db.commit()

    db.delete(customer)
    db.commit()

    assert db.scalar(select(FollowUpTask).where(FollowUpTask.customer_id == customer.id)) is None


def test_in_memory_engine_skips_wal_but_keeps_foreign_keys():
    """An in-memory database cannot use WAL; foreign keys must still be enforced."""
    engine = build_engine("sqlite://")
    try:
        Base.metadata.create_all(engine)
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
            assert connection.execute(text("PRAGMA journal_mode")).scalar().lower() != "wal"
    finally:
        engine.dispose()


def test_database_file_is_outside_the_source_tree():
    """The configured default keeps the database out of backend/ and out of version control."""
    path = settings.sqlite_path
    if path is None:
        pytest.skip("Not configured for a file-backed SQLite database.")
    parts = {part.lower() for part in path.parts}
    assert "backend" not in parts
    assert "frontend" not in parts
