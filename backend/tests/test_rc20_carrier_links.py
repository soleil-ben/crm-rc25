"""RC-UAT-20 tester note: Master Tracking and Last Mile Tracking links both reach the customer.

The tester saw only the master link on a shipment with both. DEC-0224 publishes
``carrier_links`` (at most one per generic tracking name, in leg order; ``carrier_link`` is the
first). These tests walk the real staff routes (add a leg, add a tracking reference) and then
read the public tracking route and the Customer Account detail route, under the conditions a
second link could plausibly go missing in: a consolidation member, the same carrier on both
legs, last mile entered before the master leg, a package-scoped reference, two links on the
last-mile legs. They also pin the three data conditions that *do* (by design) hide a link while
the staff Legs tab still shows it: manual source mode, a URL with a ``#fragment`` (Canada Post's
own address-bar form), and a host not on the allowlist (no ``www.``).
"""

from __future__ import annotations

import pytest

from app.core.enums import TrackingSourceMode
from app.services import leg_service, package_service
from tests.conftest import booked_shipment, make_customer
from tests.shipment_history_fixtures import customer as make_account_customer
from tests.shipment_history_fixtures import detail_url, linked_and_signed_in
from tests.shipment_history_fixtures import shipment as account_shipment
from tests.test_quotes import priced_world  # noqa: F401 - fixture

UPS = "https://www.ups.com/track?tracknum=1Z999AA10123456784"
CANADA_POST = "https://www.canadapost-postescanada.ca/track-reperage/en?pin=7023210039414604"
TRACK = "/api/v1/public/track"
MASTER = "master_tracking"
LAST_MILE = "last_mile_tracking"


def _staff_link(as_admin, shipment_id, leg_type, carrier, url, *, mode="external_link", **extra):
    """A leg and a tracking reference, entered the way staff enter them (the staff routes)."""
    leg = as_admin.post(
        f"/api/v1/shipments/{shipment_id}/legs",
        json={"leg_type": leg_type, "provider_name": carrier},
    )
    assert leg.status_code in (200, 201), leg.text
    reference = as_admin.post(
        f"/api/v1/legs/{leg.json()['id']}/tracking-references",
        json={
            "carrier_name": carrier,
            "tracking_number": f"TN-{leg_type}",
            "public_url": url,
            "source_mode": mode,
            **extra,
        },
    )
    assert reference.status_code in (200, 201), reference.text
    return leg.json()


def _links(body):
    return [
        (link["tracking_name_key"], link["carrier_name"], link["url"])
        for link in body["carrier_links"]
    ]


def _public(client, reference):
    response = client.get(f"{TRACK}/{reference}")
    assert response.status_code == 200, response.text
    return response.json()


BOTH = [
    (MASTER, "Master Tracking", UPS),
    (LAST_MILE, "Last Mile Tracking", CANADA_POST),
]


@pytest.mark.parametrize("master_leg", ["origin_pickup", "consolidation_linehaul"])
def test_public_tracking_returns_both_links_entered_through_the_staff_routes(
    client, db, as_admin, master_leg
):
    shipment = booked_shipment(db, make_customer(db, email=f"both.{master_leg}@demo.example.com"))
    db.commit()
    _staff_link(as_admin, shipment.id, master_leg, "UPS", UPS)
    _staff_link(as_admin, shipment.id, "final_delivery", "Canada Post", CANADA_POST)

    body = _public(client, shipment.public_id)
    assert _links(body) == BOTH
    assert body["carrier_link"] == body["carrier_links"][0]
    assert body["tracking_state"] == "external_link_only"
    # A package reference resolves to the same shipment and the same two links.
    package = package_service.active_packages(db, shipment.id)[0]
    assert _links(_public(client, package.package_reference)) == BOTH


def test_a_consolidation_member_shows_both_links(client, db, as_admin, priced_world):  # noqa: F811
    _con, kids = priced_world
    member = kids[0]
    _staff_link(as_admin, member.id, "consolidation_linehaul", "UPS", UPS)
    _staff_link(as_admin, member.id, "final_delivery", "Canada Post", CANADA_POST)
    assert _links(_public(client, member.public_id)) == BOTH


def test_the_same_carrier_on_both_legs_is_not_deduplicated_by_carrier(client, db, as_admin):
    shipment = booked_shipment(db, make_customer(db, email="same.carrier@demo.example.com"))
    db.commit()
    _staff_link(as_admin, shipment.id, "origin_pickup", "UPS", UPS)
    other_ups = UPS.replace("84", "85")
    _staff_link(as_admin, shipment.id, "final_delivery", "UPS", other_ups)
    assert _links(_public(client, shipment.public_id)) == [
        (MASTER, "Master Tracking", UPS),
        (LAST_MILE, "Last Mile Tracking", other_ups),
    ]


