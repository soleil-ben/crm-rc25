"""Booking confirmation, Solaris IDs, route rules, snapshots, and cancel-and-rebook.

Covers CRM.md AC-3, AC-5, AC-6, and the route validation in section 6.
"""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import BookingState, RouteGroup, ShipmentDirection
from app.models import BookingConfirmation, CustomerAddress, Shipment, ShipmentPackage
from app.services import booking_service, identifier_service, package_service
from app.services.errors import ConflictError, ValidationError
from tests.conftest import (
    ADDRESS_BY_COUNTRY,
    booked_shipment,
    confirm_draft,
    draft_payload,
    make_customer,
    make_draft,
)

# --- Route and direction validation ---------------------------------------


@pytest.mark.parametrize(
    "route_group,expected_prefix",
    [
        (RouteGroup.VCA, "SX-VCA-"),
        (RouteGroup.CAV, "SX-CAV-"),
        (RouteGroup.CAD, "SX-CAD-"),
        (RouteGroup.XUS, "SX-XUS-"),
    ],
)
def test_each_route_group_produces_its_own_id_prefix(db: Session, route_group, expected_prefix):
    customer = make_customer(db, email=f"{route_group.lower()}@demo.example.com")
    shipment = booked_shipment(db, customer, route_group)

    assert shipment.public_id.startswith(expected_prefix)
    suffix = shipment.public_id[len(expected_prefix) :]
    assert len(suffix) == 12
    # Unambiguous alphabet: no I, O, 0 or 1 can appear.
    assert set(suffix) <= set(identifier_service.UNAMBIGUOUS_ALPHABET)


@pytest.mark.parametrize(
    "route_group,direction,valid",
    [
        (RouteGroup.VCA, ShipmentDirection.VN_TO_CA, True),
        (RouteGroup.VCA, ShipmentDirection.CA_TO_VN, False),
        (RouteGroup.VCA, ShipmentDirection.CA_TO_CA, False),
        (RouteGroup.VCA, ShipmentDirection.CA_TO_US, False),
        (RouteGroup.VCA, ShipmentDirection.US_TO_CA, False),
        (RouteGroup.CAV, ShipmentDirection.CA_TO_VN, True),
        (RouteGroup.CAV, ShipmentDirection.VN_TO_CA, False),
        (RouteGroup.CAV, ShipmentDirection.CA_TO_CA, False),
        (RouteGroup.CAD, ShipmentDirection.CA_TO_CA, True),
        (RouteGroup.CAD, ShipmentDirection.CA_TO_VN, False),
        (RouteGroup.CAD, ShipmentDirection.CA_TO_US, False),
        (RouteGroup.XUS, ShipmentDirection.CA_TO_US, True),
        (RouteGroup.XUS, ShipmentDirection.US_TO_CA, True),
        (RouteGroup.XUS, ShipmentDirection.CA_TO_CA, False),
        (RouteGroup.XUS, ShipmentDirection.VN_TO_CA, False),
    ],
)
def test_every_route_direction_combination(route_group, direction, valid):
    if valid:
        assert booking_service.validate_route(route_group, direction) == direction
    else:
        with pytest.raises(ValidationError):
            booking_service.validate_route(route_group, direction)


def test_us_to_us_is_rejected_as_out_of_scope():
    with pytest.raises(ValidationError) as excinfo:
        booking_service.validate_route(
            RouteGroup.XUS, "us_to_us", origin_country="US", destination_country="US"
        )
    assert "outside the launch scope" in str(excinfo.value)


def test_single_direction_route_infers_its_direction():
    assert booking_service.validate_route(RouteGroup.CAD, None) == ShipmentDirection.CA_TO_CA


def test_cross_border_route_requires_an_explicit_direction():
    with pytest.raises(ValidationError) as excinfo:
        booking_service.validate_route(RouteGroup.XUS, None)
    assert "explicit direction" in str(excinfo.value)


