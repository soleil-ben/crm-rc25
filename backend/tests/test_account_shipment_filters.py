"""The four approved filters, and the several that are deliberately absent.

UAT round 10 added a fifth, the keyword search `q` (DEC-0156); it has its own suite,
`test_account_shipment_search.py`.

`SHIPMENT_ALLOWLISTS.md` §3.2 approves filtering by status group and by date range; §3.3,
added by **OD-41** on 2026-09-21, adds an **exact** Solaris shipment reference and an
**exact** route group. The absence tests matter as much as the presence ones: a recipient
search, a carrier-number search and a sort parameter are all plausible, all were
considered, and none is approved -- so each is asserted *not* to exist, rather than left to
be noticed missing.

The two tests that used to assert the *absence* of a reference filter and a route filter
are superseded by OD-41 and are registered as **AS-06** and **AS-07** in
`docs/customer_account/SUPERSEDED_ASSERTIONS.md`; the free-text absence AS-06's
replacement kept is superseded by the keyword search, **AS-08**.
"""

from __future__ import annotations

from datetime import UTC, timedelta

from app.core.config import settings
from app.core.enums import OperationalState, RouteGroup
from app.core.time_utils import in_zone, utcnow
from app.services.customer_account_shipment_service import (
    MAX_DATE_RANGE_DAYS,
    MAX_FILTER_VALUE_LENGTH,
    ROUTE_GROUP_VALUES,
    STATUS_GROUPS,
)
from tests.shipment_history_fixtures import (
    LIST_URL,
    linked_and_signed_in,
    reference_for,
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


# --- Status groups ---------------------------------------------------------------


def test_the_status_groups_partition_the_operational_vocabulary():
    """Four groups, every state in exactly one. A partition, not four overlapping filters.

    A state in no group would be unreachable by any filter; a state in two would make the
    groups' counts add up to more than the list. Both are the kind of thing that is obvious
    once written down and invisible otherwise.
    """
    covered = [value for group in STATUS_GROUPS.values() for value in group]
    assert sorted(covered) == sorted({member.value for member in OperationalState})
    assert len(covered) == len(set(covered))
    assert set(STATUS_GROUPS) == {"in_progress", "delivered", "cancelled", "exception"}


def test_each_status_group_returns_its_own_shipments(
    account_client, account_db, account_users, captured_mail
):
    owner = _mine(account_db)
    moving = shipment(account_db, owner, days_ago=3)
    done = shipment(account_db, owner, days_ago=4, delivered=True)
    stopped = shipment(account_db, owner, days_ago=5, cancelled=True)
    problem = shipment(account_db, owner, days_ago=6, operational_state=OperationalState.EXCEPTION)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    expected = {
        "in_progress": [moving.public_id],
        "delivered": [done.public_id],
        "cancelled": [stopped.public_id],
        "exception": [problem.public_id],
    }
    for group, references_expected in expected.items():
        body = client.get(LIST_URL, params={"status_group": group}).json()
        assert references(body) == references_expected, group
        assert body["total"] == 1, group


def test_the_return_states_are_in_the_exception_group(
    account_client, account_db, account_users, captured_mail
):
    """OD-22 is open, so returns do not get a group of their own.

    A ``returns`` filter would be the first half of a return workflow this phase is
    forbidden to start. Both return states are visible; they are grouped with the other
    things that need a person to look at them.
    """
    owner = _mine(account_db)
    in_progress = shipment(
        account_db, owner, days_ago=3, operational_state=OperationalState.RETURN_IN_PROGRESS
    )
    returned = shipment(account_db, owner, days_ago=4, operational_state=OperationalState.RETURNED)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    body = client.get(LIST_URL, params={"status_group": "exception"}).json()
    assert sorted(references(body)) == sorted([in_progress.public_id, returned.public_id])
    assert "returns" not in STATUS_GROUPS


def test_an_unknown_status_group_is_refused_by_name(
    account_client, account_db, account_users, captured_mail
):
    """Refused, not ignored.

    Silently dropping the filter would let a screen believe it had filtered and show a
    customer rows it thought it had excluded. Naming the field is safe: the vocabulary is a
    property of the API, not of any account.
    """
    owner = _mine(account_db)
    shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    response = client.get(LIST_URL, params={"status_group": "everything"})
    assert response.status_code == 422
    assert response.json()["field"] == "status_group"
    # And the refusal says nothing about what the account holds.
    assert "shipment" not in response.json()["message"].lower()


def test_a_status_group_cannot_carry_sql(account_client, account_db, account_users, captured_mail):
    """The filter is a key into a dictionary of constants, so there is nothing to inject.

    No client value ever reaches a query: the key selects a tuple this module wrote, and an
    unrecognized key is refused before any query runs.
    """
    owner = _mine(account_db)
    kept = shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    for attack in (
        "delivered' OR '1'='1",
        "delivered; DROP TABLE shipments",
        "delivered UNION SELECT 1",
        "*",
    ):
        response = client.get(LIST_URL, params={"status_group": attack})
        assert response.status_code == 422, attack

    # The table is still there and still answers.
    assert references(client.get(LIST_URL).json()) == [kept.public_id]


# --- Date range -------------------------------------------------------------------


def test_the_date_range_is_inclusive_of_both_ends_in_the_organization_timezone(
    account_client, account_db, account_users, captured_mail
):
    """Boundaries are cut at local midnight, then converted to UTC (DEC-0076).

    A parcel booked late in the evening in Mississauga belongs to that day in the filter.
    Cutting on UTC midnight instead would move it to the next day for four hours of every
    day, which is the kind of error nobody sees and everybody argues about.
    """
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=5)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    timezone_name = client.get(LIST_URL).json()["timezone"]
    local_day = in_zone(row.booking_date, timezone_name).date()

    inside = client.get(
        LIST_URL,
        params={"booked_from": local_day.isoformat(), "booked_to": local_day.isoformat()},
    ).json()
    assert references(inside) == [row.public_id]

    before = client.get(
        LIST_URL,
        params={
            "booked_from": (local_day - timedelta(days=3)).isoformat(),
            "booked_to": (local_day - timedelta(days=1)).isoformat(),
        },
    ).json()
    assert before["items"] == []

    after = client.get(
        LIST_URL,
        params={
            "booked_from": (local_day + timedelta(days=1)).isoformat(),
            "booked_to": (local_day + timedelta(days=3)).isoformat(),
        },
    ).json()
    assert after["items"] == []