def test_last_mile_entered_first_still_shows_both_in_leg_order(client, db, as_admin):
    shipment = booked_shipment(db, make_customer(db, email="reversed@demo.example.com"))
    db.commit()
    _staff_link(as_admin, shipment.id, "final_delivery", "Canada Post", CANADA_POST)
    _staff_link(as_admin, shipment.id, "origin_pickup", "UPS", UPS)
    assert _links(_public(client, shipment.public_id)) == [
        (LAST_MILE, "Last Mile Tracking", CANADA_POST),
        (MASTER, "Master Tracking", UPS),
    ]


def test_a_package_scoped_last_mile_reference_and_two_last_mile_legs(client, db, as_admin):
    shipment = booked_shipment(db, make_customer(db, email="scoped@demo.example.com"), packages=2)
    db.commit()
    package = package_service.active_packages(db, shipment.id)[1]
    _staff_link(as_admin, shipment.id, "consolidation_linehaul", "UPS", UPS)
    # destination_handling (no link) then final_delivery with a package-scoped link.
    as_admin.post(
        f"/api/v1/shipments/{shipment.id}/legs", json={"leg_type": "destination_handling"}
    )
    _staff_link(
        as_admin,
        shipment.id,
        "final_delivery",
        "Canada Post",
        CANADA_POST,
        package_id=package.id,
    )
    assert _links(_public(client, shipment.public_id)) == BOTH


@pytest.mark.parametrize(
    ("url", "mode", "why"),
    [
        (CANADA_POST, "manual", "manual source mode (the staff form's default)"),
        (
            "https://www.canadapost-postescanada.ca/track-reperage/en#/details/7023210039414604",
            "external_link",
            "a #fragment (Canada Post's own address-bar URL)",
        ),
        (
            "https://canadapost-postescanada.ca/track-reperage/en?pin=7023210039414604",
            "external_link",
            "a host not on the allowlist (no www.)",
        ),
    ],
)
def test_data_conditions_that_hide_the_last_mile_link_by_design(
    client, db, as_admin, url, mode, why
):
    """Not defects: the shared public policy (DEC-0041, DEC-0113). Pinned so a tester's
    "only the master link shows" can be traced to the reference that was entered."""
    shipment = booked_shipment(db, make_customer(db, email=f"hidden.{len(why)}@demo.example.com"))
    db.commit()
    _staff_link(as_admin, shipment.id, "origin_pickup", "UPS", UPS)
    _staff_link(as_admin, shipment.id, "final_delivery", "Canada Post", url, mode=mode)
    # The staff Legs tab still lists the stored URL...
    legs = as_admin.get(f"/api/v1/shipments/{shipment.id}/legs").json()
    assert [r["public_url"] for leg in legs for r in leg["tracking_references"]] == [UPS, url]
    # ...but the customer sees the master link only.
    assert _links(_public(client, shipment.public_id)) == [(MASTER, "Master Tracking", UPS)]


def test_the_customer_account_detail_returns_both_links(
    account_client, account_db, account_users, captured_mail
):
    mine = make_account_customer(
        account_db, full_name="Linh Tran", email="linh.canonical@demo.example.com"
    )
    row = account_shipment(account_db, mine, days_ago=3)
    for leg_type, carrier, url in (
        ("consolidation_linehaul", "UPS", UPS),
        ("final_delivery", "Canada Post", CANADA_POST),
    ):
        leg = leg_service.create_leg(
            account_db, row, {"leg_type": leg_type, "provider_name": carrier}
        )
        leg_service.add_tracking_reference(
            account_db,
            leg,
            {
                "carrier_name": carrier,
                "tracking_number": f"TN-{leg_type}",
                "public_url": url,
                "source_mode": TrackingSourceMode.EXTERNAL_LINK.value,
            },
        )
    account_db.commit()

    me = linked_and_signed_in(
        account_client,
        captured_mail,
        account_users,
        email_address="linh@demo.example.com",
        customer=mine,
    )
    response = me.get(detail_url(row.public_id))
    assert response.status_code == 200, response.text
    body = response.json()
    assert _links(body) == BOTH
    assert body["carrier_link"] == body["carrier_links"][0]
    assert set(body["carrier_links"][1]) == {"carrier_name", "tracking_name_key", "url"}
    assert "TN-final_delivery" not in response.text
