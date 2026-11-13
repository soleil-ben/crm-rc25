"""The CA-SHP-10 fixture: a booking at 23:30 Toronto time, which is the next UTC day.

`CA-SHP-10` filters the Customer Account by date and expects an evening booking to fall on
its **local** day. That can only be tested with a booking whose UTC date differs from its
Toronto date, so the seed makes one, and these tests hold it to that:

* the stored (naive UTC) timestamp is on the day *after* the Toronto booking date, and is
  exactly 23:30 in Toronto -- in summer and in winter, because the offset changes;
* it is non-demo and on the customer, so the Customer Account lists it at all;
* the Customer Account's own date filter puts it on the local day and not the UTC one;
* `uat_env.py --check` finds it.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app import seed
from app.models import Customer, Shipment
from app.services import customer_account_shipment_service as account_shipments
from tests.conftest import make_customer

TORONTO = ZoneInfo("America/Toronto")
REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_uat_env():
    path = REPO_ROOT / "scripts" / "uat_env.py"
    spec = importlib.util.spec_from_file_location("uat_env_late_evening", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _seeded(db, users, now: datetime) -> Shipment:
    customer = make_customer(db)
    shipment = seed._seed_late_evening_shipment(db, customer, actor=users["operations"], now=now)
    db.commit()
    db.expire_all()
    return db.get(Shipment, shipment.id)


@pytest.mark.parametrize(
    ("now", "expected_utc", "local_day"),
    [
        # Summer: EDT, UTC-4. 23:30 on 10 July is 03:30 UTC on 11 July.
        (datetime(2026, 7, 20, 12, 0), datetime(2026, 7, 11, 3, 30), date(2026, 7, 10)),
        # Winter: EST, UTC-5. 23:30 on 10 January is 04:30 UTC on 11 January.
        (datetime(2026, 1, 20, 12, 0), datetime(2026, 1, 11, 4, 30), date(2026, 1, 10)),
    ],
)
def test_the_stored_utc_timestamp_crosses_the_utc_date_and_is_2330_in_toronto(
    db, users, now, expected_utc, local_day
):
    shipment = _seeded(db, users, now)

    assert shipment.booking_date == expected_utc
    assert shipment.booking_date.date() == date.fromordinal(local_day.toordinal() + 1)

    in_toronto = shipment.booking_date.replace(tzinfo=ZoneInfo("UTC")).astimezone(TORONTO)
    assert in_toronto.date() == local_day
    assert in_toronto.time() == time(23, 30)


def test_it_is_a_non_demo_shipment_the_customer_account_lists(db, users):
    shipment = _seeded(db, users, datetime(2026, 7, 20, 12, 0))
    assert shipment.is_demo_record is False
    assert shipment.booking_reference == seed.LATE_EVENING_BOOKING_REFERENCE
    # Every event follows the booking, so the timeline does not run backwards.
    assert shipment.first_handoff_at > shipment.booking_date
    assert all(event.occurred_at > shipment.booking_date for event in shipment.events)


def test_the_account_date_filter_puts_it_on_its_local_day(db, users):
    """The behaviour CA-SHP-10 checks, at the service the Customer Account calls."""
    shipment = _seeded(db, users, datetime(2026, 7, 20, 12, 0))
    customer = db.get(Customer, shipment.customer_id)

    def listed(day_from: str, day_to: str) -> list[str]:
        filters = account_shipments.parse_filters(
            status_group=None,
            booked_from=day_from,
            booked_to=day_to,
            limit=None,
            offset=None,
            timezone_name="America/Toronto",
        )
        page = account_shipments.list_shipments(
            db, customer=customer, filters=filters, timezone_name="America/Toronto"
        )
        return [item.shipment_reference for item in page.items]

    assert shipment.public_id in listed("2026-07-10", "2026-07-10")
    assert shipment.public_id not in listed("2026-07-09", "2026-07-09")
    # The UTC date. Cutting on UTC midnight would wrongly put it here.
    assert shipment.public_id not in listed("2026-07-11", "2026-07-11")


def test_reseeding_does_not_add_a_second_one(db, users):
    customer = make_customer(db)
    now = datetime(2026, 7, 20, 12, 0)
    assert seed._seed_late_evening_shipment(db, customer, actor=users["operations"], now=now)
    assert (
        seed._seed_late_evening_shipment(db, customer, actor=users["operations"], now=now) is None
    )
    db.commit()
    count = db.scalars(
        select(Shipment).where(Shipment.booking_reference == seed.LATE_EVENING_BOOKING_REFERENCE)
    ).all()
    assert len(count) == 1


def test_uat_env_check_reports_it(db, users, db_path):
    uat_env = _load_uat_env()
    category = next(
        item for item in uat_env.COVERAGE if item.name.startswith("late-evening Toronto booking")
    )
    assert category.required is True

    database = Path(db_path.removeprefix("sqlite:///"))
    with sqlite3.connect(database) as connection:
        assert category.count(connection) == 0
    _seeded(db, users, datetime(2026, 1, 20, 12, 0))
    with sqlite3.connect(database) as connection:
        assert category.count(connection) == 1
