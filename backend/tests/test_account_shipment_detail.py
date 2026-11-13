"""The authenticated detail: every field, and the single failure that hides everything else.

The equivalence tests at the bottom are the ones that matter most. A customer who can tell
"no such shipment" from "that one is somebody else's" has an oracle for the existence of
other people's parcels, and an oracle is worth having even when the parcel itself is not
readable (T-03).
"""

from __future__ import annotations

from datetime import timedelta

from app.core.enums import BookingState, OperationalState, RouteGroup
from app.core.time_utils import utcnow
from app.models import CustomerIdAlias
from tests.shipment_history_fixtures import (
    add_event,
    detail_url,
    linked_and_signed_in,
    shipment,
)
from tests.shipment_history_fixtures import customer as make

MINE = "hanh@demo.example.com"


def _mine(account_db):
    return make(account_db, full_name="Hanh Nguyen", email="hanh.canonical@demo.example.com")


def _theirs(account_db):
    return make(account_db, full_name="Someone Else", email="someone.else@demo.example.com")


def _signed_in(account_client, captured_mail, account_users, customer):
    return linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=customer
    )


# --- The twenty-five fields ------------------------------------------------------


def test_every_detail_field_carries_the_value_its_source_holds(
    account_client, account_db, account_users, captured_mail
):
    """Registered in `SUPERSEDED_ASSERTIONS.md` (AS-23, AS-29): twenty-four keys until UAT
    round 12; twenty-five until RC-UAT-19 added ``carrier_links`` (2026-10-22)."""
    mine = _mine(account_db)
    estimate = utcnow() + timedelta(days=3)
    row = shipment(
        account_db,
        mine,
        days_ago=12,
        route_group=RouteGroup.CAV,
        estimated_delivery_at=estimate,
        packages=2,
        cancelled_packages=1,
        booking_reference="  PO-7781  ",
    )
    event = add_event(account_db, row, days_ago=2, text="Arrived at the destination facility.")

    client = _signed_in(account_client, captured_mail, account_users, mine)
    response = client.get(detail_url(row.public_id))

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["shipment_reference"] == row.public_id
    assert body["booking_reference"] == "PO-7781"
    assert body["matched_reference_type"] == "shipment"
    assert body["selected_package_reference"] is None
    assert body["route_group"] == RouteGroup.CAV.value
    assert body["route_label"] == "Canada to Vietnam"
    assert body["origin"] == {
        "city": "Mississauga",
        "country_code": "CA",
        "country_label": "Canada",
    }
    assert body["destination"] == {
        "city": "Ho Chi Minh City",
        "country_code": "VN",
        "country_label": "Vietnam",
    }
    assert body["status"] == OperationalState.IN_TRANSIT.value
    assert body["status_label"]
    assert body["package_count_active"] == 2
    assert body["package_count_cancelled"] == 1
    assert body["package_count_delivered"] == 0
    assert body["progress_summary"]
    assert len(body["packages"]) == 3
    assert body["estimated_delivery_at"] is not None
    assert body["delivered_at"] is None
    assert body["cancelled_at"] is None
    assert len(body["timeline"]) == 1
    assert body["timeline"][0]["message"] == "Arrived at the destination facility."
    assert body["timeline"][0]["source_label"] == "manual_update"
    assert body["tracking_state"] == "manual_updates"
    assert body["last_public_update_at"].startswith(event.occurred_at.isoformat()[:10])
    assert body["carrier_link"] is None
    assert body["data_mode"] == "live"
    assert body["timezone"]
    assert len(body) == 26  # 25 until RC-UAT-19 added carrier_links (2026-10-22)


