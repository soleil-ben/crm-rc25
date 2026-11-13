"""Sprint 13 Lane A, A-1: the suspend and reinstate routes (fix pack of 2026-10-14).

The service functions existed since Phase 9 with no route reaching them
(`docs/DECISION_REGISTER.md` finding A8). These tests cover the routes: who may call them,
what they do to sessions and sign-in, what the audit log records, and what they refuse.
"""

from __future__ import annotations

from app.core.config import settings
from app.core.enums import Role
from app.models import AuditEvent, CustomerIdentity
from tests.account_fixtures import sign_in
from tests.approval_fixtures import (
    acknowledged_preview,
    approve_create,
    pending_identity,
    staff,
)
from tests.conftest import see_committed_changes

IDENTITIES = "/api/v1/customer-account/identities"
APPLICANT = "hanh@demo.example.com"


def _identity(db) -> CustomerIdentity:
    see_committed_changes(db)
    return db.query(CustomerIdentity).filter_by(email_normalized=APPLICANT).one()


def _activated(account_client, account_users, captured_mail) -> str:
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    fingerprint = acknowledged_preview(api, reference, "create_new")
    assert approve_create(api, reference, fingerprint).status_code == 200
    account_client.cookies.clear()
    return reference


def test_the_status_read_reports_the_state_and_the_linked_customer(
    account_client, account_db, account_users, captured_mail
):
    reference = _activated(account_client, account_users, captured_mail)
    api = staff(account_client, account_users[Role.OPERATIONS].email)

    response = api.get(f"{IDENTITIES}/{reference}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "active"
    assert body["linked_customer_public_id"].startswith("STCA-")
    assert body["can_suspend"] is True
    assert body["can_reinstate"] is False
    assert body["email_verified"] is True
    # No proposal field, no password material, no shipment anything.
    assert "fields" not in body
    assert "password" not in response.text.lower()
    # The read is audited.
    see_committed_changes(account_db)
    assert (
        account_db.query(AuditEvent).filter_by(action="customer_account.status_read").count() == 1
    )


def test_suspension_ends_live_sessions_and_refuses_sign_in_indistinguishably(
    account_client, account_db, account_users, captured_mail
):
    reference = _activated(account_client, account_users, captured_mail)

    # A live customer session, then a staff suspension.
    signed_in = sign_in(account_client, APPLICANT)
    assert signed_in.status_code == 200
    customer_cookie = account_client.cookies[settings.account_session_cookie_name]
    account_client.cookies.clear()

    api = staff(account_client, account_users[Role.ADMIN].email)
    response = api.post(f"{IDENTITIES}/{reference}/suspend", json={"reason_code": "staff_review"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "suspended"
    assert response.json()["can_reinstate"] is True
    assert response.json()["can_suspend"] is False
    assert _identity(account_db).status == "suspended"
    assert _identity(account_db).suspended_by_user_id == account_users[Role.ADMIN].id

    # The session that was live is dead on its next request.
    account_client.cookies.clear()
    account_client.cookies.set(settings.account_session_cookie_name, customer_cookie)
    assert account_client.get("/api/v1/account/me").status_code == 401

    # And sign-in is refused with the same answer a wrong password gets.
    account_client.cookies.clear()
    refused = sign_in(account_client, APPLICANT)
    wrong = sign_in(account_client, APPLICANT, password="not-the-password-2026")
    assert refused.status_code == wrong.status_code == 401
    assert refused.json() == wrong.json()

    see_committed_changes(account_db)
    row = account_db.query(AuditEvent).filter_by(action="customer_account.suspend").one()
    assert row.actor_user_id == account_users[Role.ADMIN].id
    assert "staff_review" in str(row.detail_json)


def test_reinstating_a_linked_account_returns_it_to_active(
    account_client, account_db, account_users, captured_mail
):
    reference = _activated(account_client, account_users, captured_mail)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    api.post(f"{IDENTITIES}/{reference}/suspend", json={"reason_code": "customer_request"})

    response = api.post(
        f"{IDENTITIES}/{reference}/reinstate", json={"reason_code": "review_complete"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"
    assert response.json()["suspended_at"] is None
    account_client.cookies.clear()
    assert sign_in(account_client, APPLICANT).status_code == 200
    see_committed_changes(account_db)
    assert account_db.query(AuditEvent).filter_by(action="customer_account.reinstate").count() == 1


def test_reinstating_an_unlinked_account_returns_it_to_review_not_to_active(
    account_client, account_db, account_users, captured_mail
):
    """Transition 7: never a second door into ``active``."""
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    assert (
        api.post(
            f"{IDENTITIES}/{reference}/suspend", json={"reason_code": "abuse_or_test"}
        ).status_code
        == 200
    )

    response = api.post(
        f"{IDENTITIES}/{reference}/reinstate", json={"reason_code": "suspended_in_error"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "pending_approval"


def test_the_wrong_state_is_refused_with_a_409_and_writes_nothing(
    account_client, account_db, account_users, captured_mail
):
    reference = _activated(account_client, account_users, captured_mail)
    api = staff(account_client, account_users[Role.OPERATIONS].email)

    # Not suspended, so nothing to reinstate.
    refused = api.post(
        f"{IDENTITIES}/{reference}/reinstate", json={"reason_code": "review_complete"}
    )
    assert refused.status_code == 409
    assert _identity(account_db).status == "active"

    api.post(f"{IDENTITIES}/{reference}/suspend", json={"reason_code": "staff_review"})
    again = api.post(f"{IDENTITIES}/{reference}/suspend", json={"reason_code": "staff_review"})
    assert again.status_code == 409
    see_committed_changes(account_db)
    assert account_db.query(AuditEvent).filter_by(action="customer_account.suspend").count() == 1


def test_an_unlisted_reason_code_is_refused_by_name(
    account_client, account_db, account_users, captured_mail
):
    reference = _activated(account_client, account_users, captured_mail)
    api = staff(account_client, account_users[Role.OPERATIONS].email)

    response = api.post(
        f"{IDENTITIES}/{reference}/suspend", json={"reason_code": "because I said so"}
    )

    assert response.status_code == 422
    assert response.json()["field"] == "reason_code"
    assert _identity(account_db).status == "active"


def test_an_unknown_reference_is_a_plain_not_found(account_client, account_users):
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    assert api.get(f"{IDENTITIES}/CA-000000").status_code == 404
    assert (
        api.post(
            f"{IDENTITIES}/CA-000000/suspend", json={"reason_code": "staff_review"}
        ).status_code
        == 404
    )


def test_marketing_and_the_manager_cannot_suspend_anyone(
    account_client, account_db, account_users, captured_mail
):
    reference = _activated(account_client, account_users, captured_mail)
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        api = staff(account_client, account_users[role].email)
        assert api.get(f"{IDENTITIES}/{reference}").status_code == 403
        assert (
            api.post(
                f"{IDENTITIES}/{reference}/suspend", json={"reason_code": "staff_review"}
            ).status_code
            == 403
        )
    assert _identity(account_db).status == "active"
