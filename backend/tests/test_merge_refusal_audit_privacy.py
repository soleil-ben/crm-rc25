"""What a refused merge writes down, and everything it must not (OD-40 section 5).

The technique is `tests/test_account_review_privacy.py`'s: plant a distinctive sentinel in
every private field of a **populated** record, drive the refusal, and then search the
written audit rows and the HTTP body for each sentinel by name. Asserting absence against
an empty database proves nothing, so everything here is populated first.

A merge refusal is written by the *customer* surface, into a table read by everyone who can
read customer audit. That population is wider than the approval queue, which is why the
payload is narrower than an approval's: it carries two customer references, which side
blocked and a reason code, and deliberately not the account reference -- naming
``CA-000017`` here would publish "this customer has an account, and here is its reference"
to readers who were never shown the approval that created it (T-02).

Four audit events are checked, because OD-40 asks for four things to be visible:

* the refusal itself, and which side caused it;
* a concurrency conflict;
* a preview invalidated by merge state, distinguishable from ordinary drift;
* and, by absence, that no ``customer.merge`` row is written when no merge happened.
"""

from __future__ import annotations

import json
import re

from app.core.db import persist_refusal_audit
from app.core.enums import Role
from app.models import AuditEvent, CustomerAuthToken, CustomerIdentity, CustomerSession
from app.services import customer_account_audit as account_audit
from app.services import customer_account_link_policy as link_policy
from app.services import customer_service
from tests.approval_fixtures import (
    acknowledged_preview,
    add_shipment,
    approve_link,
    make_customer,
    pending_identity,
    staff,
)

APPLICANT = "hanh@demo.example.com"

#: Things that exist in the database and must not reach an audit payload or a refusal body.
PLANTED = {
    "customer_notes": "PLANTED-CUSTOMER-NOTE",
    "restriction": "PLANTED-SERVICE-RESTRICTION",
    "recipient": "PLANTED-RECIPIENT-NAME",
    "internal_notes": "PLANTED-SHIPMENT-INTERNAL-NOTE",
    "contents": "PLANTED-CONTENTS-DESCRIPTION",
    "booking_reference": "PLANTED-BOOKING-REFERENCE",
}


def _populate(session, customer):
    customer.notes = PLANTED["customer_notes"]
    customer.service_restriction_note = PLANTED["restriction"]
    shipment = add_shipment(session, customer, days_ago=18)
    shipment.recipient_name = PLANTED["recipient"]
    shipment.recipient_email = "planted-recipient@demo.example.com"
    shipment.internal_notes = PLANTED["internal_notes"]
    shipment.contents_description = PLANTED["contents"]
    shipment.booking_reference = PLANTED["booking_reference"]
    shipment.selling_amount = 4321.99
    shipment.shipping_cost = 1234.56
    session.commit()
    return shipment


def _detail(row: AuditEvent) -> dict:
    """The payload as a dict. It is stored as text, so a test has to parse it back."""
    return json.loads(row.detail_json) if row.detail_json else {}


def _audit_text(session) -> str:
    """Every audit row, serialized whole, so a nested payload cannot hide a value."""
    rows = session.query(AuditEvent).all()
    return json.dumps(
        [
            {
                "action": row.action,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "summary": row.summary,
                "actor_label": row.actor_label,
                "detail": _detail(row),
            }
            for row in rows
        ],
        default=str,
    )


def _assert_no_planted_value(text: str, *, shipment) -> None:
    for name, value in PLANTED.items():
        assert value not in text, name
    assert shipment.public_id not in text, "a shipment reference reached the audit trail"
    assert "4321.99" not in text and "1234.56" not in text, "a financial value was audited"


def _refuse_and_record(session, source, survivor) -> None:
    """Drive the refusal and persist its record, exactly as a route does.

    ``persist_refusal_audit`` is the mechanism: the service attaches the audit call to the
    exception and writes nothing, and this rolls the session back clean before the row is
    written (DEC-0111). Calling it here rather than committing by hand is what makes these
    assertions about the real path instead of about a test's own bookkeeping.
    """
    try:
        customer_service.merge_customers(session, source=source, target=survivor)
    except link_policy.LinkedCustomerMergeRefused as exc:
        persist_refusal_audit(session, exc)
    else:  # pragma: no cover - the refusal is the point of the fixture
        raise AssertionError("the merge was not refused")


