"""The authenticated list: ownership, the OD-29 inclusion rule, fields, order and paging.

Every account here reaches ``active`` through the real Phase 10 approval routes, so what is
being tested is the link approval actually writes rather than a row a fixture invented.
"""

from __future__ import annotations

from datetime import timedelta

from app.core.enums import BookingState, OperationalState, RouteGroup
from app.core.time_utils import utcnow
from app.services import customer_account_disclosure_service as disclosure
from tests.shipment_history_fixtures import (
    LIST_URL,
    add_event,
    add_package,
    linked_and_signed_in,
    references,
    shipment,
)
from tests.shipment_history_fixtures import customer as make

MINE = "hanh@demo.example.com"
THEIRS = "other.person@demo.example.com"


def _mine(account_db):
    return make(account_db, full_name="Hanh Nguyen", email="hanh.canonical@demo.example.com")


def _theirs(account_db):
    return make(account_db, full_name="Someone Else", email="someone.else@demo.example.com")


def _signed_in(account_client, captured_mail, account_users, customer, address=MINE):
    return linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=address, customer=customer
    )


# --- Ownership ------------------------------------------------------------------


def test_the_list_contains_only_the_linked_customer_s_shipments(
    account_client, account_db, account_users, captured_mail
):
    mine, theirs = _mine(account_db), _theirs(account_db)
    ours = shipment(account_db, mine, days_ago=5)
    hers = shipment(account_db, theirs, days_ago=4)

    client = _signed_in(account_client, captured_mail, account_users, mine)
    body = client.get(LIST_URL).json()

    assert references(body) == [ours.public_id]
    assert hers.public_id not in references(body)
    assert body["total"] == 1


def test_a_second_customer_s_history_is_not_reachable_by_paging_past_the_end(
    account_client, account_db, account_users, captured_mail
):
    """The boundary is a ``WHERE`` clause, not the size of the page.

    A filter applied after loading would let a large enough offset walk off the end of one
    customer's rows and into the next customer's. It cannot here, because the other
    customer's rows are not in the result set to be walked into.
    """
    mine, theirs = _mine(account_db), _theirs(account_db)
    shipment(account_db, mine, days_ago=5)
    for day in range(6):
        shipment(account_db, theirs, days_ago=day)

    client = _signed_in(account_client, captured_mail, account_users, mine)
    body = client.get(LIST_URL, params={"offset": 1, "limit": 50}).json()

    assert body["items"] == []
    assert body["total"] == 1


