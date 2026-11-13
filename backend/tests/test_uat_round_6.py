"""UAT round 6 fix pack (RC-UAT-9 findings and owner decisions, 2026-10-15).

1. One email per customer. Linking an account makes the record's email the verified
   sign-in email, shown in the preview and audited; consent then lands on that address;
   a linked customer's email cannot be edited away from it.
2. A suppression blocks marketing email only. Verification, the registration-attempt
   notice, reset and the decision notices reach a suppressed address; the opt-in stays
   ineffective and the customer never reads about the suppression.
3. A customer whose only account was deactivated can be taken over by a new registration,
   by a staff approval that ends the old link, audited.
4. (The evidence-reference helper text is a screen change; see ``uatRound6.test.jsx``.)
"""

from __future__ import annotations

import json

from app.core.account_enums import RegistrationOutcome
from app.core.enums import ConsentStatus, Role
from app.core.security import rate_limiter
from app.models import (
    AuditEvent,
    ConsentEvent,
    ContactSuppression,
    Customer,
    CustomerIdentity,
    CustomerIdentityLink,
    CustomerRegistrationAttempt,
)
from app.services import consent_service, customer_identity_service
from app.services.customer_service import LINKED_EMAIL_MESSAGE
from tests.account_fixtures import (
    ACCOUNT_PASSWORD,
    register,
    registration,
    sign_in,
    verification_token,
)
from tests.approval_fixtures import (
    acknowledged_preview,
    approve_create,
    approve_link,
    pending_identity,
    preview,
    staff,
)
from tests.conftest import make_customer, see_committed_changes

APPLICANT = "hanh@demo.example.com"
SECOND = "minh@demo.example.com"
RECORD_EMAIL = "existing@demo.example.com"
CUSTOMERS = "/api/v1/customers"
IDENTITIES = "/api/v1/customer-account/identities"
REGISTRATIONS = "/api/v1/customer-account/registrations"
REGISTER = "/api/v1/account/register"
RESEND = "/api/v1/account/verification/resend"
FORGOT = "/api/v1/account/password/forgot"
SUPPRESSION_REASON = "Bounced twice, then asked by phone"


def _existing(account_db, **overrides):
    payload = {"full_name": "Existing Person", "email": RECORD_EMAIL, "phone": "+1 416 555 0144"}
    payload.update(overrides)
    return make_customer(account_db, **payload)


def _suppress(account_db, address=APPLICANT):
    consent_service.add_suppression(
        account_db, channel="email", address_value=address, reason=SUPPRESSION_REASON
    )
    account_db.commit()


def _templates(captured_mail, to_email=None):
    return [
        message["template_key"]
        for message in captured_mail.messages
        if to_email is None or message["to_email"] == to_email
    ]


def _operations(account_client, account_users):
    return staff(account_client, account_users[Role.OPERATIONS].email)


def _admin(account_client, account_users):
    return staff(account_client, account_users[Role.ADMIN].email)


def _audit(account_db, action):
    see_committed_changes(account_db)
    return account_db.query(AuditEvent).filter_by(action=action).all()


# --- 1. One email per customer ----------------------------------------------------------


def test_the_link_preview_shows_the_email_change_before_the_reviewer_confirms(
    account_client, account_db, account_users, captured_mail
):
    customer = _existing(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)

    body = preview(api, reference, "link_existing", customer.public_id).json()
    assert body["email_change"] == {"current": RECORD_EMAIL, "new": APPLICANT}
    assert body["ends_link_of"] is None

    # Previewing changes nothing.
    see_committed_changes(account_db)
    assert account_db.get(Customer, customer.id).email_normalized == RECORD_EMAIL


def test_no_email_change_is_shown_when_the_record_already_holds_the_sign_in_email(
    account_client, account_db, account_users, captured_mail
):
    customer = _existing(account_db, email="Hanh@Demo.Example.com")
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    body = preview(api, reference, "link_existing", customer.public_id).json()
    assert body["email_change"] is None


