"""UAT round 5 fix pack (RC-UAT-8 findings and owner decisions, 2026-10-15).

1. The staff customer form: a bad email and a negative monthly estimate are refused with
   a field the form can link to (the friendly wording is the form's; see the frontend).
2. Registration refuses a malformed email with the same sentence as the staff form.
3. A marketing choice made at registration reaches the linked customer as express consent,
   on create-new and on link-existing, and a suppression still wins.
4. Audit: ``suppression.add`` shows its evidence reference; a lifecycle summary names the
   account.
6. Owner decisions: Operations cannot suppress through a consent event; a deactivated
   account keeps its link and no longer blocks a merge; the resend 429 is generic.
"""

from __future__ import annotations

import json

from app.core.config import settings
from app.core.enums import ConsentBasis, ConsentStatus, Role
from app.core.normalization import INVALID_EMAIL_MESSAGE
from app.models import (
    AuditEvent,
    ConsentEvent,
    ContactSuppression,
    Customer,
    CustomerDataProposal,
    CustomerIdentity,
    CustomerIdentityLink,
)
from app.services import audit_service, consent_service, customer_identity_service
from app.services.customer_account_approval_service import REGISTRATION_CONSENT_SOURCE
from tests.account_fixtures import REQUIRED_ADDRESS, register, registration, verification_token
from tests.approval_fixtures import (
    acknowledged_preview,
    approve_create,
    approve_link,
    pending_identity,
    staff,
)
from tests.conftest import make_customer, see_committed_changes

APPLICANT = "hanh@demo.example.com"
CUSTOMERS = "/api/v1/customers"
IDENTITIES = "/api/v1/customer-account/identities"
REGISTER = "/api/v1/account/register"
RESEND = "/api/v1/account/verification/resend"


# --- 1. The staff customer form --------------------------------------------------------


def test_a_bad_email_on_the_staff_form_names_the_field_in_plain_words(api_for):
    api = api_for(Role.OPERATIONS)
    response = api.post(CUSTOMERS, json={"full_name": "Trần Văn Bình", "email": "bad"})
    assert response.status_code == 422
    body = response.json()
    assert body["field"] == "email"
    assert body["message"] == INVALID_EMAIL_MESSAGE


def test_a_negative_monthly_estimate_is_refused_naming_its_field(api_for, db):
    """The request-validation 422 the form maps: ``loc`` ends in the field's name."""
    api = api_for(Role.OPERATIONS)
    response = api.post(
        CUSTOMERS,
        json={
            "full_name": "Trần Văn Bình",
            "phone": "+1 416 555 0101",
            "estimated_monthly_shipments": -1,
        },
    )
    assert response.status_code == 422
    locations = [item["loc"][-1] for item in response.json()["detail"]]
    assert locations == ["estimated_monthly_shipments"]
    see_committed_changes(db)
    assert db.query(Customer).count() == 0


# --- 2. Registration email ---------------------------------------------------------------


def test_registration_refuses_a_malformed_email_with_the_shared_sentence(
    account_client, account_db, captured_mail
):
    response = account_client.post(REGISTER, json=registration(email="bad"))
    assert response.status_code == 422
    assert response.json()["field"] == "email"
    assert response.json()["message"] == INVALID_EMAIL_MESSAGE
    assert account_db.query(CustomerIdentity).count() == 0


def test_a_malformed_contact_email_in_the_customer_block_gets_the_same_sentence(
    account_client, account_db, captured_mail
):
    body = registration()
    body["customer"]["email"] = "name@localhost"
    response = account_client.post(REGISTER, json=body)
    assert response.status_code == 422
    assert response.json()["message"] == INVALID_EMAIL_MESSAGE


# --- 3. Marketing consent carried to the customer ---------------------------------------


def _existing(account_db, **overrides):
    payload = {
        "full_name": "Existing Person",
        "email": "existing@demo.example.com",
        "phone": "+1 416 555 0144",
    }
    payload.update(overrides)
    return make_customer(account_db, **payload)


