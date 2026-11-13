"""Sign-in, sessions, CSRF, and the isolation between the three realms.

The isolation tests are the reason this module and `conftest`'s `account_client` install all
three dependency overrides against one database. "A staff cookie authenticates nothing on a
customer route" is only worth asserting if both surfaces are genuinely reachable and
genuinely backed by the same data; against separate databases it would pass for the wrong
reason.

What is asserted, in order: that a refusal is one sentence whatever caused it; that a
session rotates, revokes and expires; that the two cookie realms cannot reach each other;
and that a suspension takes effect on the **next request** rather than at the next sign-in,
because the session row holds no cached grant.
"""

from __future__ import annotations

import contextlib
from datetime import timedelta

from app.core.account_enums import IdentityStatus
from app.core.config import settings
from app.core.security import hash_token
from app.core.time_utils import utcnow
from app.models import CustomerIdentity, CustomerSession, User, UserSession
from app.services import customer_auth_service
from app.services.errors import AuthenticationError
from tests.account_fixtures import (
    csrf_headers,
    register,
    registered_and_verified,
    sign_in,
)
from tests.conftest import TEST_PASSWORD

ADDRESS = "hanh@demo.example.com"
ME = "/api/v1/account/me"
SIGN_OUT = "/api/v1/account/sign-out"


def _identity(db) -> CustomerIdentity:
    return db.query(CustomerIdentity).filter_by(email_normalized=ADDRESS).one()


def _fingerprint(response) -> tuple:
    return (response.status_code, response.json())


# --- Sign-in ------------------------------------------------------------------


def test_a_verified_but_unapproved_identity_may_sign_in_and_reaches_only_its_own_state(
    account_client, account_db, captured_mail
):
    """`pending_approval` is a real signed-in state, and it is the only one Phase 9 produces."""
    registered_and_verified(account_client, captured_mail, ADDRESS)

    response = sign_in(account_client, ADDRESS)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"account_reference", "status", "email_verified", "csrf_token"}
    assert body["status"] == IdentityStatus.PENDING_APPROVAL
    assert body["email_verified"] is True
    assert body["account_reference"].startswith("CA-")

    me = account_client.get(ME)
    assert me.status_code == 200
    assert me.json()["shipment_history_available"] is False
    assert me.json()["linked"] is False


def test_an_unverified_identity_cannot_sign_in(account_client, account_db, captured_mail):
    register(account_client, email=ADDRESS)
    response = sign_in(account_client, ADDRESS)
    assert response.status_code == 401
    assert response.json()["message"] == customer_auth_service.GENERIC_SIGN_IN_FAILURE


def test_every_refusal_says_the_same_thing(account_client, account_db, captured_mail):
    """Unknown, wrong password, unverified, suspended, rejected, deactivated: one sentence."""
    registered_and_verified(account_client, captured_mail, ADDRESS)

    unknown = _fingerprint(sign_in(account_client, "nobody@demo.example.com"))
    wrong = _fingerprint(sign_in(account_client, ADDRESS, password="WrongPassword!2026"))
    assert wrong == unknown

    identity = _identity(account_db)
    for state in (
        IdentityStatus.PENDING_VERIFICATION,
        IdentityStatus.SUSPENDED,
        IdentityStatus.REJECTED,
        IdentityStatus.DEACTIVATED,
    ):
        identity.status = state.value
        account_db.commit()
        assert _fingerprint(sign_in(account_client, ADDRESS)) == unknown, state


def test_a_locked_account_is_refused_with_the_same_sentence(
    account_client, account_db, captured_mail
):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    identity = _identity(account_db)
    identity.locked_until = utcnow() + timedelta(minutes=10)
    account_db.commit()

    response = sign_in(account_client, ADDRESS)
    assert response.status_code == 401
    assert response.json()["message"] == customer_auth_service.GENERIC_SIGN_IN_FAILURE
    assert "lock" not in response.json()["message"].lower()


def test_the_lockout_engages_and_is_bounded_in_time(account_client, account_db, captured_mail):
    """Bounded and never permanent: a permanent lockout is a denial of service."""
    registered_and_verified(account_client, captured_mail, ADDRESS)
    identity = _identity(account_db)

    for _ in range(settings.account_lockout_threshold):
        # The service is driven directly rather than through HTTP, because the route would
        # hit the sign-in rate limiter first and the limiter is a different control with a
        # different test. What is under test here is the per-identity counter.
        with contextlib.suppress(AuthenticationError):
            customer_auth_service.authenticate(
                account_db,
                email_normalized=ADDRESS,
                password="WrongPassword!2026",
                ip_address=None,
                user_agent=None,
            )
    account_db.commit()
    account_db.refresh(identity)

    assert identity.locked_until is not None
    assert identity.locked_until <= utcnow() + timedelta(
        minutes=settings.account_lockout_minutes + 1
    )