def test_a_late_evening_local_booking_falls_on_its_local_day(
    account_client, account_db, account_users, captured_mail
):
    """The boundary case the timezone rule exists for, exercised directly."""
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=2)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)
    timezone_name = client.get(LIST_URL).json()["timezone"]

    local = in_zone(utcnow(), timezone_name).replace(hour=23, minute=30) - timedelta(days=2)
    # Stored as naive UTC, the way every timestamp in this system is. 23:30 local is the
    # next day in UTC for a western-hemisphere office, which is exactly the case that a
    # UTC-midnight boundary would put on the wrong day.
    row.booking_date = local.astimezone(UTC).replace(tzinfo=None)
    account_db.commit()
    assert row.booking_date.date() != local.date()

    day = local.date()
    body = client.get(
        LIST_URL, params={"booked_from": day.isoformat(), "booked_to": day.isoformat()}
    ).json()
    assert references(body) == [row.public_id]


def test_a_shipment_with_no_booking_date_is_outside_every_range(
    account_client, account_db, account_users, captured_mail
):
    """Outside every range rather than inside all of them, which is what a filter means."""
    owner = _mine(account_db)
    undated = shipment(account_db, owner, days_ago=5)
    undated.booking_date = None
    account_db.commit()
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    today = utcnow().date()
    body = client.get(
        LIST_URL,
        params={
            "booked_from": (today - timedelta(days=300)).isoformat(),
            "booked_to": today.isoformat(),
        },
    ).json()
    assert body["items"] == []
    # It is still in the unfiltered list; only the date filter excludes it.
    assert references(client.get(LIST_URL).json()) == [undated.public_id]


def test_the_date_range_is_bounded(account_client, account_db, account_users, captured_mail):
    owner = _mine(account_db)
    shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)
    today = utcnow().date()

    ok = client.get(
        LIST_URL,
        params={
            "booked_from": (today - timedelta(days=MAX_DATE_RANGE_DAYS)).isoformat(),
            "booked_to": today.isoformat(),
        },
    )
    assert ok.status_code == 200

    too_wide = client.get(
        LIST_URL,
        params={
            "booked_from": (today - timedelta(days=MAX_DATE_RANGE_DAYS + 1)).isoformat(),
            "booked_to": today.isoformat(),
        },
    )
    assert too_wide.status_code == 422
    assert too_wide.json()["field"] == "booked_to"


