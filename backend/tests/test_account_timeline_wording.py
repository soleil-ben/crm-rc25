"""Phase 15: each Customer Account timeline entry names its published event type, so the
account shows the standard wording for that step in the customer's language with the staff's
published text beneath it. Internal notes and unpublished events never appear; the public
tracking contract is unchanged."""

from __future__ import annotations

from app.core.enums import OperationalState
from app.models import ShipmentEvent
from tests.shipment_history_fixtures import add_event, detail_url, linked_and_signed_in, shipment
from tests.shipment_history_fixtures import customer as make

MINE = "p15.timeline@demo.example.com"


def test_entries_carry_the_event_type_and_never_an_internal_note(
    account_client, account_db, account_users, captured_mail
):
    mine = make(account_db, full_name="Lan Tran", email="lan.canonical@demo.example.com")
    row = shipment(account_db, mine, days_ago=6)
    collection = add_event(
        account_db,
        row,
        days_ago=1,
        text="Pick up at the District 1 office.",
        internal_detail="SENTINEL-INTERNAL: customer owes a fee",
        state=OperationalState.OUT_FOR_DELIVERY,
    )
    # A collection-point handover reads as "out for delivery" in the status, but its own
    # standard wording differs: the entry names the event type, not just the state.
    collection.event_type = "delivered_to_collection_point"
    add_event(
        account_db,
        row,
        days_ago=3,
        text=None,
        template_key="in_transit.v1",
        state=OperationalState.IN_TRANSIT,
    )
    add_event(account_db, row, public=False, internal_detail="SENTINEL-UNPUBLISHED", days_ago=2)
    account_db.commit()

    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=mine
    )
    body = client.get(detail_url(row.public_id)).json()

    assert [(e["event_type"], e["status"]) for e in body["timeline"]] == [
        ("delivered_to_collection_point", "out_for_delivery"),
        ("in_transit", "in_transit"),
    ]
    assert body["timeline"][0]["message"] == "Pick up at the District 1 office."
    assert body["timeline"][1]["message_template_key"] == "in_transit.v1"
    assert "SENTINEL" not in str(body)
    assert account_db.query(ShipmentEvent).filter_by(shipment_id=row.id).count() == 3


def test_the_public_tracking_timeline_shape_is_unchanged():
    from app.schemas.public_tracking import PublicTimelineEntry

    assert "event_type" not in PublicTimelineEntry.model_fields


def test_a_parcel_level_entry_is_scoped_to_the_package(
    account_client, account_db, account_users, captured_mail
):
    from app.services import package_service

    mine = make(account_db, full_name="Minh Pham", email="minh.canonical@demo.example.com")
    row = shipment(account_db, mine, days_ago=6, packages=3)
    packages = package_service.active_packages(account_db, row.id)
    # One parcel delivered on its own; then a milestone recorded on every parcel.
    add_event(
        account_db,
        row,
        days_ago=1,
        text="Left with the neighbour.",
        state=OperationalState.DELIVERED,
        package_id=packages[0].id,
    ).event_type = "delivered_to_recipient"
    together = [
        add_event(
            account_db,
            row,
            days_ago=3,
            text="On its way.",
            state=OperationalState.IN_TRANSIT,
            package_id=package.id,
        )
        for package in packages
    ]
    for event in together:  # one milestone recorded on every parcel at once
        event.occurred_at = together[0].occurred_at
    account_db.commit()

    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=mine
    )
    timeline = client.get(detail_url(row.public_id)).json()["timeline"]
    assert [(e["event_type"], e["scope"], len(e["package_references"])) for e in timeline] == [
        ("delivered_to_recipient", "package", 1),
        ("in_transit", "shipment", 3),
    ]
