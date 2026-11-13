"""Public tracking: lookup, normalization, status rules, freshness, and rate limiting.

The privacy assertions -- what may never appear in a public payload -- live in
``test_public_privacy.py``. This file covers behaviour: what resolves, what does not, and
what the customer is told in each case.
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.config import settings
from app.core.enums import (
    BookingState,
    OperationalState,
    RouteGroup,
    ShipmentEventType,
    TrackingSourceMode,
)
from app.core.security import SlidingWindowRateLimiter, rate_limiter
from app.core.time_utils import utcnow
from app.models import Shipment
from app.services import booking_service, event_service, leg_service, package_service
from tests.conftest import booked_shipment, make_customer, make_draft

TRACK = "/api/v1/public/track"


# --- Helpers --------------------------------------------------------------


def public_get(client, reference):
    return client.get(f"{TRACK}/{reference}")


def record(db, shipment, event_type, *, days_ago=1, public_text=None, **extra):
    payload = {
        "event_type": event_type.value if hasattr(event_type, "value") else event_type,
        "occurred_at": utcnow() - timedelta(days=days_ago),
        "is_public_update": public_text is not None,
        "public_update_text": public_text,
        **extra,
    }
    events = event_service.record_event(db, shipment, payload)
    db.commit()
    return events


# --- Reference lookup -----------------------------------------------------


def test_a_parent_shipment_reference_resolves(client, db):
    customer = make_customer(db, full_name="Trần Quốc Tuấn")
    shipment = booked_shipment(db, customer, packages=2)
    db.commit()

    response = public_get(client, shipment.public_id)

    assert response.status_code == 200
    body = response.json()
    assert body["shipment_reference"] == shipment.public_id
    assert body["matched_reference_type"] == "shipment"
    assert body["selected_package_reference"] is None
    assert body["package_count_active"] == 2


def test_a_package_reference_resolves_to_the_same_shipment_and_highlights_it(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer, packages=3)
    db.commit()
    packages = package_service.active_packages(db, shipment.id)
    second = packages[1].package_reference

    parent = public_get(client, shipment.public_id).json()
    scanned = public_get(client, second).json()

    # Same shipment, same status, same progress -- only the selection differs.
    assert scanned["shipment_reference"] == parent["shipment_reference"] == shipment.public_id
    assert scanned["status"] == parent["status"]
    assert scanned["progress_summary"] == parent["progress_summary"]
    assert scanned["matched_reference_type"] == "package"
    assert scanned["selected_package_reference"] == second
    selected = [p for p in scanned["packages"] if p["is_selected"]]
    assert [p["package_reference"] for p in selected] == [second]
    assert all(not p["is_selected"] for p in parent["packages"])


@pytest.mark.parametrize("route_group", list(RouteGroup))
def test_every_route_prefix_is_accepted_in_full_match_form(client, db, route_group):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer, route_group=route_group)
    db.commit()

    assert shipment.public_id.startswith(f"SX-{route_group.value}-")
    assert public_get(client, shipment.public_id).status_code == 200


@pytest.mark.parametrize(
    "mangled",
    [
        "{reference}",
        "{reference}".lower(),
        "  {reference}  ",
        "{reference}.",
        '"{reference}"',
        "{reference}​",  # zero-width space, the classic paste artefact
        "{ref_underscore}",
        "{ref_endash}",
    ],
)
def test_scanner_and_paste_noise_is_normalized(client, db, mangled):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    db.commit()
    reference = shipment.public_id
    candidate = (
        mangled.replace("{reference}", reference)
        .replace("{ref_underscore}", reference.replace("-", "_"))
        .replace("{ref_endash}", reference.replace("-", "–"))
    )

    response = client.get(f"{TRACK}/{candidate}")

    assert response.status_code == 200, candidate
    assert response.json()["shipment_reference"] == reference


@pytest.mark.parametrize(
    "mangled",
    [
        "{reference}\n",  # a scanner wedge that appends Enter as a character
        "{reference}\t",
        "  {reference}\r\n",
        "SX -CAV- {suffix}",  # spaces the customer added while reading it aloud
    ],
)
def test_whitespace_a_url_path_cannot_carry_is_still_normalized(mangled):
    """Asserted at the normalizer, because a URL path cannot contain these characters."""
    from app.core.public_reference import parse_public_reference

    reference = "SX-CAV-7K9D2M4R8T6W"
    candidate = mangled.replace("{reference}", reference).replace(
        "{suffix}", reference.split("-")[-1]
    )

    parsed = parse_public_reference(candidate)

    assert parsed is not None, candidate
    assert parsed.value == reference


def test_lowercase_package_reference_resolves(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer, packages=2)
    db.commit()
    reference = package_service.active_packages(db, shipment.id)[0].package_reference

    response = public_get(client, reference.lower())

    assert response.status_code == 200
    assert response.json()["selected_package_reference"] == reference


@pytest.mark.parametrize(
    "bad",
    [
        "SX-CAV-SHORT",  # suffix too short
        "SX-CAV-AAAAAAAAAAAAA",  # suffix too long
        "SX-ZZZ-ABCDEFGHJKLM",  # unknown route prefix
        "SX-CAV-ABCDEFGHIKLM",  # 'I' is not in the unambiguous alphabet
        "SX-CAV-ABCDEFGHJKL0",  # '0' is not in the unambiguous alphabet
        "XX-CAV-ABCDEFGHJKLM",  # wrong brand prefix
        "SX-CAV-ABCDEFGHJKLM-00",  # sequence 00 is never allocated
        "SX-CAV-ABCDEFGHJKLM-1",  # sequence must be two digits
        "SX-CAV-ABCDEFGHJKLM-001",
        "nguyen thi bich hanh",
        "STCA-000001",
        "DEMO-CAV-0001",
    ],
)
def test_a_malformed_reference_never_reaches_a_lookup(client, db, bad):
    customer = make_customer(db)
    booked_shipment(db, customer)
    db.commit()

    response = client.get(f"{TRACK}/{bad}")

    assert response.status_code == 404
    assert response.json()["code"] == "tracking_not_found"


def test_a_partial_reference_matches_nothing(client, db):
    """Exact match only: a prefix must not fan out into other customers' shipments."""
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    db.commit()

    for partial in (shipment.public_id[:-1], shipment.public_id[3:], shipment.public_id[:10]):
        assert client.get(f"{TRACK}/{partial}").status_code == 404