def test_linking_makes_the_record_email_the_sign_in_email_audited(
    account_client, account_db, account_users, captured_mail
):
    customer = _existing(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)
    assert approve_link(api, reference, customer.public_id, fingerprint).status_code == 200

    see_committed_changes(account_db)
    record = account_db.get(Customer, customer.id)
    assert record.email_normalized == APPLICANT
    assert record.email_entered == APPLICANT

    [applied] = _audit(account_db, "customer_account.sign_in_email_applied")
    detail = json.loads(applied.detail_json)
    assert detail == {
        "identity_public_id": reference,
        "customer_public_id": customer.public_id,
        "previous_email_present": True,
        "reason_code": "single_email_rule",
    }
    assert applied.actor_user_id == account_users[Role.OPERATIONS].id
    # Neither address is in the audit trail; the records hold them.
    for row in _audit(account_db, "customer_account.sign_in_email_applied") + _audit(
        account_db, "customer.update"
    ):
        assert APPLICANT not in (row.detail_json or "") + row.summary
        assert RECORD_EMAIL not in (row.detail_json or "") + row.summary
    assert len(_audit(account_db, "customer.update")) == 1

    approve_row = _audit(account_db, "customer_account.approve")[0]
    assert json.loads(approve_row.detail_json)["applied_field_keys"] == ["email"]


def test_the_opt_in_lands_on_the_record_email_and_the_state_row_reflects_it(
    account_client, account_db, account_users, captured_mail
):
    """Owner question 36.4.1: the email state row now reads the address consent was for."""
    customer = _existing(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)
    assert approve_link(api, reference, customer.public_id, fingerprint).status_code == 200

    see_committed_changes(account_db)
    record = account_db.get(Customer, customer.id)
    [event] = account_db.query(ConsentEvent).filter_by(customer_id=customer.id).all()
    assert event.address_value == record.email_normalized == APPLICANT
    state = consent_service.current_state(account_db, record, "email")
    assert state.address_value == APPLICANT
    assert state.status == ConsentStatus.CONSENTED
    assert consent_service.marketing_eligible(account_db, record, "email") is True


def test_a_record_with_no_email_gets_the_sign_in_email(
    account_client, account_db, account_users, captured_mail
):
    customer = _existing(account_db, email=None)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    body = preview(api, reference, "link_existing", customer.public_id).json()
    assert body["email_change"] == {"current": None, "new": APPLICANT}
    assert approve_link(api, reference, customer.public_id, body["fingerprint"]).status_code == 409

    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)
    assert approve_link(api, reference, customer.public_id, fingerprint).status_code == 200
    see_committed_changes(account_db)
    assert account_db.get(Customer, customer.id).email_normalized == APPLICANT
    [applied] = _audit(account_db, "customer_account.sign_in_email_applied")
    assert json.loads(applied.detail_json)["previous_email_present"] is False


def test_an_email_edited_after_the_preview_makes_it_stale(
    account_client, account_db, account_users, captured_mail
):
    """The change the reviewer saw is the change that happens, or nothing does."""
    customer = _existing(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)

    from app.services import customer_service

    customer_service.update_customer(account_db, customer, {"email": "moved@demo.example.com"})
    account_db.commit()

    response = approve_link(api, reference, customer.public_id, fingerprint)
    assert response.status_code == 409
    see_committed_changes(account_db)
    assert account_db.get(Customer, customer.id).email_normalized == "moved@demo.example.com"


def test_create_new_takes_the_sign_in_email_over_a_different_form_email(
    account_client, account_db, account_users, captured_mail
):
    body = registration(email=APPLICANT)
    body["customer"]["email"] = "someone.else@demo.example.com"
    assert account_client.post(REGISTER, json=body).status_code == 200
    account_client.post(
        "/api/v1/account/verify-email",
        json={"token": verification_token(captured_mail, APPLICANT)},
    )
    reference = account_db.query(CustomerIdentity).one().public_id
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "create_new")
    created = approve_create(api, reference, fingerprint)
    assert created.status_code == 200, created.text

    see_committed_changes(account_db)
    record = account_db.query(Customer).one()
    assert record.email_normalized == APPLICANT
    assert account_db.query(ConsentEvent).one().address_value == APPLICANT


