"""Rate limits: the buckets, their separation from the other surfaces, and the ordering.

Three claims, and the third is the one that is easy to get wrong.

**The buckets exist and recover.** Each refuses at its configured limit and works again
after the window, and the two that must return the *ordinary* generic body rather than a 429
do so -- a 429 that appeared only for addresses somebody kept trying would be the
enumeration oracle the generic body exists to close.

**The namespace is separate.** A customer-side flood must not consume the staff login
allowance or the public tracking allowance. That is asserted directly, by flooding one
surface and then using another, because it is the entire reason the namespaces exist: a
registration flood that locked operations out of the CRM would do so during exactly the
incident they need to respond to.

**The ordering holds.** A malformed request must still consume an attempt, and a refused
request must issue **zero** database statements. Both are asserted by counting statements on
the engine rather than by reading the handler, because the property is about what runs, not
about what the code appears to say.
"""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import event

from app.core import account_security
from app.core.config import settings
from app.core.security import rate_limiter
from app.models import CustomerIdentity, CustomerRegistrationAttempt
from app.services import customer_identity_service
from tests.account_fixtures import ACCOUNT_PASSWORD, register, registration, sign_in
from tests.conftest import TEST_PASSWORD

REGISTER = "/api/v1/account/register"
RESEND = "/api/v1/account/verification/resend"
FORGOT = "/api/v1/account/password/forgot"
SIGN_IN = "/api/v1/account/sign-in"
VERIFY = "/api/v1/account/verify-email"
ADDRESS = "hanh@demo.example.com"


@contextmanager
def counting_statements(engine):
    """Count every statement the engine executes inside the block.

    An engine listener rather than a mock, so what is counted is what SQLAlchemy actually
    sent -- including anything a dependency issued before the handler ran, which is exactly
    the thing this file exists to rule out.
    """
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


# --- The buckets --------------------------------------------------------------


def test_registration_per_ip_refuses_at_its_limit_with_a_retry_after(
    account_client, account_db, captured_mail
):
    limit = settings.account_register_ip_attempts
    for index in range(limit):
        response = account_client.post(
            REGISTER, json=registration(email=f"person{index}@demo.example.com")
        )
        assert response.status_code == 200, index

    refused = account_client.post(
        REGISTER, json=registration(email="one-too-many@demo.example.com")
    )
    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) > 0
    # The body is the narrow three-key one, with no detail to differ between two refusals.
    assert set(refused.json()) == {"code", "message", "field"}
    # And its sentence is the ordinary registration sentence, not "Too many requests"
    # (UAT round 3): what a person reads is the same whether the limit decided or not.
    assert refused.json()["message"] == customer_identity_service.GENERIC_REGISTRATION_MESSAGE
    assert "too many" not in refused.text.lower()


def test_the_per_address_refusal_returns_the_ordinary_body_and_sends_nothing(
    account_client, account_db, captured_mail
):
    """`RATE_LIMITS_AND_ABUSE.md` section 3: the mail is suppressed, the answer is unchanged."""
    allowed = settings.account_register_address_attempts
    baseline = None
    for _ in range(allowed):
        baseline = account_client.post(REGISTER, json=registration(email=ADDRESS))
        assert baseline.status_code == 200

    before = len(captured_mail.messages)
    refused = account_client.post(REGISTER, json=registration(email=ADDRESS))

    assert refused.status_code == 200
    assert refused.json() == baseline.json()
    assert "retry-after" not in {key.lower() for key in refused.headers}
    assert len(captured_mail.messages) == before


def test_the_reset_per_address_refusal_does_the_same(account_client, account_db, captured_mail):
    register(account_client, email=ADDRESS)
    rate_limiter.reset()

    baseline = None
    for _ in range(settings.account_reset_address_attempts):
        baseline = account_client.post(FORGOT, json={"email": ADDRESS})
        assert baseline.status_code == 200

    before = len(captured_mail.messages)
    refused = account_client.post(FORGOT, json={"email": ADDRESS})
    assert refused.status_code == 200
    assert refused.json() == baseline.json()
    assert len(captured_mail.messages) == before


def test_sign_in_has_separate_ip_and_account_buckets(account_client, account_db, captured_mail):
    """Two buckets, and the account one bites first for a single targeted address.

    The per-account limit is lower than the per-IP limit on purpose: one attacker working
    through many addresses from one host and one attacker hammering one address are
    different attacks, and a single bucket would let each hide inside the other's allowance.
    """
    assert settings.account_signin_address_attempts < settings.account_signin_ip_attempts

    for _ in range(settings.account_signin_address_attempts):
        assert sign_in(account_client, ADDRESS, password="WrongPassword!2026").status_code == 401

    # The account bucket is exhausted while the IP bucket still has room.
    assert sign_in(account_client, ADDRESS, password="WrongPassword!2026").status_code == 429
    # A different address from the same IP still gets through to a 401, not a 429.
    assert sign_in(account_client, "other@demo.example.com", password="x" * 14).status_code == 401