def _linked_pair(account_client, account_db, account_users, captured_mail):
    """A linked source, a survivor, and a populated record behind both."""
    source = make_customer(account_db, full_name="Hanh Nguyen", email=APPLICANT)
    survivor = make_customer(account_db, full_name="Survivor", email="survivor@demo.example.com")
    shipment = _populate(account_db, source)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    fingerprint = acknowledged_preview(api, reference, "link_existing", source.public_id)
    assert approve_link(api, reference, source.public_id, fingerprint).status_code == 200
    account_db.rollback()
    account_db.expire_all()
    return source, survivor, shipment, reference, api


# --- What is audited -----------------------------------------------------------


def test_the_refusal_is_audited_with_a_reason_code_and_the_blocking_side(
    account_client, account_db, account_users, captured_mail
):
    source, survivor, _shipment, _reference, _api = _linked_pair(
        account_client, account_db, account_users, captured_mail
    )

    _refuse_and_record(account_db, source, survivor)

    account_db.rollback()
    row = account_db.query(AuditEvent).filter_by(action=account_audit.ACTION_MERGE_REFUSED).one()
    assert _detail(row)["blocked_side"] == link_policy.SIDE_SOURCE
    assert _detail(row)["reason_code"] == account_audit.REASON_LINK_PRESENT
    assert _detail(row)["source_public_id"] == source.public_id
    assert _detail(row)["target_public_id"] == survivor.public_id


def test_the_target_side_is_named_when_the_survivor_is_the_linked_one(
    account_client, account_db, account_users, captured_mail
):
    survivor, source, _shipment, _reference, _api = _linked_pair(
        account_client, account_db, account_users, captured_mail
    )
    # `survivor` is the linked record here; merge the other one into it.
    _refuse_and_record(account_db, source, survivor)

    account_db.rollback()
    row = account_db.query(AuditEvent).filter_by(action=account_audit.ACTION_MERGE_REFUSED).one()
    assert _detail(row)["blocked_side"] == link_policy.SIDE_TARGET


def test_no_merge_audit_row_is_written_when_the_merge_did_not_happen(
    account_client, account_db, account_users, captured_mail
):
    """The other half of "audit the refusal": do not audit a merge that did not occur."""
    source, survivor, _shipment, _reference, _api = _linked_pair(
        account_client, account_db, account_users, captured_mail
    )
    _refuse_and_record(account_db, source, survivor)

    account_db.rollback()
    actions = [row.action for row in account_db.query(AuditEvent).all()]
    assert "customer.merge" not in actions


def test_a_preview_invalidated_by_a_merge_is_audited_as_merge_drift(
    account_client, account_db, account_users, captured_mail
):
    """Ordinary drift and merge-caused drift refuse identically and log differently.

    That distinction is the operational one: "approvals keep going stale" and "approvals
    keep going stale because merges are running underneath them" have different answers.
    """
    source = make_customer(account_db, full_name="Source", email="source@demo.example.com")
    survivor = make_customer(account_db, full_name="Survivor", email="survivor@demo.example.com")
    add_shipment(account_db, source, days_ago=33)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    stale = acknowledged_preview(api, reference, "link_existing", survivor.public_id)
    account_db.commit()

    customer_service.merge_customers(account_db, source=source, target=survivor)
    account_db.commit()
    account_db.expire_all()

    assert approve_link(api, reference, survivor.public_id, stale).status_code == 409

    account_db.rollback()
    rows = account_db.query(AuditEvent).filter_by(action=account_audit.ACTION_PREVIEW_STALE).all()
    assert rows, "a stale preview was not audited"
    assert _detail(rows[-1])["reason_code"] == account_audit.REASON_PREVIEW_MERGE_DRIFT


