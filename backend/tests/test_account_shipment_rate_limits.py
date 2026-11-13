"""The authenticated read bucket: its own namespace, its ordering, and what it costs.

Two properties carry this file. **Separation** -- a customer-side flood must not stop
operations signing in or Public Tracking answering, which is why the namespaces exist at all
(`RATE_LIMITS_AND_ABUSE.md` §2, AC-CA-1.6). And **ordering** -- the limiter runs before the
reference is parsed and before the ownership query, so a refused request performs no
database work and a malformed reference cannot buy unlimited attempts.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event as sa_event

from app.core.account_security import BUCKET_NAMESPACE, read_identity_bucket
from app.core.config import settings
from app.core.enums import Role
from app.core.security import rate_limiter
from tests.approval_fixtures import staff
from tests.shipment_history_fixtures import (
    LIST_URL,
    detail_url,
    linked_and_signed_in,
    shipment,
)
from tests.shipment_history_fixtures import customer as make

MINE = "hanh@demo.example.com"


@pytest.fixture
def small_read_limit(monkeypatch):
    """Three reads per window, so exhaustion is a test rather than a load generator.

    The real limit is 300 in five minutes, which is configuration precisely so it can be
    turned down here. Turning it down is also the honest way to test it: a test that sent
    300 requests would be measuring the test client.
    """
    monkeypatch.setattr(settings, "account_read_identity_attempts", 3)
    monkeypatch.setattr(settings, "account_read_identity_window_seconds", 300)


def _mine(account_db):
    return make(account_db, full_name="Hanh Nguyen", email="hanh.canonical@demo.example.com")


def _signed_in(account_client, account_db, account_users, captured_mail):
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=4)
    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=owner
    )
    return client, row


# --- The bucket -------------------------------------------------------------------


def test_the_read_bucket_is_in_the_account_namespace():
    bucket = read_identity_bucket("CA-000001")
    assert bucket.startswith(f"{BUCKET_NAMESPACE}:")
    assert bucket == "account:read:identity:CA-000001"


def test_the_bucket_is_keyed_by_the_account_and_holds_no_address(
    account_client, account_db, account_users, captured_mail
):
    """The limiter's in-memory keys must not become a list of who has an account (T-13)."""
    client, _ = _signed_in(account_client, account_db, account_users, captured_mail)
    rate_limiter.reset()
    client.get(LIST_URL)

    keys = list(rate_limiter._buckets)  # noqa: SLF001 - the point is the live key set
    read_keys = [key for key in keys if key.startswith("account:read:")]
    assert read_keys
    for key in read_keys:
        assert MINE not in key
        assert "@" not in key
        assert key.split(":")[-1].startswith("CA-")


def test_the_limit_refuses_and_says_when_to_come_back(
    account_client, account_db, account_users, captured_mail, small_read_limit
):
    client, row = _signed_in(account_client, account_db, account_users, captured_mail)
    rate_limiter.reset()

    for _ in range(3):
        assert client.get(LIST_URL).status_code == 200

    refused = client.get(LIST_URL)
    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) > 0
    assert row.public_id not in refused.text


def test_the_list_and_the_detail_share_one_read_allowance(
    account_client, account_db, account_users, captured_mail, small_read_limit
):
    """One bucket for reading, not one per route.

    Two buckets would let a scraper take both allowances, and the thing being bounded is how
    much of a history a compromised session can pull, not which URL it pulled it through.
    """
    client, row = _signed_in(account_client, account_db, account_users, captured_mail)
    rate_limiter.reset()

    assert client.get(LIST_URL).status_code == 200
    assert client.get(detail_url(row.public_id)).status_code == 200
    assert client.get(LIST_URL).status_code == 200
    assert client.get(detail_url(row.public_id)).status_code == 429


def test_normal_pagination_stays_far_inside_the_real_limit():
    """The configured limit must not make ordinary use unusable.

    300 reads in five minutes is fifteen full pages a minute sustained. A person paging
    through their own history does not reach it, and the bound still stops a session being
    used to pull a large history quickly.
    """
    assert settings.account_read_identity_attempts >= 300
    assert settings.account_read_identity_window_seconds <= 300
    pages_per_minute = settings.account_read_identity_attempts / (
        settings.account_read_identity_window_seconds / 60
    )
    assert pages_per_minute >= 60


# --- Ordering ------------------------------------------------------------------------


def test_a_refused_request_performs_no_further_database_work(
    account_client, account_db, account_users, captured_mail, small_read_limit
):
    """The limiter runs before the link resolution, the reference parsing and every query.

    "No further" rather than "none at all": resolving the session is what produces the
    account the bucket is keyed by, so a refused request has done exactly that and stopped.
    The assertion is that nothing after it ran -- no shipment query, no link read, no
    customer read and no audit write.
    """
    client, row = _signed_in(account_client, account_db, account_users, captured_mail)
    rate_limiter.reset()
    for _ in range(3):
        client.get(LIST_URL)

    bind = account_db.get_bind()
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(" ".join(statement.split()).lower())

    sa_event.listen(bind, "before_cursor_execute", record)
    try:
        refused = client.get(detail_url(row.public_id))
    finally:
        sa_event.remove(bind, "before_cursor_execute", record)

    assert refused.status_code == 429
    for statement in statements:
        assert "from shipments" not in statement, statement
        assert "from customer_identity_links" not in statement, statement
        assert "from customers" not in statement, statement
        assert "insert into audit_events" not in statement, statement


