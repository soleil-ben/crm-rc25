"""What the authenticated shipment surface must never publish, asserted two ways.

**By key**, recursively, over the whole decoded body -- a forbidden key nested three levels
inside a timeline entry is still a disclosure, and a top-level-only scan would miss it.

**By value**, with sentinels. This is the half that catches the real failure mode. A field
called `internal_notes` is easy to notice and easy to exclude; the dangerous version is a
staff note that arrives inside a summary string, a recipient address that a "location" field
happens to render, or a financial figure that a progress sentence includes. So a unique,
searchable value is written into a **real column** in every excluded category, the response
is serialized, and the whole text is searched for each one. `FIELD_MATRIX.md` §7.2 asks for
exactly this: absence asserted against a *populated* record, never an empty one.

One exception: since UAT round 11 the list row carries the customer's own
``booking_reference`` (DEC-0160), and since UAT round 12 the detail does too (DEC-0163),
so that key and its sentinel are allowed in both bodies, once, as a top-level key, and
nowhere else. Entries AS-13, AS-14, AS-24 and AS-25 of
`docs/customer_account/SUPERSEDED_ASSERTIONS.md`.
"""

from __future__ import annotations

import json

from app.core.enums import OperationalState, TrackingSourceMode
from app.models import LegTrackingReference, ShipmentLeg
from tests.shipment_history_fixtures import (
    LIST_URL,
    add_event,
    detail_url,
    linked_and_signed_in,
    shipment,
    walk,
)
from tests.shipment_history_fixtures import customer as make

MINE = "hanh@demo.example.com"

#: One sentinel per excluded category, each one a string that appears nowhere else.
SENTINELS = {
    "internal_note": "SENTINEL-INTERNALNOTE-8f21",
    "event_internal_detail": "SENTINEL-EVENTDETAIL-3a77",
    "recipient_name": "SENTINEL-RECIPIENTNAME-b104",
    "recipient_phone": "+15559990001",
    "recipient_email": "sentinel-recipient@example.invalid",
    "recipient_address": "SENTINEL-RECIPIENTSTREET-c5e2",
    "recipient_postal": "S3N-T1L",
    "sender_name": "SENTINEL-SENDERNAME-d9a4",
    "sender_address": "SENTINEL-SENDERSTREET-e6b8",
    "sender_email": "sentinel-sender@example.invalid",
    "sender_phone": "+15559990002",
    "booking_reference": "SENTINEL-BOOKINGREF-11aa",
    "idempotency_key": "SENTINEL-IDEMPOTENCY-22bb",
    "source_record_id": "SENTINEL-SOURCEREC-33cc",
    "contents": "SENTINEL-CONTENTS-44dd",
    "cancellation_reason": "SENTINEL-CANCELREASON-55ee",
    "delivery_note": "SENTINEL-DELIVERYNOTE-66ff",
    "carrier_tracking_number": "SENTINEL1TRACKING2NUMBER3",
    "customer_note": "SENTINEL-CUSTOMERNOTE-77aa",
}

#: Allowed in the list row (DEC-0160) and the detail (DEC-0163), as a top-level key only.
PUBLISHED_KEYS = {"booking_reference"}
PUBLISHED_SENTINELS = {"booking_reference"}

#: Numeric sentinels. Financial values are numbers, so they are searched for as the digits
#: they would serialize as rather than as a word.
MONEY = {
    "selling_amount": 123456.78,
    "shipping_cost": 98765.43,
    "surcharges_amount": 11111.11,
    "discount_amount": 22222.22,
    "refund_amount": 33333.33,
    "declared_value": 44444.44,
}

