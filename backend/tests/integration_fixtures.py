"""Shared helpers for the Phase 4A integration suites.

A tracking assignment in this schema is a ``leg_tracking_references`` row hanging off a
transport leg (Phase 2, DEC-0041), so a test that exercises the queue, the inbox, or the
event mapping needs a genuine customer, booking, package, leg, and reference behind it.

Building the real chain rather than inserting rows directly matters more than it looks.
SQLite enforces foreign keys on every connection here, and every service under test writes
through the same constraints the application does -- so a fixture that took a shortcut
would be testing a schema the application never sees.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.enums import LegType, TrackingSourceMode
from app.models import LegTrackingReference, Shipment, ShipmentLeg, ShipmentPackage
from app.services import leg_service, package_service
from tests.conftest import booked_shipment, make_customer

#: Carrier reference the fake adapter refers to. Visibly synthetic.
FAKE_TRACKING_NUMBER = "FAKE-TRACK-0001"


@dataclass
class TrackedShipment:
    """A confirmed booking with a leg and an active carrier tracking assignment."""

    shipment: Shipment
    packages: list[ShipmentPackage]
    leg: ShipmentLeg
    assignment: LegTrackingReference

    @property
    def package(self) -> ShipmentPackage:
        return self.packages[0]


def tracked_shipment(
    db: Session,
    *,
    packages: int = 1,
    tracking_number: str = FAKE_TRACKING_NUMBER,
    final_delivery: bool = True,
    package_scoped: bool = True,
    full_name: str = "Trần Quốc Tuấn",
) -> TrackedShipment:
    """A confirmed shipment with one leg and one active tracking assignment.

    ``final_delivery`` marks the leg as ending at the consignee. A leg ending at a Solaris
    warehouse is ``False``, which is what keeps an intermediate delivery from completing a
    Vietnam-bound shipment (CRM.md section 7).
    """
    customer = make_customer(db, full_name=full_name)
    shipment = booked_shipment(db, customer, packages=packages)
    package_rows = package_service.active_packages(db, shipment.id)

    leg = leg_service.create_leg(
        db,
        shipment,
        {
            "leg_type": LegType.FINAL_DELIVERY if final_delivery else LegType.ORIGIN_PICKUP,
            "provider_name": "Other",
            "destination_label": "Recipient address" if final_delivery else "Solaris warehouse",
            "destination_country_code": "VN" if final_delivery else "CA",
            "is_final_recipient_delivery": final_delivery,
            "package_ids": [package.id for package in package_rows],
        },
    )
    assignment = leg_service.add_tracking_reference(
        db,
        leg,
        {
            "carrier_name": "Other",
            "tracking_number": tracking_number,
            # Manual is the only honest mode: no provider is connected, and
            # ``connected_api`` is still refused by the service.
            "source_mode": TrackingSourceMode.MANUAL,
            "package_id": package_rows[0].id if package_scoped else None,
        },
    )
    db.commit()
    return TrackedShipment(
        shipment=shipment, packages=list(package_rows), leg=leg, assignment=assignment
    )
