"""Transport legs, package associations, and tracking-reference placeholders."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.core.enums import LegType, RouteGroup, TrackingSourceMode
from app.services import leg_service, package_service
from app.services.errors import ConflictError, NotFoundError, ValidationError
from tests.conftest import booked_shipment, make_customer


def _multi_leg(db, shipment):
    packages = package_service.active_packages(db, shipment.id)
    legs = [
        leg_service.create_leg(
            db,
            shipment,
            {
                "leg_type": LegType.ORIGIN_PICKUP,
                "provider_name": "Purolator",
                "origin_label": "Customer address, Mississauga",
                "origin_country_code": "CA",
                "destination_label": "Solaris Mississauga warehouse",
                "destination_country_code": "CA",
                "package_ids": [package.id for package in packages],
            },
        ),
        leg_service.create_leg(
            db,
            shipment,
            {
                "leg_type": LegType.CONSOLIDATION_LINEHAUL,
                "provider_name": "Solaris Express",
                "origin_label": "Solaris Mississauga warehouse",
                "origin_country_code": "CA",
                "destination_label": "Ho Chi Minh City gateway",
                "destination_country_code": "VN",
                "consolidation_reference": "SOL-CONS-2026-014",
                "package_ids": [package.id for package in packages],
            },
        ),
        leg_service.create_leg(
            db,
            shipment,
            {
                "leg_type": LegType.DESTINATION_HANDLING,
                "provider_name": "Vietnam Post",
                "destination_country_code": "VN",
                "package_ids": [package.id for package in packages],
            },
        ),
        leg_service.create_leg(
            db,
            shipment,
            {
                "leg_type": LegType.FINAL_DELIVERY,
                "provider_name": "Vietnam Post",
                "destination_label": "Recipient address",
                "destination_country_code": "VN",
                "is_final_recipient_delivery": True,
                "package_ids": [package.id for package in packages],
            },
        ),
    ]
    db.commit()
    return legs, packages


def test_a_multi_leg_vietnam_shipment_orders_its_legs(db: Session):
    customer = make_customer(db, email="multileg@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV, packages=2)
    legs, packages = _multi_leg(db, shipment)

    assert [leg.sequence for leg in legs] == [1, 2, 3, 4]
    assert [leg.leg_type for leg in legs] == [
        LegType.ORIGIN_PICKUP,
        LegType.CONSOLIDATION_LINEHAUL,
        LegType.DESTINATION_HANDLING,
        LegType.FINAL_DELIVERY,
    ]
    # Only the last leg reaches the consignee; the warehouse legs do not.
    assert [leg.is_final_recipient_delivery for leg in legs] == [False, False, False, True]
    assert legs[1].consolidation_reference == "SOL-CONS-2026-014"
    for leg in legs:
        assert {link.package_id for link in leg.package_links} == {
            package.id for package in packages
        }


def test_package_associations_can_be_replaced(db: Session):
    customer = make_customer(db, email="legpackages@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV, packages=3)
    packages = package_service.active_packages(db, shipment.id)
    leg = leg_service.create_leg(
        db,
        shipment,
        {"leg_type": LegType.ORIGIN_PICKUP, "package_ids": [p.id for p in packages]},
    )
    db.commit()

    leg_service.set_leg_packages(db, leg, [packages[0].id])
    db.commit()
    assert {link.package_id for link in leg.package_links} == {packages[0].id}


def test_a_package_from_another_shipment_is_rejected(db: Session):
    customer = make_customer(db, email="legcross@demo.example.com")
    first = booked_shipment(db, customer, RouteGroup.CAV)
    second = booked_shipment(db, customer, RouteGroup.CAD)
    foreign = package_service.active_packages(db, second.id)[0]

    with pytest.raises(NotFoundError):
        leg_service.create_leg(
            db, first, {"leg_type": LegType.ORIGIN_PICKUP, "package_ids": [foreign.id]}
        )


def test_an_unknown_leg_type_is_rejected(db: Session):
    customer = make_customer(db, email="legtype@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD)
    with pytest.raises(ValidationError):
        leg_service.create_leg(db, shipment, {"leg_type": "teleportation"})


# --- Tracking reference placeholders --------------------------------------


def test_tracking_references_are_retired_not_overwritten(db: Session):
    customer = make_customer(db, email="retire@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD)
    leg = leg_service.create_leg(db, shipment, {"leg_type": LegType.ORIGIN_PICKUP})
    db.commit()

    first = leg_service.add_tracking_reference(
        db, leg, {"carrier_name": "UPS", "tracking_number": "1Z999AA10123456784"}
    )
    db.commit()
    leg_service.retire_tracking_reference(db, first, reason="Label voided by the carrier")
    second = leg_service.add_tracking_reference(
        db, leg, {"carrier_name": "UPS", "tracking_number": "1Z999AA10123456785"}
    )
    db.commit()

    assert first.is_active is False
    assert first.retired_at is not None
    assert first.tracking_number == "1Z999AA10123456784"  # history preserved
    assert second.is_active is True
    assert len(leg.tracking_references) == 2


def test_one_package_can_carry_several_sequential_references(db: Session):
    customer = make_customer(db, email="sequential@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV, packages=2)
    packages = package_service.active_packages(db, shipment.id)
    legs, _packages = _multi_leg(db, shipment)

    leg_service.add_tracking_reference(
        db,
        legs[0],
        {"carrier_name": "Purolator", "tracking_number": "PUR-1", "package_id": packages[0].id},
    )
    leg_service.add_tracking_reference(
        db,
        legs[2],
        {"carrier_name": "Vietnam Post", "tracking_number": "VN-1", "package_id": packages[0].id},
    )
    db.commit()

    references = [
        reference
        for leg in legs
        for reference in leg.tracking_references
        if reference.package_id == packages[0].id
    ]
    assert len(references) == 2
    assert {reference.carrier_name for reference in references} == {"Purolator", "Vietnam Post"}


def test_a_master_reference_covers_a_whole_leg(db: Session):
    customer = make_customer(db, email="master@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV, packages=3)
    legs, _packages = _multi_leg(db, shipment)
    reference = leg_service.add_tracking_reference(
        db, legs[1], {"carrier_name": "Solaris Express", "tracking_number": "MASTER-7781"}
    )
    db.commit()
    assert reference.package_id is None


def test_connected_api_mode_is_refused_until_a_provider_is_verified(db: Session):
    """No provider account is connected, so nothing may claim automatic tracking."""
    customer = make_customer(db, email="connected@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD)
    leg = leg_service.create_leg(db, shipment, {"leg_type": LegType.ORIGIN_PICKUP})
    db.commit()

    with pytest.raises(ValidationError) as excinfo:
        leg_service.add_tracking_reference(
            db,
            leg,
            {
                "carrier_name": "UPS",
                "tracking_number": "1Z999AA10123456784",
                "source_mode": TrackingSourceMode.CONNECTED_API,
            },
        )
    assert "No provider account is connected" in str(excinfo.value)


def test_external_link_mode_validates_the_url(db: Session):
    customer = make_customer(db, email="link@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD)
    leg = leg_service.create_leg(db, shipment, {"leg_type": LegType.FINAL_DELIVERY})
    db.commit()

    ok = leg_service.add_tracking_reference(
        db,
        leg,
        {
            "carrier_name": "Canada Post",
            "tracking_number": "CP123",
            "source_mode": TrackingSourceMode.EXTERNAL_LINK,
            "public_url": "https://www.canadapost-postescanada.ca/track/en#/details/CP123",
        },
    )
    db.commit()
    assert ok.public_url.startswith("https://")

    for bad in ("http://insecure.example.com/t", "https://localhost/t", "not a url"):
        with pytest.raises(ValidationError):
            leg_service.add_tracking_reference(
                db,
                leg,
                {
                    "carrier_name": "Other",
                    "tracking_number": "X1",
                    "source_mode": TrackingSourceMode.EXTERNAL_LINK,
                    "public_url": bad,
                },
            )


def test_a_leg_with_active_references_cannot_be_deleted(db: Session):
    customer = make_customer(db, email="legdelete@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD)
    leg = leg_service.create_leg(db, shipment, {"leg_type": LegType.ORIGIN_PICKUP})
    db.commit()
    leg_service.add_tracking_reference(db, leg, {"carrier_name": "UPS", "tracking_number": "1Z1"})
    db.commit()

    with pytest.raises(ConflictError) as excinfo:
        leg_service.delete_leg(db, leg)
    assert "carrier history is not lost" in str(excinfo.value)


def test_carrier_names_are_labelled_as_display_only(as_admin):
    meta = as_admin.get("/api/v1/shipments/meta").json()
    assert "UPS" in meta["carriers"]
    assert "No provider account is connected" in meta["carrier_note"]


def test_leg_api_round_trip(as_admin, db: Session):
    customer = make_customer(db, email="legapi@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV, packages=2)
    packages = package_service.active_packages(db, shipment.id)

    created = as_admin.post(
        f"/api/v1/shipments/{shipment.id}/legs",
        json={
            "leg_type": "consolidation_linehaul",
            "provider_name": "Solaris Express",
            "destination_country_code": "Viet Nam",
            "package_ids": [package.id for package in packages],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["destination_country_code"] == "VN"
    assert body["leg_type_label"] == "Consolidation linehaul"
    assert sorted(body["package_references"]) == [
        f"{shipment.public_id}-01",
        f"{shipment.public_id}-02",
    ]

    reference = as_admin.post(
        f"/api/v1/legs/{body['id']}/tracking-references",
        json={"carrier_name": "Vietnam Post", "tracking_number": "VN-99887"},
    )
    assert reference.status_code == 201
    assert reference.json()["source_mode_label"] == "Manual"

    listed = as_admin.get(f"/api/v1/shipments/{shipment.id}/legs").json()
    assert len(listed[0]["tracking_references"]) == 1
