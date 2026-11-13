"""What a public tracking payload may never contain.

This is the file that has to fail when somebody adds a convenient field to the public
response, so it is written to be hard to satisfy accidentally.

Two scans run over the **raw JSON**, recursively, at every depth:

* a **key scan** against forbidden field names, so ``customer_email`` cannot appear
  anywhere in the tree, including inside a nested package or timeline entry;
* a **value scan** against sentinel values planted in the database, so renaming
  ``customer_email`` to ``contact`` does not make the test pass. This is the half that
  matters: a name-only check is defeated by a rename, and a rename is exactly what
  happens when somebody is refactoring rather than thinking about privacy.

Sentinels are deliberately distinctive strings that could not occur by chance
(``PRIVATE-EMAIL-9Q4X``), so a match is a leak and never a coincidence.

AC-12: "Public lookup responses contain no private customer details, notes, costs,
signatures, provider credentials, or other customers' consolidation data."
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.enums import RouteGroup, ShipmentEventType, TrackingSourceMode
from app.core.time_utils import utcnow
from app.services import booking_service, event_service, leg_service, package_service
from tests.conftest import booked_shipment, make_customer

TRACK = "/api/v1/public/track"


# --- Forbidden names -------------------------------------------------------

#: Every key name that must never appear at any depth of a public payload. Grouped the
#: way CRM.md section 10 groups them so a future reader can see what each entry protects.
FORBIDDEN_KEYS = frozenset(
    {
        # Customer identity
        "customer_id",
        "customer",
        "customer_public_id",
        "customer_name",
        "full_name",
        "public_customer_id",
        # Sender and recipient identity
        "sender_name",
        "sender_company",
        "recipient_name",
        "recipient_company",
        "sender",
        "recipient",
        # Contact details
        "email",
        "email_entered",
        "email_normalized",
        "sender_email",
        "recipient_email",
        "phone",
        "phone_entered",
        "phone_e164",
        "sender_phone",
        "sender_phone_entered",
        "sender_phone_e164",
        "recipient_phone",
        "recipient_phone_entered",
        "recipient_phone_e164",
        # Addresses
        "address_line1",
        "address_line2",
        "sender_address_line1",
        "sender_address_line2",
        "recipient_address_line1",
        "recipient_address_line2",
        "postal_code",
        "sender_postal_code",
        "recipient_postal_code",
        "sender_address_id",
        "recipient_address_id",
        "address_id",
        "province_state",
        "sender_province_state",
        "recipient_province_state",
        "delivery_note",
        "recipient_delivery_note",
        # Internal identifiers
        "id",
        "shipment_id",
        "package_id",
        "leg_id",
        "event_id",
        "owner_user_id",
        "created_by_user_id",
        "recorded_by_user_id",
        "confirmed_by_user_id",
        "cancelled_by_user_id",
        "user_id",
        "booking_reference",
        "idempotency_key",
        "source_record_id",
        "source_system",
        # Internal narrative
        "internal_detail",
        "internal_notes",
        "notes",
        "cancellation_reason",
        "voided_reason",
        "retired_reason",
        "is_voided",
        "audit",
        "audit_events",
        "recorded_by",
        "generated_by",
        "staff",
        "owner",
        # Money
        "declared_value",
        "declared_value_currency",
        "selling_amount",
        "shipping_cost",
        "surcharges_amount",
        "discount_amount",
        "refund_amount",
        "currency",
        "financials",
        "costs",
        "gross_profit",
        "revenue",
        "payment_state",
        # Carrier and consolidation
        "tracking_number",
        "carrier_tracking_number",
        "tracking_references",
        "consolidation_reference",
        "master_reference",
        # Phase 13B: the master a shipment rides in, and who pays for it
        "consolidation",
        "consolidation_id",
        "vendor_reference",
        "chargeable_weight_kg",
        "payer",
        "payer_customer_id",
        # Phase 13C: the quote and its figures
        "quote",
        "quotes",
        "selling_rate_cad",
        "total_revenue_cad",
        "gross_profit_cad",
        "allocated_cost_cad",
        "actual_cost_cad",
        "vendor_invoice",
        "vendor_invoices",
        "cost_allocations",
        "variance_cad",
        "expected_cad",
        "profit_cad",
        "margin_percent",
        "provider_payload",
        "raw_payload",
        "raw_status",
        "legs",
        # Proof of delivery
        "signature",
        "signature_image",
        "proof_of_delivery",
        "pod",
        "photo",
        # Authentication
        "session",
        "session_token",
        "csrf_token",
        "password",
        "password_hash",
        "api_key",
        "secret",
        "token",
        "permissions",
        "role",
        # Contents and measurements are operational detail, not tracking status
        "contents_description",
        "contents_summary",
        "weight_kg",
        "weight_value",
        "handling_note",
        "warehouse_location",
        "dimension_unit",
    }
)

#: Substrings that must not appear inside any key. Catches ``customer_email_address`` and
#: similar variants the exact-name list would miss.
FORBIDDEN_KEY_FRAGMENTS = (
    "password",
    "secret",
    "csrf",
    "api_key",
    "internal",
    "signature",
    "postal",
    "declared",
    "cost",
    "tracking_number",
    "consolidation",
)

#: Keys the payload legitimately uses that would otherwise trip a fragment above.
ALLOWED_EXACT_KEYS = frozenset({"package_count_active", "package_count_cancelled"})


def walk(node, path="$"):
    """Yield ``(path, key, value)`` for every key and every scalar in the tree."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield f"{path}.{key}", key, value
            yield from walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, f"{path}[{index}]")


