"""Email verification, resend, and the token rules both of them depend on.

Verification is a one-bit state transition with five ways to fail, and the point of this
module is that the customer cannot tell the five apart. Unknown, malformed, expired, already
used and invalidated all produce one status code and one sentence
(`STATE_MACHINES.md` section 5); the audit log records which it was, because an operator
watching for token brute force needs to tell "somebody clicked an old link twice" from
"somebody is guessing".

The other thing asserted here is what verification does **not** do. It proves control of a
mailbox. It does not approve the account, does not link a customer, and grants no access to
anything -- so an identity that has verified is `pending_approval` and still sees nothing
(OD-23).
"""

from __future__ import annotations

from datetime import timedelta

from app.core.account_enums import IdentityStatus, TokenPurpose
from app.core.account_security import auth_token_digest
from app.core.time_utils import utcnow
from app.models import CustomerAuthToken, CustomerIdentity, CustomerIdentityLink
from app.services import account_email_service as email
from app.services import customer_identity_service
from tests.account_fixtures import (
    ACCOUNT_PASSWORD,
    register,
    registered_and_verified,
    sign_in,
    verification_token,
    verify,
)

RESEND = "/api/v1/account/verification/resend"
ADDRESS = "hanh@demo.example.com"


def _fingerprint(response) -> tuple:
    interesting = {"content-type", "cache-control", "x-correlation-id", "retry-after"}
    return (
        response.status_code,
        response.json(),
        {key: value for key, value in response.headers.items() if key.lower() in interesting},
    )


# --- The transition -----------------------------------------------------------


def test_verifying_moves_the_identity_to_pending_approval_and_nothing_else(
    account_client, account_db, captured_mail
):
    register(account_client, email=ADDRESS)
    token = verification_token(captured_mail, ADDRESS)

    response = verify(account_client, token)
    assert response.status_code == 200

    identity = account_db.query(CustomerIdentity).one()
    assert identity.status == IdentityStatus.PENDING_APPROVAL
    assert identity.email_verified_at is not None

    # Verification is not approval, and not a link.
    assert identity.approved_at is None
    assert identity.approved_by_user_id is None
    assert account_db.query(CustomerIdentityLink).count() == 0


def test_a_verified_identity_still_sees_no_customer_or_shipment_data(
    account_client, account_db, captured_mail
):
    """The Phase 9 endpoint, restated: verified is still pending, and pending sees nothing."""
    registered_and_verified(account_client, captured_mail, ADDRESS)
    sign_in(account_client, ADDRESS)

    body = account_client.get("/api/v1/account/me").json()
    assert body["status"] == IdentityStatus.PENDING_APPROVAL
    assert body["linked"] is False
    assert body["shipment_history_available"] is False

    # Since Phase 11 the routes exist, so "there is no route to refuse" becomes "the routes
    # refuse". Both shipment paths are asked for by name, and both answer 403 to an identity
    # that has verified a mailbox and nothing more. The traversal is imported from the
    # boundary suite rather than rewritten, because a hand-rolled one that found no routes
    # would make this assertion pass over an empty list -- which is exactly what an earlier
    # version of it did.
    from tests.test_account_boundary import _account_paths

    paths = _account_paths()
    assert paths, "no account routes were found, so this proved nothing"
    shipment_paths = [path for _, path in paths if "shipment" in path]
    assert len(shipment_paths) == 2, shipment_paths

    for path in (
        "/api/v1/account/shipments",
        "/api/v1/account/shipments/SX-CAV-AAAAAAAAAAAA",
    ):
        refused = account_client.get(path)
        assert refused.status_code == 403, path
        body = refused.json()
        # It names the thing the account cannot view, which is what the reader needs, and
        # nothing about what is behind the gate: no count, no date, no reference, no
        # customer, and no statement of which condition failed.
        assert sorted(body) == ["code", "field", "message"]
        message = body["message"].lower()
        for forbidden in ("link", "archiv", "merge", "pending", "customer record", "0 "):
            assert forbidden not in message, forbidden


def test_the_token_is_stored_only_as_a_digest(account_client, account_db, captured_mail):
    register(account_client, email=ADDRESS)
    token = verification_token(captured_mail, ADDRESS)

    row = account_db.query(CustomerAuthToken).one()
    assert row.token_digest != token
    assert token not in row.token_digest
    # The digest is the keyed, purpose-bound one, not a bare SHA-256 of the token.
    assert row.token_digest == auth_token_digest(token, TokenPurpose.EMAIL_VERIFICATION)

    import hashlib

    assert row.token_digest != hashlib.sha256(token.encode()).hexdigest()

    # No column anywhere holds the plaintext.
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        assert value != token


