"""Synthetic demo seed (CRM.md section 3 and section 16).

Every record created here is fictional and flagged ``is_demo_record``. The command
refuses to run when ``ENVIRONMENT`` is production or ``ALLOW_DEMO_SEED`` is false, so
fake customers can never be seeded into a production database.

Phase 2 demo bookings are built through ``booking_service``, ``package_service``,
``leg_service``, and ``event_service`` rather than by writing rows directly, so the
seeded data obeys exactly the same rules the API enforces: real route validation, real
Solaris IDs, real package references, and derived status.

Run with::

    python -m app.seed            # create demo data
    python -m app.seed --reset    # delete existing demo data first
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import delete, select

from app.core.config import settings
from app.core.db import session_scope
from app.core.enums import (
    EVENT_TYPE_TO_OPERATIONAL_STATE,
    BookingState,
    ConsentBasis,
    ConsentChannel,
    ConsentStatus,
    ContactChannel,
    CustomerCategory,
    DimensionUnit,
    EventSource,
    InteractionDirection,
    LegType,
    OperationalState,
    PreferredLanguage,
    Role,
    RouteGroup,
    ServiceIssueStatus,
    ServiceType,
    ShipmentEventType,
    ShippingFrequency,
    ShippingPurpose,
    TaskPriority,
    TaskPurpose,
    TaskStatus,
    TrackingSourceMode,
    TransportMode,
    WeightUnit,
)
from app.core.time_utils import utcnow, zone
from app.models import (
    ConsentEvent,
    Customer,
    CustomerAddress,
    CustomerTag,
    FollowUpTask,
    Interaction,
    OrganizationSettings,
    Referral,
    SavedSegment,
    ServiceIssue,
    Shipment,
    ShipmentEvent,
    ShipmentPackage,
    Tag,
    User,
)
from app.services import (
    auth_service,
    booking_service,
    customer_service,
    event_service,
    leg_service,
    package_service,
    segment_service,
)
from app.services.identifier_service import random_suffix

DEMO_PASSWORD = "SolarisDemo!2026"

DEMO_STAFF = [
    ("admin@demo.example.com", "Demo Admin", Role.ADMIN),
    ("ops@demo.example.com", "Demo Operations", Role.OPERATIONS),
    ("marketing@demo.example.com", "Demo Marketing", Role.MARKETING),
    ("manager@demo.example.com", "Demo Read-only Manager", Role.READ_ONLY_MANAGER),
]

DEMO_TAGS = [
    ("frequent-shipper", "Frequent shipper", "orange"),
    ("family-support", "Family support", "teal"),
    ("small-business", "Small business", "info"),
    ("needs-documents", "Needs documents", "warning"),
    ("service-recovery", "Service recovery", "danger"),
]

# Fictional demo identities. Any resemblance to a real customer is unintended; these are
# never imported into production (see the environment guard above).
DEMO_CUSTOMERS = [
    {
        "full_name": "Nguyễn Thị Bích Hạnh (demo)",
        "phone": "+1 416 555 0142",
        "email": "bich.hanh.demo@demo.example.com",
        "city": "Toronto",
        "province_state": "ON",
        "country_code": "CA",
        "preferred_language": PreferredLanguage.VI,
        "primary_route_group": RouteGroup.CAV,
        "primary_shipping_purpose": ShippingPurpose.GIFTS_FAMILY_SUPPORT,
        "shipping_frequency": ShippingFrequency.MONTHLY,
        "tags": ["frequent-shipper", "family-support"],
        "shipments": [(RouteGroup.CAV, 96), (RouteGroup.CAV, 54), (RouteGroup.CAV, 12)],
    },
    {
        "full_name": "Trần Quốc Minh Khôi (demo)",
        "phone": "+1 905 555 0188",
        "email": "minh.khoi.demo@demo.example.com",
        "city": "Mississauga",
        "province_state": "ON",
        "country_code": "CA",
        "preferred_language": PreferredLanguage.VI,
        "primary_route_group": RouteGroup.CAV,
        "primary_shipping_purpose": ShippingPurpose.PERSONAL_ITEMS,
        "shipping_frequency": ShippingFrequency.OCCASIONAL,
        "tags": ["family-support"],
        "shipments": [(RouteGroup.CAV, 75)],
    },
    {
        "full_name": "Priya Raghunathan (demo)",
        "phone": "+1 647 555 0119",
        "email": "priya.demo@demo.example.com",
        "city": "Brampton",
        "province_state": "ON",
        "country_code": "CA",
        "preferred_language": PreferredLanguage.EN,
        "primary_route_group": RouteGroup.CAD,
        "category": CustomerCategory.BUSINESS,
        "business_name": "Northlight Studio (demo)",
        "business_type": "online_seller",
        "primary_shipping_purpose": ShippingPurpose.ONLINE_ORDERS,
        "shipping_frequency": ShippingFrequency.WEEKLY,
        "tags": ["small-business", "frequent-shipper"],
        "shipments": [
            (RouteGroup.CAD, 30),
            (RouteGroup.CAD, 18),
            (RouteGroup.CAD, 9),
            (RouteGroup.XUS, 4),
        ],
    },
    {
        "full_name": "Lê Hoàng Phương Uyên (demo)",
        "phone": "+84 90 555 0173",
        "email": "phuong.uyen.demo@demo.example.com",
        "city": "Ho Chi Minh City",
        "province_state": "Hồ Chí Minh",
        "country_code": "VN",
        "preferred_language": PreferredLanguage.VI,
        "primary_route_group": RouteGroup.VCA,
        "primary_shipping_purpose": ShippingPurpose.GIFTS_FAMILY_SUPPORT,
        "shipping_frequency": ShippingFrequency.OCCASIONAL,
        "tags": ["family-support"],
        "shipments": [(RouteGroup.VCA, 120), (RouteGroup.VCA, 88)],
    },
    {
        "full_name": "Daniel O'Sullivan (demo)",
        "phone": "+1 289 555 0164",
        "email": "daniel.demo@demo.example.com",
        "city": "Hamilton",
        "province_state": "ON",
        "country_code": "CA",
        "preferred_language": PreferredLanguage.EN,
        "primary_route_group": RouteGroup.XUS,
        "primary_shipping_purpose": ShippingPurpose.BUSINESS_SAMPLES,
        "shipping_frequency": ShippingFrequency.MONTHLY,
        "tags": ["small-business"],
        "shipments": [(RouteGroup.XUS, 22), (RouteGroup.XUS, 6)],
    },
    {
        "full_name": "Marie-Claude Deschênes (demo)",
        "phone": "+1 514 555 0155",
        "email": "marie.claude.demo@demo.example.com",
        "city": "Montréal",
        "province_state": "QC",
        "country_code": "CA",
        "preferred_language": PreferredLanguage.FR,
        "primary_route_group": RouteGroup.CAD,
        "primary_shipping_purpose": ShippingPurpose.MOVING,
        "shipping_frequency": ShippingFrequency.ONE_TIME,
        "tags": [],
        "shipments": [(RouteGroup.CAD, 3)],
    },
    {
        "full_name": "Phạm Ngọc Anh Thư (demo)",
        "phone": "+1 778 555 0131",
        "email": "anh.thu.demo@demo.example.com",
        "city": "Vancouver",
        "province_state": "BC",
        "country_code": "CA",
        "preferred_language": PreferredLanguage.VI,
        "primary_route_group": RouteGroup.CAV,
        "primary_shipping_purpose": ShippingPurpose.PERSONAL_ITEMS,
        "shipping_frequency": ShippingFrequency.UNKNOWN,
        "tags": ["needs-documents"],
        "shipments": [],
    },
    {
        "full_name": "Võ Thị Kim Ngân (demo)",
        "phone": "+1 613 555 0127",
        "email": "kim.ngan.demo@demo.example.com",
        "city": "Ottawa",
        "province_state": "ON",
        "country_code": "CA",
        "preferred_language": PreferredLanguage.VI,
        "primary_route_group": RouteGroup.VCA,
        "primary_shipping_purpose": ShippingPurpose.ONLINE_ORDERS,
        "shipping_frequency": ShippingFrequency.OCCASIONAL,
        "tags": ["service-recovery"],
        "shipments": [(RouteGroup.VCA, 200), (RouteGroup.VCA, 150)],
    },
    {
        "full_name": "Ahmed Al-Rashidi (demo)",
        "phone": "+1 403 555 0198",
        "email": "ahmed.demo@demo.example.com",
        "city": "Calgary",
        "province_state": "AB",
        "country_code": "CA",
        "preferred_language": PreferredLanguage.EN,
        "primary_route_group": RouteGroup.CAD,
        "primary_shipping_purpose": ShippingPurpose.RETURNS,
        "shipping_frequency": ShippingFrequency.OCCASIONAL,
        "tags": [],
        "shipments": [(RouteGroup.CAD, 46)],
    },
    {
        "full_name": "Đặng Minh Tuấn (demo)",
        "phone": "+1 416 555 0142",  # deliberately shares a phone with the first record
        "email": "minh.tuan.demo@demo.example.com",
        "city": "Toronto",
        "province_state": "ON",
        "country_code": "CA",
        "preferred_language": PreferredLanguage.VI,
        "primary_route_group": RouteGroup.CAV,
        "primary_shipping_purpose": ShippingPurpose.PERSONAL_ITEMS,
        "shipping_frequency": ShippingFrequency.UNKNOWN,
        "tags": [],
        "shipments": [],
    },
]

# The UAT pack's named test people (`docs/UAT/UAT_CASES.md`, "Test data"), seeded exactly
# as the pack lists them so UAT-AD-04, UAT-OP-11/12 and the Customer Account cases have
# their data on a fresh reset (fix pack of 2026-10-14, item 12). P4 is the deliberate
# near-duplicate of P1: same phone, unaccented name. P5 has no phone. All on the reserved
# `example.com` domain, so none of them can authenticate in production.
UAT_PERSONAS = [
    {
        "ref": "P1",
        "full_name": "Nguyễn Thị Bích Hạnh",
        "email": "hanh.uat@example.com",
        "phone": "+1 416 555 0111",
        "city": "Toronto",
        "province_state": "ON",
        "preferred_language": PreferredLanguage.VI,
        "primary_route_group": RouteGroup.CAV,
    },
    {
        "ref": "P2",
        "full_name": "Trần Quốc Tuấn",
        "email": "tuan.uat@example.com",
        "phone": "+1 416 555 0112",
        "city": "Toronto",
        "province_state": "ON",
        "preferred_language": PreferredLanguage.VI,
        "primary_route_group": RouteGroup.CAV,
    },
    {
        "ref": "P3",
        "full_name": "Daniel O'Sullivan",
        "email": "daniel.uat@example.com",
        "phone": "+1 647 555 0113",
        "city": "Mississauga",
        "province_state": "ON",
        "preferred_language": PreferredLanguage.EN,
        "primary_route_group": RouteGroup.CAD,
    },
    {
        "ref": "P4",
        "full_name": "Nguyen Thi Bich Hanh",
        "email": "hanh.dup@example.com",
        "phone": "+1 416 555 0111",
        "city": "Toronto",
        "province_state": "ON",
        "preferred_language": PreferredLanguage.EN,
        "primary_route_group": RouteGroup.CAV,
    },
    {
        "ref": "P5",
        "full_name": "Lê Thị Mai Anh",
        "email": "maianh.uat@example.com",
        "phone": None,
        "city": "Ottawa",
        "province_state": "ON",
        "preferred_language": PreferredLanguage.VI,
        "primary_route_group": RouteGroup.VCA,
    },
]

#: One customer with more shipments than a page holds, so list paging can be exercised on
#: the Staff Portal and the Customer Account (page size 25). Fictional, flagged, demo.
PAGING_CUSTOMER = {
    "full_name": "Hoàng Văn Lâm (demo)",
    "phone": "+1 416 555 0190",
    "email": "van.lam.demo@demo.example.com",
    "city": "Toronto",
    "province_state": "ON",
    "country_code": "CA",
    "preferred_language": PreferredLanguage.VI,
    "primary_route_group": RouteGroup.CAV,
    "primary_shipping_purpose": ShippingPurpose.ONLINE_ORDERS,
    "shipping_frequency": ShippingFrequency.WEEKLY,
    "tags": ["frequent-shipper", "small-business"],
}
PAGING_SHIPMENT_COUNT = 28

#: CA-SHP-10: a shipment booked late in the evening, office time, on the first customer.
#: 23:30 in Toronto is 03:30 or 04:30 UTC *the next day*, so a date filter cut on UTC
#: midnight would put it on the wrong day -- which is the defect the case exists to catch.
#: Found again by its booking reference, so a re-seed does not add a second one.
LATE_EVENING_BOOKING_REFERENCE = "UAT-CA-SHP-10"
LATE_EVENING_LOCAL_TIME = time(23, 30)
LATE_EVENING_DAYS_AGO = 10

SYSTEM_SEGMENTS = [
    (
        "Prospects awaiting first shipment",
        "Customers with no qualifying shipment yet.",
        {
            "match": "all",
            "conditions": [{"field": "lifecycle_status", "operator": "in", "value": ["prospect"]}],
        },
    ),
    (
        "First-time shippers to follow up",
        "Exactly one qualifying shipment inside the New window.",
        {
            "match": "all",
            "conditions": [{"field": "lifecycle_status", "operator": "in", "value": ["new"]}],
        },
    ),
    (
        "Repeat customers",
        "Two or more qualifying shipments.",
        {
            "match": "all",
            "conditions": [{"field": "is_repeat_customer", "operator": "is", "value": True}],
        },
    ),
    (
        "Inactive over 90 days",
        "No qualifying shipment in more than 90 days.",
        {
            "match": "all",
            "conditions": [
                {"field": "last_shipment_at", "operator": "more_than_days_ago", "value": 90}
            ],
        },
    ),
    (
        "Vietnam to Canada customers",
        "Shipped at least once on the VCA route.",
        {
            "match": "all",
            "conditions": [{"field": "observed_route_group", "operator": "in", "value": ["VCA"]}],
        },
    ),
    (
        "Canada to Vietnam customers",
        "Shipped at least once on the CAV route.",
        {
            "match": "all",
            "conditions": [{"field": "observed_route_group", "operator": "in", "value": ["CAV"]}],
        },
    ),
    (
        "Domestic Canada customers",
        "Shipped at least once on the CAD route.",
        {
            "match": "all",
            "conditions": [{"field": "observed_route_group", "operator": "in", "value": ["CAD"]}],
        },
    ),
    (
        "US Cross Border customers",
        "Shipped at least once on the XUS route.",
        {
            "match": "all",
            "conditions": [{"field": "observed_route_group", "operator": "in", "value": ["XUS"]}],
        },
    ),
    (
        "Vietnamese language preference",
        "Recorded preferred language is Vietnamese.",
        {
            "match": "all",
            "conditions": [{"field": "preferred_language", "operator": "in", "value": ["vi"]}],
        },
    ),
    (
        "Customers with overdue follow-ups",
        "At least one open follow-up task past its due time.",
        {
            "match": "all",
            "conditions": [{"field": "has_overdue_task", "operator": "is", "value": True}],
        },
    ),
    (
        "Unresolved service issues",
        "At least one open or in-review service issue.",
        {
            "match": "all",
            "conditions": [
                {"field": "has_unresolved_service_issue", "operator": "is", "value": True}
            ],
        },
    ),
    (
        "High volume shippers",
        "Five or more qualifying lifetime shipments.",
        {
            "match": "all",
            "conditions": [{"field": "total_qualifying_shipments", "operator": "gte", "value": 5}],
        },
    ),
    (
        "Canada to Vietnam, Vietnamese, lapsed 60 days",
        "Example of an AND group combining route, language, and recency.",
        {
            "match": "all",
            "conditions": [
                {"field": "observed_route_group", "operator": "in", "value": ["CAV"]},
                {"field": "preferred_language", "operator": "in", "value": ["vi"]},
                {"field": "last_shipment_at", "operator": "more_than_days_ago", "value": 60},
            ],
        },
    ),
]


def _guard() -> None:
    if settings.is_production or not settings.allow_demo_seed:
        raise SystemExit(
            "Refusing to seed: demo data is disabled for this environment. "
            "Set ENVIRONMENT=development and ALLOW_DEMO_SEED=true to seed a local database."
        )


# --- Bulk shipments, with the events their state implies ------------------------
#
# The volume shipments used to be written as a stored state and nothing else: a row that
# said "delivered" with no event anywhere saying when or to whom. Since the 2026-10-14 fix
# pack the public tracking page derives everything it shows from **published** events
# (UAT-XX-02), so a stored state with no events reads publicly as "Booked". Every bulk
# shipment therefore carries the published milestones its state implies, which is also
# what makes the seed honest: a record a tester opens has a timeline that explains it.

#: Published milestones per terminal state, as (event type, days after handoff, wording).
#: The wording is a staff-typed public sentence, flagged `(demo)` like everything else.
_STATE_MILESTONES: dict[str, list[tuple[ShipmentEventType, int, str]]] = {
    OperationalState.BOOKED: [],
    OperationalState.RECEIVED_AT_SOLARIS: [
        (ShipmentEventType.RECEIVED_AT_SOLARIS, 0, "Received at our warehouse. (demo)"),
    ],
    OperationalState.IN_TRANSIT: [
        (ShipmentEventType.RECEIVED_AT_SOLARIS, 0, "Received at our warehouse. (demo)"),
        (ShipmentEventType.IN_TRANSIT, 1, "Your shipment is on its way. (demo)"),
    ],
    OperationalState.CUSTOMS_PROCESSING: [
        (ShipmentEventType.RECEIVED_AT_SOLARIS, 0, "Received at our warehouse. (demo)"),
        (ShipmentEventType.IN_TRANSIT, 1, "Your shipment is on its way. (demo)"),
        (ShipmentEventType.CUSTOMS_PROCESSING, 3, "Your shipment is clearing customs. (demo)"),
    ],
    OperationalState.OUT_FOR_DELIVERY: [
        (ShipmentEventType.RECEIVED_AT_SOLARIS, 0, "Received at our warehouse. (demo)"),
        (ShipmentEventType.IN_TRANSIT, 1, "Your shipment is on its way. (demo)"),
        (ShipmentEventType.OUT_FOR_DELIVERY, 5, "Out for delivery today. (demo)"),
    ],
    OperationalState.DELIVERED: [
        (ShipmentEventType.RECEIVED_AT_SOLARIS, 0, "Received at our warehouse. (demo)"),
        (ShipmentEventType.IN_TRANSIT, 1, "Your shipment is on its way. (demo)"),
        (ShipmentEventType.DELIVERED_TO_RECIPIENT, 6, "Delivered to the recipient. (demo)"),
    ],
    OperationalState.EXCEPTION: [
        (ShipmentEventType.RECEIVED_AT_SOLARIS, 0, "Received at our warehouse. (demo)"),
        (ShipmentEventType.IN_TRANSIT, 1, "Your shipment is on its way. (demo)"),
        (ShipmentEventType.EXCEPTION, 3, "Your shipment is held pending paperwork. (demo)"),
    ],
    OperationalState.DELIVERY_ATTEMPTED: [
        (ShipmentEventType.RECEIVED_AT_SOLARIS, 0, "Received at our warehouse. (demo)"),
        (ShipmentEventType.OUT_FOR_DELIVERY, 4, "Out for delivery today. (demo)"),
        (ShipmentEventType.DELIVERY_ATTEMPTED, 4, "We tried to deliver; nobody was home. (demo)"),
    ],
}

#: The states the paging customer's shipments cycle through: every one a tester can filter
#: for, plus one whose last event is deliberately **unpublished** (see `_bulk_shipment`).
_PAGING_STATES: tuple[tuple[str, int, bool], ...] = (
    # (stored state, package count, publish the last event)
    (OperationalState.DELIVERED, 1, True),
    (OperationalState.IN_TRANSIT, 2, True),
    (OperationalState.DELIVERED, 3, True),
    (OperationalState.CUSTOMS_PROCESSING, 1, True),
    (OperationalState.OUT_FOR_DELIVERY, 1, True),
    (OperationalState.PARTIALLY_DELIVERED, 3, True),
    (OperationalState.EXCEPTION, 1, True),
    (OperationalState.DELIVERED, 2, True),
    (OperationalState.RECEIVED_AT_SOLARIS, 1, True),
    (OperationalState.DELIVERY_ATTEMPTED, 1, True),
    (OperationalState.BOOKED, 1, True),
    # The UAT-XX-02 finding, reproduced on purpose: internally this shipment is an
    # exception, but the exception was never published, so the public page must still
    # say "In transit" and never "Delayed".
    (OperationalState.EXCEPTION, 1, False),
    (OperationalState.DELIVERED, 1, True),
    (OperationalState.IN_TRANSIT, 1, True),
)


def _bulk_shipment(
    db,
    customer: Customer,
    route: RouteGroup,
    *,
    days_ago: int,
    state: str,
    packages: int = 1,
    publish_last: bool = True,
    is_demo_record: bool = True,
    actor: User | None = None,
    now,
) -> Shipment:
    """One confirmed volume shipment, written as rows, with the events its state implies.

    Rows rather than services, as the volume seed always was -- the point of these is
    quantity and spread, not the booking workflow, which `_seed_phase_2_bookings` already
    exercises through the services. What changed is that the stored state is now backed
    by event rows, published ones, so the public page and the staff page agree.

    ``PARTIALLY_DELIVERED`` needs at least two packages: the first is delivered and the
    rest are out for delivery. ``publish_last=False`` leaves the final milestone as an
    internal-only event; the stored state still reflects it, as the staff portal would.
    """
    handoff = now - timedelta(days=days_ago)
    is_booked_only = state == OperationalState.BOOKED
    milestones = _STATE_MILESTONES.get(
        OperationalState.OUT_FOR_DELIVERY
        if state == OperationalState.PARTIALLY_DELIVERED
        else state,
        [],
    )
    destination = "VN" if route == RouteGroup.CAV else "US" if route == RouteGroup.XUS else "CA"
    shipment = Shipment(
        public_id=f"SX-{route.value}-{random_suffix()}",
        customer_id=customer.id,
        route_group=route.value,
        service_type=ServiceType.STANDARD_PARCEL.value,
        transport_mode=(
            TransportMode.AIR.value
            if route in (RouteGroup.VCA, RouteGroup.CAV)
            else TransportMode.GROUND.value
        ),
        booking_state=BookingState.CONFIRMED.value,
        operational_state=state,
        booking_date=handoff - timedelta(days=1),
        confirmed_at=handoff - timedelta(days=1),
        first_handoff_at=None if is_booked_only else handoff,
        package_count=packages,
        origin_country_code="VN" if route == RouteGroup.VCA else "CA",
        destination_country_code=destination,
        currency="CAD",
        selling_amount=round(random.uniform(60, 320), 2),
        shipping_cost=round(random.uniform(30, 180), 2),
        owner_user_id=customer.owner_user_id,
        is_demo_record=is_demo_record,
        contents_description="Demo contents" if is_demo_record else "Household goods",
        recipient_name="Demo Recipient" if is_demo_record else "Recipient",
        recipient_city="Ho Chi Minh City" if route == RouteGroup.CAV else "Toronto",
        recipient_country_code=destination,
        sender_city=customer.city,
        sender_country_code=customer.country_code,
    )
    db.add(shipment)
    db.flush()

    delivered_rows = 0
    for sequence in range(1, packages + 1):
        own = list(milestones)
        if state == OperationalState.PARTIALLY_DELIVERED and sequence == 1:
            own.append(
                (ShipmentEventType.DELIVERED_TO_RECIPIENT, 6, "Delivered to the recipient. (demo)")
            )
        last_state = (
            EVENT_TYPE_TO_OPERATIONAL_STATE[own[-1][0].value] if own else OperationalState.BOOKED
        )
        delivered_at = None
        package = ShipmentPackage(
            shipment_id=shipment.id,
            sequence=sequence,
            package_reference=f"{shipment.public_id}-{sequence:02d}",
            length_value=40,
            width_value=30,
            height_value=20,
            dimension_unit=DimensionUnit.CM.value,
            length_cm=40,
            width_cm=30,
            height_cm=20,
            weight_value=round(random.uniform(1.5, 9.0), 2),
            weight_unit=WeightUnit.KG.value,
            weight_kg=round(random.uniform(1.5, 9.0), 2),
            contents_summary="Demo carton" if is_demo_record else "Carton",
            operational_state=last_state,
        )
        db.add(package)
        db.flush()
        for index, (event_type, offset, wording) in enumerate(own):
            occurred = handoff + timedelta(days=offset, hours=sequence)
            is_last = index == len(own) - 1
            published = publish_last or not is_last
            is_final = event_type == ShipmentEventType.DELIVERED_TO_RECIPIENT
            if is_final:
                delivered_at = occurred
            db.add(
                ShipmentEvent(
                    shipment_id=shipment.id,
                    package_id=package.id,
                    event_type=event_type.value,
                    operational_state=EVENT_TYPE_TO_OPERATIONAL_STATE[event_type.value],
                    occurred_at=occurred,
                    recorded_at=occurred + timedelta(minutes=5),
                    location_country_code=destination
                    if offset >= 3
                    else shipment.origin_country_code,
                    internal_detail=(
                        None if published else "Commercial invoice query at the border (demo)."
                    ),
                    is_public_update=published,
                    public_update_text=wording if published else None,
                    is_final_recipient_delivery=is_final,
                    source=EventSource.MANUAL.value,
                    recorded_by_user_id=actor.id if actor else None,
                )
            )
        if delivered_at is not None:
            package.delivered_to_recipient_at = delivered_at
            delivered_rows += 1

    if delivered_rows and delivered_rows == packages:
        shipment.delivered_at = handoff + timedelta(days=6, hours=packages)
    db.flush()
    return shipment


# --- Phase 2 demo bookings -------------------------------------------------

DEMO_SENDER_CA = {
    "name": "Solaris Express — Mississauga counter (demo)",
    "company": "Solaris Express Inc.",
    "phone_entered": "+1 905 555 0110",
    "address_line1": "4120 Dixie Road, Unit 6",
    "city": "Mississauga",
    "province_state": "ON",
    "postal_code": "L4W 1V2",
    "country_code": "CA",
}

DEMO_RECIPIENT_VN = {
    "name": "Nguyễn Thị Bích Hạnh (demo)",
    "phone_entered": "+84 90 123 4567",
    "address_line1": "125 Đường Nguyễn Huệ, Phường Bến Nghé",
    "address_line2": "Quận 1",
    "city": "Thành phố Hồ Chí Minh",
    "province_state": "Hồ Chí Minh",
    "postal_code": "700000",
    "country_code": "VN",
    "delivery_note": "Call on arrival; the building has a gate (demo).",
}

DEMO_SENDER_VN = {
    "name": "Trần Đặng Hoàng Việt (demo)",
    "phone_entered": "+84 28 3822 1234",
    "address_line1": "48 Lê Lợi",
    "city": "Thành phố Hồ Chí Minh",
    "province_state": "Hồ Chí Minh",
    "postal_code": "700000",
    "country_code": "VN",
}

DEMO_RECIPIENT_CA = {
    "name": "Marie-Ève Lafontaine (demo)",
    "phone_entered": "+1 514 555 0177",
    "address_line1": "2200 Rue Sainte-Catherine Ouest",
    "city": "Montréal",
    "province_state": "QC",
    "postal_code": "H3H 1M2",
    "country_code": "CA",
}

DEMO_RECIPIENT_US = {
    "name": "Dana Whitfield (demo)",
    "phone_entered": "+1 206 555 0143",
    "address_line1": "900 Pike Street, Suite 410",
    "city": "Seattle",
    "province_state": "WA",
    "postal_code": "98101",
    "country_code": "US",
}


def _seed_phase_2_bookings(db, customers: list, staff: dict, now) -> None:
    """Build a handful of full bookings through the real services.

    Nothing is written directly: every ID, package reference, and derived status comes
    from the same code the API uses, so the demo data cannot drift from the rules.
    """
    admin = staff[Role.ADMIN]
    ops = staff[Role.OPERATIONS]

    def draft(customer, route_group, sender, recipient, packages, **extra):
        payload = {
            "customer_id": customer.id,
            "route_group": route_group.value,
            "service_type": ServiceType.STANDARD_PARCEL.value,
            "transport_mode": TransportMode.AIR.value,
            "sender": dict(sender),
            "recipient": dict(recipient),
            "packages": packages,
            "is_demo_record": True,
            "owner_user_id": customer.owner_user_id,
            **extra,
        }
        return booking_service.create_draft(db, payload, actor=ops)

    def carton(weight, contents, unit=WeightUnit.KG.value, note=None, location=None):
        return {
            "length_value": 45 if unit == WeightUnit.KG.value else 18,
            "width_value": 35 if unit == WeightUnit.KG.value else 14,
            "height_value": 25 if unit == WeightUnit.KG.value else 10,
            "dimension_unit": (
                DimensionUnit.CM.value if unit == WeightUnit.KG.value else DimensionUnit.IN.value
            ),
            "weight_value": weight,
            "weight_unit": unit,
            "contents_summary": contents,
            "handling_note": note,
            "warehouse_location": location,
        }

    # 1. Canada to Vietnam, three packages, one delivered: the "1 of 3" example.
    partial = draft(
        customers[0],
        RouteGroup.CAV,
        DEMO_SENDER_CA,
        DEMO_RECIPIENT_VN,
        [
            carton("6.4", "Winter clothing (demo)", location="A-04-1"),
            carton("4.2", "Vitamins and dried fruit (demo)", note="Keep dry", location="A-04-2"),
            carton("12.5", "Kitchenware (demo)", unit=WeightUnit.LB.value, location="A-04-3"),
        ],
        contents_description="Family gift parcel: clothing, vitamins, kitchenware (demo)",
        declared_value="480.00",
        declared_value_currency="CAD",
        booking_reference="DEMO-CAV-0001",
    )
    booking_service.confirm_booking(
        db, shipment_id=partial.id, idempotency_key="demo-seed-cav-partial", actor=ops
    )
    db.flush()

    packages = package_service.active_packages(db, partial.id)
    pickup = leg_service.create_leg(
        db,
        partial,
        {
            "leg_type": LegType.ORIGIN_PICKUP.value,
            "provider_name": "Purolator",
            "service_display": "Ground pickup",
            "origin_label": "Customer address, Mississauga",
            "origin_country_code": "CA",
            "destination_label": "Solaris Mississauga warehouse",
            "destination_country_code": "CA",
            "package_ids": [package.id for package in packages],
        },
        actor=ops,
    )
    linehaul = leg_service.create_leg(
        db,
        partial,
        {
            "leg_type": LegType.CONSOLIDATION_LINEHAUL.value,
            "provider_name": "Solaris Express",
            "service_display": "Consolidated air freight",
            "origin_label": "Solaris Mississauga warehouse",
            "origin_country_code": "CA",
            "destination_label": "Tân Sơn Nhất gateway",
            "destination_country_code": "VN",
            "consolidation_reference": "SOL-CONS-2026-014 (demo)",
            "package_ids": [package.id for package in packages],
        },
        actor=ops,
    )
    final = leg_service.create_leg(
        db,
        partial,
        {
            "leg_type": LegType.FINAL_DELIVERY.value,
            "provider_name": "Vietnam Post",
            "service_display": "Standard delivery",
            "origin_label": "Tân Sơn Nhất gateway",
            "origin_country_code": "VN",
            "destination_label": "Recipient address, Quận 1",
            "destination_country_code": "VN",
            "is_final_recipient_delivery": True,
            "package_ids": [package.id for package in packages],
        },
        actor=ops,
    )
    leg_service.add_tracking_reference(
        db,
        pickup,
        {
            "carrier_name": "Purolator",
            "tracking_number": "DEMO-PURO-4471902",
            "source_mode": TrackingSourceMode.MANUAL.value,
        },
        actor=ops,
    )
    leg_service.add_tracking_reference(
        db,
        linehaul,
        {
            "carrier_name": "Solaris Express",
            "tracking_number": "DEMO-MASTER-88120",
            "source_mode": TrackingSourceMode.MANUAL.value,
        },
        actor=ops,
    )
    leg_service.add_tracking_reference(
        db,
        final,
        {
            "carrier_name": "Vietnam Post",
            "tracking_number": "DEMO-VNPOST-77310",
            "source_mode": TrackingSourceMode.MANUAL.value,
            "package_id": packages[0].id,
        },
        actor=ops,
    )

    for event_type, days, location, country, public_text in [
        (ShipmentEventType.RECEIVED_AT_SOLARIS, 18, "Solaris Mississauga warehouse", "CA", None),
        (ShipmentEventType.PROCESSING, 17, "Solaris Mississauga warehouse", "CA", None),
        (
            ShipmentEventType.DEPARTED_ORIGIN,
            15,
            "Toronto Pearson",
            "CA",
            "Your parcels have left Canada. (demo)",
        ),
        (ShipmentEventType.CUSTOMS_PROCESSING, 11, "Tân Sơn Nhất", "VN", None),
        (ShipmentEventType.ARRIVED_DESTINATION, 9, "Thành phố Hồ Chí Minh", "VN", None),
    ]:
        event_service.record_event(
            db,
            partial,
            {
                "event_type": event_type.value,
                "occurred_at": now - timedelta(days=days),
                "location_label": location,
                "location_country_code": country,
                "is_public_update": public_text is not None,
                "public_update_text": public_text,
                "internal_detail": "Recorded by the demo seed.",
            },
            actor=ops,
        )
    # One package of three reaches the recipient: Partially delivered, "1 of 3".
    event_service.record_event(
        db,
        partial,
        {
            "event_type": ShipmentEventType.DELIVERED_TO_RECIPIENT.value,
            "occurred_at": now - timedelta(days=6),
            "package_id": packages[0].id,
            "leg_id": final.id,
            "location_label": "Quận 1",
            "location_country_code": "VN",
            "is_public_update": True,
            "public_update_text": "One of your three parcels has been delivered. (demo)",
        },
        actor=ops,
    )

    # 2. Vietnam to Canada, delivered in full, with an exception recorded and cleared.
    inbound = draft(
        customers[1],
        RouteGroup.VCA,
        DEMO_SENDER_VN,
        DEMO_RECIPIENT_CA,
        [carton("3.8", "Dried longan and tea (demo)", location="B-02-1")],
        contents_description="Food gift parcel (demo)",
        declared_value="120.00",
        declared_value_currency="CAD",
    )
    booking_service.confirm_booking(
        db, shipment_id=inbound.id, idempotency_key="demo-seed-vca-delivered", actor=ops
    )
    db.flush()
    # Published milestones, except the customs step, which stays internal: the public
    # page derives its status from published events only (UAT-XX-02), so a delivery the
    # customer was never told about would read publicly as "Booked".
    for event_type, days, public_text in [
        (ShipmentEventType.RECEIVED_AT_SOLARIS, 26, "Received at our warehouse. (demo)"),
        (ShipmentEventType.DEPARTED_ORIGIN, 24, "Your parcel has left Vietnam. (demo)"),
        (ShipmentEventType.CUSTOMS_PROCESSING, 20, None),
        (ShipmentEventType.OUT_FOR_DELIVERY, 16, "Out for delivery today. (demo)"),
        (ShipmentEventType.DELIVERED_TO_RECIPIENT, 15, "Delivered to the recipient. (demo)"),
    ]:
        event_service.record_event(
            db,
            inbound,
            {
                "event_type": event_type.value,
                "occurred_at": now - timedelta(days=days),
                "location_country_code": "CA" if days < 22 else "VN",
                "is_public_update": public_text is not None,
                "public_update_text": public_text,
            },
            actor=ops,
        )

    # 3. US cross border with a delivery exception, for the exception queue.
    cross_border = draft(
        customers[2],
        RouteGroup.XUS,
        DEMO_SENDER_CA,
        DEMO_RECIPIENT_US,
        [carton("9.0", "Business samples (demo)", unit=WeightUnit.LB.value)],
        contents_description="Business samples (demo)",
        transport_mode=TransportMode.GROUND.value,
    )
    booking_service.confirm_booking(
        db, shipment_id=cross_border.id, idempotency_key="demo-seed-xus-exception", actor=ops
    )
    db.flush()
    event_service.record_event(
        db,
        cross_border,
        {
            "event_type": ShipmentEventType.IN_TRANSIT.value,
            "occurred_at": now - timedelta(days=4),
            "location_label": "Fort Erie",
            "location_country_code": "CA",
        },
        actor=ops,
    )
    event_service.record_event(
        db,
        cross_border,
        {
            "event_type": ShipmentEventType.EXCEPTION.value,
            "occurred_at": now - timedelta(days=2),
            "location_label": "Buffalo",
            "location_country_code": "US",
            "internal_detail": "Commercial invoice query at the border (demo).",
            "is_public_update": True,
            "public_update_text": "Your shipment is held pending paperwork. (demo)",
        },
        actor=ops,
    )

    # 4. A domestic draft left unconfirmed, so the list shows a resumable draft with no
    #    customer-facing ID.
    draft(
        customers[3],
        RouteGroup.CAD,
        DEMO_SENDER_CA,
        {
            "name": "Amara Okonkwo (demo)",
            "phone_entered": "+1 604 555 0122",
            "address_line1": "1055 West Georgia Street",
            "city": "Vancouver",
            "province_state": "BC",
            "postal_code": "V6E 3P3",
            "country_code": "CA",
        },
        [carton("2.1", "Documents and a small gift (demo)")],
        contents_description="Documents and a small gift (demo)",
    )

    # 5. A cancelled-and-rebooked pair, so the corrected-route workflow is visible.
    wrong_route = draft(
        customers[4],
        RouteGroup.CAD,
        DEMO_SENDER_CA,
        {
            "name": "Lê Minh Quân (demo)",
            "phone_entered": "+1 416 555 0166",
            "address_line1": "77 King Street West",
            "city": "Toronto",
            "province_state": "ON",
            "postal_code": "M5K 1A1",
            "country_code": "CA",
        },
        [carton("5.0", "Household goods (demo)")],
        contents_description="Household goods (demo)",
    )
    booking_service.confirm_booking(
        db, shipment_id=wrong_route.id, idempotency_key="demo-seed-cad-wrong", actor=ops
    )
    db.flush()
    replacement = booking_service.rebook_shipment(
        db,
        wrong_route,
        reason="Booked as domestic Canada; the parcel is going to Vietnam (demo)",
        changes={
            "route_group": RouteGroup.CAV.value,
            "recipient": dict(DEMO_RECIPIENT_VN),
        },
        actor=admin,
    )
    booking_service.confirm_booking(
        db, shipment_id=replacement.id, idempotency_key="demo-seed-cav-rebooked", actor=ops
    )
    db.flush()

    for shipment in (partial, inbound, cross_border, replacement):
        shipment.currency = "CAD"
        shipment.selling_amount = round(random.uniform(90, 340), 2)
        shipment.shipping_cost = round(random.uniform(40, 190), 2)
    db.flush()


def _seed_uat_fixtures(db, created: list, staff: dict, tags: dict, now) -> None:
    """The data the UAT packs name and the fix-pack review asked for.

    * the five named test people, **P1-P5**, exactly as `UAT_CASES.md` lists them, so a
      tester opening the pack finds its data rather than typing it;
    * **P1** with history worth looking at: one shipment in transit with published
      milestones, one plainly cancelled, and one cancelled-and-rebooked pair -- a customer
      with cancelled *and* rebooked shipments, through the real services;
    * one customer with **more shipments than a page holds** (`PAGING_SHIPMENT_COUNT`),
      cycling through every operational state a tester can filter for, including one whose
      exception was never published (the UAT-XX-02 finding, kept on purpose);
    * one **non-demo** shipment for the first customer (`STCA-000001` on a fresh database),
      because the Customer Account's inclusion rule excludes demo records outright and a
      tester linking an account to it otherwise saw an empty list;
    * a second non-demo shipment on that customer **booked at 23:30 Toronto time**, which is
      the next UTC date, for the date-filter boundary case `CA-SHP-10` (UAT round 3).
    """
    admin = staff[Role.ADMIN]
    ops = staff[Role.OPERATIONS]

    # --- P1 to P5 ------------------------------------------------------------------
    personas: dict[str, Customer] = {}
    for spec in UAT_PERSONAS:
        existing = db.scalar(select(Customer).where(Customer.email_normalized == spec["email"]))
        if existing is not None:
            personas[spec["ref"]] = existing
            continue
        payload = {
            "full_name": spec["full_name"],
            "phone": spec["phone"],
            "email": spec["email"],
            "city": spec["city"],
            "province_state": spec["province_state"],
            "country_code": "CA",
            "preferred_language": spec["preferred_language"].value,
            "category": CustomerCategory.INDIVIDUAL.value,
            "primary_shipping_purpose": ShippingPurpose.GIFTS_FAMILY_SUPPORT.value,
            "primary_route_group": spec["primary_route_group"].value,
            "shipping_frequency": ShippingFrequency.OCCASIONAL.value,
            "preferred_contact_channel": ContactChannel.PHONE.value
            if spec["phone"]
            else ContactChannel.EMAIL.value,
            "owner_user_id": ops.id,
            "notes": f"UAT test person {spec['ref']} (docs/UAT/UAT_CASES.md). Seeded.",
        }
        customer = customer_service.create_customer(db, payload, actor=admin, is_demo_record=True)
        db.flush()
        personas[spec["ref"]] = customer

    p1 = personas["P1"]

    def draft(customer, route_group, sender, recipient, packages, **extra):
        payload = {
            "customer_id": customer.id,
            "route_group": route_group.value,
            "service_type": ServiceType.STANDARD_PARCEL.value,
            "transport_mode": TransportMode.AIR.value,
            "sender": dict(sender),
            "recipient": dict(recipient),
            "packages": packages,
            "is_demo_record": True,
            "owner_user_id": customer.owner_user_id,
            **extra,
        }
        return booking_service.create_draft(db, payload, actor=ops)

    carton = {
        "length_value": 40,
        "width_value": 30,
        "height_value": 20,
        "dimension_unit": DimensionUnit.CM.value,
        "weight_value": "5.5",
        "weight_unit": WeightUnit.KG.value,
        "contents_summary": "Clothing and dried fruit (demo)",
    }

    if db.scalar(select(Shipment).where(Shipment.customer_id == p1.id)) is None:
        # In transit, with published milestones a tester can read on the public page.
        moving = draft(
            p1,
            RouteGroup.CAV,
            DEMO_SENDER_CA,
            DEMO_RECIPIENT_VN,
            [dict(carton), dict(carton)],
            contents_description="Family parcel: clothing and dried fruit (demo)",
            booking_reference="UAT-P1-0001",
        )
        booking_service.confirm_booking(
            db, shipment_id=moving.id, idempotency_key="uat-seed-p1-moving", actor=ops
        )
        db.flush()
        for event_type, days, text in [
            (ShipmentEventType.RECEIVED_AT_SOLARIS, 9, "Received at our warehouse. (demo)"),
            (ShipmentEventType.DEPARTED_ORIGIN, 7, "Your parcels have left Canada. (demo)"),
            (ShipmentEventType.IN_TRANSIT, 5, "Your shipment is on its way. (demo)"),
        ]:
            event_service.record_event(
                db,
                moving,
                {
                    "event_type": event_type.value,
                    "occurred_at": now - timedelta(days=days),
                    "location_country_code": "CA" if days > 6 else "VN",
                    "is_public_update": True,
                    "public_update_text": text,
                },
                actor=ops,
            )

        # Plainly cancelled: confirmed, then withdrawn before departure.
        withdrawn = draft(
            p1,
            RouteGroup.CAV,
            DEMO_SENDER_CA,
            DEMO_RECIPIENT_VN,
            [dict(carton)],
            contents_description="Gift parcel, withdrawn (demo)",
            booking_reference="UAT-P1-0002",
        )
        booking_service.confirm_booking(
            db, shipment_id=withdrawn.id, idempotency_key="uat-seed-p1-withdrawn", actor=ops
        )
        db.flush()
        booking_service.cancel_shipment(
            db, withdrawn, reason="Customer cancelled before departure (demo)", actor=ops
        )

        # Cancelled and rebooked: the corrected-route pair, both halves linked.
        wrong = draft(
            p1,
            RouteGroup.CAD,
            DEMO_SENDER_CA,
            {
                "name": "Nguyễn Văn Hùng (demo)",
                "phone_entered": "+1 416 555 0170",
                "address_line1": "88 Queen Street East",
                "city": "Toronto",
                "province_state": "ON",
                "postal_code": "M5C 1S6",
                "country_code": "CA",
            },
            [dict(carton)],
            contents_description="Household goods, booked on the wrong route (demo)",
            booking_reference="UAT-P1-0003",
        )
        booking_service.confirm_booking(
            db, shipment_id=wrong.id, idempotency_key="uat-seed-p1-wrong", actor=ops
        )
        db.flush()
        replacement = booking_service.rebook_shipment(
            db,
            wrong,
            reason="Booked as domestic Canada; the parcel is going to Vietnam (demo)",
            changes={"route_group": RouteGroup.CAV.value, "recipient": dict(DEMO_RECIPIENT_VN)},
            actor=admin,
        )
        booking_service.confirm_booking(
            db, shipment_id=replacement.id, idempotency_key="uat-seed-p1-rebooked", actor=ops
        )
        db.flush()
        for shipment in (moving, withdrawn, wrong, replacement):
            shipment.currency = "CAD"
            shipment.selling_amount = round(random.uniform(90, 340), 2)
            shipment.shipping_cost = round(random.uniform(40, 190), 2)
        db.flush()

    # --- The paging customer -----------------------------------------------------------
    paging = db.scalar(
        select(Customer).where(Customer.email_normalized == PAGING_CUSTOMER["email"])
    )
    if paging is None:
        payload = {
            key: (value.value if hasattr(value, "value") else value)
            for key, value in PAGING_CUSTOMER.items()
            if key != "tags"
        }
        payload.update(
            {
                "category": CustomerCategory.INDIVIDUAL.value,
                "preferred_contact_channel": ContactChannel.MESSAGING_APP.value,
                "owner_user_id": ops.id,
                "notes": "Demo record with more shipments than one page holds, for paging.",
            }
        )
        paging = customer_service.create_customer(db, payload, actor=admin, is_demo_record=True)
        db.flush()
        for slug in PAGING_CUSTOMER["tags"]:
            db.add(
                CustomerTag(
                    customer_id=paging.id,
                    tag_id=tags[slug].id,
                    created_at=now,
                    created_by_user_id=admin.id,
                )
            )
        routes = (RouteGroup.CAV, RouteGroup.CAV, RouteGroup.VCA, RouteGroup.CAD, RouteGroup.XUS)
        for index in range(PAGING_SHIPMENT_COUNT):
            state, packages, publish_last = _PAGING_STATES[index % len(_PAGING_STATES)]
            _bulk_shipment(
                db,
                paging,
                routes[index % len(routes)],
                days_ago=3 + index * 4,
                state=state,
                packages=packages,
                publish_last=publish_last,
                actor=ops,
                now=now,
            )

    # --- A non-demo shipment for the first customer ------------------------------------
    first = created[0]
    if (
        db.scalar(
            select(Shipment).where(
                Shipment.customer_id == first.id, Shipment.is_demo_record.is_(False)
            )
        )
        is None
    ):
        _bulk_shipment(
            db,
            first,
            RouteGroup.CAV,
            days_ago=7,
            state=OperationalState.IN_TRANSIT,
            packages=2,
            is_demo_record=False,
            actor=ops,
            now=now,
        )

    # --- CA-SHP-10: the late-evening booking ------------------------------------------
    _seed_late_evening_shipment(db, first, actor=ops, now=now)
    db.flush()


def late_evening_booking_utc(now: datetime, tz_name: str | None = None) -> datetime:
    """Naive UTC for 23:30 office time, ``LATE_EVENING_DAYS_AGO`` local days before ``now``.

    Resolved through ``zoneinfo`` for that date rather than by a fixed offset, because
    Toronto observes daylight saving and the UTC hour differs between summer and winter.
    """
    local_zone = zone(tz_name)
    local_today = now.replace(tzinfo=UTC).astimezone(local_zone).date()
    day = local_today - timedelta(days=LATE_EVENING_DAYS_AGO)
    local = datetime.combine(day, LATE_EVENING_LOCAL_TIME, tzinfo=local_zone)
    return local.astimezone(UTC).replace(tzinfo=None)


def _seed_late_evening_shipment(
    db, customer: Customer, *, actor: User | None, now: datetime
) -> Shipment | None:
    """A non-demo shipment on ``customer`` booked at 23:30 office time (CA-SHP-10).

    Non-demo, like the other one on this customer, because the Customer Account excludes
    demo records and the case is run from the Customer Account. Written by
    ``_bulk_shipment`` and then given its booking time: the booking services stamp "now",
    and no service books into the past.
    """
    existing = db.scalar(
        select(Shipment).where(
            Shipment.customer_id == customer.id,
            Shipment.booking_reference == LATE_EVENING_BOOKING_REFERENCE,
        )
    )
    if existing is not None:
        return None
    org = db.scalar(select(OrganizationSettings))
    booked = late_evening_booking_utc(now, org.office_timezone if org else None)
    shipment = _bulk_shipment(
        db,
        customer,
        RouteGroup.CAV,
        # Handed over at least a week after the booking, so every event follows it.
        days_ago=LATE_EVENING_DAYS_AGO - 2,
        state=OperationalState.IN_TRANSIT,
        is_demo_record=False,
        actor=actor,
        now=now,
    )
    shipment.booking_date = booked
    shipment.confirmed_at = booked
    shipment.booking_reference = LATE_EVENING_BOOKING_REFERENCE
    db.flush()
    return shipment


def reset_demo_data(db) -> None:
    """Remove demo records only. Real records are never touched."""
    demo_customer_ids = list(
        db.scalars(select(Customer.id).where(Customer.is_demo_record.is_(True))).all()
    )
    if demo_customer_ids:
        for model in (
            Interaction,
            FollowUpTask,
            ConsentEvent,
            ServiceIssue,
            CustomerAddress,
            CustomerTag,
        ):
            db.execute(delete(model).where(model.customer_id.in_(demo_customer_ids)))
        db.execute(delete(Referral).where(Referral.referrer_customer_id.in_(demo_customer_ids)))
        db.execute(delete(Shipment).where(Shipment.customer_id.in_(demo_customer_ids)))
        db.execute(delete(Customer).where(Customer.id.in_(demo_customer_ids)))
    db.execute(delete(SavedSegment).where(SavedSegment.is_system.is_(True)))


def seed(reset: bool = False) -> None:
    _guard()
    random.seed(20260908)

    with session_scope() as db:
        from app.api.deps import get_org_settings

        org = get_org_settings(db)
        org.is_demo_environment = True

        if reset:
            reset_demo_data(db)

        # --- Staff -------------------------------------------------------
        staff: dict[str, User] = {}
        for email, full_name, role in DEMO_STAFF:
            existing = db.scalar(select(User).where(User.email == email))
            if existing is None:
                existing = auth_service.create_user(
                    db, email=email, full_name=full_name, password=DEMO_PASSWORD, role=role.value
                )
            staff[role.value] = existing
        db.flush()

        # --- Tags --------------------------------------------------------
        tags: dict[str, Tag] = {}
        for slug, name, color in DEMO_TAGS:
            tag = db.scalar(select(Tag).where(Tag.slug == slug))
            if tag is None:
                tag = Tag(
                    slug=slug, name=name, color_token=color, created_by_user_id=staff[Role.ADMIN].id
                )
                db.add(tag)
            tags[slug] = tag
        db.flush()

        if (
            db.scalar(select(Customer).where(Customer.is_demo_record.is_(True))) is not None
            and not reset
        ):
            print("Demo customers already present. Re-run with --reset to rebuild them.")
            return

        owners = [staff[Role.OPERATIONS], staff[Role.ADMIN], staff[Role.MARKETING]]
        created: list[Customer] = []
        now = utcnow()

        for index, spec in enumerate(DEMO_CUSTOMERS):
            payload = {
                "full_name": spec["full_name"],
                "phone": spec["phone"],
                "email": spec["email"],
                "city": spec["city"],
                "province_state": spec["province_state"],
                "country_code": spec["country_code"],
                "preferred_language": spec["preferred_language"].value,
                "category": spec.get("category", CustomerCategory.INDIVIDUAL).value
                if hasattr(spec.get("category", CustomerCategory.INDIVIDUAL), "value")
                else spec.get("category"),
                "business_name": spec.get("business_name"),
                "business_type": spec.get("business_type"),
                "primary_shipping_purpose": spec["primary_shipping_purpose"].value,
                "primary_route_group": spec["primary_route_group"].value,
                "shipping_frequency": spec["shipping_frequency"].value,
                "preferred_contact_channel": ContactChannel.PHONE.value,
                "owner_user_id": owners[index % len(owners)].id,
                "notes": "Demo record created by the synthetic seed command.",
            }
            customer = customer_service.create_customer(
                db, payload, actor=staff[Role.ADMIN], is_demo_record=True
            )
            db.flush()
            created.append(customer)

            for slug in spec["tags"]:
                db.add(
                    CustomerTag(
                        customer_id=customer.id,
                        tag_id=tags[slug].id,
                        created_at=now,
                        created_by_user_id=staff[Role.ADMIN].id,
                    )
                )

            db.add(
                CustomerAddress(
                    customer_id=customer.id,
                    label="Home (demo)",
                    contact_name=spec["full_name"],
                    phone_entered=spec["phone"],
                    address_line1="123 Demo Street",
                    city=spec["city"],
                    province_state=spec["province_state"],
                    country_code=spec["country_code"],
                    is_default_sender=True,
                )
            )

            # Shipments: confirmed, handed off N days ago, delivered shortly after -- with
            # the published milestones that state implies (see `_bulk_shipment`).
            for route, days_ago in spec["shipments"]:
                is_delivered = days_ago > random.randint(4, 21)
                _bulk_shipment(
                    db,
                    customer,
                    route,
                    days_ago=days_ago,
                    state=(
                        OperationalState.DELIVERED if is_delivered else OperationalState.IN_TRANSIT
                    ),
                    packages=random.randint(1, 3),
                    actor=staff[Role.OPERATIONS],
                    now=now,
                )

            # A draft and a cancelled booking that must NOT count as qualifying (AC-14).
            if index == 0:
                db.add(
                    Shipment(
                        customer_id=customer.id,
                        route_group=RouteGroup.CAV.value,
                        booking_state=BookingState.DRAFT.value,
                        operational_state=OperationalState.BOOKED.value,
                        booking_date=now - timedelta(days=2),
                        package_count=1,
                        is_demo_record=True,
                    )
                )
                db.add(
                    Shipment(
                        public_id=f"SX-CAV-{random_suffix()}",
                        customer_id=customer.id,
                        route_group=RouteGroup.CAV.value,
                        booking_state=BookingState.CANCELLED.value,
                        operational_state=OperationalState.CANCELLED.value,
                        booking_date=now - timedelta(days=40),
                        first_handoff_at=now - timedelta(days=39),
                        cancelled_at=now - timedelta(days=38),
                        cancellation_reason="Customer cancelled before departure (demo)",
                        package_count=1,
                        is_demo_record=True,
                    )
                )

            db.add(
                Interaction(
                    customer_id=customer.id,
                    occurred_at=now - timedelta(days=random.randint(1, 30)),
                    channel=ContactChannel.PHONE.value,
                    direction=InteractionDirection.INBOUND.value,
                    subject="Asked about delivery timing (demo)",
                    body="Demo interaction recorded by the seed command.",
                    outcome="Explained current status",
                    author_user_id=staff[Role.OPERATIONS].id,
                )
            )

            # Consent: mixed states so the UI shows real variety.
            if index % 3 == 0:
                db.add(
                    ConsentEvent(
                        customer_id=customer.id,
                        channel=ConsentChannel.EMAIL.value,
                        address_value=customer.email_normalized,
                        status=ConsentStatus.CONSENTED.value,
                        basis=ConsentBasis.EXPRESS.value,
                        obtained_at=now - timedelta(days=60),
                        source="Demo counter sign-up form",
                        evidence_reference="DEMO-CONSENT-0001",
                        recorded_at=now - timedelta(days=60),
                        recorded_by_user_id=staff[Role.OPERATIONS].id,
                    )
                )
            elif index % 3 == 1:
                db.add(
                    ConsentEvent(
                        customer_id=customer.id,
                        channel=ConsentChannel.EMAIL.value,
                        address_value=customer.email_normalized,
                        status=ConsentStatus.UNKNOWN.value,
                        basis=ConsentBasis.NOT_RECORDED.value,
                        note="Imported without consent evidence; not marketing eligible.",
                        recorded_at=now - timedelta(days=45),
                        recorded_by_user_id=staff[Role.ADMIN].id,
                    )
                )

        db.flush()

        # --- Follow-up tasks ---------------------------------------------
        task_specs = [
            (
                created[0],
                "Confirm delivery experience",
                TaskPurpose.FIRST_SHIPMENT_FOLLOW_UP,
                -3,
                TaskPriority.NORMAL,
            ),
            (
                created[1],
                "Check in after lapse in shipping",
                TaskPurpose.AT_RISK_CHECK_IN,
                -1,
                TaskPriority.HIGH,
            ),
            (
                created[2],
                "Collect commercial invoice details",
                TaskPurpose.DOCUMENT_REQUEST,
                1,
                TaskPriority.NORMAL,
            ),
            (created[6], "Call about first booking", TaskPurpose.GENERAL, 2, TaskPriority.NORMAL),
            (
                created[7],
                "Resolve delivery exception",
                TaskPurpose.DELIVERY_EXCEPTION,
                -2,
                TaskPriority.URGENT,
            ),
            (created[4], "Quote follow-up", TaskPurpose.QUOTE_REQUEST, 4, TaskPriority.LOW),
        ]
        for customer, subject, purpose, due_offset_days, priority in task_specs:
            db.add(
                FollowUpTask(
                    customer_id=customer.id,
                    subject=f"{subject} (demo)",
                    purpose=purpose.value,
                    priority=priority.value,
                    status=TaskStatus.SCHEDULED.value,
                    due_at=now + timedelta(days=due_offset_days),
                    assignee_user_id=customer.owner_user_id,
                    created_by_user_id=staff[Role.ADMIN].id,
                )
            )
        db.add(
            FollowUpTask(
                customer_id=created[0].id,
                subject="Welcome call (demo)",
                purpose=TaskPurpose.GENERAL.value,
                priority=TaskPriority.NORMAL.value,
                status=TaskStatus.COMPLETED.value,
                due_at=now - timedelta(days=20),
                completed_at=now - timedelta(days=19),
                outcome="Spoke with customer; no issues.",
                assignee_user_id=created[0].owner_user_id,
                created_by_user_id=staff[Role.ADMIN].id,
                completed_by_user_id=staff[Role.OPERATIONS].id,
            )
        )

        # --- Service issue and referral ----------------------------------
        db.add(
            ServiceIssue(
                customer_id=created[7].id,
                title="Parcel delayed at destination sort facility (demo)",
                detail="Demo service issue used to exercise the service-recovery views.",
                status=ServiceIssueStatus.OPEN.value,
                opened_at=now - timedelta(days=5),
                opened_by_user_id=staff[Role.OPERATIONS].id,
            )
        )
        db.add(
            Referral(
                referrer_customer_id=created[0].id,
                referred_customer_id=created[9].id,
                note="Referred by a family member (demo).",
                recorded_by_user_id=staff[Role.OPERATIONS].id,
            )
        )

        # --- System segments ---------------------------------------------
        for name, description, definition in SYSTEM_SEGMENTS:
            slug = name.lower().replace(",", "").replace(" ", "-")
            if db.scalar(select(SavedSegment).where(SavedSegment.slug == slug)) is not None:
                continue
            db.add(
                SavedSegment(
                    slug=slug,
                    name=name,
                    description=description,
                    definition_json=segment_service.dump_definition(
                        segment_service.validate_definition(definition)
                    ),
                    is_system=True,
                    is_shared=True,
                    owner_user_id=staff[Role.ADMIN].id,
                )
            )

        # --- Phase 2 bookings, packages, legs, and manual events ---------
        _seed_phase_2_bookings(db, created, staff, now)

        # --- UAT fixtures (fix pack of 2026-10-14, item 12) ----------------
        _seed_uat_fixtures(db, created, staff, tags, now)

    print("Seeded synthetic demo data.")
    print(f"Demo staff password for every seeded account: {DEMO_PASSWORD}")
    for email, _, role in DEMO_STAFF:
        print(f"  {role.value:<20} {email}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed synthetic Solaris CRM demo data.")
    parser.add_argument("--reset", action="store_true", help="Delete existing demo records first.")
    args = parser.parse_args(argv)
    seed(reset=args.reset)
    return 0


if __name__ == "__main__":
    sys.exit(main())