def test_reusing_one_idempotency_key_for_two_decisions_is_audited_as_a_conflict(
    account_client, account_db, account_users, captured_mail
):
    """The conflict that is reachable through a route, audited and surviving the refusal.

    One key, two different decisions. The claim's unique index catches it, the refusal
    names the key rather than the decision, and the audit row says
    ``idempotency_key_reused`` -- which is the distinction an operator needs between "two
    reviewers raced" and "a client is reusing keys".
    """
    from tests.approval_fixtures import approve_create, key, reject

    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    shared = key()
    assert reject(api, reference, "abuse_or_test", key=shared).status_code == 200
    assert approve_create(api, reference, "irrelevant-fingerprint", key=shared).status_code == 409

    account_db.rollback()
    rows = (
        account_db.query(AuditEvent).filter_by(action=account_audit.ACTION_APPROVAL_CONFLICT).all()
    )
    assert rows, "an idempotency-key conflict was not audited"
    assert _detail(rows[-1])["reason_code"] == "idempotency_key_reused"


# --- What is not audited -------------------------------------------------------


def test_the_refusal_audit_carries_no_planted_value(
    account_client, account_db, account_users, captured_mail
):
    source, survivor, shipment, _reference, _api = _linked_pair(
        account_client, account_db, account_users, captured_mail
    )
    _refuse_and_record(account_db, source, survivor)

    account_db.rollback()
    _assert_no_planted_value(_audit_text(account_db), shipment=shipment)


def test_the_refusal_audit_carries_no_credential_token_session_or_address(
    account_client, account_db, account_users, captured_mail
):
    """The Customer Account payload rules, applied to a row the customer surface writes.

    The identity's own reference is absent too, deliberately: this row is read by a wider
    population than the approval queue, and it does not need to say which account.
    """
    source, survivor, _shipment, _reference, _api = _linked_pair(
        account_client, account_db, account_users, captured_mail
    )
    identity = account_db.query(CustomerIdentity).one()
    secrets = [identity.password_hash, identity.email_normalized, identity.email_entered]
    secrets += [row.token_digest for row in account_db.query(CustomerAuthToken).all()]
    secrets += [row.session_token_hash for row in account_db.query(CustomerSession).all()]
    secrets += [row.csrf_token_hash for row in account_db.query(CustomerSession).all()]

    _refuse_and_record(account_db, source, survivor)

    account_db.rollback()
    row = account_db.query(AuditEvent).filter_by(action=account_audit.ACTION_MERGE_REFUSED).one()
    serialized = json.dumps({"summary": row.summary, "detail": _detail(row)}, default=str)
    for secret in secrets:
        if secret:
            assert secret not in serialized
    # Anchored: a customer identifier ``STCA-000001`` ends in ``CA-000001``, which is also the
    # shape of an account identifier, so a bare substring check would trip on the customer's
    # own id (DEC-0174). The account id is absent when nothing precedes it with a letter.
    assert re.search(rf"(?<![A-Za-z]){re.escape(identity.public_id)}", serialized) is None, (
        "the refusal named the account, which this surface's readers were never shown"
    )
    assert set(_detail(row)) == {
        "source_public_id",
        "target_public_id",
        "blocked_side",
        "reason_code",
    }


def test_the_refusal_response_body_carries_no_planted_value(as_admin, db):
    """Through HTTP, against the staff database, with the same sentinels."""
    from app.core.account_enums import IdentityStatus, LinkRole, LinkStatus
    from app.core.time_utils import utcnow
    from app.models import CustomerIdentityLink

    source = make_customer(db, full_name="Source", email="source@demo.example.com")
    survivor = make_customer(db, full_name="Survivor", email="survivor@demo.example.com")
    shipment = _populate(db, source)
    identity = CustomerIdentity(
        public_id="CA-000099",
        email_entered="holder@demo.example.com",
        email_normalized="holder@demo.example.com",
        password_hash="PLANTED-PASSWORD-HASH",
        status=IdentityStatus.ACTIVE.value,
        email_verified_at=utcnow(),
        approved_at=utcnow(),
    )
    db.add(identity)
    db.flush()
    db.add(
        CustomerIdentityLink(
            identity_id=identity.id,
            customer_id=source.id,
            link_role=LinkRole.OWNER.value,
            status=LinkStatus.ACTIVE.value,
            linked_at=utcnow(),
        )
    )
    db.commit()

    response = as_admin.post(
        "/api/v1/customers/merge",
        json={
            "source_customer_id": source.id,
            "target_customer_id": survivor.id,
            "confirmation": source.public_id,
        },
    )
    assert response.status_code == 409
    _assert_no_planted_value(response.text, shipment=shipment)
    assert "PLANTED-PASSWORD-HASH" not in response.text
    assert identity.public_id not in response.text
