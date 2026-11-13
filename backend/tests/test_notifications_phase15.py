"""Phase 15: a milestone behind the furthest milestone already reached never notifies, whatever
the shipment's current state; a returned or cancelled shipment notifies nothing further."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.enums import RouteGroup, ShipmentEventType
from app.core.time_utils import utcnow
from app.models import NotificationOutbox
from app.services import booking_service, event_service
from app.services import notification_service as ns
from tests.conftest import booked_shipment, make_customer


def _publish(db, shipment, event_type, text="Update", *, days_ago=None):
    payload = {"event_type": event_type, "is_public_update": True, "public_update_text": text}
    if days_ago is not None:
        payload["occurred_at"] = utcnow() - timedelta(days=days_ago)
    created = event_service.record_event(db, shipment, payload)
    db.commit()
    return created


def _milestones(db, shipment_id):
    return [
        r.milestone
        for r in db.query(NotificationOutbox)
        .filter_by(shipment_id=shipment_id)
        .order_by(NotificationOutbox.id)
    ]


@pytest.fixture
def shipment(db):
    return booked_shipment(db, make_customer(db, email="p15@demo.example.com"), RouteGroup.VCA)


def test_on_hold_does_not_let_an_earlier_step_through(db, shipment):
    _publish(db, shipment, ShipmentEventType.OUT_FOR_DELIVERY)
    _publish(db, shipment, ShipmentEventType.EXCEPTION, "On hold awaiting the recipient")
    assert shipment.operational_state == "exception"
    # A late "in transit" recorded while the shipment is on hold: behind out for delivery.
    _publish(db, shipment, ShipmentEventType.IN_TRANSIT, "Late entry", days_ago=2)
    assert _milestones(db, shipment.id) == ["out_for_delivery"]
    assert ns.furthest_reached(db, shipment) == 3


def test_an_exception_keeps_the_furthest_point_and_a_later_step_still_notifies(db, shipment):
    _publish(db, shipment, ShipmentEventType.IN_TRANSIT)
    _publish(db, shipment, ShipmentEventType.DELIVERY_ATTEMPTED, "Nobody home")
    _publish(db, shipment, ShipmentEventType.EXCEPTION, "Address problem")
    _publish(db, shipment, ShipmentEventType.RECEIVED_AT_SOLARIS, "Backdated", days_ago=5)
    assert _milestones(db, shipment.id) == ["in_transit"]
    _publish(db, shipment, ShipmentEventType.OUT_FOR_DELIVERY, "Second attempt")
    assert _milestones(db, shipment.id) == ["in_transit", "out_for_delivery"]


def test_unpublished_and_voided_events_do_not_count_toward_the_furthest_point(db, shipment):
    event_service.record_event(db, shipment, {"event_type": ShipmentEventType.OUT_FOR_DELIVERY})
    voided = _publish(db, shipment, ShipmentEventType.IN_TRANSIT)
    event_service.void_event(db, voided[0], reason="Wrong shipment")
    _publish(db, shipment, ShipmentEventType.EXCEPTION, "Held")
    db.commit()
    assert ns.furthest_reached(db, shipment) == 0
    _publish(db, shipment, ShipmentEventType.RECEIVED_AT_SOLARIS, "Received", days_ago=1)
    assert "received" in _milestones(db, shipment.id)


def test_a_returned_shipment_notifies_nothing_further(db, shipment):
    _publish(db, shipment, ShipmentEventType.RECEIVED_AT_SOLARIS)
    _publish(db, shipment, ShipmentEventType.RETURN_IN_PROGRESS, "Returning")
    _publish(db, shipment, ShipmentEventType.RETURNED, "Returned to sender")
    # A late entry leaves the state returned: nothing.
    _publish(db, shipment, ShipmentEventType.OUT_FOR_DELIVERY, "Late", days_ago=3)
    assert shipment.operational_state == "returned"
    assert _milestones(db, shipment.id) == ["received"]


def test_a_returned_shipment_sent_out_again_notifies_later_milestones(db, shipment):
    _publish(db, shipment, ShipmentEventType.RECEIVED_AT_SOLARIS)
    _publish(db, shipment, ShipmentEventType.IN_TRANSIT)
    _publish(db, shipment, ShipmentEventType.RETURNED, "Returned to sender")
    # Re-dispatched: the state is back on the ladder and later steps notify normally.
    _publish(db, shipment, ShipmentEventType.OUT_FOR_DELIVERY, "Sent out again")
    _publish(db, shipment, ShipmentEventType.DELIVERED_TO_RECIPIENT, "Delivered")
    assert _milestones(db, shipment.id) == [
        "received",
        "in_transit",
        "out_for_delivery",
        "delivered",
    ]


def test_one_parcel_of_three_returned_does_not_close_the_shipment(db):
    from app.services import package_service

    customer = make_customer(db, email="p15three@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=3)
    packages = package_service.active_packages(db, shipment.id)
    _publish(db, shipment, ShipmentEventType.IN_TRANSIT)
    event_service.record_event(
        db,
        shipment,
        {
            "event_type": ShipmentEventType.RETURNED,
            "package_id": packages[0].id,
            "is_public_update": True,
            "public_update_text": "Parcel 1 returned",
        },
    )
    db.commit()
    assert shipment.operational_state != "returned"
    _publish(db, shipment, ShipmentEventType.OUT_FOR_DELIVERY, "The other two")
    assert _milestones(db, shipment.id) == ["in_transit", "out_for_delivery"]


def test_voiding_a_mistaken_return_frees_the_closed_milestone(db, shipment):
    _publish(db, shipment, ShipmentEventType.OUT_FOR_DELIVERY)
    returned = _publish(db, shipment, ShipmentEventType.RETURNED, "Recorded by mistake")
    ns.dispatch_pending(db)
    db.commit()
    closed = db.query(NotificationOutbox).filter_by(shipment_id=shipment.id).one()
    assert (closed.status, closed.skip_reason) == ("skipped", "closed")
    assert closed.dedup_key.endswith(f":closed:{closed.id}")
    event_service.void_event(db, returned[0], reason="Wrong shipment")
    db.commit()
    _publish(db, shipment, ShipmentEventType.OUT_FOR_DELIVERY, "Out for delivery")
    live = [
        r
        for r in db.query(NotificationOutbox).filter_by(shipment_id=shipment.id)
        if r.status == "queued"
    ]
    assert [r.milestone for r in live] == ["out_for_delivery"]


def test_a_return_before_dispatch_skips_the_queued_row(db, shipment):
    _publish(db, shipment, ShipmentEventType.OUT_FOR_DELIVERY)
    _publish(db, shipment, ShipmentEventType.RETURNED, "Refused by recipient")
    ns.dispatch_pending(db)
    db.commit()
    row = db.query(NotificationOutbox).filter_by(shipment_id=shipment.id).one()
    assert (row.status, row.skip_reason) == ("skipped", "closed")


def test_a_cancelled_shipment_notifies_nothing_further(db, shipment):
    created = _publish(db, shipment, ShipmentEventType.RECEIVED_AT_SOLARIS)
    booking_service.cancel_shipment(db, shipment, reason="Customer cancelled")
    db.commit()
    # Queueing again for a standing event (as a retry or fan-out would) queues nothing.
    db.query(NotificationOutbox).delete()
    db.commit()
    assert ns.enqueue_for_events(db, shipment, created) == []
    assert ns.furthest_reached(db, shipment) == 1


def test_a_cancellation_before_dispatch_skips_the_queued_row(db, shipment):
    _publish(db, shipment, ShipmentEventType.RECEIVED_AT_SOLARIS)
    booking_service.cancel_shipment(db, shipment, reason="Customer cancelled")
    db.commit()
    ns.dispatch_pending(db)
    db.commit()
    row = db.query(NotificationOutbox).filter_by(shipment_id=shipment.id).one()
    assert (row.status, row.skip_reason) == ("skipped", "closed")


def test_one_parcel_delivered_counts_as_out_for_delivery_not_delivered(db):
    from app.services import package_service

    customer = make_customer(db, email="p15multi@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=2)
    first, second = package_service.active_packages(db, shipment.id)
    event_service.record_event(
        db,
        shipment,
        {
            "event_type": ShipmentEventType.DELIVERED_TO_RECIPIENT,
            "package_id": first.id,
            "is_public_update": True,
            "public_update_text": "Parcel 1",
        },
    )
    db.commit()
    assert ns.furthest_reached(db, shipment) == 3
    event_service.record_event(
        db,
        shipment,
        {
            "event_type": ShipmentEventType.OUT_FOR_DELIVERY,
            "package_id": second.id,
            "is_public_update": True,
            "public_update_text": "Parcel 2 out",
        },
    )
    db.commit()
    assert _milestones(db, shipment.id) == ["out_for_delivery"]