def test_a_one_sided_range_is_bounded_too(account_client, account_db, account_users, captured_mail):
    """ "Everything before this date" is a full scan with a friendly name.

    The missing end is filled in at the maximum span, so a one-sided filter costs the same
    as a two-sided one.
    """
    owner = _mine(account_db)
    recent = shipment(account_db, owner, days_ago=5)
    ancient = shipment(account_db, owner, days_ago=MAX_DATE_RANGE_DAYS + 50)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    today = utcnow().date()
    body = client.get(LIST_URL, params={"booked_to": today.isoformat()}).json()
    assert references(body) == [recent.public_id]
    assert ancient.public_id not in references(body)


def test_only_one_date_spelling_is_accepted(
    account_client, account_db, account_users, captured_mail
):
    """Canonical parsing. ``date.fromisoformat`` would accept several ISO 8601 spellings.

    A filter with more than one spelling behaves differently depending on which one a client
    chose, so the shape is checked before the parser ever sees the value.
    """
    owner = _mine(account_db)
    shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    shapes = set()
    for bad in (
        "20260101",
        "2026-W01-1",
        "01/01/2026",
        "2026-1-1",
        "2026-01-01T00:00:00",
        "x" * 200,
    ):
        response = client.get(LIST_URL, params={"booked_from": bad})
        assert response.status_code == 422, bad
        body = response.json()
        assert body["field"] == "booked_from", bad
        shapes.add(tuple(sorted(body)))

    # One shape for every malformed spelling, including the oversized one. A FastAPI
    # `Query(max_length=...)` would have answered that last case with the framework's own
    # 422 body instead, which is a second failure shape on a route that should have one.
    assert shapes == {("code", "field", "message")}

    # An empty value is "no filter", not a malformed one.
    assert client.get(LIST_URL, params={"booked_from": ""}).status_code == 200


def test_an_inverted_range_is_refused(account_client, account_db, account_users, captured_mail):
    owner = _mine(account_db)
    shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)
    today = utcnow().date()

    response = client.get(
        LIST_URL,
        params={
            "booked_from": today.isoformat(),
            "booked_to": (today - timedelta(days=5)).isoformat(),
        },
    )
    assert response.status_code == 422
    assert response.json()["field"] == "booked_to"


def test_the_filters_combine(account_client, account_db, account_users, captured_mail):
    owner = _mine(account_db)
    wanted = shipment(account_db, owner, days_ago=5, delivered=True)
    shipment(account_db, owner, days_ago=5)  # right date, wrong group
    shipment(account_db, owner, days_ago=200, delivered=True)  # right group, wrong date
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    today = utcnow().date()
    body = client.get(
        LIST_URL,
        params={
            "status_group": "delivered",
            "booked_from": (today - timedelta(days=30)).isoformat(),
            "booked_to": today.isoformat(),
        },
    ).json()
    assert references(body) == [wanted.public_id]
    assert body["total"] == 1


# --- What is deliberately absent -----------------------------------------------------


# --- OD-41: the exact reference filter -----------------------------------------------


def test_the_reference_filter_is_exact_and_unknown_parameters_are_ignored(
    account_client, account_db, account_users, captured_mail
):
    """The whole reference matches; a fragment of it matches nothing.

    This test replaces `test_there_is_no_reference_search`. See
    `docs/customer_account/SUPERSEDED_ASSERTIONS.md`, entries AS-06 and AS-08.

    Three claims in one place, because they are the same claim from three sides: the filter
    works, it is **exact**, and the parameters that are not filters are still ignored. `q`
    left that list in UAT round 10, when it became the keyword search (DEC-0156); the
    partial matching lives there, and `reference` stays exact.
    """
    owner = _mine(account_db)
    wanted = shipment(account_db, owner, days_ago=3)
    other = shipment(account_db, owner, days_ago=4)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    body = client.get(LIST_URL, params={"reference": wanted.public_id}).json()
    assert references(body) == [wanted.public_id]
    assert body["total"] == 1

    # A prefix is not a reference. Every one of these would match under a `LIKE`.
    for fragment in (
        wanted.public_id[:-1],
        wanted.public_id[:8],
        wanted.public_id[4:],
        "SX-",
        wanted.public_id[:-1] + "%",
    ):
        body = client.get(LIST_URL, params={"reference": fragment}).json()
        assert references(body) == [], fragment
        assert body["total"] == 0, fragment

    # The parameters the original absence test named, other than `q`, are still not filters.
    for parameter in ("search", "shipment_reference"):
        body = client.get(LIST_URL, params={parameter: wanted.public_id}).json()
        assert sorted(references(body)) == sorted([wanted.public_id, other.public_id]), parameter