def test_token_redemption_is_rate_limited_per_caller(account_client, account_db):
    for _ in range(settings.account_token_ip_attempts):
        assert account_client.post(VERIFY, json={"token": "a" * 43}).status_code == 422
    assert account_client.post(VERIFY, json={"token": "a" * 43}).status_code == 429


def test_a_bucket_recovers_after_its_window(account_client, account_db, captured_mail):
    """Recovery is asserted by resetting the limiter rather than by sleeping an hour.

    The sliding window itself is `SlidingWindowRateLimiter`'s own test in
    `test_public_tracking.py`; what matters here is that the endpoint is not latched -- that
    a refusal is a refusal of one request and not of the account.
    """
    for _ in range(settings.account_register_ip_attempts + 1):
        account_client.post(REGISTER, json=registration(email="flood@demo.example.com"))

    rate_limiter.reset()
    assert (
        account_client.post(
            REGISTER, json=registration(email="after-window@demo.example.com")
        ).status_code
        == 200
    )


# --- Namespace separation -----------------------------------------------------


def test_a_customer_flood_does_not_consume_the_staff_login_allowance(
    account_client, account_db, account_users, captured_mail
):
    """The reason the namespaces exist, asserted directly (AC-CA-1.6)."""
    for index in range(settings.account_register_ip_attempts + 5):
        account_client.post(REGISTER, json=registration(email=f"flood{index}@demo.example.com"))
    for _ in range(settings.account_signin_ip_attempts + 5):
        sign_in(account_client, "nobody@demo.example.com", password="WrongPassword!2026")

    account_client.cookies.clear()
    staff = account_client.post(
        "/api/v1/auth/login",
        json={"email": account_users["admin"].email, "password": TEST_PASSWORD},
    )
    assert staff.status_code == 200, "a customer flood locked staff out of the CRM"


def test_a_customer_flood_does_not_consume_the_public_tracking_allowance(
    account_client, account_db, captured_mail
):
    for index in range(settings.account_register_ip_attempts + 5):
        account_client.post(REGISTER, json=registration(email=f"flood{index}@demo.example.com"))

    public = account_client.get("/api/v1/public/track/SX-CAV-7K9D2M4R8T6W")
    # Not found, because nothing was booked -- but *answered*, which is the claim.
    assert public.status_code == 404
    assert public.json()["code"] == "tracking_not_found"


def test_a_staff_login_flood_does_not_consume_the_customer_allowance(
    account_client, account_db, account_users, captured_mail
):
    for _ in range(settings.login_rate_limit_attempts + 3):
        account_client.post(
            "/api/v1/auth/login",
            json={"email": account_users["admin"].email, "password": "WrongPassword!2026"},
        )

    assert account_client.post(REGISTER, json=registration(email=ADDRESS)).status_code == 200


def test_every_customer_bucket_is_in_its_own_namespace():
    """Asserted over the key builders, so a new bucket cannot quietly join another surface."""
    builders = [
        account_security.register_ip_bucket("1.2.3.4"),
        account_security.register_address_bucket(ADDRESS),
        account_security.resend_ip_bucket("1.2.3.4"),
        account_security.resend_address_bucket(ADDRESS),
        account_security.signin_ip_bucket("1.2.3.4"),
        account_security.signin_address_bucket(ADDRESS),
        account_security.reset_ip_bucket("1.2.3.4"),
        account_security.reset_address_bucket(ADDRESS),
        account_security.token_ip_bucket("1.2.3.4"),
        account_security.token_identity_bucket("CA-000001"),
    ]
    assert len(set(builders)) == len(builders), "two buckets collide"
    for key in builders:
        assert key.startswith(f"{account_security.BUCKET_NAMESPACE}:")
        assert not key.startswith("login:")
        assert not key.startswith("public:")


def test_limiter_state_holds_no_raw_address(account_client, account_db, captured_mail):
    """`RATE_LIMITS_AND_ABUSE.md` section 8.5, asserted over the limiter's live keys."""
    account_client.post(REGISTER, json=registration(email=ADDRESS))
    sign_in(account_client, ADDRESS, password="WrongPassword!2026")
    account_client.post(FORGOT, json={"email": ADDRESS})

    keys = list(rate_limiter._buckets)  # noqa: SLF001 - the point is the internal state
    assert keys
    for key in keys:
        assert ADDRESS not in key
        assert "@" not in key


def test_the_address_key_is_stable_and_not_reversible():
    first = account_security.address_key(ADDRESS)
    assert first == account_security.address_key(ADDRESS.upper())
    assert first != account_security.address_key("someone.else@demo.example.com")
    assert ADDRESS not in first
    assert len(first) == 64


# --- Ordering -----------------------------------------------------------------


