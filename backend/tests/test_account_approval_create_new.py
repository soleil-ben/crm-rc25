"""Approving by creating a new canonical customer.

The claim under test is that this path produces a customer **indistinguishable from one a
staff member typed in** -- same services, same validation, same normalization, same
``public_id`` allocation, same audit -- and that it either produces all of it or none of
it.

The rollback tests are the ones that matter most, and they are done by making a real step
fail rather than by reasoning about the transaction: a customer, addresses, a consent
event, a proposal update, a link row and a status change are written in one transaction,
and the assertion is that a failure anywhere leaves the database exactly as it was.
"""

from __future__ import annotations

import pytest

from app.core.enums import ConsentStatus, Role
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
    approve_create,
    key,
    make_customer,
    pending_identity,
    staff,
)
from tests.conftest import see_committed_changes

APPLICANT = "hanh@demo.example.com"


def _operations(account_client, account_users):
    return staff(account_client, account_users[Role.OPERATIONS].email)


def _approve(account_client, account_users, reference, **extra):
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "create_new")
    return api, approve_create(api, reference, fingerprint, **extra)


def test_the_happy_path_creates_links_and_activates(
    account_client, account_db, account_users, captured_mail
):
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    _api, response = _approve(account_client, account_users, reference)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["status"] == "active"
    assert body["outcome"] == "approved_created"
    assert body["replayed"] is False
    assert body["customer_public_id"].startswith("STCA-")

    account_db.expire_all()
    customer = account_db.query(Customer).one()
    assert customer.full_name == "Nguyễn Thị Bích Hạnh"
    assert customer.legal_name == "Nguyễn Thị Bích Hạnh"
    assert customer.display_name == "Hạnh"
    assert customer.email_normalized == APPLICANT
    assert customer.phone_e164 == "+84901234567"
    assert customer.country_code == "VN"

    identity = account_db.query(CustomerIdentity).one()
    assert identity.status == "active"
    assert identity.approved_at is not None
    assert identity.approved_by_user_id is not None

    link = account_db.query(CustomerIdentityLink).one()
    assert link.status == "active"
    assert link.customer_id == customer.id
    assert link.link_role == "owner"


def test_the_addresses_land_with_the_roles_the_mapping_decided(
    account_client, account_db, account_users, captured_mail
):
    """One billing row and one sender row, from the registration fixture's two groups."""
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    _api, response = _approve(account_client, account_users, reference)
    assert response.status_code == 200

    account_db.expire_all()
    addresses = account_db.query(CustomerAddress).order_by(CustomerAddress.id).all()
    assert [address.role for address in addresses] == ["billing", "sender"]
    billing, sender = addresses
    assert billing.city == "Thành phố Hồ Chí Minh"
    assert billing.is_default_sender is False
    assert sender.city == "Mississauga"
    assert sender.is_default_sender is True
    assert sender.contact_name == "Tran Quoc Tuan"
    assert sender.country_code == "CA"


def test_the_proposal_is_approved_with_per_field_applied_flags(
    account_client, account_db, account_users, captured_mail
):
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    _api, response = _approve(account_client, account_users, reference)
    assert response.status_code == 200

    account_db.expire_all()
    proposal = account_db.query(CustomerDataProposal).one()
    assert proposal.status == "approved"
    assert proposal.reviewed_by_user_id is not None
    assert proposal.customer_id is not None
    applied = {row.field_key for row in proposal.fields if row.applied}
    assert "legal_name" in applied
    assert "billing_address.city" in applied
    assert "pickup_address.1.address_line1" in applied


def test_an_explicit_marketing_choice_becomes_one_consent_event(
    account_client, account_db, account_users, captured_mail
):
    """The registration fixture chooses marketing explicitly, so one row is written."""
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    _api, response = _approve(account_client, account_users, reference)
    assert response.status_code == 200

    account_db.expire_all()
    events = account_db.query(ConsentEvent).all()
    assert len(events) == 1
    assert events[0].status == ConsentStatus.CONSENTED
    assert events[0].address_value == APPLICANT