def scan_keys(payload) -> list[str]:
    offences = []
    for path, key, _ in walk(payload):
        if key in ALLOWED_EXACT_KEYS:
            continue
        if key in FORBIDDEN_KEYS:
            offences.append(f"forbidden key {key} at {path}")
        for fragment in FORBIDDEN_KEY_FRAGMENTS:
            if fragment in key.lower():
                offences.append(f"forbidden fragment '{fragment}' in key at {path}")
    return offences


def scan_values(payload, sentinels: dict[str, str]) -> list[str]:
    """Find any sentinel anywhere in the serialized payload.

    Serializing the whole tree and searching it catches a value hidden in a key name, in a
    nested list, or in a string that was concatenated from private parts -- all of which a
    field-by-field comparison would miss.
    """
    raw = json.dumps(payload, ensure_ascii=False, default=str)
    return [f"{label} leaked: {value!r}" for label, value in sentinels.items() if value in raw]


# --- The fixture with everything private on it -----------------------------


@pytest.fixture
def loaded_shipment(db, users):
    """A confirmed shipment carrying a distinctive private value in every private field."""
    sentinels = {
        "customer name": "PRIVATE-CUSTOMER-9Q4X",
        "customer email": "private-email-9q4x@demo.example.com",
        "sender name": "PRIVATE-SENDER-7T2M",
        "sender street": "PRIVATE-SENDER-STREET-4H8K",
        "sender postal": "P4V4TE",
        "sender phone": "+15195550000",
        "recipient name": "PRIVATE-RECIPIENT-3B6L",
        "recipient street": "PRIVATE-RECIPIENT-STREET-8N1P",
        "recipient postal": "R3C1P1",
        "recipient phone": "+84905550000",
        "recipient email": "private-recipient-3b6l@demo.example.com",
        "delivery note": "PRIVATE-DELIVERY-NOTE-2W5Z",
        "booking reference": "PRIVATE-BOOKING-REF-6K3D",
        "contents": "PRIVATE-CONTENTS-1J7R",
        "internal notes": "PRIVATE-INTERNAL-NOTE-5F9C",
        "internal event detail": "PRIVATE-EVENT-DETAIL-0X2V",
        "cancellation reason": "PRIVATE-CANCEL-REASON-8L4Q",
        "handling note": "PRIVATE-HANDLING-3D7S",
        "warehouse location": "PRIVATE-BIN-A-04-9",
        "carrier tracking number": "PRIVATE-CARRIER-NUM-1Z999AA",
        "consolidation reference": "PRIVATE-CONSOL-MASTER-4R8T",
        "leg internal note": "PRIVATE-LEG-NOTE-6Y2U",
        "declared value": "4815.00",
        "selling amount": "1234.56",
        "shipping cost": "789.01",
        "voided reason": "PRIVATE-VOID-REASON-7P3W",
        "staff email": users["operations"].email,
        "staff name": users["operations"].full_name,
    }

    customer = make_customer(
        db,
        full_name=sentinels["customer name"],
        email=sentinels["customer email"],
        phone="+1 416 555 0999",
    )
    payload = {
        "customer_id": customer.id,
        "route_group": RouteGroup.CAV.value,
        "service_type": "standard_parcel",
        "transport_mode": "air",
        "booking_reference": sentinels["booking reference"],
        "contents_description": sentinels["contents"],
        "declared_value": sentinels["declared value"],
        "declared_value_currency": "CAD",
        "sender": {
            "name": sentinels["sender name"],
            "phone_entered": sentinels["sender phone"],
            "address_line1": sentinels["sender street"],
            "address_line2": "Unit 1201",
            "city": "Mississauga",
            "province_state": "ON",
            "postal_code": sentinels["sender postal"],
            "country_code": "CA",
        },
        "recipient": {
            "name": sentinels["recipient name"],
            "phone_entered": sentinels["recipient phone"],
            "email": sentinels["recipient email"],
            "address_line1": sentinels["recipient street"],
            "city": "Thành phố Hồ Chí Minh",
            "province_state": "Hồ Chí Minh",
            "postal_code": sentinels["recipient postal"],
            "country_code": "VN",
            "delivery_note": sentinels["delivery note"],
        },
        "packages": [
            {
                "length_value": "40",
                "width_value": "30",
                "height_value": "20",
                "weight_value": "5.5",
                "contents_summary": sentinels["contents"],
                "handling_note": sentinels["handling note"],
                "warehouse_location": sentinels["warehouse location"],
            }
            for _ in range(3)
        ],
    }
    shipment = booking_service.create_draft(db, payload, actor=users["operations"])
    db.commit()
    booking_service.confirm_booking(
        db, shipment_id=shipment.id, idempotency_key="privacy-key", actor=users["operations"]
    )
    shipment.internal_notes = sentinels["internal notes"]
    shipment.currency = "CAD"
    shipment.selling_amount = Decimal(sentinels["selling amount"])
    shipment.shipping_cost = Decimal(sentinels["shipping cost"])
    db.commit()

    packages = package_service.active_packages(db, shipment.id)

    leg = leg_service.create_leg(
        db,
        shipment,
        {
            "leg_type": "consolidation_linehaul",
            "provider_name": "Solaris Express",
            "consolidation_reference": sentinels["consolidation reference"],
            "internal_notes": sentinels["leg internal note"],
            "package_ids": [package.id for package in packages],
        },
        actor=users["operations"],
    )
    leg_service.add_tracking_reference(
        db,
        leg,
        {
            "carrier_name": "UPS",
            "tracking_number": sentinels["carrier tracking number"],
            "public_url": "https://www.ups.com/track?loc=en_CA&tracknum=PRIVATE-CARRIER-NUM-1Z999AA",
            "source_mode": TrackingSourceMode.EXTERNAL_LINK.value,
        },
        actor=users["operations"],
    )

    # An internal-only event, an approved public one, and a voided correction.
    event_service.record_event(
        db,
        shipment,
        {
            "event_type": ShipmentEventType.RECEIVED_AT_SOLARIS.value,
            "occurred_at": utcnow() - timedelta(days=6),
            "location_label": "Solaris Mississauga warehouse",
            "location_country_code": "CA",
            "internal_detail": sentinels["internal event detail"],
        },
        actor=users["operations"],
    )
    event_service.record_event(
        db,
        shipment,
        {
            "event_type": ShipmentEventType.DEPARTED_ORIGIN.value,
            "occurred_at": utcnow() - timedelta(days=4),
            "location_label": "Toronto Pearson",
            "location_country_code": "CA",
            "internal_detail": sentinels["internal event detail"],
            "is_public_update": True,
            "public_update_text": "Your parcels have left Canada.",
        },
        actor=users["operations"],
    )
    mistake = event_service.record_event(
        db,
        shipment,
        {
            "event_type": ShipmentEventType.EXCEPTION.value,
            "occurred_at": utcnow() - timedelta(days=3),
            "is_public_update": True,
            "public_update_text": "Held pending paperwork.",
        },
        actor=users["operations"],
    )
    for event in mistake:
        event_service.void_event(db, event, reason=sentinels["voided reason"])
    db.commit()

    return shipment, sentinels, packages