#: Keys that must not appear anywhere in a response, at any depth.
FORBIDDEN_KEYS = {
    # Phase 13B: the master a shipment rides in, the vendor's number, and who pays
    "consolidation",
    "consolidation_id",
    "vendor_reference",
    "chargeable_weight_kg",
    "payer",
    "payer_customer_id",
    # Phase 13C: the quote and its figures (customer documents come in 13D, from their own schema)
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
    # Internal identity and bookkeeping
    "id",
    "customer_id",
    "shipment_id",
    "owner_user_id",
    "internal_notes",
    "notes",
    "internal_detail",
    "idempotency_key",
    "booking_reference",
    "source_system",
    "source_record_id",
    "is_demo_record",
    "booking_state",
    "payment_state",
    # Sender and recipient beyond the allowlist
    "recipient_name",
    "recipient_company",
    "recipient_phone",
    "recipient_phone_e164",
    "recipient_email",
    "recipient_address_line1",
    "recipient_address_line2",
    "recipient_postal_code",
    "recipient_delivery_note",
    "sender_name",
    "sender_company",
    "sender_phone",
    "sender_phone_e164",
    "sender_email",
    "sender_address_line1",
    "sender_address_line2",
    "sender_postal_code",
    "address_line1",
    "postal_code",
    "province_state",
    # Money (OD-32)
    "currency",
    "selling_amount",
    "shipping_cost",
    "surcharges_amount",
    "discount_amount",
    "refund_amount",
    "declared_value",
    "declared_value_currency",
    "invoice",
    "balance",
    "profit",
    "revenue",
    "cost",
    # Staff, audit and internal judgement
    "actor",
    "actor_user_id",
    "actor_label",
    "recorded_by",
    "recorded_by_user_id",
    "audit",
    "audit_events",
    "duplicate_score",
    "match_count",
    "lifecycle_status",
    "tags",
    "interactions",
    "follow_up_tasks",
    "service_issues",
    "is_archived",
    "archived_at",
    "archive_reason",
    "merged_into_customer_id",
    "merged_at",
    "do_not_contact",
    "service_restriction_note",
    "email_normalized",
    "name_match_key",
    "phone_match_key",
    # Credentials, sessions, workers, providers
    "password",
    "password_hash",
    "token",
    "token_digest",
    "session_token",
    "session_token_hash",
    "csrf",
    "csrf_token",
    "credential_ref",
    "api_key",
    "secret",
    "integration_connection_id",
    "provider",
    "provider_status",
    "provider_payload",
    "raw_payload",
    "last_synced_at",
    "sync_status",
    "freshness_seconds",
    "stale_after",
    "worker",
    "job_state",
    "heartbeat_at",
    "tracking_number",
    "carrier_tracking_number",
    "leg_id",
    "legs",
}


def _mine(account_db):
    return make(
        account_db,
        full_name="Hanh Nguyen",
        email="hanh.canonical@demo.example.com",
        notes=SENTINELS["customer_note"],
    )


def _populated(account_db, owner):
    """One shipment with a sentinel in every excluded column that exists today."""
    row = shipment(
        account_db,
        owner,
        days_ago=9,
        packages=2,
        cancelled_packages=1,
        internal_notes=SENTINELS["internal_note"],
        recipient_name=SENTINELS["recipient_name"],
        recipient_company=SENTINELS["recipient_name"],
        recipient_phone_e164=SENTINELS["recipient_phone"],
        recipient_phone_entered=SENTINELS["recipient_phone"],
        recipient_email=SENTINELS["recipient_email"],
        recipient_address_line1=SENTINELS["recipient_address"],
        recipient_address_line2=SENTINELS["recipient_address"],
        recipient_postal_code=SENTINELS["recipient_postal"],
        recipient_delivery_note=SENTINELS["delivery_note"],
        sender_name=SENTINELS["sender_name"],
        sender_company=SENTINELS["sender_name"],
        sender_address_line1=SENTINELS["sender_address"],
        sender_address_line2=SENTINELS["sender_address"],
        sender_email=SENTINELS["sender_email"],
        sender_phone_e164=SENTINELS["sender_phone"],
        sender_phone_entered=SENTINELS["sender_phone"],
        booking_reference=SENTINELS["booking_reference"],
        idempotency_key=SENTINELS["idempotency_key"],
        source_system="sentinel-source",
        source_record_id=SENTINELS["source_record_id"],
        contents_description=SENTINELS["contents"],
        cancellation_reason=SENTINELS["cancellation_reason"],
        currency="CAD",
        declared_value_currency="CAD",
        **MONEY,
    )
    add_event(
        account_db,
        row,
        days_ago=2,
        text="Arrived at the destination facility.",
        internal_detail=SENTINELS["event_internal_detail"],
    )
    add_event(
        account_db,
        row,
        public=False,
        internal_detail=SENTINELS["event_internal_detail"],
        days_ago=1,
        state=OperationalState.EXCEPTION,
    )
    leg = ShipmentLeg(
        shipment_id=row.id,
        sequence=1,
        leg_type="linehaul",
        provider_name="Sentinel Carrier",
    )
    account_db.add(leg)
    account_db.commit()
    account_db.add(
        LegTrackingReference(
            leg_id=leg.id,
            carrier_name="Sentinel Carrier",
            tracking_number=SENTINELS["carrier_tracking_number"],
            source_mode=TrackingSourceMode.MANUAL,
            is_active=True,
        )
    )
    account_db.commit()
    return row


