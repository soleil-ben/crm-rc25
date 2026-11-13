"""Manual operational events and the derived overall status.

Covers CRM.md AC-7 (one of three delivered is Partially delivered), AC-8 (an
intermediate warehouse is not final delivery), and the rule that a late or older event
must not regress a newer valid state.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.enums import OperationalState, RouteGroup, ShipmentEventType
from app.core.time_utils import utcnow
from app.models import ShipmentEvent
from app.services import event_service, package_service
from app.services.errors import ConflictError, ValidationError
from tests.conftest import booked_shipment, make_customer, make_draft


def record(db, shipment, event_type, *, package=None, minutes_ago=0, **extra):
    payload = {
        "event_type": event_type,
        "occurred_at": utcnow() - timedelta(minutes=minutes_ago),
        "package_id": package.id if package else None,
        **extra,
    }
    events = event_service.record_event(db, shipment, payload)
    db.commit()
    return events


# --- Partial delivery ------------------------------------------------------


def test_one_of_three_delivered_is_partially_delivered(db: Session):
    """AC-7."""
    customer = make_customer(db, email="partial@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=3)
    packages = package_service.active_packages(db, shipment.id)

    record(db, shipment, ShipmentEventType.DELIVERED_TO_RECIPIENT, package=packages[0])
    db.refresh(shipment)

    assert shipment.operational_state == OperationalState.PARTIALLY_DELIVERED
    assert shipment.operational_state != OperationalState.DELIVERED
    progress = package_service.progress(db, shipment.id)
    assert progress.delivered == 1
    assert progress.active == 3
    assert progress.summary == "1 of 3 packages delivered"
    assert shipment.delivered_at is None


def test_all_three_delivered_is_delivered(db: Session):
    customer = make_customer(db, email="alldelivered@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=3)
    for package in package_service.active_packages(db, shipment.id):
        record(db, shipment, ShipmentEventType.DELIVERED_TO_RECIPIENT, package=package)
    db.refresh(shipment)

    assert shipment.operational_state == OperationalState.DELIVERED
    assert shipment.delivered_at is not None
    assert package_service.progress(db, shipment.id).summary == "3 of 3 packages delivered"


def test_a_cancelled_package_does_not_block_overall_delivery(db: Session):
    """Cancelled packages are handled explicitly rather than corrupting the count."""
    customer = make_customer(db, email="cancelprogress@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=3)
    packages = package_service.active_packages(db, shipment.id)
    package_service.cancel_package(db, packages[2], reason="Held back by the customer")
    db.commit()

    for package in packages[:2]:
        record(db, shipment, ShipmentEventType.DELIVERED_TO_RECIPIENT, package=package)
    db.refresh(shipment)

    assert shipment.operational_state == OperationalState.DELIVERED
    progress = package_service.progress(db, shipment.id)
    assert progress.summary == "2 of 2 packages delivered"
    assert progress.cancelled == 1


# --- Intermediate warehouse ------------------------------------------------


def test_warehouse_receipt_does_not_deliver_a_vietnam_bound_shipment(db: Session):
    """AC-8: a UPS delivery to the Solaris Canadian warehouse is a milestone."""
    customer = make_customer(db, email="warehouse@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV, packages=2)

    record(
        db,
        shipment,
        ShipmentEventType.RECEIVED_AT_SOLARIS,
        location_label="Solaris Mississauga warehouse",
        location_country_code="CA",
    )
    db.refresh(shipment)

    assert shipment.operational_state == OperationalState.RECEIVED_AT_SOLARIS
    assert shipment.operational_state != OperationalState.DELIVERED
    assert shipment.delivered_at is None
    assert package_service.progress(db, shipment.id).delivered == 0
    # The destination is still Vietnam.
    assert shipment.recipient_country_code == "VN"


def test_arrival_at_destination_is_not_delivery(db: Session):
    customer = make_customer(db, email="arrived@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)
    record(db, shipment, ShipmentEventType.ARRIVED_DESTINATION, location_country_code="VN")
    db.refresh(shipment)
    assert shipment.operational_state == OperationalState.ARRIVED_DESTINATION
    assert package_service.progress(db, shipment.id).delivered == 0


def test_collection_point_handover_is_not_final_delivery(db: Session):
    """CRM.md section 10: a collection point is separate from confirmed final delivery."""
    customer = make_customer(db, email="collection@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD)
    record(db, shipment, ShipmentEventType.DELIVERED_TO_COLLECTION_POINT)
    db.refresh(shipment)

    assert shipment.operational_state != OperationalState.DELIVERED
    assert package_service.progress(db, shipment.id).delivered == 0


def test_only_a_recipient_delivery_event_may_be_marked_final(db: Session):
    customer = make_customer(db, email="notfinal@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)
    with pytest.raises(ValidationError) as excinfo:
        event_service.record_event(
            db,
            shipment,
            {
                "event_type": ShipmentEventType.RECEIVED_AT_SOLARIS,
                "is_final_recipient_delivery": True,
            },
        )
    assert "milestone" in str(excinfo.value)


# --- Ordering and regression ----------------------------------------------


def test_an_older_event_recorded_late_does_not_regress_delivered(db: Session):
    customer = make_customer(db, email="regress@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD)
    package = package_service.active_packages(db, shipment.id)[0]

    record(db, shipment, ShipmentEventType.DELIVERED_TO_RECIPIENT, package=package, minutes_ago=10)
    db.refresh(shipment)
    assert shipment.operational_state == OperationalState.DELIVERED

    # A courier's paperwork arrives late: an In transit event from three hours ago.
    record(db, shipment, ShipmentEventType.IN_TRANSIT, package=package, minutes_ago=180)
    db.refresh(package)
    db.refresh(shipment)

    assert shipment.operational_state == OperationalState.DELIVERED
    assert package.operational_state == OperationalState.DELIVERED
    assert package.delivered_to_recipient_at is not None
    # occurred_at and recorded_at are stored separately, so the late entry is visible.
    late = db.query(ShipmentEvent).filter_by(event_type=ShipmentEventType.IN_TRANSIT).one()
    assert late.recorded_at > late.occurred_at


def test_a_newer_event_does_advance_state(db: Session):
    customer = make_customer(db, email="advance@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD)
    record(db, shipment, ShipmentEventType.IN_TRANSIT, minutes_ago=120)
    record(db, shipment, ShipmentEventType.OUT_FOR_DELIVERY, minutes_ago=10)
    db.refresh(shipment)
    assert shipment.operational_state == OperationalState.OUT_FOR_DELIVERY


def test_a_future_event_is_rejected(db: Session):
    customer = make_customer(db, email="future@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD)
    with pytest.raises(ValidationError) as excinfo:
        event_service.record_event(
            db,
            shipment,
            {
                "event_type": ShipmentEventType.IN_TRANSIT,
                "occurred_at": utcnow() + timedelta(hours=2),
            },
        )
    assert excinfo.value.field == "occurred_at"


def test_the_shipment_is_only_as_advanced_as_its_least_advanced_package(db: Session):
    customer = make_customer(db, email="leastadvanced@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV, packages=2)
    packages = package_service.active_packages(db, shipment.id)

    record(db, shipment, ShipmentEventType.IN_TRANSIT, package=packages[0])
    record(db, shipment, ShipmentEventType.RECEIVED_AT_SOLARIS, package=packages[1])
    db.refresh(shipment)
    assert shipment.operational_state == OperationalState.RECEIVED_AT_SOLARIS


def test_an_exception_on_one_package_surfaces_on_the_shipment(db: Session):
    customer = make_customer(db, email="exception@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV, packages=2)
    packages = package_service.active_packages(db, shipment.id)
    record(db, shipment, ShipmentEventType.IN_TRANSIT, package=packages[0])
    record(db, shipment, ShipmentEventType.EXCEPTION, package=packages[1])
    db.refresh(shipment)
    assert shipment.operational_state == OperationalState.EXCEPTION


def test_voiding_an_event_recomputes_state_and_preserves_history(db: Session):
    customer = make_customer(db, email="void@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD)
    created = record(db, shipment, ShipmentEventType.DELIVERED_TO_RECIPIENT)
    db.refresh(shipment)
    assert shipment.operational_state == OperationalState.DELIVERED

    event_service.void_event(db, created[0], reason="Recorded against the wrong shipment")
    db.commit()
    db.refresh(shipment)

    assert shipment.operational_state != OperationalState.DELIVERED
    assert package_service.progress(db, shipment.id).delivered == 0
    # The row survives as history rather than being deleted.
    assert db.query(ShipmentEvent).count() == 1
    assert db.query(ShipmentEvent).one().is_voided is True


# --- Public updates versus internal notes ----------------------------------


def test_internal_detail_is_never_treated_as_a_public_update(db: Session):
    customer = make_customer(db, email="internal@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)
    created = record(
        db,
        shipment,
        ShipmentEventType.IN_TRANSIT,
        internal_detail="Customer owes a balance; hold at the desk.",
    )
    event = created[0]
    assert event.is_public_update is False
    assert event.public_update_text is None
    assert event.internal_detail is not None


def test_a_public_update_needs_its_own_approved_wording(db: Session):
    customer = make_customer(db, email="publictext@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)
    with pytest.raises(ValidationError) as excinfo:
        event_service.record_event(
            db,
            shipment,
            {
                "event_type": ShipmentEventType.IN_TRANSIT,
                "is_public_update": True,
                "internal_detail": "Something internal",
            },
        )
    assert excinfo.value.field == "public_update_text"


def test_public_wording_without_the_flag_is_refused(db: Session):
    customer = make_customer(db, email="unflagged@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)
    with pytest.raises(ValidationError) as excinfo:
        event_service.record_event(
            db,
            shipment,
            {
                "event_type": ShipmentEventType.IN_TRANSIT,
                "public_update_text": "Your parcel has left Toronto.",
            },
        )
    assert excinfo.value.field == "is_public_update"


def test_the_list_latest_update_never_shows_internal_detail(as_admin, db: Session):
    customer = make_customer(db, email="listupdate@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)
    record(
        db,
        shipment,
        ShipmentEventType.IN_TRANSIT,
        internal_detail="Do not tell the customer about the delay cause.",
    )
    listed = as_admin.get("/api/v1/shipments", params={"customer_id": customer.id}).json()
    latest = listed["items"][0]["latest_update"]
    assert "Do not tell" not in (latest or "")
    assert latest == "In transit"


# --- Guards ----------------------------------------------------------------


def test_events_cannot_be_recorded_against_a_draft(db: Session):
    customer = make_customer(db, email="draftevent@demo.example.com")
    shipment = make_draft(db, customer, RouteGroup.CAV)
    with pytest.raises(ConflictError) as excinfo:
        event_service.record_event(db, shipment, {"event_type": ShipmentEventType.IN_TRANSIT})
    assert "Confirm the booking" in str(excinfo.value)


def test_events_cannot_be_recorded_against_a_cancelled_package(db: Session):
    customer = make_customer(db, email="cancelledpkgevent@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV, packages=2)
    packages = package_service.active_packages(db, shipment.id)
    package_service.cancel_package(db, packages[1], reason="Withdrawn")
    db.commit()
    with pytest.raises(ConflictError):
        event_service.record_event(
            db,
            shipment,
            {"event_type": ShipmentEventType.IN_TRANSIT, "package_id": packages[1].id},
        )


def test_a_shipment_wide_event_applies_to_every_active_package(db: Session):
    customer = make_customer(db, email="broadcast@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=3)
    created = record(db, shipment, ShipmentEventType.DEPARTED_ORIGIN)
    assert len(created) == 3
    assert {event.package_id for event in created} == {
        package.id for package in package_service.active_packages(db, shipment.id)
    }


def test_first_handoff_is_set_by_the_first_custody_event(db: Session):
    """The qualifying-shipment trigger comes from a real custody event, not the booking."""
    customer = make_customer(db, email="handoff@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)
    assert shipment.first_handoff_at is None

    record(db, shipment, ShipmentEventType.RECEIVED_AT_SOLARIS, minutes_ago=30)
    db.refresh(shipment)
    first = shipment.first_handoff_at
    assert first is not None

    record(db, shipment, ShipmentEventType.IN_TRANSIT, minutes_ago=5)
    db.refresh(shipment)
    assert shipment.first_handoff_at == first