# --- The scans -------------------------------------------------------------


def test_no_forbidden_key_appears_at_any_depth(client, loaded_shipment):
    shipment, _, packages = loaded_shipment

    for reference in [shipment.public_id, packages[0].package_reference]:
        body = client.get(f"{TRACK}/{reference}").json()
        assert scan_keys(body) == []


def test_no_private_value_appears_anywhere_in_the_raw_json(client, loaded_shipment):
    """The rename-proof half: forbidden *values*, not just forbidden names.

    One value is excluded, and the exclusion is the point rather than a loophole. A
    public carrier tracking link *is* the tracking number plus a host -- that is how
    every carrier's public tracking page is addressed -- so a link whose query string
    contains the number is unavoidable if a link is offered at all. CRM.md section 10
    permits "an optional validated public carrier link"; what it forbids is exposing the
    carrier tracking number *separately*, as a field a scraper can read without following
    a link, or next to a parcel it does not belong to.

    ``test_the_carrier_tracking_number_appears_only_inside_the_approved_link`` below
    pins that distinction down, so removing this exclusion cannot quietly widen it.
    """
    shipment, sentinels, packages = loaded_shipment

    private = {
        label: value for label, value in sentinels.items() if label != "carrier tracking number"
    }

    for reference in [shipment.public_id, packages[1].package_reference]:
        body = client.get(f"{TRACK}/{reference}").json()
        assert scan_values(body, private) == []


