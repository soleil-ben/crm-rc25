"""What the list costs, measured rather than reasoned about.

The property that matters is **independence from page size**. A per-row query is easy to
write by accident -- ``package_service.progress`` is one call away and would be correct --
and it is invisible until somebody with two years of history opens the page. So the
statements are counted at three page sizes over a realistic history, and the counts have to
be the same number.

No timing assertion appears here. A wall-clock threshold on a shared machine is a flaky test
rather than a performance control; what is asserted is the work performed, which is what a
timing measurement would have been measuring.
"""

from __future__ import annotations

import gc
import pathlib
import sys

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import text

from tests.shipment_history_fixtures import (
    LIST_URL,
    add_event,
    add_package,
    detail_url,
    linked_and_signed_in,
    shipment,
)
from tests.shipment_history_fixtures import customer as make

MINE = "hanh@demo.example.com"

#: A history size a real customer reaches: about four years of weekly shipping.
REALISTIC_HISTORY = 60


def _mine(account_db):
    return make(account_db, full_name="Hanh Nguyen", email="hanh.canonical@demo.example.com")


@pytest.fixture
def history(account_client, account_db, account_users, captured_mail):
    """One account with a realistic history, each shipment carrying packages and events."""
    owner = _mine(account_db)
    rows = []
    for day in range(1, REALISTIC_HISTORY + 1):
        row = shipment(account_db, owner, days_ago=day)
        rows.append(row)
        for sequence in (1, 2, 3):
            add_package(account_db, row, sequence=sequence)
        add_event(account_db, row, days_ago=max(1, day - 1), text="In transit.")
        add_event(account_db, row, public=False, internal_detail="Internal.", days_ago=day)
    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=owner
    )
    client.get(LIST_URL)  # warm the session row's throttled `last_seen_at` update
    return client, owner, rows


def _count_statements(account_db, call):
    bind = account_db.get_bind()
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(" ".join(statement.split()))

    sa_event.listen(bind, "before_cursor_execute", record)
    try:
        result = call()
    finally:
        sa_event.remove(bind, "before_cursor_execute", record)
    return result, statements


# --- Query counts ------------------------------------------------------------------


def test_the_list_runs_the_same_number_of_statements_at_every_page_size(account_db, history):
    """Page sizes 1, 10 and 50 over sixty shipments with 180 packages and 120 events."""
    client, _, _ = history
    counts = {}
    for limit in (1, 10, 50):
        response, statements = _count_statements(
            account_db, lambda limit=limit: client.get(LIST_URL, params={"limit": limit})
        )
        assert response.status_code == 200, response.text
        assert len(response.json()["items"]) == limit
        counts[limit] = len(statements)

    assert len(set(counts.values())) == 1, counts


def test_the_list_is_a_small_fixed_number_of_statements(account_db, history):
    """The budget, written down and measured, so that adding a query is a test failure.

    Nine selects, in two groups:

    * **five before any shipment is touched** -- the session, the identity, the effective
      link, the linked customer and the organization's display timezone. Four of those five
      are the authorization chain, re-read on every request precisely because nothing is
      cached on the session row (T-14);
    * **four for the page itself** -- the ``COUNT(*)``, the page of shipment rows, and one
      grouped aggregate against each of ``shipment_packages`` and ``shipment_events``.

    The second group is the number that must not move with the page size, and the test
    above asserts that it does not.
    """
    client, _, _ = history
    response, statements = _count_statements(
        account_db, lambda: client.get(LIST_URL, params={"limit": 50})
    )
    assert response.status_code == 200

    selects = [line for line in statements if line.upper().startswith("SELECT")]
    assert len(selects) == 9, selects
    # Exactly one query against each of the two child tables, whatever the page holds.
    assert sum(1 for line in selects if "FROM shipment_packages" in line) == 1
    assert sum(1 for line in selects if "FROM shipment_events" in line) == 1
    assert sum(1 for line in selects if "FROM shipments" in line) == 2  # the count and the page
    # The authorization chain, read fresh: session, identity, link, customer.
    assert sum(1 for line in selects if "FROM customer_sessions" in line) == 1
    assert sum(1 for line in selects if "FROM customer_identity_links" in line) == 1
    assert sum(1 for line in selects if "FROM customers" in line) == 1


def test_the_aggregates_are_grouped_rather_than_joined(account_db, history):
    """A join would multiply rows; a grouped aggregate cannot.

    Asserted on the statement text as well as on the result, because "the counts happen to
    be right" and "the query cannot produce a duplicate" are different guarantees.
    """
    client, _, _ = history
    response, statements = _count_statements(
        account_db, lambda: client.get(LIST_URL, params={"limit": 50})
    )
    body = response.json()

    assert len(body["items"]) == 50
    assert len({item["shipment_reference"] for item in body["items"]}) == 50
    assert all(item["package_count_active"] == 3 for item in body["items"])

    page_query = next(
        line for line in statements if line.upper().startswith("SELECT") and "LIMIT" in line.upper()
    )
    assert "JOIN shipment_packages" not in page_query
    assert "JOIN shipment_events" not in page_query


