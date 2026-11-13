"""UAT round 3: the shipment and report corrections, each stated as the behaviour wanted.

* the shipment detail omits ``financials.costs`` for a role without cost access, rather
  than sending ``"costs": null``; an admin still receives the block;
* "N booking(s) were cancelled" honours the route filter like the figures it qualifies;
* a cancelled booking refuses a new operational event, whatever the client sends.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Role, RouteGroup
from app.models import OrganizationSettings, ShipmentEvent
from app.services import booking_service, event_service, report_service
from app.services.errors import ConflictError
from tests.conftest import add_shipment, booked_shipment, make_customer


@pytest.fixture
def priced(db: Session):
    customer = make_customer(db, email="uat3.priced@demo.example.com")
    booking = booked_shipment(db, customer, RouteGroup.CAV)
    booking.currency = "CAD"
    booking.selling_amount = 220
    booking.shipping_cost = 140
    db.commit()
    return booking


# --- Cost block: omitted, not null ---------------------------------------------------


def test_an_admin_still_receives_the_cost_block(api_for, priced):
    body = api_for(Role.ADMIN).get(f"/api/v1/shipments/{priced.id}").json()
    assert body["financials"]["costs"]["shipping_cost"] == "140.00"


@pytest.mark.parametrize("role", [Role.OPERATIONS, Role.READ_ONLY_MANAGER])
def test_a_role_without_cost_access_receives_no_costs_key(api_for, priced, role):
    response = api_for(role).get(f"/api/v1/shipments/{priced.id}")
    assert response.status_code == 200, response.text
    financials = response.json()["financials"]
    assert financials["selling_amount"] == "220.00"
    # Absent, not `null`: the key alone would say a cost exists.
    assert "costs" not in financials
    assert '"costs"' not in response.text


def test_saving_amounts_as_operations_also_omits_the_costs_key(api_for, priced):
    response = api_for(Role.OPERATIONS).patch(
        f"/api/v1/shipments/{priced.id}/financials", json={"selling_amount": "230"}
    )
    assert response.status_code == 200, response.text
    assert "costs" not in response.json()["financials"]


# --- The cancelled count honours the route filter --------------------------------------


def _cancelled_note(notes: list[str]) -> str | None:
    return next((note for note in notes if "were cancelled" in note), None)


def test_the_cancelled_count_honours_the_route_filter(db):
    org = db.scalar(select(OrganizationSettings))
    customer = make_customer(db, email="uat3.routes@demo.example.com")
    add_shipment(db, customer, days_ago=3, route_group=RouteGroup.CAV, cancelled=True)
    add_shipment(db, customer, days_ago=3, route_group=RouteGroup.CAV, cancelled=True)
    add_shipment(db, customer, days_ago=4, route_group=RouteGroup.VCA, cancelled=True)
    period = report_service.resolve_period(from_date=None, to_date=None, org=org)

    everything = _cancelled_note(report_service.coverage_notes(db, period))
    cav = _cancelled_note(report_service.coverage_notes(db, period, [RouteGroup.CAV.value]))
    vca = _cancelled_note(report_service.coverage_notes(db, period, [RouteGroup.VCA.value]))
    cad = _cancelled_note(report_service.coverage_notes(db, period, [RouteGroup.CAD.value]))

    assert everything is not None and everything.startswith("3 booking(s)")
    assert cav is not None and cav.startswith("2 booking(s)")
    assert vca is not None and vca.startswith("1 booking(s)")
    # No cancellation on the selected route: no note claiming one.
    assert cad is None


def test_the_reports_route_passes_the_filter_to_the_cancelled_count(as_admin, db):
    customer = make_customer(db, email="uat3.api@demo.example.com")
    add_shipment(db, customer, days_ago=3, route_group=RouteGroup.CAV, cancelled=True)
    add_shipment(db, customer, days_ago=4, route_group=RouteGroup.VCA, cancelled=True)

    unfiltered = as_admin.get("/api/v1/reports").json()["coverage_notes"]
    filtered = as_admin.get("/api/v1/reports", params={"route_group": "VCA"}).json()[
        "coverage_notes"
    ]

    assert _cancelled_note(unfiltered).startswith("2 booking(s)")
    assert _cancelled_note(filtered).startswith("1 booking(s)")


# --- A cancelled booking takes no new events ------------------------------------------


@pytest.fixture
def cancelled(db: Session):
    customer = make_customer(db, email="uat3.cancelled@demo.example.com")
    booking = booked_shipment(db, customer, RouteGroup.CAV, packages=2)
    booking_service.cancel_shipment(db, booking, reason="Customer withdrew")
    db.commit()
    return booking


def test_the_service_refuses_an_event_on_a_cancelled_booking(db, cancelled):
    with pytest.raises(ConflictError, match="cancelled"):
        event_service.record_event(db, cancelled, {"event_type": "in_transit"})
    assert (
        db.scalar(select(ShipmentEvent.id).where(ShipmentEvent.shipment_id == cancelled.id)) is None
    )


def test_the_api_refuses_an_event_on_a_cancelled_booking(as_admin, db, cancelled):
    response = as_admin.post(
        f"/api/v1/shipments/{cancelled.id}/events", json={"event_type": "in_transit"}
    )
    assert response.status_code == 409, response.text
    assert "cancelled" in response.json()["message"]
    assert (
        db.scalar(select(ShipmentEvent.id).where(ShipmentEvent.shipment_id == cancelled.id)) is None
    )


def test_a_live_booking_still_takes_events(as_admin, db):
    customer = make_customer(db, email="uat3.live@demo.example.com")
    booking = booked_shipment(db, customer, RouteGroup.CAV)
    response = as_admin.post(
        f"/api/v1/shipments/{booking.id}/events", json={"event_type": "in_transit"}
    )
    assert response.status_code == 201, response.text