def test_direction_must_match_the_address_countries(db: Session):
    customer = make_customer(db, email="mismatch@demo.example.com")
    payload = draft_payload(customer, RouteGroup.CAV)
    payload["recipient"] = dict(ADDRESS_BY_COUNTRY["US"])
    with pytest.raises(ValidationError) as excinfo:
        booking_service.create_draft(db, payload)
    assert "requires a destination in VN" in str(excinfo.value)


def test_route_validation_is_enforced_over_the_api(as_admin, db: Session):
    """A bypassed frontend cannot book an out-of-scope lane."""
    customer = make_customer(db, email="api.route@demo.example.com")
    payload = draft_payload(customer, RouteGroup.XUS)
    payload["direction"] = "ca_to_ca"
    response = as_admin.post("/api/v1/shipments", json=payload)
    assert response.status_code == 422, response.text


# --- Drafts ---------------------------------------------------------------


def test_a_draft_has_no_customer_facing_id(db: Session):
    customer = make_customer(db, email="draft@demo.example.com")
    shipment = make_draft(db, customer, RouteGroup.VCA, packages=2)

    assert shipment.booking_state == BookingState.DRAFT
    assert shipment.public_id is None
    packages = package_service.all_packages(db, shipment.id)
    assert len(packages) == 2
    assert all(package.package_reference is None for package in packages)


def test_a_draft_persists_so_staff_can_resume_it(as_admin, db: Session):
    customer = make_customer(db, email="resume@demo.example.com")
    created = as_admin.post("/api/v1/shipments", json=draft_payload(customer, RouteGroup.CAD))
    assert created.status_code == 201, created.text
    shipment_id = created.json()["id"]

    listed = as_admin.get("/api/v1/shipments", params={"booking_state": "draft"})
    assert shipment_id in [item["id"] for item in listed.json()["items"]]

    fetched = as_admin.get(f"/api/v1/shipments/{shipment_id}")
    assert fetched.json()["public_id"] is None
    assert fetched.json()["booking_state"] == "draft"


def test_draft_edits_may_change_the_route(db: Session):
    customer = make_customer(db, email="editroute@demo.example.com")
    shipment = make_draft(db, customer, RouteGroup.CAD)

    booking_service.update_shipment(
        db,
        shipment,
        {
            "route_group": RouteGroup.CAV,
            "recipient": dict(ADDRESS_BY_COUNTRY["VN"]),
        },
    )
    db.commit()
    assert shipment.route_group == RouteGroup.CAV
    assert shipment.direction == ShipmentDirection.CA_TO_VN


# --- Confirmation ---------------------------------------------------------


def test_confirmation_generates_exactly_one_id(db: Session):
    customer = make_customer(db, email="confirm@demo.example.com")
    shipment = make_draft(db, customer, RouteGroup.VCA, packages=3)
    result = confirm_draft(db, shipment, "confirm-key-0001")

    assert result.created is True
    assert result.shipment.public_id is not None
    assert result.shipment.booking_state == BookingState.CONFIRMED
    assert result.shipment.confirmed_at is not None
    assert db.scalar(select(Shipment.id).where(Shipment.public_id == result.shipment.public_id))
    assert db.query(BookingConfirmation).filter_by(shipment_id=shipment.id).count() == 1


def test_confirmation_requires_a_complete_booking(db: Session):
    customer = make_customer(db, email="incomplete@demo.example.com")
    payload = draft_payload(customer, RouteGroup.CAV)
    payload["contents_description"] = None
    shipment = booking_service.create_draft(db, payload)
    db.commit()

    with pytest.raises(ValidationError) as excinfo:
        confirm_draft(db, shipment, "incomplete-key-1")
    assert "contents_description" in str(excinfo.value.detail)


def test_confirmation_requires_at_least_one_package(db: Session):
    customer = make_customer(db, email="nopackages@demo.example.com")
    shipment = make_draft(db, customer, RouteGroup.CAV, packages=0)
    with pytest.raises(ValidationError) as excinfo:
        confirm_draft(db, shipment, "nopack-key-1")
    assert "at least one package" in str(excinfo.value)