def test_the_public_surface_cannot_be_searched_by_customer_details(client, db):
    customer = make_customer(db, full_name="Nguyễn Thị Bích Hạnh", email="hanh@demo.example.com")
    shipment = make_draft(db, customer)
    booking_service.confirm_booking(db, shipment_id=shipment.id, idempotency_key="k-search")
    db.commit()

    for term in [
        "Nguyen",
        "hanh@demo.example.com",
        "+14165550100",
        customer.public_id,
        "Mississauga",
    ]:
        assert client.get(f"{TRACK}/{term}").status_code == 404


# --- Enumeration resistance ------------------------------------------------


def test_invalid_and_unknown_references_are_indistinguishable(client, db):
    """Same status, same body, same headers -- a lookup cannot confirm an ID exists."""
    customer = make_customer(db)
    booked_shipment(db, customer)
    db.commit()

    invalid = client.get(f"{TRACK}/definitely-not-a-solaris-reference")
    unknown = client.get(f"{TRACK}/SX-CAV-ABCDEFGHJKLM")
    unknown_package = client.get(f"{TRACK}/SX-CAV-ABCDEFGHJKLM-01")

    for other in (unknown, unknown_package):
        assert invalid.status_code == other.status_code == 404
        assert invalid.content == other.content
        ignored = {"date", "server", "content-length"}
        assert {k: v for k, v in invalid.headers.items() if k.lower() not in ignored} == {
            k: v for k, v in other.headers.items() if k.lower() not in ignored
        }


def test_the_failure_message_names_neither_format_nor_existence(client):
    body = client.get(f"{TRACK}/rubbish").json()

    message = body["message"].lower()
    for giveaway in [
        "invalid",
        "malformed",
        "bad format",
        "incorrect format",
        "does not exist",
        "no such",
        "unknown reference",
        "not a valid",
    ]:
        assert giveaway not in message
    assert set(body) == {"code", "message"}


def test_a_draft_is_never_publicly_retrievable(client, db):
    customer = make_customer(db)
    draft = make_draft(db, customer)
    db.commit()

    assert draft.public_id is None
    # There is no identifier to try, which is the point; confirm, capture the ID, then
    # roll the record back to draft to prove the service refuses it even so.
    booking_service.confirm_booking(db, shipment_id=draft.id, idempotency_key="k-draft")
    db.commit()
    public_id = draft.public_id
    assert public_get(client, public_id).status_code == 200

    draft.booking_state = BookingState.DRAFT
    db.commit()
    assert public_get(client, public_id).status_code == 404


def test_a_demo_record_is_hidden_in_production_and_flagged_elsewhere(client, db, monkeypatch):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    shipment.is_demo_record = True
    db.commit()

    body = public_get(client, shipment.public_id).json()
    assert body["data_mode"] == "demo"
    assert body["tracking_state"] == "demo"

    monkeypatch.setattr(settings, "environment", "production")
    assert public_get(client, shipment.public_id).status_code == 404


# --- Cancellation ----------------------------------------------------------


def test_a_cancelled_shipment_is_indistinguishable_from_an_unknown_reference(client, db):
    """UAT-XX-02. A stranger must not be able to confirm that a cancelled ID was issued.

    Before the 2026-10-14 fix pack a cancelled booking answered 200 with a safe summary,
    which told anyone probing identifiers that this one existed. Now it takes the same
    path a draft and an unknown reference take: the one generic 404, same body, same
    headers.
    """
    customer = make_customer(db)
    shipment = booked_shipment(db, customer, packages=2)
    record(db, shipment, ShipmentEventType.IN_TRANSIT, days_ago=3, public_text="On its way.")
    booking_service.cancel_shipment(db, shipment, reason="Customer withdrew the booking")
    db.commit()

    cancelled = public_get(client, shipment.public_id)
    unknown = public_get(client, "SX-CAV-ABCDEFGHJKLM")

    assert cancelled.status_code == 404
    assert cancelled.status_code == unknown.status_code
    assert cancelled.json() == unknown.json()
    assert cancelled.text == unknown.text
    for header in ("cache-control", "referrer-policy", "x-robots-tag", "content-type"):
        assert cancelled.headers[header] == unknown.headers[header]
    # Nothing about the record leaks through the refusal, reason included.
    assert "Customer withdrew" not in cancelled.text
    assert shipment.public_id not in cancelled.text


def test_a_cancelled_package_reference_on_a_cancelled_booking_is_not_found_either(client, db):
    """The package reference is a second door into the same record; it is closed too."""
    customer = make_customer(db)
    shipment = booked_shipment(db, customer, packages=2)
    reference = package_service.active_packages(db, shipment.id)[0].package_reference
    booking_service.cancel_shipment(db, shipment, reason="Withdrawn")
    db.commit()

    response = public_get(client, reference)

    assert response.status_code == 404
    assert response.json() == public_get(client, "SX-CAV-ABCDEFGHJKLM").json()


def response_text(body) -> str:
    import json

    return json.dumps(body, ensure_ascii=False)