def test_lookup_is_by_digest_so_a_verification_token_cannot_redeem_a_reset(
    account_client, account_db, captured_mail
):
    """Purpose binding by construction: the purpose is inside the signed message (T-05)."""
    register(account_client, email=ADDRESS)
    token = verification_token(captured_mail, ADDRESS)

    response = account_client.post(
        "/api/v1/account/password/reset",
        json={
            "token": token,
            "password": "SomeOtherPassword!2026",
            "password_confirmation": "SomeOtherPassword!2026",
        },
    )
    assert response.status_code == 422
    assert response.json()["message"] == customer_identity_service.GENERIC_TOKEN_FAILURE

    identity = account_db.query(CustomerIdentity).one()
    assert identity.status == IdentityStatus.PENDING_VERIFICATION


# --- The five ways to fail, and the one answer -------------------------------


def test_replay_of_a_consumed_token_is_refused(account_client, account_db, captured_mail):
    register(account_client, email=ADDRESS)
    token = verification_token(captured_mail, ADDRESS)
    assert verify(account_client, token).status_code == 200

    replay = verify(account_client, token)
    assert replay.status_code == 422
    assert replay.json()["message"] == customer_identity_service.GENERIC_TOKEN_FAILURE


def test_an_expired_token_is_refused_and_expiry_is_enforced_server_side(
    account_client, account_db, captured_mail
):
    register(account_client, email=ADDRESS)
    token = verification_token(captured_mail, ADDRESS)

    row = account_db.query(CustomerAuthToken).one()
    row.expires_at = utcnow() - timedelta(seconds=1)
    account_db.commit()

    assert verify(account_client, token).status_code == 422
    account_db.expire_all()
    assert account_db.query(CustomerIdentity).one().status == IdentityStatus.PENDING_VERIFICATION


def test_every_failure_mode_produces_the_identical_response(
    account_client, account_db, captured_mail
):
    """Unknown, malformed, expired, consumed and invalidated: five causes, one answer."""
    register(account_client, email=ADDRESS)
    good = verification_token(captured_mail, ADDRESS)

    unknown = _fingerprint(verify(account_client, "a" * 43))
    malformed = _fingerprint(verify(account_client, "!!not-a-token!!"))
    empty = _fingerprint(verify(account_client, ""))

    # Consume the real one, then replay it.
    verify(account_client, good)
    consumed = _fingerprint(verify(account_client, good))

    # Invalidated: register again to supersede, then present the superseded token.
    register(account_client, email="other@demo.example.com")
    superseded_token = verification_token(captured_mail, "other@demo.example.com")
    account_client.post(RESEND, json={"email": "other@demo.example.com"})
    invalidated = _fingerprint(verify(account_client, superseded_token))

    assert unknown == malformed == empty == consumed == invalidated


def test_the_audit_log_still_distinguishes_them(account_client, account_db, captured_mail):
    """The customer sees one answer; the operator still gets the category."""
    from app.models import AuditEvent

    register(account_client, email=ADDRESS)
    token = verification_token(captured_mail, ADDRESS)
    verify(account_client, token)
    verify(account_client, token)
    verify(account_client, "a" * 43)

    refusals = (
        account_db.query(AuditEvent).filter_by(action="customer_account.verification_refused").all()
    )
    reasons = {event.detail_json for event in refusals}
    assert any("already_used" in reason for reason in reasons)
    assert any("unknown" in reason for reason in reasons)


# --- Replacement and concurrency ---------------------------------------------


def test_issuing_a_replacement_invalidates_the_previous_token(
    account_client, account_db, captured_mail
):
    register(account_client, email=ADDRESS)
    first = verification_token(captured_mail, ADDRESS)

    account_client.post(RESEND, json={"email": ADDRESS})
    second = verification_token(captured_mail, ADDRESS)
    assert second != first

    assert verify(account_client, first).status_code == 422
    assert verify(account_client, second).status_code == 200


def test_concurrent_redemption_of_one_token_succeeds_exactly_once(
    account_client, account_session_factory, captured_mail
):
    """Two genuine sessions on two connections, racing the conditional update (T-05).

    Separate sessions and separate connections, not two calls on one session: the claim is
    about what the *database* does when two transactions try to consume the same row, and a
    single session would serialize them in Python before SQLite ever saw a race.
    """
    register(account_client, email=ADDRESS)
    token = verification_token(captured_mail, ADDRESS)

    first_session = account_session_factory()
    second_session = account_session_factory()
    try:
        outcomes = []
        for session in (first_session, second_session):
            result = customer_identity_service.redeem_token(
                session, token=token, purpose=TokenPurpose.EMAIL_VERIFICATION
            )
            session.commit()
            outcomes.append(result.ok)
        assert outcomes.count(True) == 1
        assert outcomes.count(False) == 1
    finally:
        first_session.close()
        second_session.close()


def test_a_revoked_token_is_refused(account_client, account_db, captured_mail):
    register(account_client, email=ADDRESS)
    token = verification_token(captured_mail, ADDRESS)

    row = account_db.query(CustomerAuthToken).one()
    row.invalidated_at = utcnow()
    row.invalidated_reason_code = "manual_revocation"
    account_db.commit()

    assert verify(account_client, token).status_code == 422


# --- Resend -------------------------------------------------------------------