def test_the_scan_itself_detects_a_planted_leak(client, loaded_shipment):
    """A privacy test that cannot fail is worse than no privacy test."""
    shipment, sentinels, _ = loaded_shipment
    body = client.get(f"{TRACK}/{shipment.public_id}").json()

    leaky = dict(body)
    leaky["timeline"] = list(body["timeline"]) + [
        {"message": f"Handled by {sentinels['staff email']}", "recipient_name": "someone"}
    ]

    assert scan_values(leaky, sentinels) != []
    assert scan_keys(leaky) != []


def test_the_payload_contains_exactly_the_documented_allowlist(client, loaded_shipment):
    """The top-level keys are a closed set. Adding one must be a deliberate act.

    Registered in `SUPERSEDED_ASSERTIONS.md` (AS-34): ``carrier_links`` added by RC-UAT-19
    (2026-10-22).
    """
    shipment, _, _ = loaded_shipment

    body = client.get(f"{TRACK}/{shipment.public_id}").json()

    assert set(body) == {
        "shipment_reference",
        "matched_reference_type",
        "selected_package_reference",
        "route_group",
        "route_label",
        "origin",
        "destination",
        "status",
        "status_label",
        "package_count_active",
        "package_count_cancelled",
        "package_count_delivered",
        "progress_summary",
        "packages",
        "estimated_delivery_at",
        "delivered_at",
        "cancelled_at",
        "timeline",
        "tracking_state",
        "last_public_update_at",
        "carrier_link",
        "carrier_links",  # one per generic tracking name (2026-10-22)
        "data_mode",
        "help_url",
        "timezone",
    }
    assert set(body["origin"]) == {"city", "country_code", "country_label"}
    assert set(body["packages"][0]) == {
        "package_reference",
        "status",
        "status_label",
        "is_selected",
        "is_cancelled",
        "delivered_at",
    }
    assert set(body["timeline"][0]) == {
        "status",
        "status_label",
        "message",
        # Phase 5A1. An approved catalogue key, so the page can render the milestone in the
        # reader's language (DEC-0084). It names wording, never anything about the
        # shipment, the customer, or who recorded it.
        "message_template_key",
        "occurred_at",
        "location",
        "package_references",
        "source_label",
    }


def test_internal_detail_never_appears_even_as_a_unique_sentinel(client, loaded_shipment):
    shipment, sentinels, _ = loaded_shipment

    raw = client.get(f"{TRACK}/{shipment.public_id}").text

    assert sentinels["internal event detail"] not in raw
    assert "internal_detail" not in raw
    # And the approved wording that replaced it is present, so the timeline is not empty
    # for an uninteresting reason.
    assert "Your parcels have left Canada." in raw


def test_the_carrier_tracking_number_appears_only_inside_the_approved_link(client, loaded_shipment):
    """It may be part of the link's URL. It may not be a field of its own.

    The distinction matters because the two are read differently. A customer following a
    link goes to the carrier's own page for their own parcel. A ``tracking_number`` field
    is a machine-readable identifier sitting in a JSON response, and once it is there it
    will end up in a log, a screenshot, or somebody's scraper.

    Registered in `SUPERSEDED_ASSERTIONS.md` (AS-35): the link's keys were
    ``{carrier_name, url}`` until RC-UAT-19 added ``tracking_name_key`` (2026-10-22).
    """
    shipment, sentinels, _ = loaded_shipment
    number = sentinels["carrier tracking number"]

    body = client.get(f"{TRACK}/{shipment.public_id}").json()
    link = body["carrier_link"]

    assert link is not None
    # No number field beside it; the name is the leg's generic one (owner, 2026-10-22).
    assert set(link) == {"carrier_name", "tracking_name_key", "url"}
    assert number in link["url"]  # it is the carrier's own address for this parcel

    # It appears nowhere else in the tree -- not on a package, not in the timeline, not
    # as a sibling of the link.
    without_link = {
        key: value for key, value in body.items() if key not in ("carrier_link", "carrier_links")
    }
    assert number not in json.dumps(without_link, ensure_ascii=False)


