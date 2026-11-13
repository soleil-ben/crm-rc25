"""The functional half of the 2026-10-14 UAT fix pack, item by item.

Items 1-3 (public tracking, cache headers, link tokens) and item 10 (identity lifecycle)
have their own modules. This file covers the smaller functional corrections -- each one a
behaviour a tester saw, stated as the behaviour they should have seen.

* item 4 -- the customer list and export accept ``?q=`` as well as ``?search=``;
* item 5 -- the "Archived" lifecycle filter returns archived records;
* item 6 -- a referral says who recorded it;
* item 7 -- a role that may read cost also sees gross profit, and nobody else does;
* item 8 -- the "How shipments are counted" headline honours the route filter.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.core.enums import Role, RouteGroup
from app.models import OrganizationSettings, Shipment
from app.services import report_service
from tests.conftest import add_shipment, booked_shipment, make_customer
from tests.report_fixtures import PERIOD_FROM, PERIOD_TO, TZ, build_dataset

CUSTOMERS = "/api/v1/customers"
EXPORT = "/api/v1/exports/customers.csv"


def _ids(response) -> set[str]:
    assert response.status_code == 200, response.text
    return {item["public_id"] for item in response.json()["items"]}


# --- Item 4: `?q=` ---------------------------------------------------------------


def test_q_filters_the_customer_list_like_search_does(as_admin, db):
    hanh = make_customer(db, full_name="Nguyễn Thị Bích Hạnh", email="hanh@demo.example.com")
    make_customer(db, full_name="Trần Quốc Tuấn", email="tuan@demo.example.com")

    by_q = _ids(as_admin.get(CUSTOMERS, params={"q": "hạnh"}))
    by_search = _ids(as_admin.get(CUSTOMERS, params={"search": "hạnh"}))

    assert by_q == by_search == {hanh.public_id}
    # Both spellings at once: `search` wins, so a bookmarked URL keeps meaning one thing.
    assert _ids(as_admin.get(CUSTOMERS, params={"q": "tuấn", "search": "hạnh"})) == {hanh.public_id}


def test_q_matches_by_id_email_and_phone_too(as_admin, db):
    hanh = make_customer(db, email="hanh@demo.example.com", phone="+1 416 555 0111")
    make_customer(db, full_name="Somebody Else", email="else@demo.example.com")

    assert _ids(as_admin.get(CUSTOMERS, params={"q": hanh.public_id})) == {hanh.public_id}
    assert _ids(as_admin.get(CUSTOMERS, params={"q": "hanh@demo"})) == {hanh.public_id}
    assert _ids(as_admin.get(CUSTOMERS, params={"q": "4165550111"})) == {hanh.public_id}


def test_the_export_applies_q_as_the_same_predicate(as_admin, db):
    hanh = make_customer(db, full_name="Nguyễn Thị Bích Hạnh", email="hanh@demo.example.com")
    other = make_customer(db, full_name="Somebody Else", email="else@demo.example.com")

    text = as_admin.get(EXPORT, params={"q": "hạnh"}).text

    assert hanh.public_id in text
    assert other.public_id not in text


# --- Item 5: the Archived filter -----------------------------------------------------


def test_the_archived_lifecycle_filter_returns_archived_customers(as_admin, db):
    live = make_customer(db, full_name="Live Person", email="live@demo.example.com")
    gone = make_customer(db, full_name="Archived Person", email="gone@demo.example.com")
    as_admin.post(f"{CUSTOMERS}/{gone.id}/archive", json={"reason": "Moved away"})

    # Before the fix this answered zero: the status filter selected the archived record
    # and the default exclusion removed it again.
    archived = _ids(as_admin.get(CUSTOMERS, params={"lifecycle_status": "archived"}))
    assert archived == {gone.public_id}

    # The default list still hides archived records, and `include_archived` still widens it.
    assert _ids(as_admin.get(CUSTOMERS)) == {live.public_id}
    assert _ids(as_admin.get(CUSTOMERS, params={"include_archived": "true"})) == {
        live.public_id,
        gone.public_id,
    }


def test_asking_for_archived_alongside_another_status_shows_both(as_admin, db):
    prospect = make_customer(db, full_name="Prospect", email="p@demo.example.com")
    gone = make_customer(db, full_name="Archived", email="a@demo.example.com")
    as_admin.post(f"{CUSTOMERS}/{gone.id}/archive", json={"reason": None})

    found = _ids(
        as_admin.get(
            CUSTOMERS, params=[("lifecycle_status", "archived"), ("lifecycle_status", "prospect")]
        )
    )

    assert found == {prospect.public_id, gone.public_id}


def test_the_export_honours_the_archived_filter_the_same_way(as_admin, db):
    make_customer(db, full_name="Live Person", email="live@demo.example.com")
    gone = make_customer(db, full_name="Archived Person", email="gone@demo.example.com")
    as_admin.post(f"{CUSTOMERS}/{gone.id}/archive", json={"reason": None})

    text = as_admin.get(EXPORT, params={"lifecycle_status": "archived"}).text

    assert gone.public_id in text
    assert "Live Person" not in text


# --- Item 6: who recorded a referral ----------------------------------------------------


def test_a_referral_names_the_staff_member_who_recorded_it(as_admin, db, users):
    referrer = make_customer(db, full_name="Referrer", email="r@demo.example.com")
    referred = make_customer(db, full_name="Referred", email="d@demo.example.com")

    created = as_admin.post(
        f"{CUSTOMERS}/{referrer.id}/referrals",
        json={"referred_customer_id": referred.id, "note": "Told us at the counter"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["recorded_by"]["id"] == users["admin"].id
    assert created.json()["recorded_by"]["full_name"] == users["admin"].full_name

    listed = as_admin.get(f"{CUSTOMERS}/{referred.id}/referrals").json()
    assert listed[0]["recorded_by"]["email"] == users["admin"].email
    assert listed[0]["created_at"]


def test_a_referral_with_no_recorder_says_so_rather_than_failing(as_admin, db):
    from app.models import Referral

    referrer = make_customer(db, full_name="Referrer", email="r@demo.example.com")
    referred = make_customer(db, full_name="Referred", email="d@demo.example.com")
    db.add(
        Referral(
            referrer_customer_id=referrer.id,
            referred_customer_id=referred.id,
            recorded_by_user_id=None,
        )
    )
    db.commit()

    listed = as_admin.get(f"{CUSTOMERS}/{referrer.id}/referrals")
    assert listed.status_code == 200
    assert listed.json()[0]["recorded_by"] is None


# --- Item 7: gross profit ---------------------------------------------------------------


def _priced(db, **amounts) -> Shipment:
    customer = make_customer(db, email="profit@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV, packages=1)
    shipment.currency = "CAD"
    for key, value in amounts.items():
        setattr(shipment, key, value)
    db.commit()
    return shipment


def test_an_admin_sees_gross_profit_inside_the_cost_block(api_for, db):
    shipment = _priced(
        db,
        selling_amount=220,
        discount_amount=10,
        refund_amount=5,
        shipping_cost=140,
        surcharges_amount=12,
    )

    body = api_for(Role.ADMIN).get(f"/api/v1/shipments/{shipment.id}").json()

    assert body["financials"]["costs"]["gross_profit"] == "53.00"


def test_gross_profit_is_unknown_when_a_side_is_unrecorded(api_for, db):
    """Unknown, never zero: a profit computed from half the figures is a number somebody
    would act on."""
    no_cost = _priced(db, selling_amount=220, shipping_cost=None)
    body = api_for(Role.ADMIN).get(f"/api/v1/shipments/{no_cost.id}").json()
    assert body["financials"]["costs"]["gross_profit"] is None

    no_price = _priced(db, selling_amount=None, shipping_cost=140)
    body = api_for(Role.ADMIN).get(f"/api/v1/shipments/{no_price.id}").json()
    assert body["financials"]["costs"]["gross_profit"] is None

    # Optional adjustments absent means "no adjustment", not "unknown".
    plain = _priced(db, selling_amount=200, shipping_cost=150)
    body = api_for(Role.ADMIN).get(f"/api/v1/shipments/{plain.id}").json()
    assert Decimal(body["financials"]["costs"]["gross_profit"]) == Decimal("50.00")


def test_gross_profit_never_reaches_a_role_without_cost_permission(api_for, db):
    shipment = _priced(db, selling_amount=220, shipping_cost=140)
    for role in (Role.OPERATIONS, Role.MARKETING, Role.READ_ONLY_MANAGER):
        response = api_for(role).get(f"/api/v1/shipments/{shipment.id}")
        assert "gross_profit" not in response.text, role
        assert "shipping_cost" not in response.text, role


# --- Item 8: the counting guard and the route filter ------------------------------------


def test_the_counting_guard_honours_the_route_filter(db):
    org = db.scalar(select(OrganizationSettings))
    org.office_timezone = TZ
    db.commit()
    build_dataset(db)
    period = report_service.resolve_period(from_date=PERIOD_FROM, to_date=PERIOD_TO, org=org)

    everything = report_service.package_and_leg_guard(db, period)
    cav_only = report_service.package_and_leg_guard(db, period, [RouteGroup.CAV.value])
    route_mix = report_service.route_mix(db, period, [RouteGroup.CAV.value])

    assert everything["qualifying_shipments"] > cav_only["qualifying_shipments"]
    # The headline and the Route mix table beneath it now agree.
    assert cav_only["qualifying_shipments"] == route_mix.rows[0]["count"]
    assert cav_only["packages_on_those_shipments"] <= everything["packages_on_those_shipments"]
    assert cav_only["route_groups"] == ["CAV"]
    assert "Canada to Vietnam" in cav_only["note"]
    assert everything["route_groups"] == []


def test_the_reports_route_passes_the_filter_through(as_admin, db):
    org = db.scalar(select(OrganizationSettings))
    org.office_timezone = TZ
    db.commit()
    customer = make_customer(db, email="routes@demo.example.com")
    add_shipment(db, customer, days_ago=3, route_group=RouteGroup.CAV)
    add_shipment(db, customer, days_ago=4, route_group=RouteGroup.VCA)

    unfiltered = as_admin.get("/api/v1/reports").json()["counting_guard"]
    filtered = as_admin.get("/api/v1/reports", params={"route_group": "VCA"}).json()[
        "counting_guard"
    ]

    assert unfiltered["qualifying_shipments"] == 2
    assert filtered["qualifying_shipments"] == 1
    assert filtered["route_groups"] == ["VCA"]