def _linked_customer(account_client, account_db, account_users, captured_mail):
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    admin = _admin(account_client, account_users)
    fingerprint = acknowledged_preview(admin, reference, "create_new")
    approved = approve_create(admin, reference, fingerprint)
    assert approved.status_code == 200, approved.text
    see_committed_changes(account_db)
    customer = (
        account_db.query(Customer).filter_by(public_id=approved.json()["customer_public_id"]).one()
    )
    return reference, customer, admin


def _patch(api, customer_id, body):
    return api.client.patch(f"{CUSTOMERS}/{customer_id}", headers=api.headers, json=body)


def test_staff_cannot_change_a_linked_customers_email(
    account_client, account_db, account_users, captured_mail
):
    reference, customer, admin = _linked_customer(
        account_client, account_db, account_users, captured_mail
    )
    response = _patch(admin, customer.id, {"email": "other@demo.example.com"})
    assert response.status_code == 409
    assert response.json()["field"] == "email"
    assert response.json()["message"] == LINKED_EMAIL_MESSAGE

    # The whole form is sent on every save: the same address, in any case, passes.
    assert _patch(admin, customer.id, {"email": APPLICANT.upper(), "city": "Hue"}).status_code == (
        200
    )
    see_committed_changes(account_db)
    assert account_db.get(Customer, customer.id).email_normalized == APPLICANT


def test_a_suspended_account_still_holds_the_email_and_a_deactivated_one_does_not(
    account_client, account_db, account_users, captured_mail
):
    reference, customer, admin = _linked_customer(
        account_client, account_db, account_users, captured_mail
    )
    assert (
        admin.post(f"{IDENTITIES}/{reference}/suspend", json={"reason_code": "security_concern"})
    ).status_code == 200
    assert _patch(admin, customer.id, {"email": "other@demo.example.com"}).status_code == 409

    assert (
        admin.post(f"{IDENTITIES}/{reference}/deactivate", json={"reason_code": "customer_request"})
    ).status_code == 200
    assert _patch(admin, customer.id, {"email": "other@demo.example.com"}).status_code == 200


# --- 2. A suppression blocks marketing email only ----------------------------------------


def test_a_suppressed_address_registers_and_receives_its_verification_email(
    account_client, account_db, captured_mail
):
    """The UAT round 6 defect: 'registration received', and no verification, ever."""
    _suppress(account_db)
    response = register(account_client, email=APPLICANT)
    assert response.status_code == 200
    assert response.json()["message"] == customer_identity_service.GENERIC_REGISTRATION_MESSAGE
    assert _templates(captured_mail, APPLICANT) == ["account.verify_email"]

    see_committed_changes(account_db)
    identity = account_db.query(CustomerIdentity).one()
    assert identity.status == "pending_verification"
    [received] = _audit(account_db, "customer_account.register")
    assert json.loads(received.detail_json)["outcome"] == "created"
    assert _audit(account_db, "customer_account.verification_issued")

    verified = account_client.post(
        "/api/v1/account/verify-email",
        json={"token": verification_token(captured_mail, APPLICANT)},
    )
    assert verified.status_code == 200
    see_committed_changes(account_db)
    assert account_db.query(CustomerIdentity).one().status == "pending_approval"
    # The suppression is untouched.
    assert account_db.query(ContactSuppression).one().released_at is None


def test_resend_reset_and_the_attempt_notice_reach_a_suppressed_address(
    account_client, account_db, captured_mail
):
    register(account_client, email=APPLICANT)
    _suppress(account_db)
    captured_mail.messages.clear()

    rate_limiter.reset()
    assert account_client.post(RESEND, json={"email": APPLICANT}).status_code == 200
    rate_limiter.reset()
    assert account_client.post(FORGOT, json={"email": APPLICANT}).status_code == 200
    rate_limiter.reset()
    assert register(account_client, email=APPLICANT).status_code == 200

    assert _templates(captured_mail, APPLICANT) == [
        "account.verify_email",
        "account.password_reset",
        "account.registration_attempt_notice",
    ]