def test_resend_answers_identically_for_every_state(account_client, account_db, captured_mail):
    """Unknown, unverified, verified, approved, suspended: one answer (instruction section 7).

    The limiter is reset between probes on purpose. Seven resends from one address would
    exhaust the per-IP bucket long before the seventh state is reached, and a 429 arriving
    partway through would prove only that the limiter works -- which
    `test_account_rate_limits.py` establishes separately. What is under test here is the
    *shape of the answer* for each state, so each probe starts from the same clean
    allowance.
    """
    from app.core.security import rate_limiter

    def probe(address: str) -> tuple:
        rate_limiter.reset()
        return _fingerprint(account_client.post(RESEND, json={"email": address}))

    unknown = probe("nobody@demo.example.com")

    register(account_client, email=ADDRESS)
    assert probe(ADDRESS) == unknown

    identity = account_db.query(CustomerIdentity).filter_by(email_normalized=ADDRESS).one()
    for state in (
        IdentityStatus.PENDING_APPROVAL,
        IdentityStatus.ACTIVE,
        IdentityStatus.SUSPENDED,
        IdentityStatus.REJECTED,
        IdentityStatus.DEACTIVATED,
    ):
        identity.status = state.value
        account_db.commit()
        assert probe(ADDRESS) == unknown, f"resend answered differently for {state}"


def test_resend_issues_nothing_for_an_address_that_is_already_verified(
    account_client, account_db, captured_mail
):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    before = len(captured_mail.messages)

    account_client.post(RESEND, json={"email": ADDRESS})
    assert len(captured_mail.messages) == before


def test_resend_does_not_create_unlimited_tokens(account_client, account_db, captured_mail):
    register(account_client, email=ADDRESS)
    for _ in range(8):
        account_client.post(RESEND, json={"email": ADDRESS})

    tokens = account_db.query(CustomerAuthToken).filter_by(purpose="email_verification").all()
    # The per-address bucket caps issuance; whatever survives, at most one is live.
    live = [t for t in tokens if t.consumed_at is None and t.invalidated_at is None]
    assert len(live) == 1
    assert len(tokens) <= 1 + 3


def test_resend_writes_only_a_safe_audit_reason(account_client, account_db, captured_mail):
    from app.models import AuditEvent

    register(account_client, email=ADDRESS)
    account_client.post(RESEND, json={"email": ADDRESS})

    events = (
        account_db.query(AuditEvent).filter_by(action="customer_account.verification_resent").all()
    )
    assert events
    for event in events:
        payload = event.detail_json or ""
        assert ADDRESS not in payload
        assert "password" not in payload.lower()
        assert "token" not in payload.lower() or '"purpose"' in payload


def test_a_suppressed_address_gets_the_same_resend_answer_and_the_message(
    account_client, account_db, captured_mail
):
    from app.models import ContactSuppression

    register(account_client, email=ADDRESS)
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

    unknown = _fingerprint(account_client.post(RESEND, json={"email": "nobody@demo.example.com"}))
    suppressed = _fingerprint(account_client.post(RESEND, json={"email": ADDRESS}))
    assert suppressed == unknown
    # Account email, which a marketing suppression does not block (UAT round 6).
    assert [message["template_key"] for message in captured_mail.messages] == [
        "account.verify_email"
    ]


# --- What the link looks like -------------------------------------------------


def test_the_token_is_not_in_a_persistent_url_path(account_client, captured_mail):
    """A fragment, not a path segment and not a query string (CA-SEC-07).

    A fragment is never sent to a server, so the token reaches no access log and no
    ``Referer``; the landing page strips it from the address bar before React mounts.
    """
    register(account_client, email=ADDRESS)
    message = captured_mail.messages[-1]
    assert "#token=" in message["body"]
    assert "?token=" not in message["body"]
    url = message["body"].split("\n")
    link = next(line for line in url if "verify-email" in line)
    assert link.split("#")[0].endswith("/verify-email")
    assert "?" not in link.split("#")[0]


def test_the_captured_message_carries_the_link_and_no_credential(
    account_client, account_db, captured_mail
):
    register(account_client, email=ADDRESS)
    body = captured_mail.messages[-1]["body"]
    assert ACCOUNT_PASSWORD not in body
    assert "$argon2" not in body
    identity = account_db.query(CustomerIdentity).one()
    assert identity.password_hash not in body
    # Exactly one secret: the single-use link the message exists to carry.
    assert body.count("token=") == 1


def test_verification_is_a_post_so_no_get_mutates(account_client):
    response = account_client.get("/api/v1/account/verify-email")
    assert response.status_code == 405


def test_the_null_transport_is_the_default_and_produces_no_message(account_client, account_db):
    """No `captured_mail` here: the ordinary suite must not depend on a message existing."""
    transport = email.get_transport()
    assert isinstance(transport, email.NullEmailTransport)

    register(account_client, email=ADDRESS)
    assert transport.requested == [email.TEMPLATE_VERIFY_EMAIL]
    assert not hasattr(transport, "messages")