def _link(account_client, account_users, reference, customer):
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)
    response = approve_link(api, reference, customer.public_id, fingerprint)
    assert response.status_code == 200, response.text
    return response


def _consents(account_db, customer_id):
    see_committed_changes(account_db)
    return account_db.query(ConsentEvent).filter_by(customer_id=customer_id).all()


def test_link_existing_carries_the_marketing_choice_as_express_consent(
    account_client, account_db, account_users, captured_mail
):
    customer = _existing(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    _link(account_client, account_users, reference, customer)

    events = _consents(account_db, customer.id)
    assert len(events) == 1
    event = events[0]
    assert event.status == ConsentStatus.CONSENTED
    assert event.basis == ConsentBasis.EXPRESS
    assert event.channel == "email"
    assert event.address_value == APPLICANT
    assert event.source == REGISTRATION_CONSENT_SOURCE
    assert reference in event.evidence_reference
    proposal = account_db.query(CustomerDataProposal).one()
    assert event.obtained_at == proposal.submitted_at
    assert event.recorded_by_user_id == account_users[Role.OPERATIONS].id
    # Consent is appended, not applied. Since UAT round 6 the record's email is the
    # applicant's verified sign-in email (one email per customer), so the event is for the
    # record's own address; nothing else on the record moved (OD-28).
    assert account_db.get(Customer, customer.id).email_normalized == APPLICANT
    assert {row.field_key for row in proposal.fields if row.applied} <= {"email"}
    assert account_db.query(AuditEvent).filter_by(action="consent.record").count() == 1


def test_link_existing_reads_eligible_when_the_linked_address_is_the_applicants(
    account_client, account_db, account_users, captured_mail
):
    customer = _existing(account_db, email=APPLICANT)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    _link(account_client, account_users, reference, customer)

    see_committed_changes(account_db)
    assert consent_service.marketing_eligible(account_db, customer, "email") is True


def test_link_existing_writes_nothing_without_an_explicit_choice(
    account_client, account_db, account_users, captured_mail
):
    customer = _existing(account_db)
    response = register(
        account_client,
        email=APPLICANT,
        customer={"customer_type": "individual", "legal_name": "No Marketing", **REQUIRED_ADDRESS},
        billing_same_as_shipping=True,
    )
    assert response.status_code == 200
    account_client.post(
        "/api/v1/account/verify-email",
        json={"token": verification_token(captured_mail, APPLICANT)},
    )
    reference = account_db.query(CustomerIdentity).one().public_id
    _link(account_client, account_users, reference, customer)
    assert _consents(account_db, customer.id) == []


def test_link_existing_respects_a_suppression_and_still_approves(
    account_client, account_db, account_users, captured_mail
):
    customer = _existing(account_db)
    # Suppressed after verification. (Since UAT round 6 the order no longer matters: a
    # suppressed address is sent its verification message like any other.)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    consent_service.add_suppression(
        account_db, channel="email", address_value=APPLICANT, reason="Bounced"
    )
    account_db.commit()
    response = _link(account_client, account_users, reference, customer)

    assert response.json()["status"] == "active"
    assert _consents(account_db, customer.id) == []
    assert account_db.query(ContactSuppression).one().released_at is None


