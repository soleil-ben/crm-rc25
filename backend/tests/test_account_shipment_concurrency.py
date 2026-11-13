"""Reads racing state changes, on genuinely separate sessions and connections.

Every test here writes the state change on a **second session**, from a second connection,
and commits it -- then issues the next request. That is the difference between testing a
race and testing a variable: a change made on the request's own session would be visible
because it was never anywhere else, and would prove nothing about what a second actor doing
it at the same time would produce.

Since DEC-0108 a session holds its SQLite read snapshot from its first statement until it
commits or rolls back, so the observing session rolls back before re-reading. That is what
`conftest.see_committed_changes` exists for, and the reason is in its docstring.
"""

from __future__ import annotations

import threading

from sqlalchemy.orm import sessionmaker

from app.core.account_enums import IdentityStatus, LinkStatus
from app.core.enums import BookingState, OperationalState
from app.core.time_utils import utcnow
from app.models import Customer, CustomerIdentity, CustomerIdentityLink, CustomerSession
from tests.conftest import see_committed_changes
from tests.shipment_history_fixtures import (
    LIST_URL,
    detail_url,
    linked_and_signed_in,
    references,
    shipment,
)
from tests.shipment_history_fixtures import customer as make

MINE = "hanh@demo.example.com"


def _mine(account_db):
    return make(account_db, full_name="Hanh Nguyen", email="hanh.canonical@demo.example.com")


def _signed_in(account_client, account_db, account_users, captured_mail, owner):
    return linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=owner
    )


def _other_session(account_engine):
    """A second session on its own connection. The whole point of this file."""
    factory = sessionmaker(
        bind=account_engine, autoflush=False, expire_on_commit=False, future=True
    )
    return factory()


# --- Authorization is re-evaluated on every request ---------------------------------


def test_a_session_revoked_on_another_connection_stops_the_next_read(
    account_client, account_db, account_engine, account_users, captured_mail
):
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)
    assert client.get(detail_url(row.public_id)).status_code == 200

    other = _other_session(account_engine)
    try:
        for session_row in other.query(CustomerSession).all():
            session_row.revoked_at = utcnow()
        other.commit()
    finally:
        other.close()

    assert client.get(detail_url(row.public_id)).status_code == 401
    assert client.get(LIST_URL).status_code == 401


def test_a_suspension_on_another_connection_stops_the_next_read(
    account_client, account_db, account_engine, account_users, captured_mail
):
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)
    assert client.get(LIST_URL).status_code == 200

    other = _other_session(account_engine)
    try:
        other.query(CustomerIdentity).one().status = IdentityStatus.SUSPENDED.value
        other.commit()
    finally:
        other.close()

    for response in (client.get(LIST_URL), client.get(detail_url(row.public_id))):
        assert response.status_code in {401, 403}
        assert row.public_id not in response.text


def test_a_deactivation_on_another_connection_stops_the_next_read(
    account_client, account_db, account_engine, account_users, captured_mail
):
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)
    assert client.get(LIST_URL).status_code == 200

    other = _other_session(account_engine)
    try:
        other.query(CustomerIdentity).one().status = IdentityStatus.DEACTIVATED.value
        other.commit()
    finally:
        other.close()

    refused = client.get(LIST_URL)
    assert refused.status_code in {401, 403}
    assert row.public_id not in refused.text
    assert client.get(detail_url(row.public_id)).status_code in {401, 403}


def test_a_link_revoked_on_another_connection_stops_the_next_read(
    account_client, account_db, account_engine, account_users, captured_mail
):
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)
    assert client.get(detail_url(row.public_id)).status_code == 200

    other = _other_session(account_engine)
    try:
        other.query(CustomerIdentityLink).one().status = LinkStatus.REVOKED.value
        other.commit()
    finally:
        other.close()

    assert client.get(detail_url(row.public_id)).status_code == 403
    assert client.get(LIST_URL).status_code == 403