def test_terms_acknowledgement_is_never_converted_into_marketing_consent(
    account_client, account_db, account_users, captured_mail
):
    """An applicant who accepted the terms and declined marketing gets **no** consent row.

    The two are separate tables written at separate times, and the approval reads only the
    marketing field. Asserted against a registration that accepted the terms -- as every
    registration must (OD-37) -- and left marketing off.
    """
    from tests.account_fixtures import REQUIRED_ADDRESS, register, verification_token

    body_overrides = {
        "customer_type": "individual",
        "legal_name": "No Marketing Please",
        **REQUIRED_ADDRESS,
    }
    response = register(
        account_client,
        email="nomarketing@demo.example.com",
        customer=body_overrides,
        billing_same_as_shipping=True,
    )
    assert response.status_code == 200
    account_client.post(
        "/api/v1/account/verify-email",
        json={"token": verification_token(captured_mail, "nomarketing@demo.example.com")},
    )
    identity = (
        account_db.query(CustomerIdentity)
        .filter_by(email_normalized="nomarketing@demo.example.com")
        .one()
    )

    _api, approved = _approve(account_client, account_users, identity.public_id)
    assert approved.status_code == 200

    account_db.expire_all()
    assert account_db.query(ConsentEvent).count() == 0
    from app.models import CustomerTermsAcknowledgement

    assert account_db.query(CustomerTermsAcknowledgement).count() >= 2


def test_a_suppressed_address_gets_no_consent_row_and_the_approval_still_succeeds(
    account_client, account_db, account_users, captured_mail
):
    """A suppression wins over a consent grant, and does not fail the decision (T-08).

    Two things are being asserted at once, and both matter: the suppression stands, and
    the account is still approved. Failing the approval would let a suppression -- an
    operational block on *contacting* somebody -- silently become a block on their having
    an account.
    """
    from app.services import consent_service

    # Suppressed *after* verification, not before: a suppression in force at registration
    # stops the verification message being sent at all (Phase 9), so the applicant would
    # never reach `pending_approval` and there would be nothing to approve. The case worth
    # testing is the one where the suppression arrives while the application is waiting.
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    consent_service.add_suppression(
        account_db,
        channel="email",
        address_value=APPLICANT,
        reason="Recorded while the application was waiting",
    )
    account_db.commit()

    _api, response = _approve(account_client, account_users, reference)
    assert response.status_code == 200

    account_db.expire_all()
    assert account_db.query(ConsentEvent).count() == 0
    assert account_db.query(CustomerIdentity).one().status == "active"


def test_a_duplicate_candidate_blocks_creation_until_a_reason_is_given(
    account_client, account_db, account_users, captured_mail
):
    """OD-28: creating a separate record despite a match is a decision, not a default."""
    make_customer(account_db, full_name="Hanh Nguyen", email=APPLICANT)
    reference = pending_identity(account_client, captured_mail, APPLICANT)

    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "create_new")
    refused = approve_create(api, reference, fingerprint)
    assert refused.status_code == 409
    assert "override_reason_code" in refused.text

    account_db.expire_all()
    assert account_db.query(Customer).count() == 1  # only the pre-existing one
    assert account_db.query(CustomerIdentityLink).count() == 0

    allowed = approve_create(api, reference, fingerprint, override_reason_code="different_party")
    assert allowed.status_code == 200
    see_committed_changes(account_db)
    assert account_db.query(Customer).count() == 2


def test_an_override_reason_with_no_candidate_is_refused(
    account_client, account_users, captured_mail
):
    """A reason code for a decision nobody had to make is noise in an audit trail."""
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "create_new")
    response = approve_create(api, reference, fingerprint, override_reason_code="different_party")
    assert response.status_code == 422


def test_an_unverified_applicant_cannot_be_approved(account_client, account_db, account_users):
    """Verification is not approval, and approval without it is T-06 with the lock off."""
    from tests.account_fixtures import register

    register(account_client, email="unverified@demo.example.com")
    identity = (
        account_db.query(CustomerIdentity)
        .filter_by(email_normalized="unverified@demo.example.com")
        .one()
    )
    api = _operations(account_client, account_users)
    response = api.get(
        f"/api/v1/customer-account/registrations/{identity.public_id}/preview",
        params={"action": "create_new"},
    )
    # The preview is available; the approval is not.
    assert response.status_code == 200
    approve = approve_create(api, identity.public_id, response.json()["fingerprint"])
    assert approve.status_code == 409
    assert account_db.query(Customer).count() == 0