def test_a_cancelled_package_does_not_corrupt_active_progress(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer, packages=3)
    packages = package_service.active_packages(db, shipment.id)
    package_service.cancel_package(db, packages[2], reason="Not shipping")
    db.commit()
    record(
        db,
        shipment,
        ShipmentEventType.DELIVERED_TO_RECIPIENT,
        days_ago=1,
        package_id=packages[0].id,
        public_text="One parcel has been delivered.",
    )

    body = public_get(client, shipment.public_id).json()

    assert body["package_count_active"] == 2
    assert body["package_count_cancelled"] == 1
    assert body["package_count_delivered"] == 1
    assert body["progress_summary"] == "1 of 2 packages delivered"
    assert body["status"] == OperationalState.PARTIALLY_DELIVERED
    cancelled = [p for p in body["packages"] if p["is_cancelled"]]
    assert len(cancelled) == 1
    assert cancelled[0]["package_reference"] == packages[2].package_reference


def test_a_cancelled_package_reference_still_resolves_to_its_shipment(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer, packages=2)
    packages = package_service.active_packages(db, shipment.id)
    reference = packages[1].package_reference
    package_service.cancel_package(db, packages[1], reason="Withdrawn")
    db.commit()

    body = public_get(client, reference).json()

    assert body["selected_package_reference"] == reference
    assert body["shipment_reference"] == shipment.public_id


# --- Status rules ----------------------------------------------------------


def test_one_of_three_delivered_stays_partially_delivered(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer, packages=3)
    packages = package_service.active_packages(db, shipment.id)
    record(
        db,
        shipment,
        ShipmentEventType.DELIVERED_TO_RECIPIENT,
        days_ago=1,
        package_id=packages[0].id,
        public_text="One of your three parcels has been delivered.",
    )

    body = public_get(client, shipment.public_id).json()

    assert body["status"] == OperationalState.PARTIALLY_DELIVERED
    assert body["status_label"] == "Partially delivered"
    assert body["progress_summary"] == "1 of 3 packages delivered"
    assert body["delivered_at"] is None


def test_delivered_requires_every_active_package(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer, packages=2)
    for package in package_service.active_packages(db, shipment.id):
        record(
            db,
            shipment,
            ShipmentEventType.DELIVERED_TO_RECIPIENT,
            days_ago=1,
            package_id=package.id,
            public_text="Delivered.",
        )

    body = public_get(client, shipment.public_id).json()

    assert body["status"] == OperationalState.DELIVERED
    assert body["package_count_delivered"] == 2
    assert body["delivered_at"] is not None


def test_an_unpublished_delivery_does_not_count_publicly(client, db):
    """Two packages, one delivery published and one not: the page says 1 of 2."""
    customer = make_customer(db)
    shipment = booked_shipment(db, customer, packages=2)
    first, second = package_service.active_packages(db, shipment.id)
    record(
        db,
        shipment,
        ShipmentEventType.DELIVERED_TO_RECIPIENT,
        days_ago=2,
        package_id=first.id,
        public_text="Delivered.",
    )
    record(db, shipment, ShipmentEventType.DELIVERED_TO_RECIPIENT, days_ago=1, package_id=second.id)

    body = public_get(client, shipment.public_id).json()

    # Internally the shipment is delivered; publicly only the told-about parcel is.
    db.refresh(shipment)
    assert shipment.operational_state == OperationalState.DELIVERED
    assert body["status"] == OperationalState.PARTIALLY_DELIVERED
    assert body["package_count_delivered"] == 1
    assert body["progress_summary"] == "1 of 2 packages delivered"
    assert body["delivered_at"] is None
    by_reference = {item["package_reference"]: item for item in body["packages"]}
    assert by_reference[first.package_reference]["status"] == OperationalState.DELIVERED
    assert by_reference[second.package_reference]["status"] == OperationalState.BOOKED
    assert by_reference[second.package_reference]["delivered_at"] is None


def test_intermediate_warehouse_receipt_is_not_delivery(client, db):
    """A UPS delivery to the Solaris warehouse on a Vietnam-bound parcel is a milestone."""
    customer = make_customer(db)
    shipment = booked_shipment(db, customer, route_group=RouteGroup.CAV, packages=2)
    record(
        db,
        shipment,
        ShipmentEventType.RECEIVED_AT_SOLARIS,
        days_ago=4,
        location_label="Solaris Mississauga warehouse",
        location_country_code="CA",
        public_text="Your parcels have arrived at our Mississauga facility.",
    )

    body = public_get(client, shipment.public_id).json()

    assert body["status"] == OperationalState.RECEIVED_AT_SOLARIS
    assert body["status"] != OperationalState.DELIVERED
    assert body["package_count_delivered"] == 0
    assert body["delivered_at"] is None


