"""Planted values, and every place they must not turn up.

The technique is the one `tests/test_account_privacy.py` established: put a distinctive
sentinel into every private field of a **populated** record, drive the whole review and
approval path, and then search the serialized responses and the written audit rows for
each sentinel by name. Asserting absence against an empty database proves nothing, which
is why every fixture here is populated first.

Three surfaces are searched:

* **the staff responses**, which may legitimately carry a lot -- a reviewer is deciding
  about a real person -- but must not carry a credential, a digest, another customer's
  contact details, or any shipment detail;
* **the audit payloads**, which are append-only, widely readable, and must carry codes,
  public identifiers, field keys, counts and fingerprints and nothing else;
* **the customer-facing surface**, which must gain nothing at all from this phase.
"""

from __future__ import annotations

import json

from app.core.enums import Role
from app.models import (
    AuditEvent,
    CustomerAuthToken,
    CustomerIdentity,
    CustomerSession,
    Shipment,
)
from tests.account_fixtures import sign_in
from tests.approval_fixtures import (
    BASE,
    acknowledged_preview,
    add_shipment,
    approve_link,
    make_customer,
    pending_identity,
    preview,
    staff,
)

APPLICANT = "hanh@demo.example.com"

#: Values planted on records the review path touches. Each one is a thing that exists in
#: the database and must not reach a response or an audit payload.
PLANTED = {
    "customer_notes": "PLANTED-CUSTOMER-NOTE",
    "restriction": "PLANTED-SERVICE-RESTRICTION",
    "recipient": "PLANTED-RECIPIENT-NAME",
    "recipient_email": "planted-recipient@demo.example.com",
    "internal_notes": "PLANTED-SHIPMENT-INTERNAL-NOTE",
    "contents": "PLANTED-CONTENTS-DESCRIPTION",
    "booking_reference": "PLANTED-BOOKING-REFERENCE",
    "source_record": "PLANTED-SOURCE-RECORD-ID",
}


def _populated_customer(session):
    customer = make_customer(
        session,
        full_name="Hanh Nguyen",
        email=APPLICANT,
        phone="+1 416 555 0166",
        notes=PLANTED["customer_notes"],
    )
    customer.service_restriction_note = PLANTED["restriction"]
    customer.source_system = "legacy"
    customer.source_record_id = PLANTED["source_record"]
    shipment = add_shipment(session, customer, days_ago=20)
    shipment.recipient_name = PLANTED["recipient"]
    shipment.recipient_email = PLANTED["recipient_email"]
    shipment.internal_notes = PLANTED["internal_notes"]
    shipment.contents_description = PLANTED["contents"]
    shipment.booking_reference = PLANTED["booking_reference"]
    shipment.selling_amount = 4321.99
    shipment.shipping_cost = 1234.56
    session.commit()
    return customer, shipment


def _assert_clean(text: str, *, allow: set[str] = frozenset()) -> None:
    for name, value in PLANTED.items():
        if name in allow:
            continue
        assert value not in text, name
    assert "4321.99" not in text
    assert "1234.56" not in text


def test_no_staff_response_in_the_review_path_carries_a_planted_value(
    account_client, account_db, account_users, captured_mail
):
    customer, shipment = _populated_customer(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.OPERATIONS].email)

    bodies = [
        api.get(BASE).text,
        api.get(f"{BASE}/{reference}").text,
        api.get(f"{BASE}/{reference}/duplicate-candidates").text,
        preview(api, reference, "create_new").text,
        preview(api, reference, "link_existing", customer.public_id).text,
    ]
    for body in bodies:
        _assert_clean(body)
        assert shipment.public_id not in body
        assert "payment_state" not in body


def test_no_response_carries_a_credential_or_a_digest(
    account_client, account_db, account_users, captured_mail
):
    """Password hashes, token digests, session digests and CSRF digests, by value.

    Read out of the database and searched for, rather than searched for by column name:
    a response that happened to include a digest under a different key would pass a
    name-based check and fail this one.
    """
    customer, _shipment = _populated_customer(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    sign_in(account_client, APPLICANT)
    account_db.expire_all()

    secrets = [account_db.query(CustomerIdentity).one().password_hash]
    secrets += [row.token_digest for row in account_db.query(CustomerAuthToken).all()]
    for row in account_db.query(CustomerSession).all():
        secrets += [row.session_token_hash, row.csrf_token_hash]
    assert len(secrets) > 2

    api = staff(account_client, account_users[Role.OPERATIONS].email)
    bodies = [
        api.get(BASE).text,
        api.get(f"{BASE}/{reference}").text,
        api.get(f"{BASE}/{reference}/duplicate-candidates").text,
        preview(api, reference, "link_existing", customer.public_id).text,
    ]
    for body in bodies:
        for secret in secrets:
            assert secret not in body


def test_the_preview_never_names_a_shipment(
    account_client, account_db, account_users, captured_mail
):
    """Counts and two dates. The row exists and its reference does not appear."""
    customer, shipment = _populated_customer(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.OPERATIONS].email)

    body = preview(api, reference, "link_existing", customer.public_id)
    disclosure = body.json()["disclosure"]
    assert disclosure["shipment_count"] == 1
    assert shipment.public_id not in body.text
    # The whole shape: a count, two dates, two booleans and the rule's version. Anything
    # else in here would be a shipment detail arriving through the one field that carries
    # numbers about shipments.
    assert set(disclosure) == {
        "shipment_count",
        "oldest_booked_at",
        "newest_booked_at",
        "includes_cancelled",
        "includes_rebooked",
        "definition_version",
    }