def test_approval_is_idempotent_on_retry(account_client, account_db, account_users, captured_mail):
    """AC-CA-4.5: one canonical change and one approval record, plus a replay record."""
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "create_new")
    shared = key()

    first = approve_create(api, reference, fingerprint, key=shared)
    assert first.status_code == 200
    assert first.json()["replayed"] is False

    second = approve_create(api, reference, fingerprint, key=shared)
    assert second.status_code == 200
    assert second.json()["replayed"] is True
    assert second.json()["customer_public_id"] == first.json()["customer_public_id"]

    account_db.expire_all()
    assert account_db.query(Customer).count() == 1
    assert account_db.query(CustomerIdentityLink).count() == 1
    assert account_db.query(CustomerAddress).count() == 2
    assert account_db.query(ConsentEvent).count() == 1
    approvals = account_db.query(AuditEvent).filter_by(action="customer_account.approve").count()
    assert approvals == 1
    replays = (
        account_db.query(AuditEvent).filter_by(action="customer_account.approval_replayed").count()
    )
    assert replays == 1


def test_a_replay_sends_no_second_message(account_client, account_db, account_users, captured_mail):
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "create_new")
    shared = key()

    approve_create(api, reference, fingerprint, key=shared)
    approved_messages = [
        message
        for message in captured_mail.messages
        if message["template_key"] == "account.approved"
    ]
    assert len(approved_messages) == 1

    approve_create(api, reference, fingerprint, key=shared)
    approved_messages = [
        message
        for message in captured_mail.messages
        if message["template_key"] == "account.approved"
    ]
    assert len(approved_messages) == 1


def test_the_same_key_with_a_different_action_is_a_conflict(
    account_client, account_db, account_users, captured_mail
):
    """One key, two decisions, is a mistake -- not something to resolve by guessing."""
    customer = make_customer(account_db, full_name="Other", email="other@demo.example.com")
    first = pending_identity(account_client, captured_mail, "first@demo.example.com")
    api = _operations(account_client, account_users)
    shared = key()

    create_fingerprint = acknowledged_preview(api, first, "create_new")
    assert approve_create(api, first, create_fingerprint, key=shared).status_code == 200

    second = pending_identity(account_client, captured_mail, "second@demo.example.com")
    api = _operations(account_client, account_users)
    link_fingerprint = acknowledged_preview(api, second, "link_existing", customer.public_id)

    from tests.approval_fixtures import approve_link

    response = approve_link(api, second, customer.public_id, link_fingerprint, key=shared)
    assert response.status_code == 409
    assert "idempotency" in response.text.lower()


@pytest.mark.parametrize(
    "failing_step",
    ["customer", "address", "consent", "link"],
)
def test_a_failure_at_any_step_leaves_nothing_behind(
    account_client, account_db, account_users, captured_mail, monkeypatch, failing_step
):
    """AC-CA-4.4, one induced failure at a time.

    Each parameter breaks a different write in the middle of the transaction. The
    assertion is the same every time and is made over the whole database: no customer, no
    address, no consent event, no link, no active identity, and a proposal still pending.
    """
    from app.services import (
        consent_service,
        customer_account_approval_service,
        customer_address_service,
        customer_service,
    )

    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "create_new")

    def boom(*_args, **_kwargs):
        raise RuntimeError("induced failure")

    targets = {
        "customer": (customer_service, "create_customer"),
        "address": (customer_address_service, "create_address"),
        "consent": (consent_service, "record_consent_event"),
        "link": (customer_account_approval_service, "_link"),
    }
    module, name = targets[failing_step]
    monkeypatch.setattr(module, name, boom)

    with pytest.raises(RuntimeError):
        approve_create(api, reference, fingerprint)

    account_db.expire_all()
    assert account_db.query(Customer).count() == 0
    assert account_db.query(CustomerAddress).count() == 0
    assert account_db.query(ConsentEvent).count() == 0
    assert account_db.query(CustomerIdentityLink).count() == 0
    identity = account_db.query(CustomerIdentity).one()
    assert identity.status == "pending_approval"
    assert identity.approved_at is None
    assert account_db.query(CustomerDataProposal).one().status == "pending"