def test_collection_point_handover_does_not_complete_the_shipment(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    record(
        db,
        shipment,
        ShipmentEventType.DELIVERED_TO_COLLECTION_POINT,
        days_ago=1,
        public_text="Your parcel is waiting at the collection point.",
    )

    body = public_get(client, shipment.public_id).json()

    # Documented default: a collection point is Out for delivery, not Delivered.
    assert body["status"] == OperationalState.OUT_FOR_DELIVERY
    assert body["package_count_delivered"] == 0
    assert body["delivered_at"] is None


def test_a_return_in_progress_is_shown_as_itself(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    record(
        db,
        shipment,
        ShipmentEventType.RETURN_IN_PROGRESS,
        days_ago=1,
        public_text="Your parcel is being returned to the sender.",
    )

    body = public_get(client, shipment.public_id).json()

    assert body["status"] == OperationalState.RETURN_IN_PROGRESS
    assert body["package_count_delivered"] == 0


def test_a_domestic_shipment_shows_no_invented_customs_milestone(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer, route_group=RouteGroup.CAD)
    record(
        db,
        shipment,
        ShipmentEventType.IN_TRANSIT,
        days_ago=2,
        public_text="Your parcel is on its way to Vancouver.",
    )

    body = public_get(client, shipment.public_id).json()

    statuses = [entry["status"] for entry in body["timeline"]]
    assert statuses == ["in_transit"]
    assert OperationalState.CUSTOMS_PROCESSING not in statuses
    # Nothing fabricates a milestone to fill a visual gap: exactly what was recorded.
    assert len(body["timeline"]) == 1


# --- Timeline --------------------------------------------------------------


def test_only_approved_public_updates_appear(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    record(db, shipment, ShipmentEventType.RECEIVED_AT_SOLARIS, days_ago=5)  # internal only
    record(
        db,
        shipment,
        ShipmentEventType.DEPARTED_ORIGIN,
        days_ago=4,
        public_text="Your parcel has left Canada.",
    )

    body = public_get(client, shipment.public_id).json()

    assert [entry["message"] for entry in body["timeline"]] == ["Your parcel has left Canada."]
    assert body["last_public_update_at"] is not None


def test_an_internal_only_event_does_not_move_the_public_status(client, db):
    """An unpublished event is invisible in every respect, including the status it implies.

    Until the 2026-10-14 fix pack the public status was the stored one, derived from every
    event, so an internal customs note moved the page to "Customs processing" while the
    timeline stayed empty. UAT-XX-02 found the same thing with an unpublished exception
    showing as "Delayed". The public status now follows published events only.
    """
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    record(
        db,
        shipment,
        ShipmentEventType.CUSTOMS_PROCESSING,
        days_ago=1,
        location_label="Tân Sơn Nhất inspection bay 4",
        location_country_code="VN",
        internal_detail="Broker escalation SOL-2026-118; awaiting the commercial invoice.",
    )

    body = public_get(client, shipment.public_id).json()
    raw = response_text(body)

    db.refresh(shipment)
    assert shipment.operational_state == OperationalState.CUSTOMS_PROCESSING  # staff see it
    assert body["status"] == OperationalState.BOOKED  # the public does not
    assert body["status_label"] == "Booked"
    assert body["timeline"] == []
    assert body["tracking_state"] == "no_public_milestones"
    assert "inspection bay" not in raw
    assert "SOL-2026-118" not in raw
    assert "commercial invoice" not in raw


def test_an_unpublished_exception_is_not_shown_as_delayed(client, db):
    """The UAT-XX-02 finding, verbatim: a package showed "Delayed" from an event nobody
    published. The published state was "In transit" and that is what stays on the page."""
    customer = make_customer(db)
    shipment = booked_shipment(db, customer, packages=1)
    record(db, shipment, ShipmentEventType.IN_TRANSIT, days_ago=3, public_text="On its way.")
    record(
        db,
        shipment,
        ShipmentEventType.EXCEPTION,
        days_ago=1,
        internal_detail="Commercial invoice query at the border.",
    )

    body = public_get(client, shipment.public_id).json()

    db.refresh(shipment)
    assert shipment.operational_state == OperationalState.EXCEPTION
    assert body["status"] == OperationalState.IN_TRANSIT
    assert all(item["status"] == OperationalState.IN_TRANSIT for item in body["packages"])
    assert len(body["timeline"]) == 1
    assert "exception" not in response_text(body).lower()


def test_publishing_the_exception_does_move_the_public_status(client, db):
    """The counterpart: once staff publish it, the customer is told."""
    customer = make_customer(db)
    shipment = booked_shipment(db, customer, packages=1)
    record(db, shipment, ShipmentEventType.IN_TRANSIT, days_ago=3, public_text="On its way.")
    record(
        db,
        shipment,
        ShipmentEventType.EXCEPTION,
        days_ago=1,
        public_text="Your shipment is held pending paperwork.",
    )

    body = public_get(client, shipment.public_id).json()

    assert body["status"] == OperationalState.EXCEPTION
    assert body["packages"][0]["status"] == OperationalState.EXCEPTION
    assert len(body["timeline"]) == 2


def test_a_voided_published_event_no_longer_drives_the_public_status(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer, packages=1)
    record(db, shipment, ShipmentEventType.IN_TRANSIT, days_ago=3, public_text="On its way.")
    events = record(db, shipment, ShipmentEventType.EXCEPTION, days_ago=1, public_text="Held.")
    event_service.void_event(db, events[0], reason="Recorded on the wrong shipment")
    db.commit()

    body = public_get(client, shipment.public_id).json()

    assert body["status"] == OperationalState.IN_TRANSIT
    assert len(body["timeline"]) == 1


def test_a_voided_event_disappears_from_the_timeline(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    events = record(
        db,
        shipment,
        ShipmentEventType.EXCEPTION,
        days_ago=2,
        public_text="Held at customs pending paperwork.",
    )
    body_before = public_get(client, shipment.public_id).json()
    assert len(body_before["timeline"]) == 1

    event_service.void_event(db, events[0], reason="Recorded against the wrong shipment")
    db.commit()

    body = public_get(client, shipment.public_id).json()
    assert body["timeline"] == []
    assert "Held at customs" not in response_text(body)


def test_a_correction_shows_only_the_current_approved_wording(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    wrong = record(
        db,
        shipment,
        ShipmentEventType.IN_TRANSIT,
        days_ago=2,
        public_text="Departed Hanoi.",
    )
    event_service.void_event(db, wrong[0], reason="Wrong origin city")
    db.commit()
    record(
        db,
        shipment,
        ShipmentEventType.IN_TRANSIT,
        days_ago=2,
        public_text="Departed Ho Chi Minh City.",
    )

    body = public_get(client, shipment.public_id).json()
    raw = response_text(body)

    assert [entry["message"] for entry in body["timeline"]] == ["Departed Ho Chi Minh City."]
    assert "Hanoi" not in raw
    # The correction itself is internal audit history, not a customer-facing event.
    assert "Wrong origin city" not in raw


def test_identical_shipment_wide_events_are_grouped_without_losing_progress(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer, packages=3)
    record(
        db,
        shipment,
        ShipmentEventType.DEPARTED_ORIGIN,
        days_ago=3,
        public_text="Your parcels have left Canada.",
    )
    packages = package_service.active_packages(db, shipment.id)
    record(
        db,
        shipment,
        ShipmentEventType.DELIVERED_TO_RECIPIENT,
        days_ago=1,
        package_id=packages[0].id,
        public_text="One of your three parcels has been delivered.",
    )

    body = public_get(client, shipment.public_id).json()

    departures = [e for e in body["timeline"] if e["status"] == "departed_origin"]
    assert len(departures) == 1  # one entry, not three
    assert len(departures[0]["package_references"]) == 3  # all three still named
    # Package progress is unaffected by the display grouping.
    assert body["progress_summary"] == "1 of 3 packages delivered"
    assert body["status"] == OperationalState.PARTIALLY_DELIVERED


def test_the_timeline_is_newest_first_with_deterministic_tie_breaking(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    stamp = utcnow() - timedelta(days=2)
    for text in ("First wording.", "Second wording."):
        event_service.record_event(
            db,
            shipment,
            {
                "event_type": ShipmentEventType.IN_TRANSIT.value,
                "occurred_at": stamp,  # identical occurred time on purpose
                "is_public_update": True,
                "public_update_text": text,
            },
        )
    db.commit()
    record(db, shipment, ShipmentEventType.OUT_FOR_DELIVERY, days_ago=1, public_text="Out now.")

    seen = [public_get(client, shipment.public_id).json()["timeline"] for _ in range(3)]

    assert [entry["message"] for entry in seen[0]] == [
        "Out now.",
        "Second wording.",
        "First wording.",
    ]
    assert seen[0] == seen[1] == seen[2]  # stable across requests


# --- Freshness and honesty -------------------------------------------------


def test_a_shipment_with_approved_updates_reports_manual_updates(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    record(db, shipment, ShipmentEventType.IN_TRANSIT, days_ago=2, public_text="On its way.")

    body = public_get(client, shipment.public_id).json()

    assert body["tracking_state"] == "manual_updates"
    assert body["timeline"][0]["source_label"] == "manual_update"
    assert body["last_public_update_at"] is not None


def test_a_confirmed_shipment_with_nothing_published_says_so(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    db.commit()

    body = public_get(client, shipment.public_id).json()

    assert body["tracking_state"] == "no_public_milestones"
    assert body["last_public_update_at"] is None
    assert body["timeline"] == []


def test_no_synchronization_or_carrier_scan_field_is_ever_returned(client, db):
    """Phase 4 does not exist; nothing may imply it does."""
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    record(db, shipment, ShipmentEventType.IN_TRANSIT, days_ago=1, public_text="On its way.")

    body = public_get(client, shipment.public_id).json()
    raw = response_text(body).lower()

    for forbidden in [
        "last_synced",
        "last_sync",
        "synchronized",
        "synchronised",
        "last_carrier_update",
        "carrier_event",
        "connected_api",
        "automatically updated",
    ]:
        assert forbidden not in raw
    assert body["tracking_state"] in {
        "manual_updates",
        "external_link_only",
        "no_public_milestones",
        "tracking_unavailable",
        "demo",
        "cancelled",
    }


def test_an_estimated_delivery_appears_only_when_one_was_supplied(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    db.commit()
    assert public_get(client, shipment.public_id).json()["estimated_delivery_at"] is None

    shipment.estimated_delivery_at = utcnow() + timedelta(days=6)
    db.commit()
    assert public_get(client, shipment.public_id).json()["estimated_delivery_at"] is not None


def test_an_estimate_is_withdrawn_once_the_shipment_is_delivered_or_cancelled(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    shipment.estimated_delivery_at = utcnow() + timedelta(days=4)
    db.commit()
    record(db, shipment, ShipmentEventType.DELIVERED_TO_RECIPIENT, days_ago=1, public_text="Done.")

    assert public_get(client, shipment.public_id).json()["estimated_delivery_at"] is None


def test_an_unpublished_delivery_leaves_the_estimate_in_place(client, db):
    """The estimate is withdrawn by what the customer has been told, not by what staff know."""
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    shipment.estimated_delivery_at = utcnow() + timedelta(days=4)
    db.commit()
    record(db, shipment, ShipmentEventType.DELIVERED_TO_RECIPIENT, days_ago=1)

    assert public_get(client, shipment.public_id).json()["estimated_delivery_at"] is not None


# --- External carrier links ------------------------------------------------


def add_link(db, shipment, url, *, carrier="Canada Post"):
    leg = leg_service.create_leg(
        db,
        shipment,
        {
            "leg_type": "final_delivery",
            "provider_name": carrier,
            "is_final_recipient_delivery": True,
        },
    )
    reference = leg_service.add_tracking_reference(
        db,
        leg,
        {
            "carrier_name": carrier,
            "tracking_number": "DEMO-1234567890",
            "public_url": url,
            "source_mode": TrackingSourceMode.EXTERNAL_LINK.value,
        },
    )
    db.commit()
    return reference


def test_a_recognized_public_carrier_link_is_offered(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    add_link(db, shipment, "https://www.canadapost-postescanada.ca/track-reperage/en?id=DEMO1")

    body = public_get(client, shipment.public_id).json()

    # The leg's generic name, never the carrier's (owner, 2026-10-22; DEC-0224).
    assert body["carrier_link"]["carrier_name"] == "Last Mile Tracking"
    assert body["carrier_link"]["tracking_name_key"] == "last_mile_tracking"
    assert body["carrier_link"]["url"].startswith("https://www.canadapost-postescanada.ca/")
    assert body["tracking_state"] == "external_link_only"
    # The carrier's tracking number is never exposed separately.
    assert "DEMO-1234567890" not in response_text(body)


@pytest.mark.parametrize(
    "url",
    [
        "https://ship.example-private.test/dashboard/orders/1",  # not on the allowlist
        "https://user:secret@www.ups.com/track",  # credentials
        "https://www.ups.com/track#internal-note",  # fragment
        "https://www.ups.com:8443/track",  # non-default port
        "https://127.0.0.1/track",  # loopback
        "https://10.0.0.4/track",  # private network
        "https://localhost/track",
    ],
)
def test_an_unsafe_link_is_omitted_rather_than_shown(client, db, url):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    # Store it directly: some of these are refused at write time too, but the public
    # surface must not depend on that -- it makes its own, stricter decision.
    leg = leg_service.create_leg(db, shipment, {"leg_type": "final_delivery"})
    reference = leg_service.add_tracking_reference(
        db,
        leg,
        {
            "carrier_name": "Other",
            "tracking_number": "N/A",
            "source_mode": TrackingSourceMode.EXTERNAL_LINK.value,
        },
    )
    reference.public_url = url
    db.commit()

    body = public_get(client, shipment.public_id).json()

    assert body["carrier_link"] is None
    assert url not in response_text(body)


def test_a_manual_reference_never_becomes_a_public_link(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    leg = leg_service.create_leg(db, shipment, {"leg_type": "origin_pickup"})
    leg_service.add_tracking_reference(
        db,
        leg,
        {
            "carrier_name": "UPS",
            "tracking_number": "1Z999AA10123456784",
            "public_url": "https://www.ups.com/track?tracknum=1Z999AA10123456784",
            "source_mode": TrackingSourceMode.MANUAL.value,
        },
    )
    db.commit()

    body = public_get(client, shipment.public_id).json()

    assert body["carrier_link"] is None
    assert "1Z999AA10123456784" not in response_text(body)


def test_a_retired_reference_is_not_offered(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    reference = add_link(db, shipment, "https://www.ups.com/track?tracknum=abc")
    assert public_get(client, shipment.public_id).json()["carrier_link"] is not None

    leg_service.retire_tracking_reference(db, reference, reason="Carrier relabelled")
    db.commit()

    assert public_get(client, shipment.public_id).json()["carrier_link"] is None


# --- Rate limiting ---------------------------------------------------------


def test_the_public_limit_engages_and_returns_retry_after(client, db, monkeypatch):
    monkeypatch.setattr(settings, "public_tracking_rate_limit_attempts", 3)
    rate_limiter.reset()
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    db.commit()

    for _ in range(3):
        assert public_get(client, shipment.public_id).status_code == 200

    limited = public_get(client, shipment.public_id)

    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1
    assert limited.json()["code"] == "rate_limited"
    assert set(limited.json()) == {"code", "message"}
    assert "wait" in limited.json()["message"].lower()


def test_malformed_references_cannot_bypass_the_limit(client, monkeypatch):
    """The limiter runs before validation, so garbage costs the caller the same."""
    monkeypatch.setattr(settings, "public_tracking_rate_limit_attempts", 3)
    rate_limiter.reset()

    statuses = [client.get(f"{TRACK}/garbage-{index}").status_code for index in range(4)]

    assert statuses == [404, 404, 404, 429]


def test_a_forged_forwarded_header_does_not_win_a_fresh_bucket(client, monkeypatch):
    """Changing the forged address every request must not reset the allowance.

    This is the property that matters, and it is stated in terms of *the caller's own
    requests* rather than in terms of which bucket they land in. Forwarded requests get
    their own shared bucket rather than the peer's, so that a genuinely proxied caller is
    not conflated with the proxy's address once a proxy is trusted -- but an untrusted
    caller still cannot mint a new allowance by inventing a new address.
    """
    monkeypatch.setattr(settings, "public_tracking_rate_limit_attempts", 2)
    rate_limiter.reset()

    statuses = [
        client.get(
            f"{TRACK}/SX-CAV-ABCDEFGHJKLM",
            headers={
                "X-Forwarded-For": f"203.0.113.{index}",
                "X-Real-IP": f"198.51.100.{index}",
                "Forwarded": f"for=203.0.113.{index}",
            },
        ).status_code
        for index in range(4)
    ]

    # Two allowed, then refused -- exactly as if the header had never been sent.
    assert statuses == [404, 404, 429, 429]


def test_public_and_login_buckets_are_separate(client, db, users, monkeypatch):
    monkeypatch.setattr(settings, "public_tracking_rate_limit_attempts", 2)
    rate_limiter.reset()

    for _ in range(3):
        client.get(f"{TRACK}/SX-CAV-ABCDEFGHJKLM")
    assert client.get(f"{TRACK}/SX-CAV-ABCDEFGHJKLM").status_code == 429

    # Exhausting the public bucket must not lock a staff member out of signing in.
    response = client.post(
        "/api/v1/auth/login",
        json={"email": users["admin"].email, "password": "TestPassword!2026"},
    )
    assert response.status_code == 200


def test_the_limiter_prunes_expired_buckets_instead_of_growing_without_bound():
    """The public key space is 'every address that ever called', so it must be bounded."""
    limiter = SlidingWindowRateLimiter(max_buckets=50)

    for index in range(500):
        limiter.check(f"public_track:ip:198.51.100.{index}", limit=5, window_seconds=60)

    assert limiter.bucket_count() <= 50


def test_pruning_never_grants_more_than_the_configured_allowance():
    limiter = SlidingWindowRateLimiter(max_buckets=10)
    key = "public_track:ip:198.51.100.1"

    allowed = [limiter.check(key, limit=3, window_seconds=60)[0] for _ in range(5)]

    assert allowed == [True, True, True, False, False]


# --- Boundary ---------------------------------------------------------------


def test_the_endpoint_works_with_no_session_and_no_csrf_token(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    db.commit()
    client.cookies.clear()

    response = public_get(client, shipment.public_id)

    assert response.status_code == 200
    assert "set-cookie" not in {key.lower() for key in response.headers}


def test_a_signed_in_staff_session_changes_nothing_about_the_response(client, db, as_admin):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    db.commit()

    with_session = client.get(f"{TRACK}/{shipment.public_id}")
    client.cookies.clear()
    without_session = client.get(f"{TRACK}/{shipment.public_id}")

    assert with_session.status_code == without_session.status_code == 200
    assert with_session.json() == without_session.json()


def test_no_staff_cookie_is_ever_set_by_a_public_response(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    db.commit()

    for target in (shipment.public_id, "rubbish", "SX-CAV-ABCDEFGHJKLM"):
        response = client.get(f"{TRACK}/{target}")
        assert "set-cookie" not in {key.lower() for key in response.headers}
        assert settings.session_cookie_name not in response.text
        assert settings.csrf_cookie_name not in response.text


def test_the_public_package_imports_no_staff_dependency():
    """A structural check: importing app.api.deps here would attach a staff dependency."""
    from pathlib import Path

    package = Path(__file__).resolve().parents[1] / "app" / "api" / "public"
    sources = [path.read_text(encoding="utf-8") for path in package.glob("*.py")]

    import ast

    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module != "app.api.deps", f"{path.name} imports the staff dependencies"
                assert not module.startswith("app.api.v1"), f"{path.name} imports a staff router"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("app.api.deps")
                    assert not alias.name.startswith("app.api.v1")

    # Belt and braces on the names themselves: none of the staff request dependencies may
    # be bound in this package under any alias.
    import app.api.deps as staff_deps
    import app.api.public.deps as public_deps
    import app.api.public.tracking as public_tracking

    staff_only = {
        "current_user",
        "current_session",
        "require",
        "has",
        "CurrentUser",
        "OrgSettings",
        "Thresholds",
        "get_org_settings",
    }
    for module in (public_deps, public_tracking):
        bound = set(vars(module))
        assert not (staff_only & bound), f"{module.__name__} binds a staff dependency"
        # And none of the staff dependency callables is present under a different name.
        staff_callables = {
            id(getattr(staff_deps, name)) for name in staff_only if hasattr(staff_deps, name)
        }
        assert not (staff_callables & {id(value) for value in vars(module).values()})
    assert sources  # the package is not empty, so the checks above meant something


def test_the_public_route_declares_no_security_dependency(client):
    schema = client.get("/api/v1/openapi.json").json()
    path = schema["paths"]["/api/v1/public/track/{reference}"]["get"]

    assert "security" not in path
    assert schema["paths"]["/api/v1/shipments"]["get"] is not None  # staff paths still exist


def test_the_public_schemas_do_not_inherit_an_internal_schema():
    """A public model that inherited an internal one would publish its future fields."""
    from app.schemas import public_tracking as public
    from app.schemas import shipment as internal

    # Only classes *defined* in the internal module count; the shared pydantic BaseModel
    # is imported there and is a legitimate ancestor for anything.
    internal_names = {
        name
        for name, candidate in vars(internal).items()
        if isinstance(candidate, type) and candidate.__module__ == internal.__name__
    }
    assert internal_names, "the internal shipment schema module defines no classes"
    for name in dir(public):
        candidate = getattr(public, name)
        if not isinstance(candidate, type) or not hasattr(candidate, "model_fields"):
            continue
        ancestors = {base.__name__ for base in candidate.__mro__}
        assert not (ancestors & internal_names), f"{name} inherits an internal schema"
        # And no public model may be built straight from an ORM object.
        assert candidate.model_config.get("from_attributes") is not True


def test_the_public_response_is_never_an_orm_object(client, db):
    """`extra="forbid"` plus explicit construction means a stray attribute cannot ride along."""
    from app.schemas.public_tracking import PublicTrackingResult

    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    db.commit()

    with pytest.raises(PydanticValidationError):
        PublicTrackingResult.model_validate(db.get(Shipment, shipment.id))


def test_the_reference_never_appears_in_an_application_log(client, db, caplog):
    import logging

    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    db.commit()

    with caplog.at_level(logging.DEBUG):
        public_get(client, shipment.public_id)
        client.get(f"{TRACK}/SX-CAV-ABCDEFGHJKLM")

    # Only the application's own loggers are in scope. The test client's HTTP log is a
    # test-harness artefact and is not shipped anywhere; the reverse proxy's access log
    # is a deployment concern recorded as a gate in docs/OPERATIONS.md.
    #
    # Both the message *and* the structured fields are searched. Phase 5B moved the
    # lookup record from an interpolated sentence to structured fields, so a check that
    # read only the message would now pass without looking at the half of the record that
    # carries the values.
    solaris_records = [record for record in caplog.records if record.name.startswith("solaris")]
    logged = "\n".join(f"{record.getMessage()} {record.__dict__}" for record in solaris_records)
    assert shipment.public_id not in logged
    assert "SX-CAV-ABCDEFGHJKLM" not in logged

    # An outcome category and a keyed digest are recorded instead.
    lookups = [r for r in solaris_records if r.getMessage() == "public_tracking_lookup"]
    assert lookups, "the lookup was not recorded at all"
    assert {r.outcome for r in lookups} == {"found", "not_found"}
    for record in lookups:
        assert re.fullmatch(r"[0-9a-f]{12}", record.reference_digest), (
            f"the keyed digest was not recorded intact: {record.reference_digest!r}"
        )


def test_response_headers_prevent_caching_and_indexing(client, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    db.commit()

    for target in (shipment.public_id, "rubbish"):
        headers = client.get(f"{TRACK}/{target}").headers
        assert "no-store" in headers["Cache-Control"]
        assert headers["Referrer-Policy"] == "no-referrer"
        assert "noindex" in headers["X-Robots-Tag"]
        assert "nofollow" in headers["X-Robots-Tag"]
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert "geolocation=()" in headers["Permissions-Policy"]


def test_rate_limited_responses_also_carry_the_privacy_headers(client, monkeypatch):
    monkeypatch.setattr(settings, "public_tracking_rate_limit_attempts", 1)
    rate_limiter.reset()
    client.get(f"{TRACK}/SX-CAV-ABCDEFGHJKLM")

    headers = client.get(f"{TRACK}/SX-CAV-ABCDEFGHJKLM").headers

    assert headers["Cache-Control"].startswith("no-store")
    assert "noindex" in headers["X-Robots-Tag"]
    assert "Retry-After" in headers


def test_a_forwarding_header_shares_one_bucket_rather_than_minting_new_ones(client, monkeypatch):
    """The defence that does not depend on the ASGI server being configured correctly.

    Uvicorn enables ``--proxy-headers`` by default and trusts ``127.0.0.1``, so it
    rewrites the peer address from ``X-Forwarded-For`` before the application sees it.
    Declining to read the header is therefore not enough on its own: the application
    would still be handed a spoofed address and would still bucket by it.

    So every request carrying a forwarding header shares one bucket while no trusted
    proxy is configured. A caller sending a different address each time gets the same
    allowance as a caller sending none.
    """
    monkeypatch.setattr(settings, "public_tracking_rate_limit_attempts", 3)
    rate_limiter.reset()

    statuses = [
        client.get(
            f"{TRACK}/SX-CAV-ABCDEFGHJKLM",
            headers={"X-Forwarded-For": f"203.0.113.{index}"},
        ).status_code
        for index in range(5)
    ]

    assert statuses == [404, 404, 404, 429, 429]


@pytest.mark.parametrize("header", ["X-Forwarded-For", "X-Real-IP", "Forwarded", "X-Client-IP"])
def test_every_forwarding_header_variant_is_treated_the_same(client, monkeypatch, header):
    monkeypatch.setattr(settings, "public_tracking_rate_limit_attempts", 2)
    rate_limiter.reset()

    statuses = [
        client.get(
            f"{TRACK}/SX-CAV-ABCDEFGHJKLM", headers={header: f"203.0.113.{index}"}
        ).status_code
        for index in range(3)
    ]

    assert statuses[-1] == 429


def test_a_direct_caller_is_unaffected_by_someone_else_spoofing(client, monkeypatch):
    """A spoofer exhausts the shared forwarded bucket, not everybody else's allowance."""
    monkeypatch.setattr(settings, "public_tracking_rate_limit_attempts", 2)
    rate_limiter.reset()

    for index in range(4):
        client.get(
            f"{TRACK}/SX-CAV-ABCDEFGHJKLM",
            headers={"X-Forwarded-For": f"203.0.113.{index}"},
        )

    # No forwarding header: the caller's own bucket, still untouched.
    assert client.get(f"{TRACK}/SX-CAV-ABCDEFGHJKLM").status_code == 404


def test_the_forwarded_bucket_is_honoured_once_a_proxy_is_trusted(client, monkeypatch):
    """The setting exists so the behaviour can be turned on deliberately, not by accident."""
    from app.api.public.deps import UNTRUSTED_FORWARDED_KEY, public_client_key

    class _Request:
        def __init__(self, headers, host):
            self.headers = headers
            self.client = type("C", (), {"host": host})()

    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    assert (
        public_client_key(_Request({"x-forwarded-for": "203.0.113.9"}, "127.0.0.1"))
        == UNTRUSTED_FORWARDED_KEY
    )

    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    # Trusted: the peer address the ASGI server resolved is used as-is, which is what a
    # correctly configured proxy will have set.
    assert public_client_key(_Request({"x-forwarded-for": "203.0.113.9"}, "10.0.0.7")) == "10.0.0.7"


def test_the_default_is_not_to_trust_a_forwarding_header():
    """A default that had to be remembered would eventually be forgotten."""
    from app.core.config import Settings

    assert Settings.model_fields["trust_proxy_headers"].default is False


def test_a_cancelled_demo_booking_is_not_found_outside_production_either(client, db):
    """Demo visibility does not reopen the door cancellation closed."""
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    shipment.is_demo_record = True
    booking_service.cancel_shipment(db, shipment, reason="Customer withdrew")
    db.commit()

    response = public_get(client, shipment.public_id)

    assert response.status_code == 404
    assert response.json() == public_get(client, "SX-CAV-ABCDEFGHJKLM").json()


# --- The label QR and the public route must agree ---------------------------


def test_a_label_qr_addresses_the_route_the_public_app_serves(db):
    """The QR on a printed label has to open the page Phase 3 built.

    These two values were set in different phases by different code, and nothing but this
    test connects them: ``label_service`` builds ``{tracking_base_url}/{reference}``, and
    the React application registers ``/track/:reference``. Phase 2's sample-label script
    used a ``/t`` base, which was arbitrary and became wrong the moment the real route
    existed. A label is printed once and lives on a parcel for weeks, so a mismatch here
    is expensive to discover late.
    """
    from app.models import OrganizationSettings
    from app.services import label_service

    customer = make_customer(db)
    shipment = booked_shipment(db, customer, packages=2)
    db.commit()

    org = db.query(OrganizationSettings).first()
    base = label_service.tracking_base_url(org)
    packages = package_service.active_packages(db, shipment.id)
    content = label_service.build_content(
        shipment, packages[1], packages, base_url=base, timezone_name="America/Toronto"
    )

    # The path the QR encodes.
    assert "/track/" in content.tracking_url, content.tracking_url
    reference = content.tracking_url.rsplit("/", 1)[-1]

    # And that reference is one the public endpoint accepts and resolves.
    assert reference == packages[1].package_reference
    from app.core.public_reference import parse_public_reference

    parsed = parse_public_reference(reference)
    assert parsed is not None and parsed.kind == "package"


def test_the_configured_tracking_base_ends_in_the_public_route(db):
    """The default and the documented example must both address the real route."""
    from app.core.config import Settings

    assert Settings.model_fields["tracking_base_url"].default.endswith("/track")


def test_the_sample_label_script_uses_the_real_public_path():
    """The committed sample PDFs are a deliverable; their QR codes must be openable."""
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "scripts" / "render_sample_labels.py"
    source = script.read_text(encoding="utf-8")
    base = re.search(r'DEMO_TRACKING_BASE = "([^"]+)"', source).group(1)

    assert base.endswith("/track"), f"sample labels would encode {base}/<reference>"
    # The host stays a reserved placeholder: the tracking domain is not confirmed.
    assert ".test/" in base or ".example" in base
