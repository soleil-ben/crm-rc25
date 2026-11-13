"""The Customer Account shipment list's keyword search (UAT round 10, DEC-0156).

`q` replaces the screen's exact "Solaris Shipment ID" box. It matches part of the Solaris
Shipment ID, the booking reference, or the origin or destination city, ignoring case and
accents, and it composes with every other filter. Since UAT round 11 a package reference
finds its shipment too (DEC-0161), and the booking reference is shown on the row
(DEC-0160). What it must never do is widen the list: it is applied after the ownership
clause, so another customer's shipment is neither returned nor counted, whatever the
keyword. Two assertions changed in round 11, entries AS-10 and AS-11 of
`docs/customer_account/SUPERSEDED_ASSERTIONS.md`.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from app.core.enums import RouteGroup
from app.core.normalization import search_fold
from app.core.time_utils import utcnow
from app.models import ShipmentPackage
from app.services.customer_account_shipment_service import MAX_KEYWORD_LENGTH
from tests.shipment_history_fixtures import (
    LIST_URL,
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


def _search(client, keyword, **params):
    return client.get(LIST_URL, params={"q": keyword, **params})


# --- What it matches ----------------------------------------------------------------


def test_part_of_a_shipment_id_matches_in_any_case(
    account_client, account_db, account_users, captured_mail
):
    owner = _mine(account_db)
    wanted = shipment(account_db, owner, days_ago=3)
    other = shipment(account_db, owner, days_ago=4)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    tail = wanted.public_id[-6:]
    for keyword in (tail, tail.lower(), wanted.public_id.lower(), f"  {tail}  "):
        body = _search(client, keyword).json()
        assert references(body) == [wanted.public_id], keyword
        assert body["total"] == 1, keyword

    # "SX-CAV" is in both IDs, so both come back.
    body = _search(client, "sx-cav").json()
    assert sorted(references(body)) == sorted([wanted.public_id, other.public_id])


def test_part_of_a_booking_reference_matches_and_is_shown_on_the_row(
    account_client, account_db, account_users, captured_mail
):
    """Registered in `SUPERSEDED_ASSERTIONS.md` (AS-10): it was searched but not shown."""
    owner = _mine(account_db)
    wanted = shipment(account_db, owner, days_ago=3, booking_reference="PO-Bakery-4471")
    shipment(account_db, owner, days_ago=4, booking_reference="PO-Florist-0090")
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    for keyword in ("bakery", "BAKERY-44", "4471"):
        response = _search(client, keyword)
        assert references(response.json()) == [wanted.public_id], keyword
        # The row that matched says why: its own booking reference, as entered.
        assert [item["booking_reference"] for item in response.json()["items"]] == [
            "PO-Bakery-4471"
        ], keyword
        assert "Florist" not in response.text, keyword

    assert len(references(_search(client, "po-").json())) == 2


def test_origin_and_destination_cities_match_partially(
    account_client, account_db, account_users, captured_mail
):
    owner = _mine(account_db)
    to_hcm = shipment(
        account_db,
        owner,
        days_ago=3,
        origin_city="Mississauga",
        destination_city="Ho Chi Minh City",
    )
    from_hanoi = shipment(
        account_db,
        owner,
        days_ago=4,
        route_group=RouteGroup.VCA,
        origin_city="Hà Nội",
        origin_country="VN",
        destination_city="Toronto",
        destination_country="CA",
    )
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    assert references(_search(client, "chi minh").json()) == [to_hcm.public_id]
    assert references(_search(client, "TORON").json()) == [from_hanoi.public_id]
    assert references(_search(client, "sauga").json()) == [to_hcm.public_id]


def test_vietnamese_cities_match_with_or_without_accents_and_in_any_case(
    account_client, account_db, account_users, captured_mail
):
    """SQLite's lower() folds ASCII only; the registered fold handles "Đ" and the marks."""
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3, destination_city="Đà Nẵng")
    shipment(account_db, owner, days_ago=4, destination_city="Toronto")
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    for keyword in ("Đà Nẵng", "đà nẵng", "ĐÀ NẴNG", "da nang", "DA NANG", "nẵng", "Dà"):
        assert references(_search(client, keyword).json()) == [row.public_id], keyword