def _responses(account_client, account_db, account_users, captured_mail):
    owner = _mine(account_db)
    row = _populated(account_db, owner)
    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=owner
    )
    listed = client.get(LIST_URL)
    detail = client.get(detail_url(row.public_id))
    assert listed.status_code == 200, listed.text
    assert detail.status_code == 200, detail.text
    return listed, detail, owner


# --- By key ----------------------------------------------------------------------


def test_no_forbidden_key_appears_anywhere_in_either_response(
    account_client, account_db, account_users, captured_mail
):
    """Registered in `SUPERSEDED_ASSERTIONS.md` (AS-13, AS-24): the booking reference may
    appear as a top-level key of a list row (round 11) and of the detail (round 12)."""
    listed, detail, _owner = _responses(account_client, account_db, account_users, captured_mail)
    for response in (listed, detail):
        body = response.json()
        found = {key for _, key, _ in walk(body) if key in FORBIDDEN_KEYS - PUBLISHED_KEYS}
        assert not found, f"{response.url} published {sorted(found)}"
    # The exception is exactly where it was put: a top-level key of each list row and of
    # the detail, and nowhere deeper (not in a package, a timeline entry or a place).
    for item in listed.json()["items"]:
        assert set(item) & PUBLISHED_KEYS == PUBLISHED_KEYS
    assert set(detail.json()) & PUBLISHED_KEYS == PUBLISHED_KEYS
    for response in (listed, detail):
        body = response.json()
        tops = body.get("items", [body])
        nested = [
            key
            for top in tops
            for value in top.values()
            for _, key, _ in walk(value)
            if key in PUBLISHED_KEYS
        ]
        assert not nested, f"{response.url} nests {nested}"


def test_the_scan_would_notice_a_forbidden_key(
    account_client, account_db, account_users, captured_mail
):
    """The scanner, tested against a body that does contain one.

    A recursive assertion that silently walks nothing passes every time. This proves the
    walk reaches nested structures by planting a forbidden key three levels down.
    """
    _, detail, _ = _responses(account_client, account_db, account_users, captured_mail)
    tampered = detail.json()
    tampered["packages"][0]["internal_notes"] = "planted"
    # The same set the real scan uses, since the detail now carries `booking_reference`.
    found = {key for _, key, _ in walk(tampered) if key in FORBIDDEN_KEYS - PUBLISHED_KEYS}
    assert found == {"internal_notes"}


# --- By value --------------------------------------------------------------------


def test_no_planted_private_value_reaches_either_response(
    account_client, account_db, account_users, captured_mail
):
    """Registered in `SUPERSEDED_ASSERTIONS.md` (AS-14, AS-25): the booking reference is on
    the list (round 11) and on the detail (round 12)."""
    listed, detail, _owner = _responses(account_client, account_db, account_users, captured_mail)
    for response in (listed, detail):
        text = response.text
        for name, sentinel in SENTINELS.items():
            if name in PUBLISHED_SENTINELS:
                continue
            assert sentinel not in text, f"{name} leaked into {response.url}"
    # Allowed means shown once, in its own field: per list row, and on the detail.
    assert [item["booking_reference"] for item in listed.json()["items"]] == [
        SENTINELS["booking_reference"]
    ]
    assert listed.text.count(SENTINELS["booking_reference"]) == 1
    assert detail.json()["booking_reference"] == SENTINELS["booking_reference"]
    assert detail.text.count(SENTINELS["booking_reference"]) == 1


def test_no_financial_value_reaches_either_response(
    account_client, account_db, account_users, captured_mail
):
    """OD-32, asserted over the serialized body rather than over the schema.

    Every money column is populated with a distinctive amount, and the digits are searched
    for in several spellings, because a number can serialize as ``123456.78``, ``123456.8``
    or ``"123456.78"`` depending on who rendered it.
    """
    listed, detail, _owner = _responses(account_client, account_db, account_users, captured_mail)
    for response in (listed, detail):
        text = response.text
        for name, amount in MONEY.items():
            for spelling in (str(amount), str(int(amount)), f"{amount:.2f}"):
                assert spelling not in text, f"{name} ({spelling}) leaked into {response.url}"
        assert "CAD" not in text


def test_the_value_scan_would_notice_a_leak(
    account_client, account_db, account_users, captured_mail
):
    """The sentinels are searchable: proved by searching a body that has one in it."""
    _, detail, _ = _responses(account_client, account_db, account_users, captured_mail)
    tampered = detail.json()
    tampered["progress_summary"] = f"Handled by {SENTINELS['recipient_name']}"
    assert SENTINELS["recipient_name"] in json.dumps(tampered)


# --- Categories with no column today ----------------------------------------------