def test_the_miss_path_verifies_a_password_so_timing_does_not_separate_the_cases(
    account_client, account_db, monkeypatch
):
    """T-16's control is the *work performed*, so the work is what is asserted.

    A latency assertion on a shared CI machine is a flaky test, not a security control. What
    can be asserted deterministically is that an unknown address still reaches Argon2
    verification -- which is the thing that makes the two paths cost the same.
    """
    calls: list[str] = []
    original = customer_auth_service.verify_password

    def counting(password, password_hash):
        calls.append(password_hash)
        return original(password, password_hash)

    monkeypatch.setattr(customer_auth_service, "verify_password", counting)

    sign_in(account_client, "definitely-nobody@demo.example.com")
    assert len(calls) == 1
    assert calls[0].startswith("$argon2")


# --- Sessions -----------------------------------------------------------------


def test_signing_in_issues_a_new_session_token_every_time(
    account_client, account_db, captured_mail
):
    """Rotation, which is what makes session fixation impossible rather than unlikely."""
    registered_and_verified(account_client, captured_mail, ADDRESS)

    first = sign_in(account_client, ADDRESS)
    first_cookie = account_client.cookies[settings.account_session_cookie_name]
    second = sign_in(account_client, ADDRESS)
    second_cookie = account_client.cookies[settings.account_session_cookie_name]

    assert first_cookie != second_cookie
    assert first.json()["csrf_token"] != second.json()["csrf_token"]
    assert account_db.query(CustomerSession).count() == 2


def test_only_the_digest_is_stored(account_client, account_db, captured_mail):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    response = sign_in(account_client, ADDRESS)

    token = account_client.cookies[settings.account_session_cookie_name]
    csrf = response.json()["csrf_token"]
    row = account_db.query(CustomerSession).one()

    assert row.session_token_hash == hash_token(token)
    assert row.csrf_token_hash == hash_token(csrf)
    assert token not in str(row.__dict__)
    assert csrf not in str(row.__dict__)


def test_sign_out_revokes_server_side_so_a_captured_cookie_stops_working(
    account_client, account_db, captured_mail
):
    """Clearing a cookie is not a sign-out. A copy taken beforehand must stop resolving."""
    registered_and_verified(account_client, captured_mail, ADDRESS)
    response = sign_in(account_client, ADDRESS)
    stolen = account_client.cookies[settings.account_session_cookie_name]

    assert account_client.post(SIGN_OUT, headers=csrf_headers(response)).status_code == 200
    assert account_db.query(CustomerSession).one().revoked_at is not None

    # Present the captured value again, as an attacker holding a copy would.
    account_client.cookies.set(settings.account_session_cookie_name, stolen)
    assert account_client.get(ME).status_code == 401


def test_an_expired_session_is_refused(account_client, account_db, captured_mail):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    sign_in(account_client, ADDRESS)

    row = account_db.query(CustomerSession).one()
    row.expires_at = utcnow() - timedelta(seconds=1)
    account_db.commit()

    assert account_client.get(ME).status_code == 401


def test_an_idle_session_is_refused_and_revoked(account_client, account_db, captured_mail):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    sign_in(account_client, ADDRESS)

    row = account_db.query(CustomerSession).one()
    row.last_seen_at = utcnow() - timedelta(minutes=settings.account_session_idle_minutes + 1)
    account_db.commit()

    assert account_client.get(ME).status_code == 401
    account_db.expire_all()
    assert account_db.query(CustomerSession).one().revoked_at is not None


def test_a_suspension_takes_effect_on_the_next_request(account_client, account_db, captured_mail):
    """No cached grant on the session row, so state is re-read every time (T-14)."""
    registered_and_verified(account_client, captured_mail, ADDRESS)
    sign_in(account_client, ADDRESS)
    assert account_client.get(ME).status_code == 200

    identity = _identity(account_db)
    identity.status = IdentityStatus.SUSPENDED.value
    account_db.commit()

    assert account_client.get(ME).status_code == 401