def test_the_decision_notice_reaches_a_suppressed_address_and_the_opt_in_stays_ineffective(
    account_client, account_db, account_users, captured_mail
):
    _suppress(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "create_new")
    captured_mail.messages.clear()
    approved = approve_create(api, reference, fingerprint)
    assert approved.status_code == 200, approved.text

    assert _templates(captured_mail, APPLICANT) == ["account.approved"]
    see_committed_changes(account_db)
    customer = account_db.query(Customer).one()
    # The marketing opt-in is not recorded against a suppressed address, and the address
    # is not marketing-eligible; the suppression is still in force.
    assert account_db.query(ConsentEvent).count() == 0
    assert consent_service.marketing_eligible(account_db, customer, "email") is False
    assert account_db.query(ContactSuppression).one().released_at is None


def test_the_customer_never_reads_the_suppression_or_its_reason(
    account_client, account_db, account_users, captured_mail
):
    _suppress(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "create_new")
    assert approve_create(api, reference, fingerprint).status_code == 200

    account_client.cookies.clear()
    assert sign_in(account_client, APPLICANT, ACCOUNT_PASSWORD).status_code == 200
    for url in ("/api/v1/account/me", "/api/v1/account/profile"):
        response = account_client.get(url)
        assert response.status_code == 200, response.text
        text = response.text.lower()
        assert "suppress" not in text
        assert SUPPRESSION_REASON.lower() not in text
    for message in captured_mail.messages:
        rendered = json.dumps(message).lower()
        assert "suppress" not in rendered
        assert SUPPRESSION_REASON.lower() not in rendered


def test_a_registration_a_suppression_refused_before_the_fix_is_given_on_replay(
    account_db, captured_mail
):
    """An attempt row written by RC-UAT-9 must not replay 'nothing happened' for ever."""
    from app.core.account_security import address_key, opaque_digest
    from app.core.time_utils import utcnow

    _suppress(account_db)
    account_db.add(
        CustomerRegistrationAttempt(
            idempotency_key_digest=opaque_digest("key-from-round-5"),
            email_key=address_key(APPLICANT),
            request_fingerprint=customer_identity_service._fingerprint(APPLICANT, [], {}),
            outcome=RegistrationOutcome.SUPPRESSED.value,
            identity_id=None,
            created_at=utcnow(),
            request_ip=None,
        )
    )
    account_db.commit()

    result = customer_identity_service.register(
        account_db,
        email_normalized=APPLICANT,
        email_entered=APPLICANT,
        password=ACCOUNT_PASSWORD,
        fields=[],
        notification_topics={},
        terms_version="t",
        privacy_version="p",
        presented_language="en",
        idempotency_key="key-from-round-5",
        request_ip=None,
    )
    account_db.commit()
    assert result.outcome is RegistrationOutcome.CREATED
    assert _templates(captured_mail, APPLICANT) == ["account.verify_email"]
    [attempt] = account_db.query(CustomerRegistrationAttempt).all()
    assert attempt.outcome == "created"


# --- 3. Taking over a customer whose account was deactivated ------------------------------


def _deactivated_link(account_client, account_db, account_users, captured_mail):
    first, customer, admin = _linked_customer(
        account_client, account_db, account_users, captured_mail
    )
    assert (
        admin.post(f"{IDENTITIES}/{first}/deactivate", json={"reason_code": "customer_request"})
    ).status_code == 200
    second = pending_identity(account_client, captured_mail, SECOND)
    return first, second, customer


