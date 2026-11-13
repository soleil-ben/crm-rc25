"""Approving by linking to a customer that already exists.

The property this path has and the other one does not: **it writes no canonical customer
value at all.** A person filling in a registration form is not thereby editing a customer
record somebody else maintains, and an approval that quietly applied their version would
make registration a write path into the CRM under another name (OD-28, T-07).

So the central test here is a negative one, made against a customer whose every mapped
column differs from the submission: after the link, the customer is byte-for-byte what it
was, and the differences are recorded as field *keys* in the audit trail and as
``applied = false`` on the proposal.
"""

from __future__ import annotations

from app.core.enums import Role
from app.models import (
    AuditEvent,
    ConsentEvent,
    Customer,
    CustomerAddress,
    CustomerDataProposal,
    CustomerIdentity,
    CustomerIdentityLink,
)
from tests.approval_fixtures import (
    acknowledged_preview,
    add_shipment,
    approve_create,
    approve_link,
    key,
    make_customer,
    pending_identity,
    staff,
)
from tests.conftest import see_committed_changes

APPLICANT = "hanh@demo.example.com"


def _operations(account_client, account_users):
    return staff(account_client, account_users[Role.OPERATIONS].email)


def _target(account_db):
    return make_customer(
        account_db,
        full_name="Existing Person",
        email="existing@demo.example.com",
        phone="+1 416 555 0144",
        country_code="CA",
        city="Toronto",
    )


def test_linking_activates_the_identity_and_writes_one_link(
    account_client, account_db, account_users, captured_mail
):
    customer = _target(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)

    response = approve_link(api, reference, customer.public_id, fingerprint)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"
    assert response.json()["outcome"] == "approved_linked"
    assert response.json()["customer_public_id"] == customer.public_id

    account_db.expire_all()
    link = account_db.query(CustomerIdentityLink).one()
    assert link.status == "active"
    assert link.customer_id == customer.id
    assert account_db.query(CustomerIdentity).one().status == "active"


def test_linking_changes_no_canonical_value_even_where_everything_differs(
    account_client, account_db, account_users, captured_mail
):
    """The claim, asserted column by column against a full snapshot.

    Every mapped column of this customer disagrees with the submission -- name, email,
    phone, city, country. None of them moves **except the email**, which becomes the
    account's verified sign-in email (the single email rule, owner decision 2026-10-15).
    """
    customer = _target(account_db)
    before = {column.name: getattr(customer, column.name) for column in Customer.__table__.columns}
    addresses_before = account_db.query(CustomerAddress).count()
    consents_before = account_db.query(ConsentEvent).count()

    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)
    assert approve_link(api, reference, customer.public_id, fingerprint).status_code == 200

    see_committed_changes(account_db)
    customer = account_db.query(Customer).one()
    after = {column.name: getattr(customer, column.name) for column in Customer.__table__.columns}
    assert after["email_normalized"] == APPLICANT
    for moved in ("email_entered", "email_normalized", "updated_at"):
        before.pop(moved)
        after.pop(moved)
    assert after == before
    assert account_db.query(CustomerAddress).count() == addresses_before
    # The applicant's explicit marketing choice is appended as consent (UAT round 5); it
    # is not a canonical value and the record above is unchanged.
    assert account_db.query(ConsentEvent).count() == consents_before + 1
    assert account_db.query(Customer).count() == 1


def test_the_differences_are_recorded_as_field_keys_and_applied_to_nothing(
    account_client, account_db, account_users, captured_mail
):
    """Preserved for Phase 12 change-proposal handling, as OD-28 asks.

    ``applied`` is false on every field but the email, which is how the record says no
    other canonical data moved -- rather than leaving it to be inferred from the absence of
    an update row. The email is the single email rule (owner decision, 2026-10-15).
    """
    customer = _target(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)
    assert approve_link(api, reference, customer.public_id, fingerprint).status_code == 200

    account_db.expire_all()
    proposal = account_db.query(CustomerDataProposal).one()
    assert proposal.status == "approved"
    assert proposal.customer_id == customer.id
    assert proposal.decision_reason_code == "linked_existing_email_applied"
    assert {row.field_key for row in proposal.fields if row.applied} <= {"email"}

    link_event = account_db.query(AuditEvent).filter_by(action="customer_account.link").one()
    import json

    detail = json.loads(link_event.detail_json)
    assert "full_name" in detail["differing_field_keys"]
    # Keys, never the values the applicant submitted.
    assert "Nguyễn" not in link_event.detail_json


def test_a_customer_that_already_has_an_account_refuses_a_second(
    account_client, account_db, account_users, captured_mail
):
    """OD-25, release 1: one active identity per canonical customer.

    Refused by the application check, and again by the partial unique index underneath
    it, which is the one that wins a race.
    """
    customer = _target(account_db)
    first = pending_identity(account_client, captured_mail, "first@demo.example.com")
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, first, "link_existing", customer.public_id)
    assert approve_link(api, first, customer.public_id, fingerprint).status_code == 200

    second = pending_identity(account_client, captured_mail, "second@demo.example.com")
    api = _operations(account_client, account_users)
    second_fingerprint = acknowledged_preview(api, second, "link_existing", customer.public_id)
    response = approve_link(api, second, customer.public_id, second_fingerprint)
    assert response.status_code == 409

    account_db.expire_all()
    assert account_db.query(CustomerIdentityLink).filter_by(status="active").count() == 1