def test_the_reference_filter_normalizes_presentation_before_matching(
    account_client, account_db, account_users, captured_mail
):
    """Lower case, padding and an autocorrected en dash still find the customer's own row.

    Exactness is about *content*, not about how a mail client rendered a hyphen. The filter
    runs the same `parse_public_reference` the detail route runs, so a reference pasted out
    of an email matches, and a reference with a character changed does not.
    """
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    for spelling in (
        row.public_id.lower(),
        f"  {row.public_id}  ",
        row.public_id.replace("-", "\u2013"),
    ):
        body = client.get(LIST_URL, params={"reference": spelling}).json()
        assert references(body) == [row.public_id], spelling


def test_an_unknown_and_a_foreign_reference_are_the_same_empty_page(
    account_client, account_db, account_users, captured_mail
):
    """The filter is not an ownership oracle, and the proof is byte equality.

    An unknown-but-well-formed reference and another customer's real reference must produce
    the same status, the same body and the same headers. If they differed in any of the
    three -- even in `total`, even in a header -- the list would answer "that shipment
    exists but is not yours", which is precisely what §3.3 forbids.
    """
    owner = _mine(account_db)
    stranger = make(account_db, full_name="Stranger", email="stranger@demo.example.com")
    shipment(account_db, owner, days_ago=3)
    theirs = shipment(account_db, stranger, days_ago=3)
    unknown = reference_for(RouteGroup.CAV.value)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    first = client.get(LIST_URL, params={"reference": unknown})
    second = client.get(LIST_URL, params={"reference": theirs.public_id})

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["items"] == []
    assert first.json()["total"] == 0
    for header in ("cache-control", "content-type", "referrer-policy", "x-robots-tag"):
        assert first.headers.get(header) == second.headers.get(header), header


def test_a_package_reference_matches_nothing_rather_than_being_refused(
    account_client, account_db, account_users, captured_mail
):
    """A well-formed package reference is a second identifier space. It gets one answer.

    Refusing it by name, or answering it, would both say that the space exists and that the
    list knows about it. It produces the same empty page as anything else that is not a
    Solaris Shipment ID.
    """
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3, packages=2)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)
    package_reference = f"{row.public_id}-01"

    response = client.get(LIST_URL, params={"reference": package_reference})
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0


def test_a_malformed_reference_filter_is_an_empty_page_not_a_named_refusal(
    account_client, account_db, account_users, captured_mail
):
    """Junk in the box is "no match", not "that is not a reference".

    The grammar of a Solaris reference is not a secret, but a filter that told a caller
    *which* of their guesses was well formed would be a grammar oracle, and this surface
    answers one way.
    """
    owner = _mine(account_db)
    shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    for junk in ("not-a-reference", "SX--", "../../etc/passwd", "SX-CAV-000000000000", "%"):
        response = client.get(LIST_URL, params={"reference": junk})
        assert response.status_code == 200, junk
        assert response.json()["items"] == [], junk


def test_an_empty_reference_filter_clears_rather_than_matches_nothing(
    account_client, account_db, account_users, captured_mail
):
    """An empty form field is not a filter. Clearing the box shows the list again."""
    owner = _mine(account_db)
    first = shipment(account_db, owner, days_ago=3)
    second = shipment(account_db, owner, days_ago=4)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    for empty in ("", "   "):
        body = client.get(LIST_URL, params={"reference": empty}).json()
        assert sorted(references(body)) == sorted([first.public_id, second.public_id])


def test_an_oversized_reference_filter_uses_this_surfaces_validation_body(
    account_client, account_db, account_users, captured_mail
):
    """Over the filter bound is refused by the service, with this surface's own shape.

    Not FastAPI's 422: that body is a list of constraint objects echoing the submitted
    value back, and two malformed-filter shapes on one route is the defect Phase 11 found
    and fixed for dates (`PROJECT_STATUS.md` §25.14).
    """
    owner = _mine(account_db)
    shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    response = client.get(LIST_URL, params={"reference": "S" * (MAX_FILTER_VALUE_LENGTH + 1)})
    assert response.status_code == 422
    body = response.json()
    assert sorted(body) == ["code", "field", "message"]
    assert body["field"] == "reference"
    assert "S" * 20 not in body["message"]


