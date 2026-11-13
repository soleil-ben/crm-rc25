"""AC-14 and AC-17: derived activity, lifecycle rules, and financial handling."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.enums import BookingState, LifecycleStatus, RouteGroup
from app.core.time_utils import utcnow
from app.services.activity_service import (
    LifecycleThresholds,
    compute_customer_activity,
    lifecycle_status_for,
)
from tests.conftest import add_shipment, make_customer

THRESHOLDS = LifecycleThresholds()


def test_drafts_and_cancellations_do_not_count(db):
    customer = make_customer(db)
    add_shipment(db, customer, days_ago=10)
    add_shipment(db, customer, days_ago=8, booking_state=BookingState.DRAFT, handoff=False)
    add_shipment(db, customer, days_ago=6, cancelled=True)

    activity = compute_customer_activity(db, customer, THRESHOLDS)
    assert activity.total_qualifying_shipments == 1
    # Bookings include the cancelled booking but never the draft.
    assert activity.total_bookings == 2


def test_confirmed_without_handoff_does_not_count(db):
    """A label-created-only record is not physical custody (CRM.md section 4)."""
    customer = make_customer(db)
    add_shipment(db, customer, days_ago=5, handoff=False)
    activity = compute_customer_activity(db, customer, THRESHOLDS)
    assert activity.total_qualifying_shipments == 0
    assert activity.lifecycle_status == LifecycleStatus.PROSPECT


def test_returns_do_not_count_as_another_outbound_shipment(db):
    customer = make_customer(db)
    add_shipment(db, customer, days_ago=20)
    add_shipment(db, customer, days_ago=10, is_return=True)
    activity = compute_customer_activity(db, customer, THRESHOLDS)
    assert activity.total_qualifying_shipments == 1
    assert activity.is_repeat_customer is False


def test_repeat_customer_needs_two_qualifying_shipments(db):
    customer = make_customer(db)
    add_shipment(db, customer, days_ago=40)
    assert compute_customer_activity(db, customer, THRESHOLDS).is_repeat_customer is False
    add_shipment(db, customer, days_ago=10)
    assert compute_customer_activity(db, customer, THRESHOLDS).is_repeat_customer is True


def test_first_and_last_shipment_use_first_handoff(db):
    customer = make_customer(db)
    add_shipment(db, customer, days_ago=50)
    add_shipment(db, customer, days_ago=5)
    activity = compute_customer_activity(db, customer, THRESHOLDS)
    now = utcnow()
    assert (now - activity.first_shipment_at).days == 50
    assert (now - activity.last_shipment_at).days == 5


def test_observed_route_is_derived_not_declared(db):
    customer = make_customer(db, primary_route_group=RouteGroup.CAD.value)
    add_shipment(db, customer, days_ago=20, route_group=RouteGroup.VCA)
    add_shipment(db, customer, days_ago=10, route_group=RouteGroup.VCA)
    add_shipment(db, customer, days_ago=5, route_group=RouteGroup.CAV)

    activity = compute_customer_activity(db, customer, THRESHOLDS)
    assert customer.primary_route_group == RouteGroup.CAD
    assert activity.observed_primary_route_group == RouteGroup.VCA
    assert activity.route_counts == {"VCA": 2, "CAV": 1}


@pytest.mark.parametrize(
    ("count", "days", "expected"),
    [
        (0, None, LifecycleStatus.PROSPECT),
        (1, 5, LifecycleStatus.NEW),
        (1, 45, LifecycleStatus.ACTIVE),
        (3, 10, LifecycleStatus.ACTIVE),
        (2, 75, LifecycleStatus.AT_RISK),
        (2, 120, LifecycleStatus.INACTIVE),
    ],
)
def test_lifecycle_rules(count, days, expected):
    now = utcnow()
    last = now - timedelta(days=days) if days is not None else None
    assert (
        lifecycle_status_for(
            is_archived=False,
            qualifying_count=count,
            last_shipment_at=last,
            thresholds=THRESHOLDS,
            now=now,
        )
        == expected
    )


def test_archived_outranks_derived_lifecycle():
    now = utcnow()
    assert (
        lifecycle_status_for(
            is_archived=True,
            qualifying_count=5,
            last_shipment_at=now - timedelta(days=1),
            thresholds=THRESHOLDS,
            now=now,
        )
        == LifecycleStatus.ARCHIVED
    )


def test_configurable_thresholds_change_the_result():
    now = utcnow()
    strict = LifecycleThresholds(new_days=7, active_days=14, at_risk_days=21)
    assert (
        lifecycle_status_for(
            is_archived=False,
            qualifying_count=2,
            last_shipment_at=now - timedelta(days=20),
            thresholds=strict,
            now=now,
        )
        == LifecycleStatus.AT_RISK
    )
    assert (
        lifecycle_status_for(
            is_archived=False,
            qualifying_count=2,
            last_shipment_at=now - timedelta(days=20),
            thresholds=THRESHOLDS,
            now=now,
        )
        == LifecycleStatus.ACTIVE
    )


def test_financials_keep_currencies_separate(db):
    customer = make_customer(db)
    add_shipment(db, customer, days_ago=30, currency="CAD", selling_amount=100, shipping_cost=40)
    add_shipment(db, customer, days_ago=20, currency="USD", selling_amount=200, shipping_cost=90)

    activity = compute_customer_activity(
        db, customer, THRESHOLDS, include_financials=True, include_costs=True
    )
    currencies = {bucket.currency: bucket for bucket in activity.financial_by_currency}
    assert set(currencies) == {"CAD", "USD"}
    assert float(currencies["CAD"].recorded_revenue) == 100.0
    assert float(currencies["USD"].recorded_revenue) == 200.0
    # No combined total is produced anywhere.
    assert len(activity.financial_by_currency) == 2


def test_missing_financials_are_unknown_not_zero(db):
    customer = make_customer(db)
    add_shipment(db, customer, days_ago=30, currency="CAD", selling_amount=100, shipping_cost=None)
    add_shipment(db, customer, days_ago=20, currency=None)

    activity = compute_customer_activity(
        db, customer, THRESHOLDS, include_financials=True, include_costs=True
    )
    bucket = activity.financial_by_currency[0]
    assert bucket.shipments_with_revenue == 1
    assert bucket.shipments_with_cost == 0
    # Gross profit is None (unknown), not revenue-minus-zero.
    assert bucket.gross_profit is None
    assert activity.financial_coverage_shipments == 1
    assert activity.total_qualifying_shipments == 2


def test_customer_list_reflects_derived_values(db, as_admin):
    customer = make_customer(db, full_name="Derived Values")
    add_shipment(db, customer, days_ago=70)
    add_shipment(db, customer, days_ago=65)

    item = as_admin.get("/api/v1/customers").json()["items"][0]
    assert item["total_qualifying_shipments"] == 2
    assert item["lifecycle_status"] == LifecycleStatus.AT_RISK