def test_the_preview_says_whose_deactivated_link_the_approval_ends(
    account_client, account_db, account_users, captured_mail
):
    first, second, customer = _deactivated_link(
        account_client, account_db, account_users, captured_mail
    )
    api = _operations(account_client, account_users)
    body = preview(api, second, "link_existing", customer.public_id).json()
    assert body["ends_link_of"] == first
    assert body["email_change"] == {"current": APPLICANT, "new": SECOND}

    candidates = api.get(f"{REGISTRATIONS}/{second}/duplicate-candidates").json()["candidates"]
    row = next(c for c in candidates if c["customer_public_id"] == customer.public_id)
    assert row["has_active_identity_link"] is True
    assert row["linkable"] is True

    # Nothing is ended by looking, or by acknowledging.
    acknowledged_preview(api, second, "link_existing", customer.public_id)
    see_committed_changes(account_db)
    assert account_db.query(CustomerIdentityLink).one().status == "active"


def test_approving_ends_the_old_link_and_links_the_new_account_audited(
    account_client, account_db, account_users, captured_mail
):
    first, second, customer = _deactivated_link(
        account_client, account_db, account_users, captured_mail
    )
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, second, "link_existing", customer.public_id)
    response = approve_link(api, second, customer.public_id, fingerprint)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"

    see_committed_changes(account_db)
    old_identity = account_db.query(CustomerIdentity).filter_by(public_id=first).one()
    new_identity = account_db.query(CustomerIdentity).filter_by(public_id=second).one()
    old_link = account_db.query(CustomerIdentityLink).filter_by(identity_id=old_identity.id).one()
    new_link = account_db.query(CustomerIdentityLink).filter_by(identity_id=new_identity.id).one()
    assert old_link.status == "revoked"
    assert old_link.revoke_reason_code == "taken_over_by_new_account"
    assert old_link.revoked_by_user_id == account_users[Role.OPERATIONS].id
    assert old_link.revoked_at is not None
    assert new_link.status == "active"
    assert new_link.customer_id == customer.id
    assert old_identity.status == "deactivated"

    [unlink] = _audit(account_db, "customer_account.unlink")
    assert unlink.entity_id == first
    assert json.loads(unlink.detail_json) == {
        "identity_public_id": first,
        "customer_public_id": customer.public_id,
        "replaced_by_identity_public_id": second,
        "link_status": "revoked",
        "reason_code": "taken_over_by_new_account",
    }
    assert first in unlink.summary and second in unlink.summary
    # And the single email rule follows the new account.
    assert account_db.get(Customer, customer.id).email_normalized == SECOND


def test_an_active_or_suspended_account_is_never_taken_over(
    account_client, account_db, account_users, captured_mail
):
    first, customer, admin = _linked_customer(
        account_client, account_db, account_users, captured_mail
    )
    assert (
        admin.post(f"{IDENTITIES}/{first}/suspend", json={"reason_code": "security_concern"})
    ).status_code == 200
    second = pending_identity(account_client, captured_mail, SECOND)
    api = _operations(account_client, account_users)
    body = preview(api, second, "link_existing", customer.public_id).json()
    assert body["ends_link_of"] is None

    fingerprint = acknowledged_preview(api, second, "link_existing", customer.public_id)
    response = approve_link(api, second, customer.public_id, fingerprint)
    assert response.status_code == 409
    assert response.json()["field"] == "customer_public_id"
    see_committed_changes(account_db)
    assert account_db.query(CustomerIdentityLink).one().status == "active"
    assert _audit(account_db, "customer_account.unlink") == []


def test_a_deactivation_after_the_preview_makes_it_stale(
    account_client, account_db, account_users, captured_mail
):
    """The reviewer must have been shown the takeover; a preview without it does not do."""
    first, customer, admin = _linked_customer(
        account_client, account_db, account_users, captured_mail
    )
    second = pending_identity(account_client, captured_mail, SECOND)
    api = _operations(account_client, account_users)
    stale = preview(api, second, "link_existing", customer.public_id).json()["fingerprint"]

    admin = _admin(account_client, account_users)
    assert (
        admin.post(f"{IDENTITIES}/{first}/deactivate", json={"reason_code": "customer_request"})
    ).status_code == 200
    api = _operations(account_client, account_users)
    response = approve_link(api, second, customer.public_id, stale)
    assert response.status_code == 409
    see_committed_changes(account_db)
    assert account_db.query(CustomerIdentityLink).one().status == "active"