def test_a_later_answer_on_the_customer_is_not_overwritten_by_the_checkbox(
    account_client, account_db, account_users, captured_mail
):
    """A withdrawal recorded after the registration was submitted is newer evidence."""
    customer = _existing(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    consent_service.record_consent_event(
        account_db,
        customer,
        channel="email",
        status=ConsentStatus.WITHDRAWN,
        address_value=APPLICANT,
        source="phone_call",
    )
    account_db.commit()
    _link(account_client, account_users, reference, customer)

    events = _consents(account_db, customer.id)
    assert [event.status for event in events] == [ConsentStatus.WITHDRAWN]


def test_create_new_consent_names_the_account_and_the_submission_time(
    account_client, account_db, account_users, captured_mail
):
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    fingerprint = acknowledged_preview(api, reference, "create_new")
    assert approve_create(api, reference, fingerprint).status_code == 200

    see_committed_changes(account_db)
    event = account_db.query(ConsentEvent).one()
    assert reference in event.evidence_reference
    assert event.obtained_at == account_db.query(CustomerDataProposal).one().submitted_at


# --- 4. Audit display --------------------------------------------------------------------

EVIDENCE = "TICKET-5120"


def _audit_rows(api, action):
    response = api.get("/api/v1/audit", params={"action": action})
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_the_suppression_audit_row_shows_its_evidence_reference(api_for, db):
    customer = make_customer(db, email="lan@example.com")
    response = api_for(Role.MARKETING).post(
        f"{CUSTOMERS}/{customer.id}/consent/suppressions",
        json={"channel": "email", "evidence_reference": EVIDENCE, "reason": "Asked by phone"},
    )
    assert response.status_code == 201, response.text

    rows = _audit_rows(api_for(Role.ADMIN), "suppression.add")
    assert len(rows) == 1
    assert rows[0]["evidence_reference"] == EVIDENCE
    assert "lan@example.com" not in rows[0]["detail_json"]
    assert "Asked by phone" not in rows[0]["detail_json"]


def test_a_round_4_suppression_row_reads_its_evidence_from_the_consent_event(api_for, db, users):
    """Rows written before this fix carry ``consent_event_id`` and no reference."""
    customer = make_customer(db, email="old@example.com")
    consent_service.suppress_address(
        db,
        customer,
        channel="email",
        evidence_reference="FORM-77",
        reason="Asked in person",
        actor=users[Role.MARKETING],
    )
    db.flush()
    row = db.query(AuditEvent).filter_by(action="suppression.add").one()
    detail = json.loads(row.detail_json)
    del detail["evidence_reference"]
    row.detail_json = json.dumps(detail)
    db.commit()

    rows = _audit_rows(api_for(Role.ADMIN), "suppression.add")
    assert rows[0]["evidence_reference"] == "FORM-77"


def test_an_evidence_value_that_is_not_a_reference_is_not_shown():
    for value in ("someone@example.com", "Customer said on the phone that she wants" + "x" * 80):
        derived = audit_service.audit_display_fields(json.dumps({"evidence_reference": value}))
        assert derived["evidence_reference"] is None
    shown = audit_service.audit_display_fields(json.dumps({"evidence_reference": "DOC 12/A"}))
    assert shown["evidence_reference"] == "DOC 12/A"


def test_a_deactivation_summary_names_the_account(
    account_client, account_db, account_users, captured_mail
):
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.ADMIN].email)
    response = api.post(
        f"{IDENTITIES}/{reference}/deactivate", json={"reason_code": "customer_request"}
    )
    assert response.status_code == 200, response.text

    see_committed_changes(account_db)
    row = account_db.query(AuditEvent).filter_by(action="customer_account.deactivate").one()
    assert row.summary == f"Customer Account {reference} deactivated"


def test_suspend_and_reinstate_summaries_name_the_account(
    account_client, account_db, account_users, captured_mail
):
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    assert (
        api.post(f"{IDENTITIES}/{reference}/suspend", json={"reason_code": "security_concern"})
    ).status_code == 200
    assert (
        api.post(f"{IDENTITIES}/{reference}/reinstate", json={"reason_code": "review_complete"})
    ).status_code == 200

    see_committed_changes(account_db)
    summaries = {
        row.action: row.summary
        for row in account_db.query(AuditEvent).filter(
            AuditEvent.action.in_(["customer_account.suspend", "customer_account.reinstate"])
        )
    }
    assert summaries["customer_account.suspend"] == f"Customer Account {reference} suspended"
    assert summaries["customer_account.reinstate"] == f"Customer Account {reference} reinstated"


# --- 6a. Operations cannot suppress -------------------------------------------------------


def _record(api, customer_id, status, **extra):
    body = {
        "channel": "email",
        "status": status,
        "basis": "express" if status == "consented" else "not_recorded",
        "evidence_reference": "FORM-9",
        **extra,
    }
    return api.post(f"{CUSTOMERS}/{customer_id}/consent", json=body)