def test_nothing_in_the_response_describes_a_provider_or_a_worker(
    account_client, account_db, account_users, captured_mail
):
    """Integration credentials, worker state, freshness and synchronization status.

    None of these has a column a sentinel could be planted in, because no provider is
    connected (OD-34, CRM.md section 9). The assertion is therefore that the *concepts* are
    absent -- no key names them, no value claims one, and ``connected_api`` is not in the
    vocabulary at all.
    """
    listed, detail, _owner = _responses(account_client, account_db, account_users, captured_mail)
    for response in (listed, detail):
        text = response.text.lower()
        for concept in (
            "connected_api",
            "synchron",
            "last_synced",
            "freshness",
            "stale",
            "webhook",
            "credential",
            "heartbeat",
            "worker",
            "job_state",
            "uniuni",
        ):
            assert concept not in text, f"{concept} appears in {response.url}"


def test_the_carrier_tracking_number_is_never_published(
    account_client, account_db, account_users, captured_mail
):
    """A bare tracking number is a lookup key on somebody else's system.

    The public surface withholds it and the authenticated one does too: authentication says
    who is asking, not that an unapproved reference has become approved.
    """
    listed, detail, _owner = _responses(account_client, account_db, account_users, captured_mail)
    for response in (listed, detail):
        assert SENTINELS["carrier_tracking_number"] not in response.text


def test_no_audit_row_or_staff_identity_is_reachable(
    account_client, account_db, account_users, captured_mail
):
    """The approval that created this account wrote audit rows naming a staff user."""
    listed, detail, _owner = _responses(account_client, account_db, account_users, captured_mail)
    for response in (listed, detail):
        text = response.text.lower()
        assert "operations@demo.example.com" not in text
        assert "admin@demo.example.com" not in text
        assert "customer_account." not in text
        assert "audit" not in text


def test_no_internal_customer_identifier_is_published(
    account_client, account_db, account_users, captured_mail
):
    """Not the row id, and not the ``STCA-`` public id either.

    The public customer id is the customer's own reference and appears on the profile
    surface. It has no place on a shipment row: the account holder already knows who they
    are, and putting an identifier in a response is putting it in reach of whoever holds a
    stolen session.
    """
    listed, detail, owner = _responses(account_client, account_db, account_users, captured_mail)
    for response in (listed, detail):
        assert owner.public_id not in response.text
        assert f'"{owner.id}"' not in response.text


# --- Headers, cookies and caching -------------------------------------------------


def test_both_routes_carry_the_authenticated_privacy_headers(
    account_client, account_db, account_users, captured_mail
):
    listed, detail, _owner = _responses(account_client, account_db, account_users, captured_mail)
    for response in (listed, detail):
        assert response.headers["Cache-Control"] == "no-store, no-cache, must-revalidate, private"
        assert response.headers["Pragma"] == "no-cache"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"


def test_a_refusal_carries_the_same_privacy_headers(
    account_client, account_db, account_users, captured_mail
):
    """Headers a browser relies on for privacy must not depend on which path produced them."""
    owner = _mine(account_db)
    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=owner
    )
    refused = client.get(detail_url("SX-CAV-AAAAAAAAAAAA"))
    assert refused.status_code == 404
    assert refused.headers["Cache-Control"] == "no-store, no-cache, must-revalidate, private"
    assert refused.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"


def test_neither_route_sets_any_cookie(account_client, account_db, account_users, captured_mail):
    """These are reads. The session they run under was established somewhere else."""
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3)
    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=owner
    )
    for url in (LIST_URL, detail_url(row.public_id), detail_url("SX-CAV-AAAAAAAAAAAA")):
        response = client.get(url)
        assert "set-cookie" not in {key.lower() for key in response.headers}, url


def test_no_correlation_header_is_returned_on_this_surface(
    account_client, account_db, account_users, captured_mail
):
    """The Customer Account prefix is excluded from the correlation header, and stays so.

    A per-request header is by definition a value that differs between two responses, which
    is the one thing a surface built on identical answers cannot have. The id is still
    generated and still on every log record for the request.
    """
    listed, detail, _owner = _responses(account_client, account_db, account_users, captured_mail)
    for response in (listed, detail):
        assert "x-correlation-id" not in {key.lower() for key in response.headers}


def test_public_tracking_still_has_no_correlation_header(account_client, account_db):
    """Asserted from here as well, because §13 names it explicitly as a thing not to add."""
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3)
    response = account_client.get(f"/api/v1/public/track/{row.public_id}")
    assert response.status_code == 200
    assert "x-correlation-id" not in {key.lower() for key in response.headers}