def test_retrying_the_same_idempotency_key_returns_the_original_booking(db: Session):
    customer = make_customer(db, email="retry@demo.example.com")
    shipment = make_draft(db, customer, RouteGroup.CAV)

    first = confirm_draft(db, shipment, "retry-key-0001")
    second = confirm_draft(db, shipment, "retry-key-0001")

    assert second.created is False
    assert second.shipment.id == first.shipment.id
    assert second.shipment.public_id == first.shipment.public_id
    assert db.scalar(
        select(Shipment).where(Shipment.customer_id == customer.id).order_by(Shipment.id)
    )
    assert db.query(Shipment).filter_by(customer_id=customer.id).count() == 1


def test_same_key_with_materially_different_data_is_a_conflict(db: Session):
    customer = make_customer(db, email="mismatchkey@demo.example.com")
    shipment = make_draft(db, customer, RouteGroup.CAV)
    confirm_draft(db, shipment, "shared-key-0001")

    # A staff member edits the recipient, then the stale tab retries the same key.
    shipment.recipient_name = "Someone Else Entirely"
    db.commit()

    with pytest.raises(ConflictError) as excinfo:
        confirm_draft(db, shipment, "shared-key-0001")
    assert "materially different" in str(excinfo.value)


def test_reusing_a_key_across_two_different_bookings_is_a_conflict(db: Session):
    customer = make_customer(db, email="crosskey@demo.example.com")
    first = make_draft(db, customer, RouteGroup.CAV)
    second = make_draft(db, customer, RouteGroup.CAD)
    confirm_draft(db, first, "cross-key-0001")

    with pytest.raises(ConflictError) as excinfo:
        confirm_draft(db, second, "cross-key-0001")
    assert "different booking" in str(excinfo.value)


def test_confirming_twice_with_different_keys_is_refused(db: Session):
    customer = make_customer(db, email="twokeys@demo.example.com")
    shipment = make_draft(db, customer, RouteGroup.CAV)
    confirm_draft(db, shipment, "first-key-0001")

    with pytest.raises(ConflictError) as excinfo:
        confirm_draft(db, shipment, "second-key-0002")
    assert "already confirmed" in str(excinfo.value)


def test_id_generation_retries_after_a_collision(db: Session, monkeypatch):
    """A colliding suffix is discarded and a fresh one generated (CRM.md section 6)."""
    customer = make_customer(db, email="collision@demo.example.com")
    taken = booked_shipment(db, customer, RouteGroup.CAV, key="collide-existing")
    colliding_suffix = taken.public_id.rsplit("-", 1)[1]

    second = make_draft(db, customer, RouteGroup.CAV)
    suffixes = iter([colliding_suffix, colliding_suffix, "ZZZZ99999999"])
    monkeypatch.setattr(booking_service, "random_suffix", lambda length=12: next(suffixes))

    result = confirm_draft(db, second, "collide-key-0002")
    assert result.shipment.public_id == "SX-CAV-ZZZZ99999999"
    assert result.id_generation_attempts == 3
    assert result.shipment.public_id != taken.public_id


def test_double_click_over_the_api_creates_one_booking(as_admin, db: Session):
    customer = make_customer(db, email="doubleclick@demo.example.com")
    created = as_admin.post("/api/v1/shipments", json=draft_payload(customer, RouteGroup.VCA))
    shipment_id = created.json()["id"]
    body = {"idempotency_key": "double-click-key-01"}

    first = as_admin.post(f"/api/v1/shipments/{shipment_id}/confirm", json=body)
    second = as_admin.post(f"/api/v1/shipments/{shipment_id}/confirm", json=body)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert first.json()["shipment"]["public_id"] == second.json()["shipment"]["public_id"]
    assert db.query(Shipment).filter_by(customer_id=customer.id).count() == 1