def test_service_level_revocation_exists_without_a_route(account_client, account_db, captured_mail):
    """Instruction section 8 asks for administrative revocation at the service layer.

    No Phase 9 route reaches it -- suspension is a staff act and staff screens are Phase 10
    -- but "we can suspend an account" should not first become true on the day somebody
    needs it during an incident.
    """
    from app.services import customer_identity_service

    registered_and_verified(account_client, captured_mail, ADDRESS)
    sign_in(account_client, ADDRESS)

    identity = _identity(account_db)
    customer_identity_service.suspend(account_db, identity, reason_code="abuse_investigation")
    account_db.commit()

    assert account_client.get(ME).status_code == 401
    assert account_db.query(CustomerSession).one().revoked_at is not None

    customer_identity_service.reinstate(account_db, identity, reason_code="cleared")
    account_db.commit()
    # Reinstating an unapproved account returns it to pending_approval, never to active.
    assert identity.status == IdentityStatus.PENDING_APPROVAL


def test_deactivation_revokes_sessions_and_tokens_but_deletes_nothing(
    account_client, account_db, captured_mail
):
    from app.models import CustomerAuthToken
    from app.services import customer_identity_service

    registered_and_verified(account_client, captured_mail, ADDRESS)
    sign_in(account_client, ADDRESS)
    identity = _identity(account_db)

    customer_identity_service.deactivate(account_db, identity, reason_code="privacy_request")
    account_db.commit()

    assert account_client.get(ME).status_code == 401
    assert account_db.query(CustomerIdentity).count() == 1  # not a deletion (OD-35)
    live = [
        token
        for token in account_db.query(CustomerAuthToken).all()
        if token.consumed_at is None and token.invalidated_at is None
    ]
    assert live == []


# --- CSRF ---------------------------------------------------------------------


def test_a_non_safe_route_without_the_header_is_refused(account_client, account_db, captured_mail):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    sign_in(account_client, ADDRESS)

    assert account_client.post(SIGN_OUT).status_code == 403


def test_a_wrong_csrf_value_is_refused(account_client, account_db, captured_mail):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    sign_in(account_client, ADDRESS)

    response = account_client.post(
        SIGN_OUT, headers={settings.account_csrf_header_name: "not-the-token"}
    )
    assert response.status_code == 403


def test_the_staff_csrf_header_does_not_satisfy_a_customer_route(
    account_client, account_db, account_users, captured_mail
):
    """Different cookie, different header, different session row (DEC-0005)."""
    from tests.conftest import sign_in as staff_sign_in

    staff_csrf = staff_sign_in(account_client, account_users["admin"].email, TEST_PASSWORD)
    account_client.cookies.clear()

    registered_and_verified(account_client, captured_mail, ADDRESS)
    sign_in(account_client, ADDRESS)

    # The staff token, under the staff header name.
    assert (
        account_client.post(SIGN_OUT, headers={settings.csrf_header_name: staff_csrf}).status_code
        == 403
    )
    # And under the customer header name, which is the more interesting confusion.
    assert (
        account_client.post(
            SIGN_OUT, headers={settings.account_csrf_header_name: staff_csrf}
        ).status_code
        == 403
    )


def test_a_get_is_exempt_and_stays_side_effect_free(account_client, account_db, captured_mail):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    sign_in(account_client, ADDRESS)

    before = account_db.query(CustomerSession).count()
    assert account_client.get(ME).status_code == 200
    assert account_db.query(CustomerSession).count() == before


# --- Cookie and dependency isolation -----------------------------------------


def test_the_cookie_and_header_names_differ_from_the_staff_realm_by_literal_name():
    """Asserted against literals, so a copy-paste that reuses `solaris_session` fails."""
    assert settings.account_session_cookie_name == "solaris_account_session"
    assert settings.account_csrf_cookie_name == "solaris_account_csrf"
    assert settings.account_csrf_header_name == "X-Account-CSRF-Token"

    assert settings.account_session_cookie_name != settings.session_cookie_name
    assert settings.account_csrf_cookie_name != settings.csrf_cookie_name
    assert settings.account_csrf_header_name != settings.csrf_header_name


def test_signing_in_as_a_customer_issues_no_staff_cookie(account_client, account_db, captured_mail):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    sign_in(account_client, ADDRESS)

    jar = dict(account_client.cookies)
    assert settings.account_session_cookie_name in jar
    assert settings.session_cookie_name not in jar
    assert settings.csrf_cookie_name not in jar


def test_signing_in_as_staff_issues_no_customer_cookie(account_client, account_users):
    from tests.conftest import sign_in as staff_sign_in

    staff_sign_in(account_client, account_users["admin"].email, TEST_PASSWORD)
    jar = dict(account_client.cookies)
    assert settings.session_cookie_name in jar
    assert settings.account_session_cookie_name not in jar
    assert settings.account_csrf_cookie_name not in jar