def test_the_detail_does_not_scale_with_the_number_of_packages(account_db, history):
    """A detail on a three-package shipment and on a twenty-package one cost the same."""
    client, owner, rows = history
    big = rows[0]
    for sequence in range(4, 21):
        add_package(account_db, big, sequence=sequence)

    small = rows[1]
    _, small_statements = _count_statements(
        account_db, lambda: client.get(detail_url(small.public_id))
    )
    _, big_statements = _count_statements(account_db, lambda: client.get(detail_url(big.public_id)))

    assert len(small_statements) == len(big_statements)


def test_the_total_is_one_count_and_not_a_page_of_rows(account_db, history):
    """``total`` must not be computed by loading everything and measuring the list."""
    client, _, _ = history
    response, statements = _count_statements(
        account_db, lambda: client.get(LIST_URL, params={"limit": 1})
    )
    assert response.json()["total"] == REALISTIC_HISTORY
    assert any("count(" in line.lower() for line in statements)


# --- Bounds -------------------------------------------------------------------------


def test_the_response_size_is_bounded_by_the_page_size(account_db, history):
    """Sixty shipments, and the largest possible answer is fifty rows."""
    client, _, _ = history
    biggest = client.get(LIST_URL, params={"limit": 50})
    assert len(biggest.json()["items"]) == 50
    # There is no page size that returns all sixty.
    assert client.get(LIST_URL, params={"limit": 100}).status_code == 422
    assert len(biggest.content) < 60_000


def test_memory_does_not_grow_across_repeated_reads(account_db, history):
    """A page read many times allocates no more objects each time.

    A crude check, and a deliberate one: the failure it would catch is a cache or an
    accumulating list quietly retaining every row a session has ever read, which is exactly
    the kind of thing §24.12 forbids adding without evidence.
    """
    client, _, _ = history
    for _ in range(3):
        client.get(LIST_URL, params={"limit": 50})
    gc.collect()
    before = len(gc.get_objects())

    for _ in range(10):
        assert client.get(LIST_URL, params={"limit": 50}).status_code == 200
    gc.collect()
    after = len(gc.get_objects())

    # Ten full pages of fifty rows would be 500 retained items plus their nested objects.
    assert after - before < 5_000, (before, after)
    assert sys.getsizeof(client) < 100_000


def test_no_cache_was_introduced():
    """§24.12: no cache is added in Phase 11, and any future one must be isolated.

    Asserted structurally, because "we did not add a cache" is the kind of claim that is
    true until somebody adds one to fix a slow page.
    """
    import app.services.customer_account_shipment_service as service

    source = pathlib.Path(service.__file__).read_text(encoding="utf-8")
    for marker in ("lru_cache", "cached_property", "@cache", "_CACHE", "memoize"):
        assert marker not in source, marker


# --- Indexes -------------------------------------------------------------------------


def test_the_ownership_and_ordering_path_uses_an_index(account_db, history):
    """``EXPLAIN QUERY PLAN`` over the query the list actually runs.

    The ownership predicate is ``customer_id``, which carries its own index and is also the
    leading column of ``ix_shipments_customer_id_first_handoff_at``; the ordering reads
    ``booking_date``, which is indexed too. The assertion is that the planner uses an index
    rather than scanning ``shipments`` -- the difference between a customer with four years
    of history and every other customer's rows being read to answer them.
    """
    _, owner, _ = history
    plan = account_db.execute(
        text(
            "EXPLAIN QUERY PLAN "
            "SELECT id FROM shipments "
            "WHERE customer_id = :customer AND booking_state != 'draft' AND is_demo_record = 0 "
            "ORDER BY booking_date IS NULL, booking_date DESC, public_id ASC "
            "LIMIT 20"
        ),
        {"customer": owner.id},
    ).all()
    rendered = " ".join(str(row) for row in plan)

    assert "USING INDEX" in rendered.upper(), rendered
    assert "SCAN shipments" not in rendered, rendered


def test_the_package_aggregate_uses_the_shipment_index(account_db, history):
    _, _, rows = history
    ids = ",".join(str(row.id) for row in rows[:20])
    plan = account_db.execute(
        text(
            "EXPLAIN QUERY PLAN "
            f"SELECT shipment_id, COUNT(id) FROM shipment_packages WHERE shipment_id IN ({ids}) "
            "GROUP BY shipment_id"
        )
    ).all()
    rendered = " ".join(str(row) for row in plan).upper()
    assert "USING INDEX" in rendered or "USING COVERING INDEX" in rendered, rendered