def test_a_candidate_does_not_expose_the_other_customers_contact_details(
    account_client, account_db, account_users, captured_mail
):
    """The reviewer is told *why* it matched, not what the other person's details are."""
    customer, _shipment = _populated_customer(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.OPERATIONS].email)

    response = api.get(f"{BASE}/{reference}/duplicate-candidates")
    assert response.json()["candidates"][0]["matched_on"] == ["email"]
    assert "4165550166" not in response.text.replace(" ", "").replace("+1", "")
    _assert_clean(response.text)


def test_no_audit_payload_carries_a_planted_value_or_a_credential(
    account_client, account_db, account_users, captured_mail
):
    """The whole path driven, then every audit row read and searched.

    This is the assertion the instruction's audit section asks for: no password, token,
    digest, session value, CSRF value, full proposal payload, raw address, full phone
    number, shipment reference, recipient datum, financial value or integration datum.
    """
    customer, shipment = _populated_customer(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    sign_in(account_client, APPLICANT)
    account_db.expire_all()

    secrets = [account_db.query(CustomerIdentity).one().password_hash]
    secrets += [row.token_digest for row in account_db.query(CustomerAuthToken).all()]
    for row in account_db.query(CustomerSession).all():
        secrets += [row.session_token_hash, row.csrf_token_hash]

    api = staff(account_client, account_users[Role.OPERATIONS].email)
    api.get(BASE)
    api.get(f"{BASE}/{reference}")
    api.get(f"{BASE}/{reference}/duplicate-candidates")
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)
    assert approve_link(api, reference, customer.public_id, fingerprint).status_code == 200

    account_db.expire_all()
    rows = account_db.query(AuditEvent).filter(AuditEvent.action.like("customer_account.%")).all()
    assert len(rows) > 6

    blob = "\n".join(f"{row.summary}\n{row.detail_json or ''}" for row in rows)
    _assert_clean(blob)
    for secret in secrets:
        assert secret not in blob
    # No raw address, no full phone, no submitted value, no shipment reference.
    assert APPLICANT not in blob
    assert "0901234567" not in blob
    assert "Nguyễn" not in blob
    assert "Dixie Road" not in blob
    assert shipment.public_id not in blob


def test_the_approval_audit_row_carries_what_ac_ca_10_4_requires(
    account_client, account_db, account_users, captured_mail
):
    """Actor, identity, customer, the five preview figures, and a reason code."""
    customer, _shipment = _populated_customer(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)
    assert approve_link(api, reference, customer.public_id, fingerprint).status_code == 200

    account_db.expire_all()
    event = account_db.query(AuditEvent).filter_by(action="customer_account.approve").one()
    detail = json.loads(event.detail_json)

    assert event.actor_user_id is not None
    assert event.actor_label
    assert detail["identity_public_id"] == reference
    assert detail["customer_public_id"] == customer.public_id
    assert detail["reason_code"]
    assert detail["preview_fingerprint"] == fingerprint
    for figure in (
        "disclosed_shipment_count",
        "oldest_booked_at",
        "newest_booked_at",
        "includes_cancelled",
        "includes_rebooked",
        "disclosure_definition_version",
    ):
        assert figure in detail
    assert detail["disclosed_shipment_count"] == 1


