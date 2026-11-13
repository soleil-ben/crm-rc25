"""Multi-package records: references, measurement conversion, and progress counts."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.core.enums import RouteGroup
from app.services import package_service
from app.services.errors import ConflictError, ValidationError
from tests.conftest import booked_shipment, make_customer, make_draft


def test_three_packages_receive_three_stable_unique_references(db: Session):
    customer = make_customer(db, email="threepack@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=3)
    packages = package_service.active_packages(db, shipment.id)

    references = [package.package_reference for package in packages]
    assert references == [
        f"{shipment.public_id}-01",
        f"{shipment.public_id}-02",
        f"{shipment.public_id}-03",
    ]
    assert len(set(references)) == 3
    assert [package.sequence for package in packages] == [1, 2, 3]


def test_position_label_reads_one_of_three(db: Session):
    customer = make_customer(db, email="position@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=3)
    active = package_service.active_packages(db, shipment.id)

    assert package_service.position_label(active[0], active) == "Package 1 of 3"
    assert package_service.position_label(active[2], active) == "Package 3 of 3"


def test_a_draft_package_has_no_reference_until_confirmation(db: Session):
    customer = make_customer(db, email="draftpack@demo.example.com")
    shipment = make_draft(db, customer, RouteGroup.CAV, packages=2)
    assert all(
        package.package_reference is None
        for package in package_service.all_packages(db, shipment.id)
    )


# --- Measurement handling --------------------------------------------------


def test_imperial_input_is_converted_and_both_values_kept(db: Session):
    customer = make_customer(db, email="imperial@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD)
    package = package_service.add_package(
        db,
        shipment,
        {
            "length_value": "12",
            "width_value": "10",
            "height_value": "8",
            "dimension_unit": "in",
            "weight_value": "12.5",
            "weight_unit": "lb",
        },
    )
    db.commit()

    # Entered values survive exactly; canonical values are exact decimals, not floats.
    assert package.length_value == Decimal("12.00")
    assert package.dimension_unit == "in"
    assert package.length_cm == Decimal("30.48")
    assert package.width_cm == Decimal("25.40")
    assert package.height_cm == Decimal("20.32")
    assert package.weight_value == Decimal("12.500")
    assert package.weight_unit == "lb"
    assert package.weight_kg == Decimal("5.670")


def test_metric_input_is_stored_unchanged(db: Session):
    customer = make_customer(db, email="metric@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD)
    package = package_service.active_packages(db, shipment.id)[0]

    assert package.dimension_unit == "cm"
    assert package.length_value == package.length_cm == Decimal("40.00")
    assert package.weight_value == package.weight_kg == Decimal("5.500")


def test_decimal_arithmetic_is_exact(db: Session):
    """Measurements must not inherit binary-float equality surprises."""
    entered, canonical = package_service.to_centimetres("0.1", "cm", "length_value")
    other, _ = package_service.to_centimetres("0.2", "cm", "width_value")
    assert entered + other == Decimal("0.30")


@pytest.mark.parametrize("value", ["0", "-1", "-0.5", "0.00"])
def test_zero_or_negative_measurements_are_rejected(db: Session, value):
    customer = make_customer(db, email=f"reject{abs(hash(value)) % 1000}@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD)
    with pytest.raises(ValidationError):
        package_service.add_package(db, shipment, {"length_value": value})
    with pytest.raises(ValidationError):
        package_service.add_package(db, shipment, {"weight_value": value})


def test_a_missing_measurement_is_allowed_and_means_not_recorded(db: Session):
    customer = make_customer(db, email="nomeasure@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD)
    package = package_service.add_package(db, shipment, {"contents_summary": "Envelope"})
    db.commit()
    assert package.weight_value is None
    assert package.weight_kg is None
    assert package.length_cm is None


def test_an_unknown_unit_is_rejected(db: Session):
    customer = make_customer(db, email="badunit@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD)
    with pytest.raises(ValidationError) as excinfo:
        package_service.add_package(db, shipment, {"weight_value": "2", "weight_unit": "stone"})
    assert excinfo.value.field == "weight_unit"


def test_non_numeric_measurements_are_rejected(db: Session):
    customer = make_customer(db, email="notanumber@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD)
    with pytest.raises(ValidationError):
        package_service.add_package(db, shipment, {"weight_value": "heavy"})


# --- Adding, duplicating, cancelling --------------------------------------


def test_a_package_added_after_confirmation_gets_the_next_reference(db: Session):
    customer = make_customer(db, email="addlater@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV, packages=2)
    added = package_service.add_package(db, shipment, {"weight_value": "3", "weight_unit": "kg"})
    db.commit()

    assert added.package_reference == f"{shipment.public_id}-03"
    assert shipment.package_count == 3


def test_duplicating_a_package_copies_measurements_but_not_the_reference(db: Session):
    customer = make_customer(db, email="duplicate@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)
    original = package_service.active_packages(db, shipment.id)[0]
    copy = package_service.duplicate_package(db, original)
    db.commit()

    assert copy.package_reference != original.package_reference
    assert copy.length_cm == original.length_cm
    assert copy.weight_kg == original.weight_kg
    assert copy.sequence == original.sequence + 1


def test_cancelling_a_package_retains_its_reference_and_never_reuses_it(db: Session):
    customer = make_customer(db, email="cancelpack@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=3)
    packages = package_service.active_packages(db, shipment.id)
    second_reference = packages[1].package_reference

    package_service.cancel_package(db, packages[1], reason="Customer withdrew this carton")
    db.commit()

    assert packages[1].package_reference == second_reference
    assert packages[1].is_active is False

    added = package_service.add_package(db, shipment, {"weight_value": "1"})
    db.commit()
    assert added.package_reference == f"{shipment.public_id}-04"
    assert added.package_reference != second_reference


def test_cancelled_packages_do_not_corrupt_active_counts(db: Session):
    customer = make_customer(db, email="counts@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=3)
    packages = package_service.active_packages(db, shipment.id)
    package_service.cancel_package(db, packages[2], reason="Damaged before dispatch")
    db.commit()

    progress = package_service.progress(db, shipment.id)
    assert progress.total == 3
    assert progress.active == 2
    assert progress.cancelled == 1
    assert progress.delivered == 0
    assert progress.summary == "0 of 2 packages delivered"
    assert shipment.package_count == 2

    remaining = package_service.active_packages(db, shipment.id)
    assert package_service.position_label(remaining[0], remaining) == "Package 1 of 2"
    assert "cancelled" in package_service.position_label(packages[2], remaining)


def test_the_last_active_package_of_a_confirmed_shipment_cannot_be_cancelled(db: Session):
    customer = make_customer(db, email="lastpack@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD)
    only = package_service.active_packages(db, shipment.id)[0]
    with pytest.raises(ConflictError) as excinfo:
        package_service.cancel_package(db, only, reason="Mistake")
    assert "Cancel the booking instead" in str(excinfo.value)


def test_a_confirmed_package_is_cancelled_not_deleted(db: Session):
    customer = make_customer(db, email="nodelete@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV, packages=2)
    package = package_service.active_packages(db, shipment.id)[0]
    with pytest.raises(ConflictError) as excinfo:
        package_service.remove_draft_package(db, package)
    assert "reference survives" in str(excinfo.value)


def test_a_draft_package_can_be_removed(db: Session):
    customer = make_customer(db, email="draftdelete@demo.example.com")
    shipment = make_draft(db, customer, RouteGroup.CAV, packages=2)
    package = package_service.all_packages(db, shipment.id)[0]
    package_service.remove_draft_package(db, package)
    db.commit()
    assert len(package_service.all_packages(db, shipment.id)) == 1


def test_a_cancelled_package_cannot_be_edited(db: Session):
    customer = make_customer(db, email="editcancelled@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=2)
    package = package_service.active_packages(db, shipment.id)[1]
    package_service.cancel_package(db, package, reason="Withdrawn")
    db.commit()
    with pytest.raises(ConflictError):
        package_service.update_package(db, package, {"weight_value": "9"})


# --- API surface -----------------------------------------------------------


def test_package_endpoints_round_trip(as_admin, db: Session):
    customer = make_customer(db, email="packapi@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD, packages=1)

    created = as_admin.post(
        f"/api/v1/shipments/{shipment.id}/packages",
        json={
            "length_value": "20",
            "width_value": "15",
            "height_value": "10",
            "dimension_unit": "in",
            "weight_value": "4",
            "weight_unit": "lb",
            "handling_note": "Fragile — ceramics",
            "warehouse_location": "A-12-3",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["package_reference"] == f"{shipment.public_id}-02"
    assert body["position_label"] == "Package 2 of 2"
    assert body["length_cm"] == "50.80"
    assert body["weight_kg"] == "1.814"

    updated = as_admin.patch(
        f"/api/v1/packages/{body['id']}", json={"warehouse_location": "B-01-1"}
    )
    assert updated.json()["warehouse_location"] == "B-01-1"
    assert updated.json()["package_reference"] == body["package_reference"]

    rejected = as_admin.post(
        f"/api/v1/shipments/{shipment.id}/packages", json={"weight_value": "0"}
    )
    assert rejected.status_code == 422
