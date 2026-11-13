"""A deliberately awkward reporting dataset.

Every edge case the metric definitions name is present here at least once, because a
reporting bug does not look like a crash — it looks like a number that is quietly wrong.
The awkward rows are the point:

* a **draft** that must appear in no shipment metric except the booking-state one;
* a **cancelled** booking, and a **cancel-and-rebook pair** that must contribute one
  shipment rather than two or zero;
* a **return** that must not count as another outbound purchase;
* a **merged customer** whose shipments moved to the survivor, so the person is counted
  once and not twice;
* a **three-package, two-leg** shipment that must still count as one shipment;
* two shipments straddling **local midnight** in the organization timezone;
* three **currencies**, one of them recorded with no currency at all.

Timestamps are anchored to a fixed instant rather than ``utcnow()`` so a test that asserts
a bucket label does not fail once a day at midnight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.enums import (
    BookingState,
    OperationalState,
    RouteGroup,
    TrackingSourceMode,
)
from app.core.time_utils import local_midnight_utc
from app.models import (
    Customer,
    LegTrackingReference,
    Shipment,
    ShipmentLeg,
    ShipmentPackage,
)
from app.services.identifier_service import random_suffix
from tests.conftest import make_customer

#: The organization timezone the fixtures are reasoned about in.
TZ = "America/Toronto"

#: Reporting window used by most tests: the whole of September 2026, Toronto time.
PERIOD_FROM = datetime(2026, 9, 1).date()
PERIOD_TO = datetime(2026, 9, 30).date()


def toronto(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    """A naive-UTC instant for a wall-clock time in Toronto.

    The offset is not constant across the year, so this resolves it per date rather than
    subtracting a fixed number of hours.
    """
    midnight = local_midnight_utc(datetime(year, month, day).date(), TZ)
    return midnight + timedelta(hours=hour, minutes=minute)


@dataclass
class ReportDataset:
    """Handles onto the fixture rows, so a test can assert about a specific one."""

    customers: dict[str, Customer] = field(default_factory=dict)
    shipments: dict[str, Shipment] = field(default_factory=dict)

    def customer(self, key: str) -> Customer:
        return self.customers[key]

    def shipment(self, key: str) -> Shipment:
        return self.shipments[key]


def _shipment(
    db: Session,
    customer: Customer,
    *,
    route_group: str,
    booking_date: datetime,
    first_handoff_at: datetime | None = None,
    booking_state: str = BookingState.CONFIRMED,
    operational_state: str = OperationalState.IN_TRANSIT,
    cancelled_at: datetime | None = None,
    delivered_at: datetime | None = None,
    is_return: bool = False,
    currency: str | None = None,
    selling_amount: float | None = None,
    shipping_cost: float | None = None,
    surcharges_amount: float | None = None,
    discount_amount: float | None = None,
    refund_amount: float | None = None,
    package_count: int = 1,
) -> Shipment:
    shipment = Shipment(
        public_id=None
        if booking_state == BookingState.DRAFT
        # Generated from the same unambiguous alphabet the real identifier service uses.
        # A hex-derived suffix would contain 0 and 1, which the public reference parser
        # correctly refuses, and the fixture would then look like a product bug.
        else f"SX-{route_group}-{random_suffix(12)}",
        customer_id=customer.id,
        route_group=route_group,
        booking_state=booking_state,
        operational_state=operational_state,
        booking_date=booking_date,
        first_handoff_at=first_handoff_at,
        delivered_at=delivered_at,
        cancelled_at=cancelled_at,
        is_return=is_return,
        package_count=package_count,
        currency=currency,
        selling_amount=selling_amount,
        shipping_cost=shipping_cost,
        surcharges_amount=surcharges_amount,
        discount_amount=discount_amount,
        refund_amount=refund_amount,
    )
    db.add(shipment)
    db.flush()
    return shipment


def build_dataset(db: Session) -> ReportDataset:
    """Create the dataset. Returns handles so a test can name a specific row."""
    data = ReportDataset()

    # --- People ----------------------------------------------------------
    # Vietnamese names with diacritics, because these records also feed the export tests.
    data.customers["repeat"] = make_customer(
        db,
        full_name="Nguyễn Thị Bích Hạnh",
        email="hanh.nguyen@demo.example.com",
        phone="+1 416 555 0111",
        country_code="CA",
    )
    data.customers["first_timer"] = make_customer(
        db,
        full_name="Trần Quốc Tuấn",
        email="tuan.tran@demo.example.com",
        phone="+1 416 555 0112",
        country_code="CA",
    )
    data.customers["prospect"] = make_customer(
        db,
        full_name="Dana Whitfield",
        email="dana.whitfield@demo.example.com",
        phone="+1 206 555 0113",
        country_code="US",
    )
    data.customers["survivor"] = make_customer(
        db,
        full_name="Lê Minh Khôi",
        email="khoi.le@demo.example.com",
        phone="+1 905 555 0114",
        country_code="CA",
    )
    data.customers["absorbed"] = make_customer(
        db,
        full_name="Le Minh Khoi",
        email="khoi.le.alt@demo.example.com",
        phone="+1 905 555 0115",
        country_code="CA",
    )

    # Backdate creation so the customer-growth buckets are deterministic.
    creation = {
        "repeat": toronto(2026, 9, 2, 9),
        "first_timer": toronto(2026, 9, 14, 15),
        "prospect": toronto(2026, 9, 14, 16),
        "survivor": toronto(2026, 8, 20, 10),
        "absorbed": toronto(2026, 8, 21, 10),
    }
    for key, created_at in creation.items():
        data.customers[key].created_at = created_at
    db.flush()

    repeat = data.customers["repeat"]
    first_timer = data.customers["first_timer"]
    survivor = data.customers["survivor"]
    absorbed = data.customers["absorbed"]

    # --- Qualifying shipments -------------------------------------------
    data.shipments["repeat_aug"] = _shipment(
        db,
        repeat,
        route_group=RouteGroup.CAV,
        booking_date=toronto(2026, 8, 10, 9),
        first_handoff_at=toronto(2026, 8, 11, 9),
        operational_state=OperationalState.DELIVERED,
        delivered_at=toronto(2026, 8, 20, 9),
        currency="CAD",
        selling_amount=180.00,
        shipping_cost=95.00,
    )
    data.shipments["repeat_sep"] = _shipment(
        db,
        repeat,
        route_group=RouteGroup.CAV,
        booking_date=toronto(2026, 9, 3, 9),
        first_handoff_at=toronto(2026, 9, 4, 9),
        currency="CAD",
        selling_amount=200.00,
        surcharges_amount=25.00,
        discount_amount=10.00,
        refund_amount=15.00,
        shipping_cost=110.00,
        package_count=3,
    )
    # Three packages and two legs on one shipment. It is still one shipment (AC-14).
    for sequence in (1, 2, 3):
        db.add(
            ShipmentPackage(
                shipment_id=data.shipments["repeat_sep"].id,
                sequence=sequence,
                package_reference=(f"{data.shipments['repeat_sep'].public_id}-{sequence:02d}"),
                is_active=True,
                weight_value=4,
                weight_unit="kg",
                weight_kg=4,
                operational_state=OperationalState.IN_TRANSIT,
            )
        )
    for sequence, leg_type in ((1, "origin_pickup"), (2, "final_delivery")):
        db.add(
            ShipmentLeg(
                shipment_id=data.shipments["repeat_sep"].id,
                sequence=sequence,
                leg_type=leg_type,
                is_final_recipient_delivery=leg_type == "final_delivery",
            )
        )
    db.flush()

    data.shipments["first_timer_sep"] = _shipment(
        db,
        first_timer,
        route_group=RouteGroup.VCA,
        booking_date=toronto(2026, 9, 15, 11),
        first_handoff_at=toronto(2026, 9, 16, 11),
        currency="USD",
        selling_amount=90.00,
        # No cost recorded: this shipment must contribute to revenue and to the
        # revenue-coverage count, and to neither cost figure.
    )
    data.shipments["survivor_sep"] = _shipment(
        db,
        survivor,
        route_group=RouteGroup.CAD,
        booking_date=toronto(2026, 9, 7, 8),
        first_handoff_at=toronto(2026, 9, 8, 8),
        operational_state=OperationalState.EXCEPTION,
        currency=None,  # Recorded with no currency: Unknown, never folded into CAD.
        selling_amount=None,
    )

    # --- Local-midnight boundary ----------------------------------------
    # 30 September 23:30 Toronto is September business. In UTC it is 1 October 03:30, so a
    # UTC-cut report would move it into October.
    data.shipments["late_september"] = _shipment(
        db,
        repeat,
        route_group=RouteGroup.CAD,
        booking_date=toronto(2026, 9, 30, 22),
        first_handoff_at=toronto(2026, 9, 30, 23, 30),
    )
    # 1 October 00:30 Toronto is October business, and must not appear in September.
    data.shipments["early_october"] = _shipment(
        db,
        repeat,
        route_group=RouteGroup.CAD,
        booking_date=toronto(2026, 10, 1, 0, 10),
        first_handoff_at=toronto(2026, 10, 1, 0, 30),
    )

    # --- Rows that must be excluded --------------------------------------
    data.shipments["draft"] = _shipment(
        db,
        first_timer,
        route_group=RouteGroup.CAV,
        booking_date=toronto(2026, 9, 18, 10),
        first_handoff_at=None,
        booking_state=BookingState.DRAFT,
        operational_state=OperationalState.BOOKED,
    )
    data.shipments["cancelled"] = _shipment(
        db,
        first_timer,
        route_group=RouteGroup.XUS,
        booking_date=toronto(2026, 9, 19, 10),
        first_handoff_at=toronto(2026, 9, 20, 10),
        booking_state=BookingState.CANCELLED,
        operational_state=OperationalState.CANCELLED,
        cancelled_at=toronto(2026, 9, 21, 10),
    )
    # Cancel-and-rebook: the original is cancelled, the replacement qualifies. Together
    # they are one shipment.
    data.shipments["rebooked_from"] = _shipment(
        db,
        survivor,
        route_group=RouteGroup.XUS,
        booking_date=toronto(2026, 9, 9, 10),
        first_handoff_at=toronto(2026, 9, 10, 10),
        booking_state=BookingState.CANCELLED,
        operational_state=OperationalState.CANCELLED,
        cancelled_at=toronto(2026, 9, 10, 12),
    )
    data.shipments["rebooked_to"] = _shipment(
        db,
        survivor,
        route_group=RouteGroup.XUS,
        booking_date=toronto(2026, 9, 10, 13),
        first_handoff_at=toronto(2026, 9, 11, 9),
        currency="VND",
        selling_amount=1500000,
        shipping_cost=900000,
    )
    data.shipments["rebooked_from"].rebooked_to_shipment_id = data.shipments["rebooked_to"].id
    data.shipments["rebooked_to"].rebooked_from_shipment_id = data.shipments["rebooked_from"].id

    data.shipments["return_leg"] = _shipment(
        db,
        repeat,
        route_group=RouteGroup.VCA,
        booking_date=toronto(2026, 9, 22, 10),
        first_handoff_at=toronto(2026, 9, 23, 10),
        is_return=True,
        operational_state=OperationalState.RETURN_IN_PROGRESS,
    )
    data.shipments["return_leg"].return_of_shipment_id = data.shipments["repeat_sep"].id

    # --- The merge ------------------------------------------------------
    # The absorbed record shipped once before the merge. The merge moves that shipment to
    # the survivor, so the survivor holds two qualifying shipments and the absorbed record
    # must appear in no customer count at all.
    data.shipments["absorbed_sep"] = _shipment(
        db,
        absorbed,
        route_group=RouteGroup.CAD,
        booking_date=toronto(2026, 9, 5, 9),
        first_handoff_at=toronto(2026, 9, 6, 9),
    )
    db.flush()

    from app.services import customer_service

    customer_service.merge_customers(db, source=absorbed, target=survivor)

    # --- Tracking references on an exception shipment --------------------
    exception_leg = ShipmentLeg(
        shipment_id=data.shipments["survivor_sep"].id,
        sequence=1,
        leg_type="final_delivery",
        is_final_recipient_delivery=True,
    )
    db.add(exception_leg)
    db.flush()
    db.add(
        LegTrackingReference(
            leg_id=exception_leg.id,
            carrier_name="Purolator",
            tracking_number="PUR000111222",
            source_mode=TrackingSourceMode.MANUAL,
            is_active=True,
        )
    )

    db.commit()
    return data