def test_operations_cannot_suppress_through_a_consent_event(api_for, db):
    customer = make_customer(db, email="binh@example.com")
    response = _record(api_for(Role.OPERATIONS), customer.id, "suppressed")

    assert response.status_code == 403
    assert response.json()["detail"]["required_permission"] == "suppression:add"
    see_committed_changes(db)
    assert db.query(ConsentEvent).count() == 0
    assert db.query(ContactSuppression).count() == 0


def test_operations_still_records_consent_and_withdrawal(api_for, db):
    customer = make_customer(db, email="binh@example.com")
    api = api_for(Role.OPERATIONS)
    assert _record(api, customer.id, "consented").status_code == 201
    assert _record(api, customer.id, "withdrawn").status_code == 201


def test_marketing_and_admin_may_still_suppress_through_a_consent_event(api_for, db):
    for role, address in ((Role.MARKETING, "m@example.com"), (Role.ADMIN, "a@example.com")):
        customer = make_customer(db, email=address)
        assert _record(api_for(role), customer.id, "suppressed").status_code == 201
    see_committed_changes(db)
    assert db.query(ContactSuppression).count() == 2


# --- 6b. A deactivated account no longer blocks a merge ------------------------------------


def test_a_deactivated_account_keeps_its_link_and_the_customer_can_be_merged(
    account_client, account_db, account_users, captured_mail
):
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    admin = staff(account_client, account_users[Role.ADMIN].email)
    fingerprint = acknowledged_preview(admin, reference, "create_new")
    approved = approve_create(admin, reference, fingerprint)
    assert approved.status_code == 200, approved.text
    source = account_db.query(Customer).filter_by(public_id=approved.json()["customer_public_id"])
    source = source.one()
    target = make_customer(account_db, full_name="Survivor", email="survivor@example.com")

    def merge():
        return admin.post(
            f"{CUSTOMERS}/merge",
            json={
                "source_customer_id": source.id,
                "target_customer_id": target.id,
                "confirmation": source.public_id,
            },
        )

    # While the account is active the merge is refused, as before (OD-40).
    assert merge().status_code == 409

    assert (
        admin.post(
            f"{IDENTITIES}/{reference}/deactivate", json={"reason_code": "duplicate_account"}
        )
    ).status_code == 200
    response = merge()
    assert response.status_code == 200, response.text

    see_committed_changes(account_db)
    assert account_db.get(Customer, source.id).merged_into_customer_id == target.id
    link = account_db.query(CustomerIdentityLink).one()
    assert link.status == "active"
    assert link.customer_id == source.id
    assert account_db.query(CustomerIdentity).one().status == "deactivated"


def test_a_suspended_account_still_blocks_a_merge(
    account_client, account_db, account_users, captured_mail
):
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    admin = staff(account_client, account_users[Role.ADMIN].email)
    fingerprint = acknowledged_preview(admin, reference, "create_new")
    approved = approve_create(admin, reference, fingerprint)
    source = (
        account_db.query(Customer).filter_by(public_id=approved.json()["customer_public_id"]).one()
    )
    target = make_customer(account_db, full_name="Survivor", email="survivor@example.com")
    assert (
        admin.post(f"{IDENTITIES}/{reference}/suspend", json={"reason_code": "security_concern"})
    ).status_code == 200

    response = admin.post(
        f"{CUSTOMERS}/merge",
        json={
            "source_customer_id": source.id,
            "target_customer_id": target.id,
            "confirmation": source.public_id,
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "customer_account_link_present"


# --- 6c. The resend 429 is generic --------------------------------------------------------


def test_the_resend_per_connection_429_carries_the_ordinary_sentence(
    account_client, account_db, captured_mail
):
    for _ in range(settings.account_resend_ip_attempts):
        assert account_client.post(RESEND, json={"email": APPLICANT}).status_code == 200

    refused = account_client.post(RESEND, json={"email": APPLICANT})
    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) > 0
    assert set(refused.json()) == {"code", "message", "field"}
    assert refused.json()["message"] == customer_identity_service.GENERIC_REGISTRATION_MESSAGE
    assert "too many" not in refused.text.lower()