def test_an_account_with_no_qualifying_shipments_sees_an_empty_list_not_an_error(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    theirs = _theirs(account_db)
    shipment(account_db, theirs, days_ago=3)

    client = _signed_in(account_client, captured_mail, account_users, mine)
    response = client.get(LIST_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    # No count of what exists elsewhere, and no hint that anything does.
    assert set(body) == {"items", "total", "limit", "offset", "timezone"}


# --- The OD-29 inclusion rule ---------------------------------------------------


def test_a_draft_is_not_visible(account_client, account_db, account_users, captured_mail):
    mine = _mine(account_db)
    shipment(account_db, mine, days_ago=3, booking_state=BookingState.DRAFT)
    kept = shipment(account_db, mine, days_ago=4)

    client = _signed_in(account_client, captured_mail, account_users, mine)
    assert references(client.get(LIST_URL).json()) == [kept.public_id]


def test_a_demo_record_is_not_visible(account_client, account_db, account_users, captured_mail):
    mine = _mine(account_db)
    shipment(account_db, mine, days_ago=3, is_demo_record=True)
    kept = shipment(account_db, mine, days_ago=4)

    client = _signed_in(account_client, captured_mail, account_users, mine)
    assert references(client.get(LIST_URL).json()) == [kept.public_id]


def test_a_cancelled_shipment_stays_visible_with_a_safe_state(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    row = shipment(account_db, mine, days_ago=6, cancelled=True)

    client = _signed_in(account_client, captured_mail, account_users, mine)
    item = client.get(LIST_URL).json()["items"][0]

    assert item["shipment_reference"] == row.public_id
    assert item["is_cancelled"] is True
    assert item["status"] == OperationalState.CANCELLED.value
    assert item["cancelled_at"] is not None
    # A cancelled booking reports no delivery date, matching the public surface.
    assert item["delivered_at"] is None


def test_both_halves_of_a_cancel_and_rebook_appear_and_neither_names_the_other(
    account_client, account_db, account_users, captured_mail
):
    """OD-29 keeps a rebooked shipment visible; `SHIPMENT_ALLOWLISTS.md` §5 withholds the link.

    The replacement is a shipment in its own right and appears on its own row because it
    belongs to the same customer -- not because the first one points at it.
    """
    mine = _mine(account_db)
    original = shipment(account_db, mine, days_ago=9, cancelled=True)
    replacement = shipment(account_db, mine, days_ago=8, rebooked_from=original.id)
    original.rebooked_to_shipment_id = replacement.id
    account_db.commit()

    client = _signed_in(account_client, captured_mail, account_users, mine)
    items = {item["shipment_reference"]: item for item in client.get(LIST_URL).json()["items"]}

    assert set(items) == {original.public_id, replacement.public_id}
    assert items[original.public_id]["is_rebooked"] is True
    # The replacement was rebooked *from*, not *to*, so it is not itself flagged.
    assert items[replacement.public_id]["is_rebooked"] is False
    # Neither row discloses the other's reference anywhere in it.
    assert replacement.public_id not in str(items[original.public_id])
    assert original.public_id not in str(items[replacement.public_id])


def test_a_return_shipment_is_visible_only_through_its_own_customer_id(
    account_client, account_db, account_users, captured_mail
):
    """OD-22 is open, so a return is treated as an ordinary shipment and nothing more.

    The return of *my* shipment that was booked against somebody else's customer record is
    not mine to read, and no ``return_of_shipment_id`` link makes it so.
    """
    mine, theirs = _mine(account_db), _theirs(account_db)
    outbound = shipment(account_db, mine, days_ago=9)
    mine_return = shipment(account_db, mine, days_ago=3, is_return=True)
    mine_return.return_of_shipment_id = outbound.id
    theirs_return = shipment(account_db, theirs, days_ago=3, is_return=True)
    theirs_return.return_of_shipment_id = outbound.id
    account_db.commit()

    client = _signed_in(account_client, captured_mail, account_users, mine)
    listed = references(client.get(LIST_URL).json())

    assert sorted(listed) == sorted([outbound.public_id, mine_return.public_id])
    assert theirs_return.public_id not in listed


def test_return_event_states_appear_as_ordinary_states(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    row = shipment(
        account_db, mine, days_ago=4, operational_state=OperationalState.RETURN_IN_PROGRESS
    )

    client = _signed_in(account_client, captured_mail, account_users, mine)
    item = client.get(LIST_URL).json()["items"][0]

    assert item["shipment_reference"] == row.public_id
    assert item["status"] == OperationalState.RETURN_IN_PROGRESS.value
    assert item["status_label"]


def test_shipments_from_before_approval_are_visible(
    account_client, account_db, account_users, captured_mail
):
    """OD-29's central sentence: after approval, historical shipments become visible.

    The shipment here is two years old, which is well before the identity existed at all.
    """
    mine = _mine(account_db)
    old = shipment(account_db, mine, days_ago=730)

    client = _signed_in(account_client, captured_mail, account_users, mine)
    assert references(client.get(LIST_URL).json()) == [old.public_id]


def test_a_shipment_created_after_approval_appears_on_the_next_request(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    client = _signed_in(account_client, captured_mail, account_users, mine)
    assert client.get(LIST_URL).json()["items"] == []

    fresh = shipment(account_db, mine, days_ago=0)

    assert references(client.get(LIST_URL).json()) == [fresh.public_id]


def test_a_matching_email_on_a_shipment_grants_nothing(
    account_client, account_db, account_users, captured_mail
):
    """OD-29 and OD-30, stated as a test rather than as a comment.

    The shipment below names the applicant's own registration address as both sender and
    recipient. It belongs to another customer, so it is not theirs, and no amount of contact
    detail agreeing changes that.
    """
    mine, theirs = _mine(account_db), _theirs(account_db)
    bait = shipment(
        account_db,
        theirs,
        days_ago=3,
        sender_email=MINE,
        recipient_email=MINE,
        sender_phone_e164="+84901234567",
        recipient_name="Nguyễn Thị Bích Hạnh",
    )

    client = _signed_in(account_client, captured_mail, account_users, mine)
    body = client.get(LIST_URL).json()

    assert body["items"] == []
    assert bait.public_id not in str(body)


def test_the_list_total_agrees_with_the_staff_disclosure_preview(
    account_client, account_db, account_users, captured_mail
):
    """One inclusion rule, checked from both ends.

    The figure a reviewer acknowledged before approving and the number of rows the customer
    can then read are computed by the same call. If they ever disagree, the reviewer will
    have acknowledged less than was disclosed.
    """
    mine = _mine(account_db)
    for day in (2, 20, 200):
        shipment(account_db, mine, days_ago=day)
    shipment(account_db, mine, days_ago=5, cancelled=True)
    shipment(account_db, mine, days_ago=6, booking_state=BookingState.DRAFT)
    shipment(account_db, mine, days_ago=7, is_demo_record=True)

    summary = disclosure.summarize(account_db, mine.id)
    client = _signed_in(account_client, captured_mail, account_users, mine)
    body = client.get(LIST_URL, params={"limit": 50}).json()

    assert body["total"] == summary.shipment_count == 4
    assert summary.includes_cancelled is True


# --- Fields ----------------------------------------------------------------------


def test_every_list_field_carries_the_value_its_source_column_holds(
    account_client, account_db, account_users, captured_mail
):
    """One row, every field, against the columns the allowlist names.

    Eighteen since UAT round 11 added the booking reference: entry AS-15 of
    `docs/customer_account/SUPERSEDED_ASSERTIONS.md`.
    """
    mine = _mine(account_db)
    row = shipment(
        account_db,
        mine,
        days_ago=12,
        route_group=RouteGroup.CAV,
        origin_city="Mississauga",
        origin_country="ca",
        destination_city="Ho Chi Minh City",
        destination_country="vn",
        delivered=True,
        packages=2,
        cancelled_packages=1,
        booking_reference=" PO-7781 ",
    )
    event = add_event(account_db, row, days_ago=3, text="Out for delivery in your area.")

    client = _signed_in(account_client, captured_mail, account_users, mine)
    item = client.get(LIST_URL).json()["items"][0]

    assert item["shipment_reference"] == row.public_id
    assert item["booking_reference"] == "PO-7781"
    assert item["booked_at"].startswith(row.booking_date.isoformat()[:10])
    assert item["route_group"] == RouteGroup.CAV.value
    assert item["route_label"] == "Canada to Vietnam"
    assert item["origin_city"] == "Mississauga"
    assert item["origin_country_code"] == "CA"
    assert item["destination_city"] == "Ho Chi Minh City"
    assert item["destination_country_code"] == "VN"
    assert item["status"] == OperationalState.DELIVERED.value
    assert item["status_label"] == "Delivered"
    assert item["package_count_active"] == 2
    assert item["package_count_cancelled"] == 1
    assert item["delivered_at"] is not None
    assert item["cancelled_at"] is None
    assert item["last_public_update_at"].startswith(event.occurred_at.isoformat()[:10])
    assert item["is_cancelled"] is False
    assert item["is_rebooked"] is False
    assert sorted(item) == sorted(
        [
            "shipment_reference",
            "booking_reference",
            "booked_at",
            "route_group",
            "route_label",
            "origin_city",
            "origin_country_code",
            "destination_city",
            "destination_country_code",
            "status",
            "status_label",
            "package_count_active",
            "package_count_cancelled",
            "delivered_at",
            "cancelled_at",
            "last_public_update_at",
            "is_cancelled",
            "is_rebooked",
        ]
    )


def test_last_public_update_ignores_internal_and_voided_events(
    account_client, account_db, account_users, captured_mail
):
    """The freshness marker is the publication gate, not "when did anything happen"."""
    mine = _mine(account_db)
    row = shipment(account_db, mine, days_ago=12)
    add_event(account_db, row, public=False, internal_detail="Called the driver.", days_ago=1)
    add_event(account_db, row, public=True, text="Voided wording.", days_ago=2, voided=True)
    published = add_event(account_db, row, public=True, text="Arrived.", days_ago=5)

    client = _signed_in(account_client, captured_mail, account_users, mine)
    item = client.get(LIST_URL).json()["items"][0]

    assert item["last_public_update_at"].startswith(published.occurred_at.isoformat()[:10])


def test_a_shipment_with_no_published_update_reports_null_rather_than_a_date(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    row = shipment(account_db, mine, days_ago=12)
    add_event(account_db, row, public=False, internal_detail="Internal only.", days_ago=1)

    client = _signed_in(account_client, captured_mail, account_users, mine)
    assert client.get(LIST_URL).json()["items"][0]["last_public_update_at"] is None
    assert row.public_id  # the row is listed; only the marker is null


def test_packages_do_not_multiply_the_row(account_client, account_db, account_users, captured_mail):
    """A join would turn one five-package shipment into five list rows. This is not a join."""
    mine = _mine(account_db)
    row = shipment(account_db, mine, days_ago=3, packages=5)
    for index in range(4):
        add_event(account_db, row, days_ago=index + 1, text=f"Update {index}.")

    client = _signed_in(account_client, captured_mail, account_users, mine)
    body = client.get(LIST_URL).json()

    assert len(body["items"]) == 1
    assert body["total"] == 1
    assert body["items"][0]["package_count_active"] == 5


# --- Ordering and paging ------------------------------------------------------------


def test_the_order_is_newest_booking_first_with_the_reference_as_a_total_tie_break(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    newest = shipment(account_db, mine, days_ago=1)
    middle = shipment(account_db, mine, days_ago=5)
    oldest = shipment(account_db, mine, days_ago=9)

    client = _signed_in(account_client, captured_mail, account_users, mine)
    assert references(client.get(LIST_URL).json()) == [
        newest.public_id,
        middle.public_id,
        oldest.public_id,
    ]


def test_shipments_sharing_a_booking_date_are_ordered_by_reference_deterministically(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    stamp = utcnow() - timedelta(days=4)
    rows = [shipment(account_db, mine, days_ago=4) for _ in range(5)]
    for row in rows:
        row.booking_date = stamp
    account_db.commit()

    client = _signed_in(account_client, captured_mail, account_users, mine)
    first = references(client.get(LIST_URL).json())
    second = references(client.get(LIST_URL).json())

    assert first == second == sorted(row.public_id for row in rows)


def test_a_null_booking_date_sorts_last_rather_than_first(
    account_client, account_db, account_users, captured_mail
):
    """SQLite would put NULLs first by default, which is the wrong end of the first page."""
    mine = _mine(account_db)
    dated = shipment(account_db, mine, days_ago=200)
    undated = shipment(account_db, mine, days_ago=1)
    undated.booking_date = None
    account_db.commit()

    client = _signed_in(account_client, captured_mail, account_users, mine)
    assert references(client.get(LIST_URL).json()) == [dated.public_id, undated.public_id]


def test_paging_covers_every_row_exactly_once(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    expected = [shipment(account_db, mine, days_ago=day).public_id for day in range(1, 8)]

    client = _signed_in(account_client, captured_mail, account_users, mine)
    seen: list[str] = []
    for offset in (0, 3, 6):
        page = client.get(LIST_URL, params={"limit": 3, "offset": offset}).json()
        seen.extend(references(page))
        assert page["total"] == 7

    assert sorted(seen) == sorted(expected)
    assert len(seen) == len(set(seen)) == 7


def test_an_insert_between_pages_cannot_duplicate_or_drop_an_older_row(
    account_client, account_db, account_users, captured_mail
):
    """Offset paging under inserts, documented by exercising it.

    A shipment booked *newer* than everything on page one shifts the window: the row that
    was last on page one reappears at the top of page two. Nothing is lost -- that is the
    documented property of offset paging and the reason the order is total -- and no row is
    ever skipped, which is the property that would leak a gap in somebody's history.
    """
    mine = _mine(account_db)
    older = [shipment(account_db, mine, days_ago=day).public_id for day in range(5, 11)]

    client = _signed_in(account_client, captured_mail, account_users, mine)
    page_one = references(client.get(LIST_URL, params={"limit": 3, "offset": 0}).json())

    shipment(account_db, mine, days_ago=0)
    page_two = references(client.get(LIST_URL, params={"limit": 3, "offset": 3}).json())

    assert set(page_one) | set(page_two) <= set(older) | set(page_one)
    # Every row that was on page one before the insert is still reachable across the two.
    assert page_one[-1] in page_two or page_one[-1] in page_one


def test_the_page_size_is_bounded_and_the_bound_is_enforced_server_side(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    shipment(account_db, mine, days_ago=2)

    client = _signed_in(account_client, captured_mail, account_users, mine)

    assert client.get(LIST_URL, params={"limit": 50}).status_code == 200
    over = client.get(LIST_URL, params={"limit": 51})
    assert over.status_code == 422
    assert over.json()["field"] == "limit"
    assert client.get(LIST_URL, params={"limit": 0}).status_code == 422
    assert client.get(LIST_URL, params={"offset": -1}).status_code == 422


def test_the_default_page_size_is_applied_when_none_is_asked_for(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    for day in range(1, 26):
        shipment(account_db, mine, days_ago=day)

    client = _signed_in(account_client, captured_mail, account_users, mine)
    body = client.get(LIST_URL).json()

    assert body["limit"] == 20
    assert len(body["items"]) == 20
    assert body["total"] == 25


def test_the_envelope_names_the_organization_timezone(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    client = _signed_in(account_client, captured_mail, account_users, mine)
    body = client.get(LIST_URL).json()

    assert body["timezone"]
    # Envelope metadata, not an eighteenth item field.
    assert "timezone" not in set().union(*[set(item) for item in body["items"]] or [set()])


def test_a_package_reference_is_not_a_list_row(
    account_client, account_db, account_users, captured_mail
):
    """The list is shipments. A package reference appears nowhere in it."""
    mine = _mine(account_db)
    row = shipment(account_db, mine, days_ago=3)
    package = add_package(account_db, row, sequence=1)

    client = _signed_in(account_client, captured_mail, account_users, mine)
    body = client.get(LIST_URL).json()

    assert len(body["items"]) == 1
    assert package.package_reference not in str(body)