def test_a_malformed_body_still_consumes_an_attempt(account_client, account_db):
    """Otherwise an attacker who wanted unlimited attempts would simply send invalid JSON."""
    limit = settings.account_register_ip_attempts
    for _ in range(limit):
        response = account_client.post(
            REGISTER, content=b"{not json", headers={"content-type": "application/json"}
        )
        assert response.status_code == 400

    # The allowance is gone, spent entirely on requests that never reached a body model.
    assert account_client.post(REGISTER, json=registration()).status_code == 429


def test_a_body_missing_required_fields_also_consumes_an_attempt(account_client, account_db):
    for _ in range(settings.account_register_ip_attempts):
        assert account_client.post(REGISTER, json={"email": "x@y.example"}).status_code in {
            400,
            422,
        }
    assert account_client.post(REGISTER, json=registration()).status_code == 429


def test_a_rate_limited_registration_issues_no_database_statement(
    account_client, account_engine, account_db, captured_mail
):
    """The per-IP refusal happens before the body is read and before any query runs."""
    for index in range(settings.account_register_ip_attempts):
        account_client.post(REGISTER, json=registration(email=f"p{index}@demo.example.com"))

    with counting_statements(account_engine) as statements:
        refused = account_client.post(REGISTER, json=registration(email=ADDRESS))
    assert refused.status_code == 429
    assert statements == [], f"a refused request issued {len(statements)} statement(s)"


def test_a_rate_limited_sign_in_issues_no_database_statement(
    account_client, account_engine, account_db, captured_mail
):
    for _ in range(settings.account_signin_address_attempts):
        sign_in(account_client, ADDRESS, password="WrongPassword!2026")

    with counting_statements(account_engine) as statements:
        refused = sign_in(account_client, ADDRESS, password="WrongPassword!2026")
    assert refused.status_code == 429
    assert statements == []


def test_a_rate_limited_resend_issues_no_database_statement(
    account_client, account_engine, account_db, captured_mail
):
    for _ in range(settings.account_resend_ip_attempts):
        account_client.post(RESEND, json={"email": ADDRESS})

    with counting_statements(account_engine) as statements:
        refused = account_client.post(RESEND, json={"email": ADDRESS})
    assert refused.status_code == 429
    assert statements == []


def test_the_per_address_refusal_also_issues_no_database_statement(
    account_client, account_engine, account_db, captured_mail
):
    """It answers 200 with the ordinary body -- and still touches nothing."""
    for _ in range(settings.account_register_address_attempts):
        account_client.post(REGISTER, json=registration(email=ADDRESS))

    with counting_statements(account_engine) as statements:
        refused = account_client.post(REGISTER, json=registration(email=ADDRESS))
    assert refused.status_code == 200
    assert statements == []


def test_nothing_is_created_by_a_refused_request(account_client, account_db, captured_mail):
    for index in range(settings.account_register_ip_attempts):
        account_client.post(REGISTER, json=registration(email=f"p{index}@demo.example.com"))
    before = (
        account_db.query(CustomerIdentity).count(),
        account_db.query(CustomerRegistrationAttempt).count(),
        len(captured_mail.messages),
    )

    for _ in range(4):
        account_client.post(REGISTER, json=registration(email=ADDRESS))

    after = (
        account_db.query(CustomerIdentity).count(),
        account_db.query(CustomerRegistrationAttempt).count(),
        len(captured_mail.messages),
    )
    assert after == before


# --- Client identity ----------------------------------------------------------


def test_a_forwarding_header_does_not_buy_a_fresh_bucket(account_client, account_db):
    """DEC-0007 and DEC-0048, reused from the public surface rather than re-reasoned.

    While proxy trust is disabled, every request carrying a forwarding header folds into one
    shared bucket. The alternative lets a caller pick their own bucket per request, which is
    to say remove the limit.
    """
    limit = settings.account_register_ip_attempts
    for index in range(limit):
        response = account_client.post(
            REGISTER,
            json=registration(email=f"spoof{index}@demo.example.com"),
            headers={"X-Forwarded-For": f"10.0.0.{index}"},
        )
        assert response.status_code == 200, index

    refused = account_client.post(
        REGISTER,
        json=registration(email="spoof-last@demo.example.com"),
        headers={"X-Forwarded-For": "10.0.0.250"},
    )
    assert refused.status_code == 429


def test_proxy_trust_is_still_disabled():
    """The gate itself, so this suite's premise cannot quietly stop being true."""
    assert settings.trust_proxy_headers is False
    assert settings.trusted_proxy_host_list == []


def test_the_limiter_stays_bounded(account_client, account_db, captured_mail):
    """Bounded memory: the customer surface adds keys to a map that already prunes itself."""
    before = rate_limiter.bucket_count()
    for index in range(50):
        sign_in(account_client, f"person{index}@demo.example.com", password=ACCOUNT_PASSWORD)
    after = rate_limiter.bucket_count()
    assert after <= before + 200
    assert after <= rate_limiter._max_buckets  # noqa: SLF001 - the bound is the claim