def test_a_link_that_is_not_a_recognized_carrier_page_is_dropped_whole(client, loaded_shipment, db):
    """Dropped, never rewritten: stripping a parameter produces a link that fails."""
    from app.models import LegTrackingReference

    shipment, sentinels, _ = loaded_shipment
    reference = db.query(LegTrackingReference).first()
    reference.public_url = "https://ship.private-dashboard.example/orders/9931"
    db.commit()

    body = client.get(f"{TRACK}/{shipment.public_id}").json()

    assert body["carrier_link"] is None
    raw = json.dumps(body, ensure_ascii=False)
    assert "private-dashboard" not in raw
    assert sentinels["carrier tracking number"] not in raw


def test_no_consolidation_or_other_customer_data_appears(client, loaded_shipment, db, users):
    """A shared consolidation must never expose the other customers in it."""
    shipment, sentinels, _ = loaded_shipment
    other_customer = make_customer(
        db, full_name="OTHER-CUSTOMER-5M8J", email="other-5m8j@demo.example.com"
    )
    other = booked_shipment(db, other_customer)
    leg = leg_service.create_leg(
        db,
        other,
        {
            "leg_type": "consolidation_linehaul",
            "consolidation_reference": sentinels["consolidation reference"],
        },
        actor=users["operations"],
    )
    assert leg is not None
    db.commit()

    raw = client.get(f"{TRACK}/{shipment.public_id}").text

    assert sentinels["consolidation reference"] not in raw
    assert "OTHER-CUSTOMER-5M8J" not in raw
    assert other.public_id not in raw


def test_no_financial_figure_appears_in_any_form(client, loaded_shipment):
    shipment, sentinels, _ = loaded_shipment

    raw = client.get(f"{TRACK}/{shipment.public_id}").text

    for label in ["declared value", "selling amount", "shipping cost"]:
        assert sentinels[label] not in raw
        # Also without the decimal places, in case a formatter rounded it.
        assert sentinels[label].split(".")[0] not in raw


def test_no_staff_identity_appears(client, loaded_shipment):
    shipment, sentinels, _ = loaded_shipment

    raw = client.get(f"{TRACK}/{shipment.public_id}").text

    assert sentinels["staff email"] not in raw
    assert sentinels["staff name"] not in raw


def test_no_internal_database_identifier_appears(client, loaded_shipment, db):
    """Not even as a bare integer under an innocuous key."""
    shipment, _, packages = loaded_shipment

    body = client.get(f"{TRACK}/{shipment.public_id}").json()

    # `bool` is a subclass of `int` in Python; the flags are not identifiers.
    integers = [
        value
        for _, _, value in walk(body)
        if isinstance(value, int) and not isinstance(value, bool)
    ]
    # Only the three package counts are integers, and none of them is a row id.
    assert sorted(integers) == [0, 0, 3]
    assert set(integers) <= {0, 3}
    raw = json.dumps(body)
    for package in packages:
        assert f'"{package.id}"' not in raw
    assert f'"{shipment.id}"' not in raw
    assert f'"{shipment.customer_id}"' not in raw


def test_a_cancelled_shipment_leaks_nothing_either(client, loaded_shipment, db, users):
    shipment, sentinels, _ = loaded_shipment
    booking_service.cancel_shipment(
        db, shipment, reason=sentinels["cancellation reason"], actor=users["admin"]
    )
    db.commit()

    body = client.get(f"{TRACK}/{shipment.public_id}").json()

    assert scan_keys(body) == []
    assert scan_values(body, sentinels) == []


def test_a_failure_response_carries_no_data_at_all(client, loaded_shipment):
    _, sentinels, _ = loaded_shipment

    for reference in ["SX-CAV-ABCDEFGHJKLM", "rubbish", "PRIVATE-CUSTOMER-9Q4X"]:
        response = client.get(f"{TRACK}/{reference}")
        assert scan_keys(response.json()) == []
        assert scan_values(response.json(), sentinels) == []
        assert set(response.json()) == {"code", "message"}
