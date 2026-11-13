"""Declining an application.

Rejection has to do two things well and one thing carefully.

Well: **stop the credential working**, now rather than at the next sign-in, and **write
nothing canonical**. Those are asserted directly -- a live session captured before the
rejection stops resolving on the next request, an outstanding reset link stops redeeming,
and every canonical table is unchanged.

Carefully: **say nothing**. The customer learns that the account cannot be used and
nothing else. No reason code, no mention of a duplicate, no hint that another customer
record exists -- which is `STATE_MACHINES.md` section 1 transition 5, and is the reason a
rejection message exists at all rather than silence.
"""

from __future__ import annotations

import json

from app.core.config import settings
from app.core.enums import Role
from app.models import (
    AuditEvent,
    ConsentEvent,
    Customer,
    CustomerAddress,
    CustomerAuthToken,
    CustomerDataProposal,
    CustomerIdentity,
    CustomerIdentityLink,
    CustomerSession,
)
from tests.account_fixtures import csrf_headers, reset_token, sign_in
from tests.approval_fixtures import key, pending_identity, reject, staff

APPLICANT = "hanh@demo.example.com"


def _operations(account_client, account_users):
    return staff(account_client, account_users[Role.OPERATIONS].email)


def test_rejection_moves_the_identity_and_writes_no_customer(
    account_client, account_db, account_users, captured_mail
):
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)

    response = reject(api, reference, "identity_not_established")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "rejected"
    assert response.json()["customer_public_id"] is None

    account_db.expire_all()
    identity = account_db.query(CustomerIdentity).one()
    assert identity.status == "rejected"
    assert identity.rejected_at is not None
    assert identity.rejected_by_user_id is not None
    assert identity.status_reason_code == "identity_not_established"

    assert account_db.query(Customer).count() == 0
    assert account_db.query(CustomerAddress).count() == 0
    assert account_db.query(ConsentEvent).count() == 0
    assert account_db.query(CustomerIdentityLink).count() == 0
    assert account_db.query(CustomerDataProposal).one().status == "rejected"


def test_a_reason_code_outside_the_vocabulary_is_refused(
    account_client, account_db, account_users, captured_mail
):
    """Bounded, because a sentence about a person ends up where other people read it."""
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)

    response = reject(api, reference, "they seemed suspicious to me")
    assert response.status_code == 422
    account_db.expire_all()
    assert account_db.query(CustomerIdentity).one().status == "pending_approval"


def test_rejection_revokes_a_live_session_on_the_next_request(
    account_client, account_db, account_users, captured_mail
):
    """Not at the next sign-in. The session row holds no cached grant, so revoking it is
    enough and it takes effect immediately (T-14)."""
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    signed_in = sign_in(account_client, APPLICANT)
    assert signed_in.status_code == 200
    assert account_client.get("/api/v1/account/me").status_code == 200

    api = _operations(account_client, account_users)
    assert reject(api, reference).status_code == 200

    # The customer's cookie is still in the jar; the row behind it is revoked.
    account_client.cookies.clear()
    account_client.cookies.set(
        settings.account_session_cookie_name,
        signed_in.cookies.get(settings.account_session_cookie_name),
    )
    assert account_client.get("/api/v1/account/me").status_code == 401

    account_db.expire_all()
    assert all(row.revoked_at is not None for row in account_db.query(CustomerSession).all())


def test_rejection_invalidates_an_outstanding_reset_link(
    account_client, account_db, account_users, captured_mail
):
    """Either token would otherwise be a way back into a declined account."""
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    account_client.post("/api/v1/account/password/forgot", json={"email": APPLICANT})
    token = reset_token(captured_mail, APPLICANT)

    api = _operations(account_client, account_users)
    assert reject(api, reference).status_code == 200

    account_client.cookies.clear()
    used = account_client.post(
        "/api/v1/account/password/reset",
        json={
            "token": token,
            "password": "AnotherPassword!2026",
            "password_confirmation": "AnotherPassword!2026",
        },
    )
    assert used.status_code >= 400

    account_db.expire_all()
    outstanding = [
        row
        for row in account_db.query(CustomerAuthToken).all()
        if row.consumed_at is None and row.invalidated_at is None
    ]
    assert outstanding == []