def test_the_reference_filter_cannot_carry_sql(
    account_client, account_db, account_users, captured_mail
):
    """Nothing a caller writes reaches SQL as SQL, and the rows are still there afterwards."""
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    for attempt in (
        "' OR '1'='1",
        "SX-CAV-AAAAAAAAAAAA' OR 1=1 --",
        "'; DROP TABLE shipments; --",
    ):
        response = client.get(LIST_URL, params={"reference": attempt})
        assert response.status_code in (200, 422), attempt
        if response.status_code == 200:
            assert response.json()["items"] == [], attempt

    assert references(client.get(LIST_URL).json()) == [row.public_id]


# --- OD-41: the exact route-group filter ---------------------------------------------


def test_the_route_group_filter_accepts_only_the_vocabulary(
    account_client, account_db, account_users, captured_mail
):
    """A valid group narrows; anything else is refused by name, before a query is built.

    This test replaces `test_there_is_no_route_filter`. See
    `docs/customer_account/SUPERSEDED_ASSERTIONS.md`, entry AS-07.

    Refusing by name is safe here for the reason it is safe for the status group: the route
    vocabulary is a property of the API, not of anybody's shipments, so the refusal says
    nothing about any account.
    """
    owner = _mine(account_db)
    cav = shipment(account_db, owner, days_ago=3, route_group=RouteGroup.CAV)
    vca = shipment(account_db, owner, days_ago=4, route_group=RouteGroup.VCA)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    assert references(client.get(LIST_URL, params={"route_group": "CAV"}).json()) == [cav.public_id]
    assert references(client.get(LIST_URL, params={"route_group": "VCA"}).json()) == [vca.public_id]
    # Presentation, not content: a lower-case spelling of a real group is the same group.
    assert references(client.get(LIST_URL, params={"route_group": "cav"}).json()) == [cav.public_id]
    # A group with no rows is an empty page, not a refusal: the group exists.
    assert references(client.get(LIST_URL, params={"route_group": "XUS"}).json()) == []

    for invalid in ("CAV; DROP TABLE shipments", "ALL", "cav'", "shipments.route_group", "1"):
        response = client.get(LIST_URL, params={"route_group": invalid})
        assert response.status_code == 422, invalid
        body = response.json()
        assert sorted(body) == ["code", "field", "message"]
        assert body["field"] == "route_group"
        assert invalid not in body["message"], invalid


def test_the_route_group_vocabulary_is_the_existing_enum():
    """One list, not two. A fifth route group becomes filterable without a second edit."""
    assert frozenset(group.value for group in RouteGroup) == ROUTE_GROUP_VALUES


def test_the_route_group_filter_does_not_cross_a_customer_boundary(
    account_client, account_db, account_users, captured_mail
):
    """The ownership clause is still first, so a shared route groups nothing together."""
    owner = _mine(account_db)
    stranger = make(account_db, full_name="Stranger", email="stranger@demo.example.com")
    mine = shipment(account_db, owner, days_ago=3, route_group=RouteGroup.CAV)
    for day in range(1, 6):
        shipment(account_db, stranger, days_ago=day, route_group=RouteGroup.CAV)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    body = client.get(LIST_URL, params={"route_group": "CAV"}).json()
    assert references(body) == [mine.public_id]
    assert body["total"] == 1


# --- OD-41: composition, and the limiter ----------------------------------------------


def test_all_four_filters_compose_and_only_ever_narrow(
    account_client, account_db, account_users, captured_mail
):
    """Every filter is conjunctive, and ownership is in front of all of them."""
    owner = _mine(account_db)
    wanted = shipment(account_db, owner, days_ago=5, delivered=True, route_group=RouteGroup.CAV)
    shipment(account_db, owner, days_ago=5, route_group=RouteGroup.CAV)  # wrong group
    shipment(account_db, owner, days_ago=5, delivered=True, route_group=RouteGroup.VCA)
    shipment(account_db, owner, days_ago=300, delivered=True, route_group=RouteGroup.CAV)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    today = utcnow().date()
    common = {
        "status_group": "delivered",
        "route_group": "CAV",
        "booked_from": (today - timedelta(days=30)).isoformat(),
        "booked_to": today.isoformat(),
    }
    body = client.get(LIST_URL, params=common).json()
    assert references(body) == [wanted.public_id]
    assert body["total"] == 1

    # Adding the reference narrows to the same row; adding a different one narrows to none.
    body = client.get(LIST_URL, params={**common, "reference": wanted.public_id}).json()
    assert references(body) == [wanted.public_id]
    body = client.get(
        LIST_URL, params={**common, "reference": reference_for(RouteGroup.CAV.value)}
    ).json()
    assert references(body) == []

    # A reference that exists but contradicts another filter returns nothing rather than
    # overriding it. A filter set is an intersection, not a priority order.
    contradicting = shipment(account_db, owner, days_ago=2, route_group=RouteGroup.XUS)
    body = client.get(LIST_URL, params={**common, "reference": contradicting.public_id}).json()
    assert references(body) == []