def test_the_duplicate_audit_row_carries_a_classification_and_no_score(
    account_client, account_db, account_users, captured_mail
):
    """A number that varies with a weighting table is not evidence; the reason code is."""
    customer, _shipment = _populated_customer(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    api.get(f"{BASE}/{reference}/duplicate-candidates")

    account_db.expire_all()
    event = (
        account_db.query(AuditEvent).filter_by(action="customer_account.duplicates_reviewed").one()
    )
    detail = json.loads(event.detail_json)
    assert detail["duplicate_classification"] == "exact"
    assert detail["candidate_public_ids"] == [customer.public_id]
    assert "confidence" not in detail
    assert "score" not in event.detail_json


def test_the_queue_audit_row_names_no_applicant(
    account_client, account_db, account_users, captured_mail
):
    """ "Who has been reading the applications" does not need to say whose."""
    pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    api.get(BASE)

    account_db.expire_all()
    event = account_db.query(AuditEvent).filter_by(action="customer_account.queue_reviewed").one()
    assert event.entity_id is None
    assert json.loads(event.detail_json) == {"returned_count": 1}


def test_the_customer_surface_gains_nothing_from_an_approval(
    account_client, account_db, account_users, captured_mail
):
    """After activation, ``/account/me`` still says nothing about the CRM.

    No customer id, no duplicate information, no approver, no rejection reason, no
    shipment count and no shipment history -- which is exactly the list section 14 of the
    instruction forbids, asserted against an account that now has all of them behind it.
    """
    customer, shipment = _populated_customer(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)
    assert approve_link(api, reference, customer.public_id, fingerprint).status_code == 200

    account_client.cookies.clear()
    assert sign_in(account_client, APPLICANT).status_code == 200
    response = account_client.get("/api/v1/account/me")
    body = response.json()

    assert set(body) == {
        "account_reference",
        "status",
        "email_verified",
        "linked",
        "shipment_history_available",
        "preferred_language",
        "status_reason_code",
        "has_pending_proposal",
    }
    assert body["status"] == "active"
    assert body["linked"] is True
    # True since Phase 11 -- and still a bare boolean. The field set above is unchanged, so
    # no count, no date, no customer reference and no approver arrived with it.
    assert body["shipment_history_available"] is True

    text = response.text
    assert customer.public_id not in text
    assert shipment.public_id not in text
    assert account_users[Role.OPERATIONS].email not in text
    assert "duplicate" not in text.lower()
    assert "exact" not in text.lower()
    _assert_clean(text)


def test_an_active_account_reaches_its_shipments_and_nothing_planted_comes_with_them(
    account_client, account_db, account_users, captured_mail
):
    """Phase 11 built the two read routes, so this stops being an absence test.

    It becomes the stronger thing: the routes answer, and the same planted values this file
    plants for the *staff review* surface are asserted absent from what the **customer**
    reads. The shipment carries an internal note, a recipient name and email, a contents
    description, a booking reference and two financial amounts, and the customer sees a
    reference, a route, two cities, a status and some dates.

    Fix pack 2 built ``/account/profile``, so it joins the reads: it answers, and carries
    none of the planted values either. The customer's own public reference **is** in the
    profile, deliberately: FIELD_MATRIX §3.3 lists it as read-only and visible, because
    staff quote it on the phone. It stays absent from the shipment responses.

    UAT round 11 put the booking reference on the list row (DEC-0160), and UAT round 12 on
    the detail (DEC-0163), so each may carry that one planted value, in its own field; the
    profile still carries none: entries AS-16 and AS-26 of
    `docs/customer_account/SUPERSEDED_ASSERTIONS.md`.
    """
    customer, shipment = _populated_customer(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)
    approve_link(api, reference, customer.public_id, fingerprint)

    account_client.cookies.clear()
    sign_in(account_client, APPLICANT)

    listed = account_client.get("/api/v1/account/shipments")
    detail = account_client.get(f"/api/v1/account/shipments/{shipment.public_id}")
    assert listed.status_code == 200, listed.text
    assert detail.status_code == 200, detail.text
    assert [item["shipment_reference"] for item in listed.json()["items"]] == [shipment.public_id]

    assert [item["booking_reference"] for item in listed.json()["items"]] == [
        PLANTED["booking_reference"]
    ]
    assert detail.json()["booking_reference"] == PLANTED["booking_reference"]
    for response in (listed, detail):
        text = response.text
        _assert_clean(text, allow={"booking_reference"})
        assert customer.public_id not in text
        assert account_users[Role.OPERATIONS].email not in text
        assert "4321.99" not in text and "1234.56" not in text

    profile = account_client.get("/api/v1/account/profile")
    assert profile.status_code == 200, profile.text
    _assert_clean(profile.text)
    assert account_users[Role.OPERATIONS].email not in profile.text
    assert profile.json()["details"]["customer_reference"] == customer.public_id

    # Still no way to change a shipment.
    assert account_client.post("/api/v1/account/shipments").status_code == 405


def _shipment_reference(session) -> str:
    return session.query(Shipment).first().public_id