def test_a_rejected_applicant_cannot_sign_in_and_is_told_nothing(
    account_client, account_db, account_users, captured_mail
):
    """The refusal is the generic one -- identical to a wrong password (`STATE_MACHINES.md`
    section 7)."""
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    reject(api, reference, "duplicate_application")

    account_client.cookies.clear()
    rejected = sign_in(account_client, APPLICANT)
    wrong_password = account_client.post(
        "/api/v1/account/sign-in",
        json={"email": APPLICANT, "password": "DefinitelyNotTheRightOne!2026"},
    )
    assert rejected.status_code == wrong_password.status_code
    assert rejected.json() == wrong_password.json()
    assert "duplicate" not in rejected.text.lower()
    assert "reject" not in rejected.text.lower()


def test_the_rejection_notice_names_no_reason_and_no_other_record(
    account_client, account_users, captured_mail
):
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    reject(api, reference, "duplicate_application")

    notices = [
        message
        for message in captured_mail.messages
        if message["template_key"] == "account.rejected"
    ]
    assert len(notices) == 1
    body = notices[0]["body"].lower()
    # The reason code, the duplicate result, the actor and any customer reference.
    for forbidden in ("duplicate", "reason", "cus-", "ca-", "operations", "admin"):
        assert forbidden not in body, forbidden
    # No count and no reference. The template does point at Public Tracking, which is
    # customer-safe help and discloses nothing: it names no shipment and no number.
    assert "sx-" not in body
    assert not any(character.isdigit() for character in body)
    assert "http" not in body


def test_the_rejection_audit_row_carries_a_code_and_two_counts(
    account_client, account_db, account_users, captured_mail
):
    """No prose, no address, no token. A code, and what the rejection actually did."""
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    sign_in(account_client, APPLICANT)
    api = _operations(account_client, account_users)
    reject(api, reference, "abuse_or_test", internal_detail="A note the reviewer typed")

    account_db.expire_all()
    event = account_db.query(AuditEvent).filter_by(action="customer_account.reject").one()
    detail = json.loads(event.detail_json)
    assert detail["reason_code"] == "abuse_or_test"
    assert detail["sessions_revoked"] >= 1
    assert detail["tokens_invalidated"] >= 0
    assert event.actor_user_id is not None
    # The optional internal note is validated and discarded; it reaches no row.
    assert "A note the reviewer typed" not in (event.detail_json or "")
    assert "A note the reviewer typed" not in (event.summary or "")


def test_an_over_long_internal_note_is_refused(account_client, account_users, captured_mail):
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    response = reject(api, reference, internal_detail="x" * 501)
    assert response.status_code == 422


def test_rejection_is_idempotent_on_retry(account_client, account_db, account_users, captured_mail):
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    shared = key()

    first = reject(api, reference, key=shared)
    assert first.status_code == 200
    second = reject(api, reference, key=shared)
    assert second.status_code == 200
    assert second.json()["replayed"] is True

    account_db.expire_all()
    assert account_db.query(AuditEvent).filter_by(action="customer_account.reject").count() == 1
    notices = [
        message
        for message in captured_mail.messages
        if message["template_key"] == "account.rejected"
    ]
    assert len(notices) == 1


def test_re_registration_after_rejection_creates_nothing_and_says_nothing(
    account_client, account_db, account_users, captured_mail
):
    """`STATE_MACHINES.md` section 1: the identity row persists and the address is unique.

    So a second registration with the same address behaves exactly like any other
    already-registered address -- nothing is created, the response is the generic one.
    The documented way back is transition 9, **Admin reinstatement**, which this phase's
    scope does not include and which is recorded as a deferral rather than as a ban.
    """
    from tests.account_fixtures import register

    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    reject(api, reference)

    account_db.expire_all()
    identities_before = account_db.query(CustomerIdentity).count()
    proposals_before = account_db.query(CustomerDataProposal).count()

    account_client.cookies.clear()
    again = register(account_client, email=APPLICANT)
    assert again.status_code == 200

    account_db.expire_all()
    assert account_db.query(CustomerIdentity).count() == identities_before
    assert account_db.query(CustomerDataProposal).count() == proposals_before
    assert account_db.query(CustomerIdentity).one().status == "rejected"


def test_a_rejected_application_leaves_the_queue(account_client, account_users, captured_mail):
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    assert api.get("/api/v1/customer-account/registrations").json()["total"] == 1

    reject(api, reference)
    assert api.get("/api/v1/customer-account/registrations").json()["total"] == 0


def test_admin_may_also_reject(account_client, account_users, captured_mail):
    """OD-24: Operations performs approval, Admin may act as an override."""
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    admin = staff(account_client, account_users[Role.ADMIN].email)
    response = reject(admin, reference)
    assert response.status_code == 200
    assert csrf_headers  # the customer realm's helper is not what a staff call uses