def test_a_package_carries_only_its_safe_state(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    row = shipment(account_db, mine, days_ago=4, packages=1, cancelled_packages=1)

    client = _signed_in(account_client, captured_mail, account_users, mine)
    packages = client.get(detail_url(row.public_id)).json()["packages"]

    assert sorted(packages[0]) == sorted(
        [
            "package_reference",
            "status",
            "status_label",
            "is_selected",
            "is_cancelled",
            "delivered_at",
        ]
    )
    # Nothing is "selected": this route is addressed by shipment reference only.
    assert all(package["is_selected"] is False for package in packages)
    assert [package["is_cancelled"] for package in packages] == [False, True]


def test_a_timeline_entry_carries_approved_wording_and_nothing_internal(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    row = shipment(account_db, mine, days_ago=6)
    add_event(
        account_db,
        row,
        days_ago=1,
        text="Departed the origin facility.",
        internal_detail="Driver was late; escalate to the Hanoi office.",
    )
    add_event(account_db, row, public=False, internal_detail="Never publish this.", days_ago=2)

    client = _signed_in(account_client, captured_mail, account_users, mine)
    body = client.get(detail_url(row.public_id)).json()

    assert len(body["timeline"]) == 1
    assert body["timeline"][0]["message"] == "Departed the origin facility."
    assert "escalate" not in str(body)
    assert "Never publish this" not in str(body)
    assert sorted(body["timeline"][0]) == sorted(
        [
            "status",
            "status_label",
            "event_type",
            "scope",
            "message",
            "message_template_key",
            "occurred_at",
            "location",
            "package_references",
            "source_label",
        ]
    )


def test_a_cancelled_shipment_returns_its_cancellation_and_no_journey(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    row = shipment(account_db, mine, days_ago=8, cancelled=True)
    add_event(account_db, row, days_ago=6, text="This journey did not continue.")

    client = _signed_in(account_client, captured_mail, account_users, mine)
    body = client.get(detail_url(row.public_id)).json()

    assert body["tracking_state"] == "cancelled"
    assert body["cancelled_at"] is not None
    assert body["delivered_at"] is None
    assert body["timeline"] == []
    assert body["carrier_link"] is None
    assert body["last_public_update_at"] is None


def test_a_rebooked_shipment_detail_does_not_name_its_replacement(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    original = shipment(account_db, mine, days_ago=9, cancelled=True)
    replacement = shipment(account_db, mine, days_ago=8, rebooked_from=original.id)
    original.rebooked_to_shipment_id = replacement.id
    account_db.commit()

    client = _signed_in(account_client, captured_mail, account_users, mine)
    body = client.get(detail_url(original.public_id)).json()

    assert replacement.public_id not in str(body)


def test_an_estimate_is_dropped_once_it_has_been_overtaken(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    row = shipment(account_db, mine, days_ago=9, delivered=True, estimated_delivery_at=utcnow())

    client = _signed_in(account_client, captured_mail, account_users, mine)
    body = client.get(detail_url(row.public_id)).json()

    assert body["estimated_delivery_at"] is None
    assert body["delivered_at"] is not None


def test_a_shipment_with_nothing_published_says_so_honestly(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    row = shipment(account_db, mine, days_ago=2)

    client = _signed_in(account_client, captured_mail, account_users, mine)
    body = client.get(detail_url(row.public_id)).json()

    assert body["tracking_state"] == "no_public_milestones"
    assert body["timeline"] == []
    # Nothing claims a provider was contacted, because none ever has been.
    assert "connected_api" not in str(body)
    assert "synchron" not in str(body).lower()


# --- One failure -------------------------------------------------------------------


def _bodies(client, references_to_try):
    return [client.get(detail_url(reference)) for reference in references_to_try]


def test_unknown_malformed_foreign_and_ineligible_references_answer_identically(
    account_client, account_db, account_users, captured_mail
):
    """The core T-03 assertion: five different situations, one response.

    Status, body and the privacy headers are compared, not just the status code. A header
    that differed between two of these would be the oracle the body was written to deny.
    """
    mine, theirs = _mine(account_db), _theirs(account_db)
    shipment(account_db, mine, days_ago=3)
    foreign = shipment(account_db, theirs, days_ago=3)
    draft = shipment(account_db, mine, days_ago=4, booking_state=BookingState.DRAFT)
    demo = shipment(account_db, mine, days_ago=5, is_demo_record=True)

    client = _signed_in(account_client, captured_mail, account_users, mine)
    candidates = [
        "SX-CAV-000000000000",  # well formed, unknown
        "not a reference at all",  # malformed
        foreign.public_id,  # exists, somebody else's
        demo.public_id,  # exists, mine, ineligible
        (draft.public_id or "SX-CAV-111111111111"),  # a draft has no public id at all
        "%2e%2e/%2e%2e/etc",  # path-shaped nonsense
        "x" * 300,  # oversized
    ]

    responses = _bodies(client, candidates)
    statuses = {response.status_code for response in responses}
    bodies = {response.text for response in responses}
    headers = {
        tuple(
            sorted(
                (key, value)
                for key, value in response.headers.items()
                if key.lower()
                in {
                    "cache-control",
                    "pragma",
                    "referrer-policy",
                    "x-robots-tag",
                    "x-content-type-options",
                    "x-frame-options",
                    "permissions-policy",
                    "content-type",
                }
            )
        )
        for response in responses
    }

    assert statuses == {404}
    assert len(bodies) == 1, bodies
    assert len(headers) == 1


def test_the_failure_body_names_nothing(account_client, account_db, account_users, captured_mail):
    mine, theirs = _mine(account_db), _theirs(account_db)
    foreign = shipment(
        account_db,
        theirs,
        days_ago=3,
        recipient_name="Somebody Private",
        recipient_phone_e164="+14165550188",
    )

    client = _signed_in(account_client, captured_mail, account_users, mine)
    response = client.get(detail_url(foreign.public_id))
    body = response.json()

    assert sorted(body) == ["code", "field", "message"]
    assert body["field"] is None
    for forbidden in (
        theirs.public_id,
        "Somebody Private",
        "4165550188",
        "another customer",
        "belongs",
        "not yours",
        "permission",
        "forbidden",
    ):
        assert forbidden.lower() not in response.text.lower(), forbidden


def test_a_package_reference_is_refused_like_any_unknown_value(
    account_client, account_db, account_users, captured_mail
):
    """The authenticated route addresses shipments. A second identifier space is not opened.

    Answering a package reference differently from an unknown one would say the space
    exists, which is a fact about how Solaris labels parcels that this surface has no reason
    to confirm.
    """
    mine = _mine(account_db)
    row = shipment(account_db, mine, days_ago=3, packages=1)
    account_db.refresh(row)
    package_reference = f"{row.public_id}-01"

    client = _signed_in(account_client, captured_mail, account_users, mine)
    by_package = client.get(detail_url(package_reference))
    unknown = client.get(detail_url("SX-CAV-000000000000"))

    assert by_package.status_code == unknown.status_code == 404
    assert by_package.text == unknown.text


def test_a_former_customer_id_is_not_a_shipment_reference(
    account_client, account_db, account_users, captured_mail
):
    """A merged customer's old public id resolves to nothing here, like any other string."""
    mine, theirs = _mine(account_db), _theirs(account_db)
    account_db.add(
        CustomerIdAlias(
            customer_id=theirs.id,
            alias_public_id="STCA-099999",
            created_at=utcnow(),
            reason="merge",
        )
    )
    account_db.commit()
    shipment(account_db, theirs, days_ago=2)

    client = _signed_in(account_client, captured_mail, account_users, mine)
    alias = client.get(detail_url("STCA-099999"))
    unknown = client.get(detail_url("SX-CAV-000000000000"))

    assert alias.status_code == unknown.status_code == 404
    assert alias.text == unknown.text


def test_the_two_failure_paths_run_the_same_statements_in_the_same_order(
    account_client, account_db, account_users, captured_mail
):
    """Query ordering, asserted rather than argued.

    A foreign reference and an unknown one take the same path through the same single
    statement, so neither the count, the order nor the *shape* of the database work
    separates them. Statement text is compared, not just the count: two different queries
    that happened to number the same would still be two different amounts of work.

    This is the structural half of T-16. Latency equality is deliberately **not** asserted
    as a numeric threshold -- a timing assertion on a shared CI machine is a flaky test, not
    a security control. What is asserted is the work performed, which is what the timing
    would be a measurement of.

    A warm-up request runs first. The session row's ``last_seen_at`` update is throttled, so
    the very first authenticated request after a sign-in does one thing the next one does
    not, and measuring that would compare a cold path with a warm one rather than two
    failure paths.
    """
    from sqlalchemy import event as sa_event

    mine, theirs = _mine(account_db), _theirs(account_db)
    foreign = shipment(account_db, theirs, days_ago=3)

    client = _signed_in(account_client, captured_mail, account_users, mine)
    client.get(detail_url("SX-CAV-AAAAAAAAAAAA"))  # warm-up, deliberately discarded

    bind = account_db.get_bind()
    counted: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        counted.append(" ".join(statement.split())[:120])

    sa_event.listen(bind, "before_cursor_execute", record)
    try:
        counted.clear()
        client.get(detail_url(foreign.public_id))
        foreign_statements = list(counted)
        counted.clear()
        client.get(detail_url("SX-CAV-BBBBBBBBBBBB"))
        unknown_statements = list(counted)
    finally:
        sa_event.remove(bind, "before_cursor_execute", record)

    assert foreign_statements == unknown_statements
    assert foreign_statements, "the probe recorded nothing, so it proved nothing"
    # The refusal writes one audit row and touches nothing else.
    assert sum(1 for line in foreign_statements if line.startswith("INSERT")) == 1
    assert not any(line.startswith("UPDATE shipments") for line in foreign_statements)