def test_the_fold_is_the_same_on_both_sides():
    assert search_fold("Đà  Nẵng") == search_fold("da nang") == "da nang"
    assert search_fold("SX-CAV-7K9D") == "sx-cav-7k9d"
    assert search_fold(None) is None


# --- What it does not match -----------------------------------------------------------


def test_nothing_outside_the_four_columns_is_searched(
    account_client, account_db, account_users, captured_mail
):
    """Recipient, sender, address, phone, email, contents, notes: none of them is searchable.

    Each would be a way to ask a question about a third party, or about a value this
    surface does not publish, and none is in DEC-0156.
    """
    owner = _mine(account_db)
    planted = {
        "recipient_name": "Findable Recipientname",
        "recipient_email": "findable-recipient@example.invalid",
        "recipient_phone_e164": "+15559990009",
        "recipient_address_line1": "12 Findablestreet Road",
        "recipient_postal_code": "M5V9Z9",
        "sender_name": "Findable Sendername",
        "sender_address_line1": "34 Senderstreet Avenue",
        "contents_description": "Findable contents",
        "internal_notes": "Findable internal note",
        "cancellation_reason": "Findable reason",
        "recipient_delivery_note": "Findable buzz code",
        "idempotency_key": "findable-idempotency",
        "source_record_id": "findable-source-record",
    }
    shipment(account_db, owner, days_ago=3, **planted)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    for column, value in planted.items():
        body = _search(client, value).json()
        assert body["items"] == [], column
        assert body["total"] == 0, column
    assert _search(client, "findable").json()["total"] == 0


def test_a_package_reference_finds_its_shipment(
    account_client, account_db, account_users, captured_mail
):
    """Registered in `SUPERSEDED_ASSERTIONS.md` (AS-11): a package reference found nothing.

    A package reference is the shipment ID plus "-01"; the shipment ID does not contain
    it, so only the package search can find it.
    """
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3, packages=2)
    other = shipment(account_db, owner, days_ago=4, packages=1)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    for keyword in (
        f"{row.public_id}-01",
        f"{row.public_id}-02".lower(),
        f"  {row.public_id}-02 ",
    ):
        body = _search(client, keyword).json()
        assert references(body) == [row.public_id], keyword
        assert body["total"] == 1, keyword
    # A shipment with two matching packages is still one row.
    assert _search(client, f"{row.public_id}-0").json()["total"] == 1
    assert references(_search(client, f"{other.public_id}-01").json()) == [other.public_id]
    # No such package: nothing, rather than the parent.
    assert _search(client, f"{row.public_id}-03").json()["items"] == []


def test_a_cancelled_package_reference_finds_its_shipment(
    account_client, account_db, account_users, captured_mail
):
    """The detail shows a cancelled package as cancelled, so the search finds it too."""
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3, packages=1, cancelled_packages=1)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    assert references(_search(client, f"{row.public_id}-02").json()) == [row.public_id]


def test_a_package_reference_matches_partially_with_wildcards_literal(
    account_client, account_db, account_users, captured_mail
):
    """An imported package reference need not share the shipment ID's shape."""
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3)
    plain = shipment(account_db, owner, days_ago=4)
    account_db.add_all(
        [
            ShipmentPackage(shipment_id=row.id, sequence=1, package_reference="BOX_7%-Đà"),
            ShipmentPackage(shipment_id=plain.id, sequence=1, package_reference="BOXX7Z"),
        ]
    )
    account_db.commit()
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    assert references(_search(client, "box_7%").json()) == [row.public_id]
    assert references(_search(client, "-da").json()) == [row.public_id]
    assert sorted(references(_search(client, "box").json())) == sorted(
        [row.public_id, plain.public_id]
    )