def test_a_customer_cookie_authenticates_nothing_on_a_staff_route(
    account_client, account_db, captured_mail
):
    """401, never 403: a 403 would mean the caller had been authenticated (T-12)."""
    registered_and_verified(account_client, captured_mail, ADDRESS)
    sign_in(account_client, ADDRESS)

    for path in (
        "/api/v1/customers",
        "/api/v1/shipments",
        "/api/v1/auth/me",
        "/api/v1/audit",
    ):
        response = account_client.get(path)
        assert response.status_code == 401, (path, response.status_code)


def test_the_customer_session_value_under_the_staff_cookie_name_still_authenticates_nothing(
    account_client, account_db, captured_mail
):
    """The interesting confusion: the right value, the wrong realm.

    The names differ, so this cannot happen by accident -- but if it did, the staff resolver
    would look the value up in `user_sessions` and find nothing. The separation is the table,
    not the name.
    """
    registered_and_verified(account_client, captured_mail, ADDRESS)
    sign_in(account_client, ADDRESS)
    value = account_client.cookies[settings.account_session_cookie_name]

    account_client.cookies.clear()
    account_client.cookies.set(settings.session_cookie_name, value)
    assert account_client.get("/api/v1/auth/me").status_code == 401


def test_a_staff_cookie_authenticates_nothing_on_a_customer_route(account_client, account_users):
    from tests.conftest import sign_in as staff_sign_in

    staff_sign_in(account_client, account_users["admin"].email, TEST_PASSWORD)
    assert account_client.get(ME).status_code == 401
    assert account_client.post(SIGN_OUT).status_code == 401


def test_a_staff_session_value_under_the_customer_cookie_name_authenticates_nothing(
    account_client, account_users
):
    from tests.conftest import sign_in as staff_sign_in

    staff_sign_in(account_client, account_users["admin"].email, TEST_PASSWORD)
    value = account_client.cookies[settings.session_cookie_name]

    account_client.cookies.clear()
    account_client.cookies.set(settings.account_session_cookie_name, value)
    assert account_client.get(ME).status_code == 401


def test_the_two_session_tables_never_see_each_other(
    account_client, account_db, account_users, captured_mail
):
    from tests.conftest import sign_in as staff_sign_in

    staff_sign_in(account_client, account_users["admin"].email, TEST_PASSWORD)
    account_client.cookies.clear()
    registered_and_verified(account_client, captured_mail, ADDRESS)
    sign_in(account_client, ADDRESS)

    assert account_db.query(UserSession).count() == 1
    assert account_db.query(CustomerSession).count() == 1
    # No customer is a staff row, which is the whole structural claim.
    assert account_db.query(User).filter_by(email=ADDRESS).count() == 0


def test_a_customer_identity_has_no_role_and_no_permission_path(account_db):
    """AC-CA-1.7, asserted as a property of the mapped class rather than of a docstring."""
    columns = {column.name for column in CustomerIdentity.__table__.columns}
    assert "role" not in columns
    assert not hasattr(CustomerIdentity, "role")
    assert not hasattr(CustomerIdentity, "permissions")

    from app.core import permissions

    # `permissions_for` takes a staff role string; nothing on an identity can produce one.
    assert not any(
        isinstance(getattr(CustomerIdentity, name, None), str)
        and getattr(CustomerIdentity, name) in permissions.ROLE_PERMISSIONS
        for name in dir(CustomerIdentity)
    )


# --- Headers ------------------------------------------------------------------


def test_authenticated_responses_carry_no_store(account_client, account_db, captured_mail):
    """A shipment list on a shared phone must not sit in a back-button cache."""
    registered_and_verified(account_client, captured_mail, ADDRESS)
    response = sign_in(account_client, ADDRESS)
    assert response.headers["cache-control"] == "no-store"
    assert account_client.get(ME).headers["cache-control"] == "no-store"


def test_no_correlation_header_is_returned_on_a_customer_response(
    account_client, account_db, captured_mail
):
    """DEC-0085 extended: a per-request header is a value that differs between responses."""
    registered_and_verified(account_client, captured_mail, ADDRESS)
    response = sign_in(account_client, ADDRESS)
    assert "x-correlation-id" not in {key.lower() for key in response.headers}


def test_the_staff_api_still_returns_its_correlation_header(account_client, account_users):
    """Correlation for staff APIs is preserved -- the boundary moved, not the capability."""
    from tests.conftest import sign_in as staff_sign_in

    staff_sign_in(account_client, account_users["admin"].email, TEST_PASSWORD)
    response = account_client.get("/api/v1/auth/me")
    assert response.headers.get("X-Correlation-ID")
