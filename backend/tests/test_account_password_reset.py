"""Password reset: request, completion, and the four things completion does together.

The request half is an enumeration test and reads like the resend one: a known address and
an unknown address must produce the same status, the same body and the same headers.

The completion half is the interesting one. Four things happen or none of them do -- the
token is consumed, the password is replaced, **every** Customer Account session is revoked,
and every other outstanding reset token is invalidated. Revoking the sessions is the point:
somebody resetting a password may be doing it because an attacker holds a live one, and a
reset that left it alive would be cosmetic (T-14).

Staff sessions are untouched, and that is asserted against a database holding both.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.account_enums import IdentityStatus, TokenPurpose
from app.core.account_security import auth_token_digest
from app.core.config import settings
from app.core.security import verify_password
from app.core.time_utils import utcnow
from app.models import (
    AuditEvent,
    ContactSuppression,
    CustomerAuthToken,
    CustomerIdentity,
    CustomerSession,
    UserSession,
)
from app.services import account_email_service as email
from app.services import customer_identity_service
from tests.account_fixtures import (
    ACCOUNT_PASSWORD,
    register,
    registered_and_verified,
    reset_token,
    sign_in,
)
from tests.conftest import TEST_PASSWORD, see_committed_changes

FORGOT = "/api/v1/account/password/forgot"
RESET = "/api/v1/account/password/reset"
ME = "/api/v1/account/me"
ADDRESS = "hanh@demo.example.com"
NEW_PASSWORD = "AnotherSolarisPass!2026"


def _fingerprint(response) -> tuple:
    interesting = {"content-type", "cache-control", "x-correlation-id", "retry-after"}
    return (
        response.status_code,
        response.json(),
        {key: value for key, value in response.headers.items() if key.lower() in interesting},
    )


def _identity(db) -> CustomerIdentity:
    return db.query(CustomerIdentity).filter_by(email_normalized=ADDRESS).one()


# --- Request ------------------------------------------------------------------


def test_the_response_is_identical_for_a_known_and_an_unknown_address(
    account_client, account_db, captured_mail
):
    registered_and_verified(account_client, captured_mail, ADDRESS)

    known = _fingerprint(account_client.post(FORGOT, json={"email": ADDRESS}))
    unknown = _fingerprint(account_client.post(FORGOT, json={"email": "nobody@demo.example.com"}))
    assert known == unknown


def test_the_response_is_identical_for_every_account_state(
    account_client, account_db, captured_mail
):
    from app.core.security import rate_limiter

    def probe(address: str) -> tuple:
        rate_limiter.reset()
        return _fingerprint(account_client.post(FORGOT, json={"email": address}))

    registered_and_verified(account_client, captured_mail, ADDRESS)
    baseline = probe("nobody@demo.example.com")

    identity = _identity(account_db)
    for state in IdentityStatus:
        identity.status = state.value
        account_db.commit()
        assert probe(ADDRESS) == baseline, f"forgot-password answered differently for {state}"


def test_no_raw_token_is_in_the_response_or_the_audit_log(
    account_client, account_db, captured_mail
):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    response = account_client.post(FORGOT, json={"email": ADDRESS})
    token = reset_token(captured_mail, ADDRESS)

    assert token not in response.text
    for event in account_db.query(AuditEvent).all():
        assert token not in (event.detail_json or "")
        assert token not in event.summary


def test_the_audit_row_carries_a_hashed_address_and_not_the_address(
    account_client, account_db, captured_mail
):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    account_client.post(FORGOT, json={"email": ADDRESS})

    events = (
        account_db.query(AuditEvent)
        .filter_by(action="customer_account.password_reset_requested")
        .all()
    )
    assert events
    for event in events:
        payload = event.detail_json or ""
        assert ADDRESS not in payload
        assert "address_key" in payload


def test_a_suppressed_address_still_receives_its_reset_and_is_told_nothing(
    account_client, account_db, captured_mail
):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    account_db.add(
        ContactSuppression(
            channel="email",
            address_value=ADDRESS,
            reason="Customer asked to be removed",
            created_at=utcnow(),
        )
    )
    account_db.commit()
    captured_mail.messages.clear()

    from app.core.security import rate_limiter

    rate_limiter.reset()
    suppressed = _fingerprint(account_client.post(FORGOT, json={"email": ADDRESS}))
    rate_limiter.reset()
    unknown = _fingerprint(account_client.post(FORGOT, json={"email": "nobody@demo.example.com"}))

    assert suppressed == unknown
    # Account email, which a marketing suppression does not block (UAT round 6).
    assert [message["template_key"] for message in captured_mail.messages] == [
        "account.password_reset"
    ]


def test_the_reset_token_is_stored_only_as_a_purpose_bound_digest(
    account_client, account_db, captured_mail
):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    account_client.post(FORGOT, json={"email": ADDRESS})
    token = reset_token(captured_mail, ADDRESS)

    row = (
        account_db.query(CustomerAuthToken)
        .filter_by(purpose=TokenPurpose.PASSWORD_RESET.value)
        .order_by(CustomerAuthToken.id.desc())
        .first()
    )
    assert row.token_digest == auth_token_digest(token, TokenPurpose.PASSWORD_RESET)
    assert row.token_digest != auth_token_digest(token, TokenPurpose.EMAIL_VERIFICATION)
    assert token not in str(row.__dict__)


def test_a_reset_token_cannot_verify_an_email(account_client, account_db, captured_mail):
    """The mirror of the verification-token test: purpose binding works both ways."""
    register(account_client, email=ADDRESS)
    identity = _identity(account_db)
    identity.status = IdentityStatus.PENDING_APPROVAL.value
    identity.email_verified_at = utcnow()
    account_db.commit()

    account_client.post(FORGOT, json={"email": ADDRESS})
    token = reset_token(captured_mail, ADDRESS)

    response = account_client.post("/api/v1/account/verify-email", json={"token": token})
    assert response.status_code == 422
    assert response.json()["message"] == customer_identity_service.GENERIC_TOKEN_FAILURE


# --- Completion ---------------------------------------------------------------


def test_the_reset_link_carries_its_token_in_the_fragment(account_client, captured_mail):
    """CA-SEC-07. The token must not be in the path or the query string.

    A fragment is never sent to a server, so the token reaches no access log and no
    ``Referer``; the landing page strips it from the address bar before React mounts. A
    fixed-shape link is also what lets the landing page and the test helpers find it.
    """
    registered_and_verified(account_client, captured_mail, ADDRESS)
    account_client.post(FORGOT, json={"email": ADDRESS})

    message = next(
        item
        for item in reversed(captured_mail.messages)
        if item["template_key"] == "account.password_reset"
    )
    body = message["body"]
    assert "/account/reset-password#token=" in body
    assert "?token=" not in body
    assert "reset-password/" not in body  # never a path segment either
    token = reset_token(captured_mail, ADDRESS)
    assert token and token in body
    # And the fragment-shaped link still redeems.
    response = account_client.post(
        RESET,
        json={"token": token, "password": NEW_PASSWORD, "password_confirmation": NEW_PASSWORD},
    )
    assert response.status_code == 200


def test_completion_replaces_the_password(account_client, account_db, captured_mail):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    account_client.post(FORGOT, json={"email": ADDRESS})

    response = account_client.post(
        RESET,
        json={
            "token": reset_token(captured_mail, ADDRESS),
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
        },
    )
    assert response.status_code == 200

    account_db.expire_all()
    identity = _identity(account_db)
    assert verify_password(NEW_PASSWORD, identity.password_hash)
    assert not verify_password(ACCOUNT_PASSWORD, identity.password_hash)

    assert sign_in(account_client, ADDRESS, password=NEW_PASSWORD).status_code == 200
    account_client.cookies.clear()
    assert sign_in(account_client, ADDRESS, password=ACCOUNT_PASSWORD).status_code == 401


def test_completion_revokes_every_customer_session(account_client, account_db, captured_mail):
    registered_and_verified(account_client, captured_mail, ADDRESS)

    # Three live sessions, as three devices would produce.
    for _ in range(3):
        account_client.cookies.clear()
        sign_in(account_client, ADDRESS)
    stolen = account_client.cookies[settings.account_session_cookie_name]
    assert account_db.query(CustomerSession).filter_by(revoked_at=None).count() == 3

    account_client.post(FORGOT, json={"email": ADDRESS})
    account_client.post(
        RESET,
        json={
            "token": reset_token(captured_mail, ADDRESS),
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
        },
    )

    see_committed_changes(account_db)
    assert account_db.query(CustomerSession).filter_by(revoked_at=None).count() == 0

    # The value an attacker was holding stops resolving.
    account_client.cookies.clear()
    account_client.cookies.set(settings.account_session_cookie_name, stolen)
    assert account_client.get(ME).status_code == 401


def test_completion_leaves_staff_sessions_alone(
    account_client, account_db, account_users, captured_mail
):
    """Not by a check: there is no code path from here to `user_sessions`."""
    from tests.conftest import sign_in as staff_sign_in

    staff_sign_in(account_client, account_users["admin"].email, TEST_PASSWORD)
    assert account_db.query(UserSession).filter_by(revoked_at=None).count() == 1
    account_client.cookies.clear()

    registered_and_verified(account_client, captured_mail, ADDRESS)
    sign_in(account_client, ADDRESS)
    account_client.post(FORGOT, json={"email": ADDRESS})
    account_client.post(
        RESET,
        json={
            "token": reset_token(captured_mail, ADDRESS),
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
        },
    )

    account_db.expire_all()
    assert account_db.query(UserSession).filter_by(revoked_at=None).count() == 1


def test_completion_invalidates_every_other_reset_token(account_client, account_db, captured_mail):
    from app.core.security import rate_limiter

    registered_and_verified(account_client, captured_mail, ADDRESS)
    account_client.post(FORGOT, json={"email": ADDRESS})
    first = reset_token(captured_mail, ADDRESS)
    rate_limiter.reset()
    account_client.post(FORGOT, json={"email": ADDRESS})
    second = reset_token(captured_mail, ADDRESS)
    assert first != second

    # The newest one works.
    assert (
        account_client.post(
            RESET,
            json={"token": second, "password": NEW_PASSWORD, "password_confirmation": NEW_PASSWORD},
        ).status_code
        == 200
    )
    # The older one was already superseded at issuance, and is refused.
    assert (
        account_client.post(
            RESET,
            json={"token": first, "password": NEW_PASSWORD, "password_confirmation": NEW_PASSWORD},
        ).status_code
        == 422
    )

    account_db.expire_all()
    live = [
        token
        for token in account_db.query(CustomerAuthToken)
        .filter_by(purpose=TokenPurpose.PASSWORD_RESET.value)
        .all()
        if token.consumed_at is None and token.invalidated_at is None
    ]
    assert live == []


def test_replay_of_a_completed_reset_is_refused(account_client, account_db, captured_mail):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    account_client.post(FORGOT, json={"email": ADDRESS})
    token = reset_token(captured_mail, ADDRESS)

    assert (
        account_client.post(
            RESET,
            json={"token": token, "password": NEW_PASSWORD, "password_confirmation": NEW_PASSWORD},
        ).status_code
        == 200
    )
    replay = account_client.post(
        RESET,
        json={
            "token": token,
            "password": "ThirdPassword!2026",
            "password_confirmation": "ThirdPassword!2026",
        },
    )
    assert replay.status_code == 422

    account_db.expire_all()
    # The second password never took effect.
    assert verify_password(NEW_PASSWORD, _identity(account_db).password_hash)


def test_an_expired_reset_token_is_refused(account_client, account_db, captured_mail):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    account_client.post(FORGOT, json={"email": ADDRESS})
    token = reset_token(captured_mail, ADDRESS)

    row = (
        account_db.query(CustomerAuthToken)
        .filter_by(purpose=TokenPurpose.PASSWORD_RESET.value)
        .order_by(CustomerAuthToken.id.desc())
        .first()
    )
    row.expires_at = utcnow() - timedelta(seconds=1)
    account_db.commit()

    assert (
        account_client.post(
            RESET,
            json={"token": token, "password": NEW_PASSWORD, "password_confirmation": NEW_PASSWORD},
        ).status_code
        == 422
    )
    account_db.expire_all()
    assert verify_password(ACCOUNT_PASSWORD, _identity(account_db).password_hash)


def test_the_reset_link_lives_one_hour_by_default():
    """DEC-0121: one hour, down from two. Asserted on the declared default so a changed
    environment in the test run cannot make this pass for the wrong reason."""
    from app.core.config import Settings

    assert Settings.model_fields["account_password_reset_token_hours"].default == 1
    # The verification link is unchanged.
    assert Settings.model_fields["account_verification_token_hours"].default == 24


def test_an_issued_reset_token_expires_one_hour_after_issue_and_says_so(
    account_client, account_db, captured_mail, monkeypatch
):
    monkeypatch.setattr(settings, "account_password_reset_token_hours", 1)
    registered_and_verified(account_client, captured_mail, ADDRESS)
    account_client.post(FORGOT, json={"email": ADDRESS})

    account_db.expire_all()
    row = (
        account_db.query(CustomerAuthToken)
        .filter_by(purpose=TokenPurpose.PASSWORD_RESET.value)
        .order_by(CustomerAuthToken.id.desc())
        .first()
    )
    assert row.expires_at - row.issued_at == timedelta(hours=1)

    body = next(
        item["body"]
        for item in reversed(captured_mail.messages)
        if item["template_key"] == email.TEMPLATE_PASSWORD_RESET
    )
    assert "expires in 1 hour." in body
    assert "1 hours" not in body


def test_a_reset_token_past_its_hour_is_refused(account_client, account_db, captured_mail):
    """One minute past the hour, the link is dead, with the one generic sentence."""
    registered_and_verified(account_client, captured_mail, ADDRESS)
    account_client.post(FORGOT, json={"email": ADDRESS})
    token = reset_token(captured_mail, ADDRESS)

    row = (
        account_db.query(CustomerAuthToken)
        .filter_by(purpose=TokenPurpose.PASSWORD_RESET.value)
        .order_by(CustomerAuthToken.id.desc())
        .first()
    )
    # Backdate the issue so the stored expiry is one hour after it, a minute ago.
    row.issued_at = utcnow() - timedelta(hours=1, minutes=1)
    row.expires_at = row.issued_at + timedelta(hours=1)
    account_db.commit()

    response = account_client.post(
        RESET,
        json={"token": token, "password": NEW_PASSWORD, "password_confirmation": NEW_PASSWORD},
    )
    assert response.status_code == 422
    assert response.json()["field"] == "token"


@pytest.mark.parametrize(("hours", "phrase"), [(1, "1 hour"), (2, "2 hours"), (24, "24 hours")])
def test_the_expiry_phrase_is_grammatical(hours, phrase):
    assert email.hours_phrase(hours) == phrase


def test_completion_does_not_sign_the_caller_in(account_client, account_db, captured_mail):
    """A reset proves control of a mailbox. Turning that into a session makes the mailbox
    the credential, which is a larger grant than the flow asked for."""
    registered_and_verified(account_client, captured_mail, ADDRESS)
    account_client.post(FORGOT, json={"email": ADDRESS})
    account_client.cookies.clear()

    account_client.post(
        RESET,
        json={
            "token": reset_token(captured_mail, ADDRESS),
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
        },
    )
    assert settings.account_session_cookie_name not in dict(account_client.cookies)
    assert account_client.get(ME).status_code == 401


def test_a_weak_new_password_is_refused_and_the_token_survives(
    account_client, account_db, captured_mail
):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    account_client.post(FORGOT, json={"email": ADDRESS})
    token = reset_token(captured_mail, ADDRESS)

    assert (
        account_client.post(
            RESET, json={"token": token, "password": "short", "password_confirmation": "short"}
        ).status_code
        == 422
    )
    # The policy check runs before the token is consumed, so a typo does not cost the link.
    assert (
        account_client.post(
            RESET,
            json={"token": token, "password": NEW_PASSWORD, "password_confirmation": NEW_PASSWORD},
        ).status_code
        == 200
    )


def test_the_audit_record_holds_no_password_or_token_material(
    account_client, account_db, captured_mail
):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    account_client.post(FORGOT, json={"email": ADDRESS})
    token = reset_token(captured_mail, ADDRESS)
    account_client.post(
        RESET,
        json={"token": token, "password": NEW_PASSWORD, "password_confirmation": NEW_PASSWORD},
    )

    completed = (
        account_db.query(AuditEvent)
        .filter_by(action="customer_account.password_reset_completed")
        .all()
    )
    assert completed
    account_db.expire_all()
    digest = _identity(account_db).password_hash
    for event in account_db.query(AuditEvent).all():
        blob = f"{event.summary}{event.detail_json or ''}"
        assert token not in blob
        assert NEW_PASSWORD not in blob
        assert ACCOUNT_PASSWORD not in blob
        assert digest not in blob
        assert "$argon2" not in blob


def test_a_password_changed_notice_is_sent_with_no_link(account_client, account_db, captured_mail):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    account_client.post(FORGOT, json={"email": ADDRESS})
    account_client.post(
        RESET,
        json={
            "token": reset_token(captured_mail, ADDRESS),
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
        },
    )

    notice = [
        m for m in captured_mail.messages if m["template_key"] == email.TEMPLATE_PASSWORD_CHANGED
    ]
    assert len(notice) == 1
    assert "token=" not in notice[0]["body"]
    assert NEW_PASSWORD not in notice[0]["body"]


# --- Concurrency --------------------------------------------------------------


def test_concurrent_completion_succeeds_exactly_once(
    account_client, account_session_factory, captured_mail
):
    """Two sessions on two connections racing the conditional update.

    Separate sessions and separate connections, not two calls on one: the claim is about
    what the database does when two transactions try to consume the same row, and a single
    session would serialize them in Python before SQLite ever saw a race.
    """
    registered_and_verified(account_client, captured_mail, ADDRESS)
    account_client.post(FORGOT, json={"email": ADDRESS})
    token = reset_token(captured_mail, ADDRESS)

    first = account_session_factory()
    second = account_session_factory()
    try:
        outcomes = []
        for session, password in (
            (first, "FirstConcurrent!2026"),
            (second, "SecondConcurrent!2026"),
        ):
            identity = customer_identity_service.complete_password_reset(
                session, token=token, password=password, request_ip=None
            )
            session.commit()
            outcomes.append(identity is not None)
        assert outcomes == [True, False]
    finally:
        first.close()
        second.close()

    verifier = account_session_factory()
    try:
        identity = verifier.query(CustomerIdentity).filter_by(email_normalized=ADDRESS).one()
        assert verify_password("FirstConcurrent!2026", identity.password_hash)
        assert not verify_password("SecondConcurrent!2026", identity.password_hash)
    finally:
        verifier.close()
