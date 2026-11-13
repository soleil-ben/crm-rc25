"""RC-20 (owner, 2026-10-23): legs on the staff shipment view.

* The final delivery leg offers the vendor as a provider, like every other leg, and saving
  it works.
* The staff leg payload carries the leg's generic tracking name key (DEC-0224): "Master
  Tracking" for origin pickup and consolidation / linehaul, "Last Mile Tracking" for every
  other leg. Staff still read the stored provider and carrier names.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.core.enums import LegType, RouteGroup
from app.services import leg_service, package_service
from app.services.public_tracking_service import TRACKING_NAMES
from app.services.tariff_import_service import KANGO_VENDOR_NAME
from tests.conftest import booked_shipment, make_customer

EXPECTED_KEYS = {
    "origin_pickup": "master_tracking",
    "consolidation_linehaul": "master_tracking",
    "destination_handling": "last_mile_tracking",
    "final_delivery": "last_mile_tracking",
}


def test_every_leg_type_has_an_expected_key():
    assert set(EXPECTED_KEYS) == {item.value for item in LegType}


@pytest.mark.parametrize("leg_type", [item.value for item in LegType])
def test_every_leg_type_offers_the_vendor_provider(leg_type):
    assert leg_service.VENDOR_PROVIDER == KANGO_VENDOR_NAME
    assert leg_service.VENDOR_PROVIDER in leg_service.providers_for(leg_type)


def test_final_delivery_offers_the_same_providers_as_the_other_legs():
    final = leg_service.providers_for(LegType.FINAL_DELIVERY)
    for leg_type in LegType:
        assert leg_service.providers_for(leg_type) == final
    assert "UPS" in final and "Canada Post" in final


def test_meta_offers_the_vendor_on_the_final_delivery_leg(as_admin):
    meta = as_admin.get("/api/v1/shipments/meta").json()
    providers = meta["leg_providers"]
    assert set(providers) == {item.value for item in LegType}
    assert KANGO_VENDOR_NAME in providers["final_delivery"]
    for leg_type, offered in providers.items():
        assert KANGO_VENDOR_NAME in offered, leg_type
    # The tracking-reference carrier list is unchanged.
    assert "UPS" in meta["carriers"]


def test_saving_the_vendor_on_a_final_delivery_leg_works(as_admin, db: Session):
    customer = make_customer(db, email="rc20-final-vendor@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=1)
    packages = package_service.active_packages(db, shipment.id)

    created = as_admin.post(
        f"/api/v1/shipments/{shipment.id}/legs",
        json={
            "leg_type": "final_delivery",
            "provider_name": KANGO_VENDOR_NAME,
            "is_final_recipient_delivery": True,
            "package_ids": [package.id for package in packages],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["provider_name"] == KANGO_VENDOR_NAME
    assert body["tracking_name_key"] == "last_mile_tracking"

    # Changing the provider on an existing final delivery leg to the vendor works too.
    patched = as_admin.patch(f"/api/v1/legs/{body['id']}", json={"provider_name": "UPS"})
    assert patched.status_code == 200, patched.text
    patched = as_admin.patch(
        f"/api/v1/legs/{body['id']}", json={"provider_name": KANGO_VENDOR_NAME}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["provider_name"] == KANGO_VENDOR_NAME


def test_the_staff_leg_payload_carries_the_tracking_name_key(as_admin, db: Session):
    customer = make_customer(db, email="rc20-leg-labels@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=1)
    for leg_type in EXPECTED_KEYS:
        response = as_admin.post(
            f"/api/v1/shipments/{shipment.id}/legs",
            json={"leg_type": leg_type, "provider_name": KANGO_VENDOR_NAME},
        )
        assert response.status_code == 201, response.text
        assert response.json()["tracking_name_key"] == EXPECTED_KEYS[leg_type]

    listed = as_admin.get(f"/api/v1/shipments/{shipment.id}/legs").json()
    assert [(leg["leg_type"], leg["tracking_name_key"]) for leg in listed] == list(
        EXPECTED_KEYS.items()
    )
    for leg in listed:
        assert leg["tracking_name_key"] in TRACKING_NAMES
        # Staff still see the provider as stored.
        assert leg["provider_name"] == KANGO_VENDOR_NAME


def test_the_generic_names_never_carry_a_vendor_or_carrier_name():
    forbidden = {
        KANGO_VENDOR_NAME.lower(),
        "kango",
        *(c.lower() for c in leg_service.KNOWN_CARRIERS),
    }
    for names in TRACKING_NAMES.values():
        for text in names.values():
            assert not any(word in text.lower() for word in forbidden if word != "other"), text