def test_a_malformed_reference_cannot_bypass_the_limiter(
    account_client, account_db, account_users, captured_mail, small_read_limit
):
    """Every attempt costs an attempt, whatever was in the path.

    If the reference were parsed first, an attacker wanting unlimited tries would simply
    send unparseable ones. Three malformed requests exhaust the allowance exactly as three
    valid ones would, and the fourth is refused.
    """
    client, row = _signed_in(account_client, account_db, account_users, captured_mail)
    rate_limiter.reset()

    for junk in ("!!!", "a/b/c/d", "x" * 400):
        assert client.get(detail_url(junk)).status_code == 404

    assert client.get(detail_url(row.public_id)).status_code == 429


def test_the_limiter_state_stays_bounded(account_client, account_db, account_users, captured_mail):
    """One account, many requests: one bucket, and it does not grow per request."""
    client, _ = _signed_in(account_client, account_db, account_users, captured_mail)
    rate_limiter.reset()

    for _ in range(25):
        client.get(LIST_URL)

    read_keys = [key for key in rate_limiter._buckets if key.startswith("account:read:")]  # noqa: SLF001
    assert len(read_keys) == 1


# --- Separation -----------------------------------------------------------------------


def test_a_customer_read_flood_consumes_no_staff_login_allowance(
    account_client, account_db, account_users, captured_mail, small_read_limit
):
    """AC-CA-1.6, and the reason the namespaces exist.

    A registration or scraping flood that locked operations out of the CRM would do it
    during exactly the incident they need to respond to.
    """
    client, _ = _signed_in(account_client, account_db, account_users, captured_mail)
    rate_limiter.reset()

    for _ in range(10):
        client.get(LIST_URL)
    assert client.get(LIST_URL).status_code == 429

    account_client.cookies.clear()
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    assert api.headers  # the staff sign-in succeeded and returned a CSRF token


def test_a_customer_read_flood_consumes_no_public_tracking_allowance(
    account_client, account_db, account_users, captured_mail, small_read_limit
):
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=4)
    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=owner
    )
    rate_limiter.reset()

    for _ in range(10):
        client.get(LIST_URL)
    assert client.get(LIST_URL).status_code == 429

    public = client.get(f"/api/v1/public/track/{row.public_id}")
    assert public.status_code == 200


def test_a_customer_read_flood_consumes_no_customer_sign_in_allowance(
    account_client, account_db, account_users, captured_mail, small_read_limit
):
    """Reading and signing in are different activities on the same surface.

    Sharing one bucket would mean that paging through a history could stop the same person
    signing back in after their session expired.
    """
    client, _ = _signed_in(account_client, account_db, account_users, captured_mail)
    rate_limiter.reset()
    for _ in range(10):
        client.get(LIST_URL)
    assert client.get(LIST_URL).status_code == 429

    client.cookies.clear()
    again = client.post(
        "/api/v1/account/sign-in",
        json={"email": MINE, "password": "SolarisCustomer!2026"},
    )
    assert again.status_code == 200, again.text


def test_one_account_s_flood_does_not_refuse_another_account(
    account_client, account_db, account_users, captured_mail, small_read_limit
):
    """The bucket is per account, so one compromised session is bounded on its own."""
    first = _mine(account_db)
    second = make(account_db, full_name="Second", email="second.canonical@demo.example.com")
    shipment(account_db, first, days_ago=3)
    shipment(account_db, second, days_ago=3)

    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=first
    )
    rate_limiter.reset()
    for _ in range(4):
        client.get(LIST_URL)
    assert client.get(LIST_URL).status_code == 429

    other = linked_and_signed_in(
        account_client,
        captured_mail,
        account_users,
        email_address="second.person@demo.example.com",
        customer=second,
    )
    assert other.get(LIST_URL).status_code == 200


def test_a_forwarding_header_does_not_let_a_caller_pick_a_bucket(
    account_client, account_db, account_users, captured_mail, small_read_limit
):
    """Proxy trust is off, and the read bucket does not read an address at all.

    Both halves matter. The bucket is keyed by the account, so a header cannot move it; and
    `account_client_key` folds every forwarded request into one shared bucket anyway, so
    even a bucket that did read an address could not be chosen by the caller (DEC-0007).
    """
    assert settings.trust_proxy_headers is False
    client, _ = _signed_in(account_client, account_db, account_users, captured_mail)
    rate_limiter.reset()

    for index in range(3):
        assert (
            client.get(LIST_URL, headers={"X-Forwarded-For": f"10.0.0.{index}"}).status_code == 200
        )
    refused = client.get(LIST_URL, headers={"X-Forwarded-For": "10.0.0.99"})
    assert refused.status_code == 429