def test_a_malformed_filter_cannot_bypass_the_read_limiter(
    account_client, account_db, account_users, captured_mail, monkeypatch
):
    """The bucket is consumed before the query string is parsed, so junk costs the same.

    Asserted by exhausting the allowance with *valid* requests and then presenting a
    malformed filter: it is refused with 429 rather than reaching `parse_filters` and
    answering 400. A limiter placed after validation would answer the other way round, and
    a caller could then hammer the parser for free.
    """
    owner = _mine(account_db)
    shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    monkeypatch.setattr(settings, "account_read_identity_attempts", 3)
    monkeypatch.setattr(settings, "account_read_identity_window_seconds", 60)

    for _ in range(3):
        assert client.get(LIST_URL).status_code == 200

    for params in (
        {"reference": "S" * (MAX_FILTER_VALUE_LENGTH + 5)},
        {"route_group": "NOT-A-GROUP"},
        {"status_group": "invented"},
    ):
        response = client.get(LIST_URL, params=params)
        assert response.status_code == 429, params
        assert response.headers.get("Retry-After") is not None


def test_there_is_no_recipient_or_carrier_search(
    account_client, account_db, account_users, captured_mail
):
    """No recipient name, email, phone or address search, and no carrier number search.

    Each of these would be a way to ask a question about a third party, or a way to confirm
    that a carrier reference belongs to somebody -- and none of them is approved.
    """
    owner = _mine(account_db)
    row = shipment(
        account_db,
        owner,
        days_ago=3,
        recipient_name="Findable Person",
        recipient_email="findable@example.invalid",
        recipient_phone_e164="+15559990009",
    )
    other = shipment(account_db, owner, days_ago=4)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    for parameter, value in (
        ("recipient_name", "Findable Person"),
        ("recipient_email", "findable@example.invalid"),
        ("recipient_phone", "+15559990009"),
        ("tracking_number", "SENTINEL1TRACKING2NUMBER3"),
        ("carrier_tracking_number", "SENTINEL1TRACKING2NUMBER3"),
    ):
        body = client.get(LIST_URL, params={parameter: value}).json()
        assert sorted(references(body)) == sorted([row.public_id, other.public_id]), parameter


def test_there_is_no_sort_parameter(account_client, account_db, account_users, captured_mail):
    """The order is fixed in the service, so there is no column a caller can name.

    No sort parameter means no arbitrary sort-column injection to defend against, which is a
    better answer than validating one.
    """
    owner = _mine(account_db)
    newest = shipment(account_db, owner, days_ago=1)
    oldest = shipment(account_db, owner, days_ago=9)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    for parameter, value in (
        ("sort", "booking_date"),
        ("order", "asc"),
        ("sort_by", "selling_amount"),
        ("order_by", "customers.full_name"),
    ):
        body = client.get(LIST_URL, params={parameter: value}).json()
        assert references(body) == [newest.public_id, oldest.public_id], parameter


def test_no_filter_reports_a_count_that_crosses_a_customer_boundary(
    account_client, account_db, account_users, captured_mail
):
    """``total`` counts the caller's own rows, under whatever filter, and nothing else."""
    owner = _mine(account_db)
    other = make(account_db, full_name="Other", email="other@demo.example.com")
    shipment(account_db, owner, days_ago=3, delivered=True)
    for day in range(1, 9):
        shipment(account_db, other, days_ago=day, delivered=True)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    today = utcnow().date()
    for params in (
        {},
        {"status_group": "delivered"},
        {
            "booked_from": (today - timedelta(days=100)).isoformat(),
            "booked_to": today.isoformat(),
        },
    ):
        body = client.get(LIST_URL, params=params).json()
        assert body["total"] == 1, params