def test_another_customers_package_reference_finds_nothing(
    account_client, account_db, account_users, captured_mail
):
    """A stranger's package reference: the same empty page as one that does not exist."""
    owner = _mine(account_db)
    stranger = make(account_db, full_name="Stranger", email="stranger@demo.example.com")
    mine = shipment(account_db, owner, days_ago=3, packages=1)
    theirs = shipment(account_db, stranger, days_ago=3, packages=2)
    # The stranger's package also carries a reference that looks like one of mine.
    account_db.add(
        ShipmentPackage(shipment_id=theirs.id, sequence=3, package_reference=f"{mine.public_id}-07")
    )
    account_db.commit()
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    nothing = _search(client, "NOTHING-ANYWHERE-00").json()
    assert nothing["items"] == [] and nothing["total"] == 0
    for foreign in (f"{theirs.public_id}-01", f"{theirs.public_id}-02", f"{mine.public_id}-07"):
        response = _search(client, foreign)
        assert response.status_code == 200, foreign
        assert response.json() == nothing, foreign
    assert references(_search(client, f"{mine.public_id}-01").json()) == [mine.public_id]


def test_like_wildcards_are_literal(account_client, account_db, account_users, captured_mail):
    """`%` and `_` match themselves, so neither can turn the keyword into "everything"."""
    owner = _mine(account_db)
    literal = shipment(account_db, owner, days_ago=3, booking_reference="ORDER_100%")
    plain = shipment(account_db, owner, days_ago=4, booking_reference="ORDERX1000")
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    # Unescaped, every one of these would match both rows.
    for keyword, expected in (
        ("%", [literal.public_id]),
        ("_", [literal.public_id]),
        ("%%", []),
        ("__", []),
        ("\\", []),
        ("\\%", []),
    ):
        body = _search(client, keyword).json()
        assert references(body) == expected, keyword

    assert references(_search(client, "ORDER_1").json()) == [literal.public_id]
    assert references(_search(client, "orderx").json()) == [plain.public_id]


def test_the_keyword_cannot_carry_sql(account_client, account_db, account_users, captured_mail):
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    for attempt in (
        "' OR '1'='1",
        "x' OR 1=1 --",
        "'; DROP TABLE shipments; --",
        '" OR ""="',
        ") OR (1=1",
    ):
        response = _search(client, attempt)
        assert response.status_code == 200, attempt
        assert response.json()["items"] == [], attempt

    assert references(client.get(LIST_URL).json()) == [row.public_id]


# --- Ownership ----------------------------------------------------------------------


def test_another_customers_shipments_are_never_returned_or_counted(
    account_client, account_db, account_users, captured_mail
):
    """Every column the keyword reads, set to the same value on a stranger's shipment."""
    owner = _mine(account_db)
    stranger = make(account_db, full_name="Stranger", email="stranger@demo.example.com")
    mine = shipment(
        account_db, owner, days_ago=3, booking_reference="SHARED-REF", destination_city="Huế"
    )
    theirs = [
        shipment(
            account_db,
            stranger,
            days_ago=day,
            booking_reference="SHARED-REF",
            destination_city="Huế",
        )
        for day in range(1, 6)
    ]
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    for keyword in ("shared-ref", "hue", "SX-", "a", theirs[0].public_id):
        body = _search(client, keyword).json()
        for row in theirs:
            assert row.public_id not in references(body), keyword
        assert body["total"] <= 1, keyword

    assert references(_search(client, "shared").json()) == [mine.public_id]


def test_a_stranger_only_match_is_identical_to_no_match_at_all(
    account_client, account_db, account_users, captured_mail
):
    """Not an ownership oracle: the same status, body and headers, byte for byte."""
    owner = _mine(account_db)
    stranger = make(account_db, full_name="Stranger", email="stranger@demo.example.com")
    shipment(account_db, owner, days_ago=3)
    theirs = shipment(account_db, stranger, days_ago=3, booking_reference="ONLY-THEIRS-77")
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    for foreign in ("ONLY-THEIRS", theirs.public_id[-8:]):
        first = _search(client, "NOTHING-ANYWHERE-00")
        second = _search(client, foreign)
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json() == {**first.json(), "items": [], "total": 0}
        for header in ("cache-control", "content-type", "referrer-policy", "x-robots-tag"):
            assert first.headers.get(header) == second.headers.get(header), header


def test_drafts_and_demo_rows_stay_excluded(
    account_client, account_db, account_users, captured_mail
):
    """The inclusion rule is unchanged: searching cannot surface a row the list hides."""
    owner = _mine(account_db)
    shipment(account_db, owner, days_ago=3, booking_state="draft", booking_reference="HIDDEN-1")
    shipment(account_db, owner, days_ago=3, is_demo_record=True, booking_reference="HIDDEN-2")
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    assert _search(client, "hidden").json()["total"] == 0