def test_a_customer_archived_on_another_connection_stops_the_next_read(
    account_client, account_db, account_engine, account_users, captured_mail
):
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)
    assert client.get(LIST_URL).status_code == 200

    other = _other_session(account_engine)
    try:
        other.get(Customer, owner.id).is_archived = True
        other.commit()
    finally:
        other.close()

    assert client.get(LIST_URL).status_code == 403
    assert client.get(detail_url(row.public_id)).status_code == 403


# --- Shipment state changes underneath a read ----------------------------------------


def test_a_cancellation_on_another_connection_shows_up_as_a_safe_state(
    account_client, account_db, account_engine, account_users, captured_mail
):
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)
    assert client.get(LIST_URL).json()["items"][0]["is_cancelled"] is False

    other = _other_session(account_engine)
    try:
        cancelled = other.get(type(row), row.id)
        cancelled.booking_state = BookingState.CANCELLED
        cancelled.operational_state = OperationalState.CANCELLED
        cancelled.cancelled_at = utcnow()
        other.commit()
    finally:
        other.close()

    item = client.get(LIST_URL).json()["items"][0]
    assert item["is_cancelled"] is True
    assert item["cancelled_at"] is not None
    # Still visible, with a safe state. OD-29 keeps it; it does not vanish mid-session.
    assert item["shipment_reference"] == row.public_id


def test_a_rebook_on_another_connection_produces_two_rows_and_no_cross_reference(
    account_client, account_db, account_engine, account_users, captured_mail
):
    owner = _mine(account_db)
    original = shipment(account_db, owner, days_ago=5)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)
    assert len(client.get(LIST_URL).json()["items"]) == 1

    other = _other_session(account_engine)
    try:
        replacement = shipment(other, other.get(Customer, owner.id), days_ago=1)
        source = other.get(type(original), original.id)
        source.booking_state = BookingState.CANCELLED
        source.operational_state = OperationalState.CANCELLED
        source.cancelled_at = utcnow()
        source.rebooked_to_shipment_id = replacement.id
        replacement.rebooked_from_shipment_id = source.id
        other.commit()
        replacement_reference = replacement.public_id
    finally:
        other.close()

    body = client.get(LIST_URL).json()
    listed = references(body)
    assert sorted(listed) == sorted([original.public_id, replacement_reference])
    items = {item["shipment_reference"]: item for item in body["items"]}
    assert items[original.public_id]["is_rebooked"] is True
    assert replacement_reference not in str(items[original.public_id])


def test_a_new_shipment_on_another_connection_appears_on_the_next_read(
    account_client, account_db, account_engine, account_users, captured_mail
):
    owner = _mine(account_db)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)
    assert client.get(LIST_URL).json()["items"] == []

    other = _other_session(account_engine)
    try:
        fresh = shipment(other, other.get(Customer, owner.id), days_ago=0)
        reference = fresh.public_id
    finally:
        other.close()

    assert references(client.get(LIST_URL).json()) == [reference]


def test_an_attempted_merge_leaves_the_read_exactly_where_it_was(
    account_client, account_db, account_engine, account_users, captured_mail
):
    """OD-40 refuses the merge, so the read is unchanged rather than widened or broken."""
    from app.services import customer_service
    from app.services.customer_account_link_policy import LinkedCustomerMergeRefused

    owner = _mine(account_db)
    survivor = make(account_db, full_name="Survivor", email="survivor@demo.example.com")
    mine_row = shipment(account_db, owner, days_ago=3)
    theirs_row = shipment(account_db, survivor, days_ago=2)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)
    assert references(client.get(LIST_URL).json()) == [mine_row.public_id]

    other = _other_session(account_engine)
    try:
        source = other.get(Customer, owner.id)
        target = other.get(Customer, survivor.id)
        try:
            customer_service.merge_customers(other, source=source, target=target, actor=None)
            other.commit()
            merged = True
        except LinkedCustomerMergeRefused as refusal:
            other.rollback()
            merged = False
            # The stable code a staff surface switches on, asserted here so this test fails
            # if the merge starts refusing for some other reason -- or stops refusing and
            # raises something else instead.
            assert refusal.detail["code"] == "customer_account_link_present"
    finally:
        other.close()

    assert merged is False
    body = client.get(LIST_URL).json()
    assert references(body) == [mine_row.public_id]
    assert theirs_row.public_id not in str(body)

    see_committed_changes(account_db)
    assert account_db.get(Customer, owner.id).merged_into_customer_id is None