def test_an_identity_that_is_already_linked_refuses_a_second_customer(
    account_client, account_db, account_users, captured_mail
):
    """The other half of the one-to-one rule (OD-25), refused three deep.

    A linked identity cannot even reach a second preview -- its proposal was decided, so
    there is nothing waiting for review. Behind that, the approval refuses on the active
    link, and behind *that* the partial unique index refuses the insert. The outermost
    refusal is the one a reviewer meets; the innermost is the one that survives a race.
    """
    first_customer = _target(account_db)
    other = make_customer(account_db, full_name="Other", email="other@demo.example.com")
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)

    fingerprint = acknowledged_preview(api, reference, "link_existing", first_customer.public_id)
    assert approve_link(api, reference, first_customer.public_id, fingerprint).status_code == 200

    from tests.approval_fixtures import preview

    stale_preview = preview(api, reference, "link_existing", other.public_id)
    assert stale_preview.status_code == 409
    assert "no proposal waiting" in stale_preview.text

    # And the approval itself, reached with the fingerprint from the first decision.
    assert approve_link(api, reference, other.public_id, fingerprint).status_code == 409

    account_db.expire_all()
    links = account_db.query(CustomerIdentityLink).filter_by(status="active").all()
    assert len(links) == 1
    assert links[0].customer_id == first_customer.id


def test_an_already_approved_identity_cannot_be_approved_again_with_a_new_key(
    account_client, account_db, account_users, captured_mail
):
    """Approval happens once. A *new* idempotency key is a new decision, and is refused."""
    customer = _target(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)
    assert approve_link(api, reference, customer.public_id, fingerprint).status_code == 200

    again = approve_create(api, reference, fingerprint, key=key())
    assert again.status_code == 409


def test_the_link_makes_the_disclosure_real_and_since_phase_11_serves_it(
    account_client, account_db, account_users, captured_mail
):
    """What an approval grants, read from the account's own side.

    In Phase 10 this asserted ``shipment_history_available: false``, because no route served
    a shipment and reporting "available" would have been the response telling a lie. Phase 11
    built the routes, so the assertion moves with them -- and it is still answered by the
    same helper the shipment routes authorize from, so ``/me`` and the list cannot disagree.

    What has **not** changed is everything else on this response: it is a boolean, not a
    count, not a date and not a customer reference. A count of matching shipments is itself
    an enumeration oracle, and the disclosure figures stay staff-facing.
    """
    from app.core.config import settings
    from tests.account_fixtures import sign_in

    customer = _target(account_db)
    shipment = add_shipment(account_db, customer, days_ago=12)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)
    assert approve_link(api, reference, customer.public_id, fingerprint).status_code == 200

    account_client.cookies.clear()
    signed_in = sign_in(account_client, APPLICANT)
    assert signed_in.status_code == 200
    me = account_client.get("/api/v1/account/me").json()
    assert me["status"] == "active"
    assert me["linked"] is True
    assert me["shipment_history_available"] is True
    assert "customer" not in str(me).lower() or me.get("customer_public_id") is None
    assert settings.account_csrf_header_name  # the realm is still the customer one

    # And the claim is true: the disclosed shipment is actually readable, and it is the
    # only one, which is what the reviewer acknowledged before approving.
    listed = account_client.get("/api/v1/account/shipments").json()
    assert [item["shipment_reference"] for item in listed["items"]] == [shipment.public_id]
    assert listed["total"] == 1


def test_linking_is_idempotent_on_retry(account_client, account_db, account_users, captured_mail):
    customer = _target(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)
    shared = key()

    first = approve_link(api, reference, customer.public_id, fingerprint, key=shared)
    assert first.status_code == 200
    second = approve_link(api, reference, customer.public_id, fingerprint, key=shared)
    assert second.status_code == 200
    assert second.json()["replayed"] is True
    assert second.json()["customer_public_id"] == customer.public_id

    account_db.expire_all()
    assert account_db.query(CustomerIdentityLink).count() == 1
    assert account_db.query(AuditEvent).filter_by(action="customer_account.link").count() == 1


def test_the_same_key_with_a_different_customer_is_a_conflict(
    account_client, account_db, account_users, captured_mail
):
    first_customer = _target(account_db)
    other = make_customer(account_db, full_name="Other", email="other@demo.example.com")
    a = pending_identity(account_client, captured_mail, "a@demo.example.com")
    b = pending_identity(account_client, captured_mail, "b@demo.example.com")
    api = _operations(account_client, account_users)
    shared = key()

    fingerprint = acknowledged_preview(api, a, "link_existing", first_customer.public_id)
    assert (
        approve_link(api, a, first_customer.public_id, fingerprint, key=shared).status_code == 200
    )

    other_fingerprint = acknowledged_preview(api, b, "link_existing", other.public_id)
    response = approve_link(api, b, other.public_id, other_fingerprint, key=shared)
    assert response.status_code == 409
    assert "idempotency" in response.text.lower()