def test_concurrent_confirmations_on_separate_connections_produce_one_id(
    session_factory, db: Session
):
    """Two genuinely separate sessions confirm the same draft at once.

    SQLite has no row locks, so this proves the uniqueness-based claim in
    ``booking_confirmations`` actually serializes confirmation (DEC-0031).
    """
    customer = make_customer(db, email="concurrent@demo.example.com")
    shipment = make_draft(db, customer, RouteGroup.XUS)
    shipment_id = shipment.id
    db.commit()

    start = threading.Barrier(2)
    outcomes: list[tuple[bool, str | None]] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def worker(key: str) -> None:
        session = session_factory()
        try:
            start.wait(timeout=5)
            result = booking_service.confirm_booking(
                session, shipment_id=shipment_id, idempotency_key=key
            )
            session.commit()
            with lock:
                outcomes.append((result.created, result.shipment.public_id))
        except Exception as exc:  # captured and asserted below
            session.rollback()
            with lock:
                errors.append(exc)
        finally:
            session.close()

    threads = [
        threading.Thread(target=worker, args=(f"concurrent-key-{index}",)) for index in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    # Exactly one booking, one Solaris ID, one confirmation row -- whether the loser
    # returned idempotently or was refused with a conflict.
    db.expire_all()
    confirmations = db.query(BookingConfirmation).filter_by(shipment_id=shipment_id).all()
    assert len(confirmations) == 1
    assert db.query(Shipment).filter_by(customer_id=customer.id).count() == 1
    winner = db.get(Shipment, shipment_id)
    assert winner.public_id is not None
    assert winner.public_id.startswith("SX-XUS-")
    assert len(outcomes) + len(errors) == 2
    assert sum(1 for created, _ in outcomes if created) <= 1
    for _created, public_id in outcomes:
        assert public_id == winner.public_id
    for error in errors:
        assert isinstance(error, ConflictError), error


# --- Route locking --------------------------------------------------------


def test_route_locks_after_confirmation(db: Session):
    customer = make_customer(db, email="lock@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)

    with pytest.raises(ConflictError) as excinfo:
        booking_service.update_shipment(db, shipment, {"route_group": RouteGroup.CAD})
    assert "lock once a booking is confirmed" in str(excinfo.value)

    with pytest.raises(ConflictError):
        booking_service.update_shipment(db, shipment, {"direction": ShipmentDirection.VN_TO_CA})
    assert shipment.route_group == RouteGroup.CAV


def test_route_lock_is_enforced_over_the_api(as_admin, db: Session):
    customer = make_customer(db, email="apilock@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)
    response = as_admin.patch(f"/api/v1/shipments/{shipment.id}", json={"route_group": "CAD"})
    assert response.status_code == 409, response.text


def test_permitted_fields_still_edit_after_confirmation(db: Session):
    customer = make_customer(db, email="postedit@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)
    booking_service.update_shipment(db, shipment, {"internal_notes": "Customer called."})
    db.commit()
    assert shipment.internal_notes == "Customer called."
    assert shipment.route_group == RouteGroup.CAV


# --- Address snapshots ----------------------------------------------------


def test_editing_a_saved_address_does_not_change_a_confirmed_snapshot(db: Session):
    """AC-5: the shipment holds a copy, not a reference."""
    customer = make_customer(db, email="snapshot@demo.example.com")
    address = CustomerAddress(
        customer_id=customer.id,
        label="Family in Vietnam",
        contact_name="Nguyễn Văn Bảo",
        address_line1="12 Lê Lợi",
        city="Đà Nẵng",
        province_state="Đà Nẵng",
        postal_code="550000",
        country_code="VN",
    )
    db.add(address)
    db.commit()

    payload = draft_payload(customer, RouteGroup.CAV)
    payload["recipient"] = {"address_id": address.id}
    shipment = booking_service.create_draft(db, payload)
    db.commit()
    confirm_draft(db, shipment, "snapshot-key-0001")

    address.contact_name = "Someone Different"
    address.address_line1 = "999 Somewhere Else"
    address.city = "Hà Nội"
    db.commit()
    db.refresh(shipment)

    assert shipment.recipient_name == "Nguyễn Văn Bảo"
    assert shipment.recipient_address_line1 == "12 Lê Lợi"
    assert shipment.recipient_city == "Đà Nẵng"
    # Provenance is retained without making the snapshot a live reference.
    assert shipment.recipient_address_id == address.id


def test_snapshot_preserves_vietnamese_diacritics(db: Session):
    customer = make_customer(db, email="diacritics@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)
    assert shipment.recipient_name == "Nguyễn Thị Bích Hạnh"
    assert shipment.recipient_city == "Thành phố Hồ Chí Minh"


def test_country_names_normalize_to_iso_codes(db: Session):
    customer = make_customer(db, email="countryname@demo.example.com")
    payload = draft_payload(customer, RouteGroup.CAV)
    payload["recipient"]["country_code"] = "Viet Nam"
    shipment = booking_service.create_draft(db, payload)
    db.commit()

    assert shipment.recipient_country_code == "VN"
    # The entered display value is kept alongside the normalized code.
    assert shipment.recipient_country_input == "Viet Nam"


def test_an_unrecognized_country_is_rejected(db: Session):
    customer = make_customer(db, email="badcountry@demo.example.com")
    payload = draft_payload(customer, RouteGroup.CAV)
    payload["recipient"]["country_code"] = "Freedonia"
    with pytest.raises(ValidationError) as excinfo:
        booking_service.create_draft(db, payload)
    assert excinfo.value.field == "recipient_country_code"


# --- Cancel and rebook ----------------------------------------------------


def test_cancel_and_rebook_creates_a_new_id_and_keeps_the_link(db: Session):
    customer = make_customer(db, email="rebook@demo.example.com")
    original = booked_shipment(db, customer, RouteGroup.CAD, packages=2)
    original_id = original.public_id

    replacement = booking_service.rebook_shipment(
        db,
        original,
        reason="Route group was wrong: this is a Canada to Vietnam parcel",
        changes={
            "route_group": RouteGroup.CAV,
            "recipient": dict(ADDRESS_BY_COUNTRY["VN"]),
        },
    )
    db.commit()
    confirm_draft(db, replacement, "rebook-key-0002")
    db.refresh(original)

    assert original.booking_state == BookingState.CANCELLED
    assert original.public_id == original_id  # the original ID never changes meaning
    assert replacement.public_id != original_id
    assert replacement.public_id.startswith("SX-CAV-")
    assert original.rebooked_to_shipment_id == replacement.id
    assert replacement.rebooked_from_shipment_id == original.id
    # Packages were carried forward and given their own new references.
    assert len(package_service.active_packages(db, replacement.id)) == 2


def test_a_cancelled_id_is_never_reused(db: Session):
    customer = make_customer(db, email="noreuse@demo.example.com")
    original = booked_shipment(db, customer, RouteGroup.CAD)
    cancelled_id = original.public_id
    booking_service.cancel_shipment(db, original, reason="Customer changed their mind")
    db.commit()

    for index in range(5):
        other = make_draft(db, customer, RouteGroup.CAD)
        confirm_draft(db, other, f"noreuse-key-{index}")
        assert other.public_id != cancelled_id

    # The cancelled record still owns its identifier.
    assert db.scalar(select(Shipment.id).where(Shipment.public_id == cancelled_id)) == original.id


def test_a_cancelled_booking_cannot_be_confirmed(db: Session):
    customer = make_customer(db, email="cancelconfirm@demo.example.com")
    shipment = make_draft(db, customer, RouteGroup.CAD)
    booking_service.cancel_shipment(db, shipment, reason="Duplicate entry")
    db.commit()

    with pytest.raises(ConflictError) as excinfo:
        confirm_draft(db, shipment, "cancelled-key-0001")
    assert "cancelled" in str(excinfo.value)


def test_rebooking_twice_is_refused(db: Session):
    customer = make_customer(db, email="doublerebook@demo.example.com")
    original = booked_shipment(db, customer, RouteGroup.CAD)
    booking_service.rebook_shipment(db, original, reason="First correction")
    db.commit()
    with pytest.raises(ConflictError):
        booking_service.rebook_shipment(db, original, reason="Second correction")


# --- Reference lookup -----------------------------------------------------


def test_shipment_and_package_references_resolve_to_the_same_shipment(as_admin, db: Session):
    customer = make_customer(db, email="lookup@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=3)
    packages = package_service.active_packages(db, shipment.id)
    second = packages[1]

    by_shipment = as_admin.get(
        "/api/v1/shipments/lookup", params={"reference": shipment.public_id}
    ).json()
    by_package = as_admin.get(
        "/api/v1/shipments/lookup", params={"reference": second.package_reference}
    ).json()

    assert by_shipment["shipment_id"] == by_package["shipment_id"] == shipment.id
    assert by_shipment["kind"] == "shipment"
    assert by_shipment["package_id"] is None
    # The package scan identifies which package was scanned.
    assert by_package["kind"] == "package"
    assert by_package["package_id"] == second.id
    assert by_package["package_reference"] == second.package_reference


def test_lookup_tolerates_scanner_noise_but_stays_exact(as_admin, db: Session):
    customer = make_customer(db, email="scanner@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA)

    noisy = as_admin.get(
        "/api/v1/shipments/lookup",
        params={"reference": f"  {shipment.public_id.lower()} "},
    )
    assert noisy.status_code == 200
    assert noisy.json()["shipment_id"] == shipment.id

    partial = as_admin.get(
        "/api/v1/shipments/lookup", params={"reference": shipment.public_id[:12]}
    )
    assert partial.status_code == 404


def test_the_solaris_id_survives_carrier_assignment_and_relabelling(as_admin, db: Session):
    """AC-6: the same Solaris ID works before, during, and after carrier changes."""
    customer = make_customer(db, email="carrierid@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV, packages=2)
    original_id = shipment.public_id
    references = [
        package.package_reference for package in package_service.active_packages(db, shipment.id)
    ]

    leg = as_admin.post(
        f"/api/v1/shipments/{shipment.id}/legs",
        json={"leg_type": "origin_pickup", "provider_name": "Purolator"},
    ).json()
    first = as_admin.post(
        f"/api/v1/legs/{leg['id']}/tracking-references",
        json={"carrier_name": "Purolator", "tracking_number": "PURO123456789"},
    ).json()
    as_admin.post(
        f"/api/v1/tracking-references/{first['id']}/retire",
        json={"reason": "Carrier relabelled the parcel"},
    )
    as_admin.post(
        f"/api/v1/legs/{leg['id']}/tracking-references",
        json={"carrier_name": "UPS", "tracking_number": "1Z999AA10123456784"},
    )

    db.expire_all()
    refreshed = db.get(Shipment, shipment.id)
    assert refreshed.public_id == original_id
    assert [
        package.package_reference for package in package_service.active_packages(db, shipment.id)
    ] == references
    # Both carrier references survive; the retired one is not overwritten.
    legs = as_admin.get(f"/api/v1/shipments/{shipment.id}/legs").json()
    carriers = {
        reference["carrier_name"]: reference["is_active"]
        for reference in legs[0]["tracking_references"]
    }
    assert carriers == {"Purolator": False, "UPS": True}


def test_package_references_are_unique_across_shipments(db: Session):
    customer = make_customer(db, email="uniqueref@demo.example.com")
    first = booked_shipment(db, customer, RouteGroup.CAV, packages=3)
    second = booked_shipment(db, customer, RouteGroup.CAV, packages=3)

    references = [
        package.package_reference
        for package in db.scalars(select(ShipmentPackage)).all()
        if package.package_reference
    ]
    assert len(references) == len(set(references)) == 6
    assert first.public_id != second.public_id