# --- With the other filters ----------------------------------------------------------


def test_the_keyword_composes_with_status_route_and_dates(
    account_client, account_db, account_users, captured_mail
):
    owner = _mine(account_db)
    wanted = shipment(
        account_db,
        owner,
        days_ago=5,
        delivered=True,
        route_group=RouteGroup.CAV,
        destination_city="Hà Nội",
    )
    # Each of these matches the keyword and fails exactly one other filter.
    shipment(account_db, owner, days_ago=5, route_group=RouteGroup.CAV, destination_city="Hà Nội")
    shipment(
        account_db,
        owner,
        days_ago=5,
        delivered=True,
        route_group=RouteGroup.XUS,
        destination_city="Hà Nội",
    )
    shipment(
        account_db,
        owner,
        days_ago=200,
        delivered=True,
        route_group=RouteGroup.CAV,
        destination_city="Hà Nội",
    )
    # And this one passes every other filter and fails the keyword.
    shipment(
        account_db,
        owner,
        days_ago=5,
        delivered=True,
        route_group=RouteGroup.CAV,
        destination_city="Toronto",
    )
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    today = utcnow().date()
    params = {
        "status_group": "delivered",
        "route_group": "CAV",
        "booked_from": (today - timedelta(days=30)).isoformat(),
        "booked_to": today.isoformat(),
    }
    body = _search(client, "ha noi", **params).json()
    assert references(body) == [wanted.public_id]
    assert body["total"] == 1

    # Without the keyword, the Toronto one is back; without the filters, every Hà Nội one.
    assert body["total"] < client.get(LIST_URL, params=params).json()["total"]
    assert _search(client, "ha noi").json()["total"] == 4


def test_the_keyword_and_the_exact_reference_are_both_applied(
    account_client, account_db, account_users, captured_mail
):
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3, destination_city="Toronto")
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    assert references(_search(client, "toronto", reference=row.public_id).json()) == [row.public_id]
    assert _search(client, "hanoi", reference=row.public_id).json()["items"] == []


def test_paging_counts_the_matches_only(account_client, account_db, account_users, captured_mail):
    owner = _mine(account_db)
    for day in range(1, 6):
        shipment(account_db, owner, days_ago=day, destination_city="Huế")
    shipment(account_db, owner, days_ago=9, destination_city="Toronto")
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    first = _search(client, "hue", limit=2).json()
    third = _search(client, "hue", limit=2, offset=4).json()
    assert first["total"] == third["total"] == 5
    assert len(first["items"]) == 2
    assert len(third["items"]) == 1


# --- Bounds, and what is logged -------------------------------------------------------


def test_an_empty_keyword_is_no_search(account_client, account_db, account_users, captured_mail):
    owner = _mine(account_db)
    shipment(account_db, owner, days_ago=3)
    shipment(account_db, owner, days_ago=4)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    for empty in ("", "   ", "\t"):
        assert _search(client, empty).json()["total"] == 2, repr(empty)


def test_the_keyword_is_bounded_with_this_surfaces_validation_body(
    account_client, account_db, account_users, captured_mail
):
    owner = _mine(account_db)
    shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    assert _search(client, "x" * MAX_KEYWORD_LENGTH).status_code == 200

    response = _search(client, "y" * (MAX_KEYWORD_LENGTH + 1))
    assert response.status_code == 422
    body = response.json()
    assert sorted(body) == ["code", "field", "message"]
    assert body["field"] == "q"
    assert body["message"] == f"Search for {MAX_KEYWORD_LENGTH} characters or fewer."
    assert "yyyy" not in response.text


def test_the_keyword_is_never_logged(
    account_client, account_db, account_users, captured_mail, caplog
):
    owner = _mine(account_db)
    shipment(account_db, owner, days_ago=3, booking_reference="SECRET-ORDER-9911")
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    with caplog.at_level(logging.DEBUG):
        assert _search(client, "secret-order-99").json()["total"] == 1
        _search(client, "z" * (MAX_KEYWORD_LENGTH + 1))

    text = "\n".join(
        f"{record.getMessage()} {record.__dict__}" for record in caplog.records
    ).lower()
    assert "secret-order" not in text
    assert "zzzz" not in text