# --- Genuine parallelism --------------------------------------------------------------


def test_a_read_racing_a_revocation_never_returns_a_partial_answer(
    account_client, account_db, account_engine, account_users, captured_mail
):
    """Twenty reads against a revocation landing in the middle of them.

    Every response is either a complete authorized answer or a complete refusal. What must
    never appear is a 200 carrying somebody's rows *and* a refusal's shape, or a page
    assembled half before and half after the change -- a transient state producing a
    partially authorized response.
    """
    owner = _mine(account_db)
    for day in range(1, 6):
        shipment(account_db, owner, days_ago=day)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    results: list[tuple[int, int]] = []
    stop = threading.Event()

    def revoke() -> None:
        stop.wait(0.02)
        session = _other_session(account_engine)
        try:
            session.query(CustomerIdentityLink).one().status = LinkStatus.REVOKED.value
            session.commit()
        finally:
            session.close()

    worker = threading.Thread(target=revoke)
    worker.start()
    stop.set()
    for _ in range(20):
        response = client.get(LIST_URL)
        body = response.json()
        results.append((response.status_code, len(body.get("items", []))))
    worker.join()

    assert results
    for status, count in results:
        if status == 200:
            # A complete answer: all five rows, never a truncated page.
            assert count == 5, results
        else:
            assert status == 403, results
            assert count == 0, results
    # The revocation landed, so the tail of the run is refusals.
    assert results[-1][0] == 403, results


def test_two_accounts_reading_at_once_never_cross_the_boundary(
    account_client, account_db, account_engine, account_users, captured_mail
):
    """Two live sessions, interleaved, each seeing only its own rows.

    Sequential interleaving on one client rather than two threads: the property under test
    is that no request carries a grant from the previous one, and alternating between two
    signed-in cookies exercises exactly that without making the assertion depend on thread
    scheduling.
    """
    first = _mine(account_db)
    second = make(account_db, full_name="Second", email="second.canonical@demo.example.com")
    mine_row = shipment(account_db, first, days_ago=3)
    theirs_row = shipment(account_db, second, days_ago=3)

    _signed_in(account_client, account_db, account_users, captured_mail, first)
    first_cookies = dict(account_client.cookies)

    linked_and_signed_in(
        account_client,
        captured_mail,
        account_users,
        email_address="second.person@demo.example.com",
        customer=second,
    )
    second_cookies = dict(account_client.cookies)

    for _ in range(5):
        account_client.cookies.clear()
        account_client.cookies.update(first_cookies)
        assert references(account_client.get(LIST_URL).json()) == [mine_row.public_id]

        account_client.cookies.clear()
        account_client.cookies.update(second_cookies)
        assert references(account_client.get(LIST_URL).json()) == [theirs_row.public_id]


def test_no_effective_link_points_at_a_tombstone_after_every_race(
    account_client, account_db, account_engine, account_users, captured_mail
):
    """The whole-database sweep OD-40 asks for, run after the races above have churned state."""
    owner = _mine(account_db)
    shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    other = _other_session(account_engine)
    try:
        other.query(CustomerIdentityLink).one().status = LinkStatus.REVOKED.value
        other.commit()
        other.query(CustomerIdentityLink).one().status = LinkStatus.ACTIVE.value
        other.commit()
    finally:
        other.close()

    assert client.get(LIST_URL).status_code == 200

    see_committed_changes(account_db)
    for link in account_db.query(CustomerIdentityLink).all():
        if link.status != LinkStatus.ACTIVE.value:
            continue
        customer = account_db.get(Customer, link.customer_id)
        assert customer is not None
        assert customer.merged_into_customer_id is None
        assert customer.merged_at is None
        assert customer.is_archived is False
