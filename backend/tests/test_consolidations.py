"""Consolidations (Phase 13B): membership rules, booking, master milestones, privacy, routes.

The handoff's master: one vendor booking with three customers' shipments inside it
(section 5: 21 kg, children 3, 6 and 12 kg). Directive v2.1 acceptance tests 2 (a master
milestone reaches every member and no customer sees another's) and 8 (the same milestone
twice is one event and one notification) are the shape of the tests here.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.enums import ConsolidationState, Role, RouteGroup
from app.models import AuditEvent, ConsolidationEventLink, ShipmentEvent
from app.services import consolidation_service as cs
from app.services import tariff_import_service as tis
from app.services.errors import ConflictError, NotFoundError, ValidationError
from tests.conftest import booked_shipment, make_customer, make_draft

WORKBOOK = (
    Path(__file__).resolve().parent / "fixtures" / "kango_canada_rates_2026-10-12_sanitized.xlsx"
)


@pytest.fixture
def active_tariff(db):
    version = tis.import_workbook(
        db,
        WORKBOOK.read_bytes(),
        file_name="k.xlsx",
        effective_from=date(2026, 10, 12),
        label=None,
        actor=None,
    )
    tis.activate_version(db, version, actor=None)
    db.commit()
    return version


@pytest.fixture
def three_children(db):
    """Three confirmed Vietnam → Canada shipments for three customers."""
    customers = [make_customer(db, email=f"c{i}@demo.example.com") for i in range(3)]
    return [booked_shipment(db, c, RouteGroup.VCA) for c in customers]


def _consolidation(db, **overrides):
    payload = {
        "solaris_service": "air_standard",
        "origin": "HCM",
        "vendor_reference": "AAAAA",
        "actual_weight_kg": "21",
        "length_cm": "60",
        "width_cm": "40",
        "height_cm": "40",
    }
    payload.update(overrides)
    row = cs.create_consolidation(db, payload, actor=None)
    db.commit()
    return row


# --- Membership ---------------------------------------------------------------------------------


def test_a_consolidation_gets_a_solaris_reference_and_accepts_confirmed_vca_shipments(
    db, three_children
):
    con = _consolidation(db)
    assert con.public_id == "MST-000001" and con.state == ConsolidationState.OPEN
    for shipment in three_children:
        cs.add_member(db, con, shipment, actor=None)
    db.commit()
    assert [m.shipment_id for m in cs.active_memberships(db, con.id)] == [
        s.id for s in three_children
    ]
    actions = [a.action for a in db.query(AuditEvent).order_by(AuditEvent.id)]
    assert actions.count("consolidation.member_add") == 3


def test_a_shipment_rides_in_one_consolidation_at_a_time(db, three_children):
    first = _consolidation(db)
    second = _consolidation(db, vendor_reference="BBBBB")
    cs.add_member(db, first, three_children[0], actor=None)
    db.commit()
    with pytest.raises(ConflictError, match="already in consolidation MST-000001"):
        cs.add_member(db, second, three_children[0], actor=None)
    db.rollback()
    cs.remove_member(db, first, three_children[0], reason="moved to the later flight", actor=None)
    db.commit()
    cs.add_member(db, second, three_children[0], actor=None)
    db.commit()
    assert cs.active_membership_for_shipment(db, three_children[0].id).consolidation_id == second.id
    # The history survives: two rows for the shipment, one closed.
    from app.models import ConsolidationMembership  # noqa: PLC0415

    rows = db.query(ConsolidationMembership).filter_by(shipment_id=three_children[0].id).all()
    assert len(rows) == 2 and sum(1 for r in rows if r.removed_at is None) == 1


def test_drafts_cancelled_bookings_and_other_routes_are_refused(db):
    con = _consolidation(db)
    customer = make_customer(db)
    draft = make_draft(db, customer, RouteGroup.VCA)
    with pytest.raises(ConflictError, match="confirmed booking"):
        cs.add_member(db, con, draft, actor=None)
    db.rollback()
    canada_to_vietnam = booked_shipment(db, customer, RouteGroup.CAV)
    with pytest.raises(ConflictError, match="Vietnam"):
        cs.add_member(db, con, canada_to_vietnam, actor=None)
    db.rollback()


def test_removal_needs_a_reason(db, three_children):
    con = _consolidation(db)
    cs.add_member(db, con, three_children[0], actor=None)
    db.commit()
    with pytest.raises(ValidationError, match="why"):
        cs.remove_member(db, con, three_children[0], reason="  ", actor=None)
    db.rollback()
    with pytest.raises(NotFoundError):
        cs.remove_member(db, con, three_children[1], reason="never joined", actor=None)


# --- Booking --------------------------------------------------------------------------------------


def test_booking_resolves_the_vendor_product_and_stores_the_chargeable_weight(
    db, active_tariff, three_children
):
    con = _consolidation(db)
    for shipment in three_children:
        cs.add_member(db, con, shipment, actor=None)
    db.commit()
    cs.book_consolidation(db, con, actor=None, now=datetime(2026, 10, 19, 9, 0))
    db.commit()
    assert con.state == ConsolidationState.BOOKED
    assert con.tariff_version_id == active_tariff.id
    assert con.dim_divisor == 6000
    assert con.volumetric_weight_kg == Decimal("16.000")
    assert con.chargeable_weight_kg == Decimal("21.000")
    assert con.handed_over_at == datetime(2026, 10, 19, 9, 0)
    from app.models import TariffProduct  # noqa: PLC0415

    product = db.get(TariffProduct, con.tariff_product_id)
    assert (product.code, product.origin) == ("AIR-CAD", "HCM")
    with pytest.raises(ConflictError, match="only an open consolidation"):
        cs.add_member(
            db,
            con,
            booked_shipment(db, make_customer(db, email="late@demo.example.com"), RouteGroup.VCA),
            actor=None,
        )


def test_express_maps_to_the_express_product_and_sea_is_refused_by_name(
    db, active_tariff, three_children
):
    express = _consolidation(db, solaris_service="air_express", origin="HAN")
    cs.add_member(db, express, three_children[0], actor=None)
    db.commit()
    cs.book_consolidation(db, express, actor=None)
    db.commit()
    from app.models import TariffProduct  # noqa: PLC0415

    assert db.get(TariffProduct, express.tariff_product_id).code == "AIR-CAD EXPRESS"

    # Under the RC-UAT-25 method Sea and UPS have no Kango product mapped and are refused;
    # the confirmed method books them without one (DEC-0265, test_method_v07_service.py).
    from app.services import pricing_method_service as pms  # noqa: PLC0415

    pms.update_method_settings(db, {"pricing_method": "rc25"}, actor=None)
    db.commit()
    sea = _consolidation(db, solaris_service="sea", vendor_reference="SEA01")
    cs.add_member(db, sea, three_children[1], actor=None)
    db.commit()
    with pytest.raises(ConflictError, match="Sea has no Kango product"):
        cs.book_consolidation(db, sea, actor=None)
    db.rollback()
    ups = _consolidation(db, solaris_service="ups", vendor_reference="UPS01")
    cs.add_member(db, ups, three_children[2], actor=None)
    db.commit()
    with pytest.raises(ConflictError, match="UPS has no Kango product"):
        cs.book_consolidation(db, ups, actor=None)


def test_booking_needs_members_a_reference_a_weight_and_an_active_tariff(db, three_children):
    con = _consolidation(db, vendor_reference=None, actual_weight_kg=None)
    with pytest.raises(ConflictError, match="at least one shipment"):
        cs.book_consolidation(db, con, actor=None)
    db.rollback()
    cs.add_member(db, con, three_children[0], actor=None)
    db.commit()
    with pytest.raises(ValidationError, match="booking reference"):
        cs.book_consolidation(db, con, actor=None)
    db.rollback()
    cs.update_consolidation(db, con, {"vendor_reference": "AAAAA"}, actor=None)
    with pytest.raises(ValidationError, match="actual weight"):
        cs.book_consolidation(db, con, actor=None)
    db.rollback()
    cs.update_consolidation(
        db, con, {"vendor_reference": "AAAAA", "actual_weight_kg": "21"}, actor=None
    )
    with pytest.raises(ConflictError, match="No tariff version is active"):
        cs.book_consolidation(db, con, actor=None)


def test_cancelling_releases_every_member_and_leaves_their_bookings_alone(db, three_children):
    con = _consolidation(db)
    for shipment in three_children:
        cs.add_member(db, con, shipment, actor=None)
    db.commit()
    cs.cancel_consolidation(db, con, reason="flight cancelled by the vendor", actor=None)
    db.commit()
    assert con.state == ConsolidationState.CANCELLED
    assert cs.active_memberships(db, con.id) == []
    for shipment in three_children:
        db.refresh(shipment)
        assert shipment.booking_state == "confirmed" and shipment.cancelled_at is None
    with pytest.raises(ConflictError, match="already cancelled"):
        cs.cancel_consolidation(db, con, reason="again", actor=None)


# --- Master milestones ----------------------------------------------------------------------------


def test_a_master_milestone_reaches_every_member_once_and_is_marked_as_inherited(
    db, active_tariff, three_children
):
    """Directive v2.1 tests 2 and 8."""
    con = _consolidation(db)
    for shipment in three_children:
        cs.add_member(db, con, shipment, actor=None)
    db.commit()
    cs.book_consolidation(db, con, actor=None)
    db.commit()
    when = datetime(2026, 10, 19, 10, 0)
    result = cs.record_master_event(
        db,
        con,
        {"event_type": "departed_origin", "occurred_at": when, "location_label": "SGN"},
        actor=None,
    )
    db.commit()
    assert sorted(result["applied"]) == sorted(s.public_id for s in three_children)
    assert result["duplicates"] == [] and result["refused"] == []
    links = db.query(ConsolidationEventLink).filter_by(consolidation_id=con.id).all()
    assert len(links) == 3
    assert {link.shipment_id for link in links} == {s.id for s in three_children}
    inherited = [db.get(ShipmentEvent, link.event_id) for link in links]
    assert all(e.event_type == "departed_origin" and e.occurred_at == when for e in inherited)
    for shipment in three_children:
        db.refresh(shipment)
        assert shipment.operational_state == "departed_origin"

    # The same master milestone again: nothing new, every member reported as a duplicate.
    again = cs.record_master_event(
        db, con, {"event_type": "departed_origin", "occurred_at": when}, actor=None
    )
    db.commit()
    assert again["applied"] == [] and sorted(again["duplicates"]) == sorted(result["applied"])
    assert db.query(ConsolidationEventLink).filter_by(consolidation_id=con.id).count() == 3

    # A later milestone is new; a milestone on the shipment itself is not inherited.
    later = cs.record_master_event(
        db,
        con,
        {"event_type": "arrived_destination", "occurred_at": when + timedelta(hours=2)},
        actor=None,
    )
    db.commit()
    assert len(later["applied"]) == 3
    from app.services import event_service  # noqa: PLC0415

    own = event_service.record_event(
        db,
        three_children[0],
        {"event_type": "out_for_delivery", "occurred_at": when + timedelta(hours=3)},
    )
    db.commit()
    assert (
        db.query(ConsolidationEventLink)
        .filter(ConsolidationEventLink.event_id.in_([e.id for e in own]))
        .count()
        == 0
    )


def test_a_cancelled_member_is_released_and_a_future_time_or_package_target_is_refused(
    db, active_tariff, three_children
):
    con = _consolidation(db)
    for shipment in three_children:
        cs.add_member(db, con, shipment, actor=None)
    db.commit()
    with pytest.raises(ValidationError, match="whole shipments"):
        cs.record_master_event(
            db, con, {"event_type": "departed_origin", "package_id": 1}, actor=None
        )
    db.rollback()
    # Cancelling a member's booking releases it from the consolidation, whatever the
    # consolidation's state, so the master never keeps a shipment that will not travel.
    from app.services import booking_service  # noqa: PLC0415

    booking_service.cancel_shipment(db, three_children[2], reason="customer withdrew", actor=None)
    db.commit()
    assert [m.shipment_id for m in cs.active_memberships(db, con.id)] == [
        three_children[0].id,
        three_children[1].id,
    ]
    result = cs.record_master_event(db, con, {"event_type": "departed_origin"}, actor=None)
    db.commit()
    assert len(result["applied"]) == 2 and result["refused"] == []
    far_future = datetime.utcnow() + timedelta(days=1)
    result = cs.record_master_event(
        db, con, {"event_type": "arrived_destination", "occurred_at": far_future}, actor=None
    )
    db.commit()
    assert result["applied"] == [] and len(result["refused"]) == 2
    assert all("future" in r["reason"] for r in result["refused"])


def test_a_milestone_with_no_stated_time_repeats_on_type_alone(db, active_tariff, three_children):
    """Directive v2.1 acceptance test 8 for the common case: staff click the same milestone
    twice without typing a time."""
    con = _consolidation(db)
    cs.add_member(db, con, three_children[0], actor=None)
    db.commit()
    first = cs.record_master_event(db, con, {"event_type": "departed_origin"}, actor=None)
    second = cs.record_master_event(db, con, {"event_type": "departed_origin"}, actor=None)
    db.commit()
    assert len(first["applied"]) == 1
    assert second["applied"] == [] and len(second["duplicates"]) == 1
    assert db.query(ConsolidationEventLink).filter_by(consolidation_id=con.id).count() == 1
    # A stated, different time is a new fact.
    third = cs.record_master_event(
        db,
        con,
        {"event_type": "departed_origin", "occurred_at": datetime(2026, 10, 19, 1, 0)},
        actor=None,
    )
    assert len(third["applied"]) == 1


def test_a_booked_consolidation_still_accepts_a_corrected_vendor_reference(
    db, active_tariff, three_children
):
    con = _consolidation(db, vendor_reference="AAAAA")
    cs.add_member(db, con, three_children[0], actor=None)
    db.commit()
    cs.book_consolidation(db, con, actor=None)
    db.commit()
    cs.update_consolidation(
        db, con, {"vendor_reference": "AAAAB", "internal_notes": "typo fixed"}, actor=None
    )
    assert con.vendor_reference == "AAAAB"
    with pytest.raises(ConflictError, match="only accepts corrections"):
        cs.update_consolidation(db, con, {"actual_weight_kg": "25"}, actor=None)


def test_booking_refuses_a_member_that_is_no_longer_confirmed(db, active_tariff, three_children):
    """Belt and braces for the release-on-cancel rule: a membership left behind by any other
    path cannot be booked."""
    from app.models import ConsolidationMembership  # noqa: PLC0415
    from app.services import booking_service  # noqa: PLC0415

    con = _consolidation(db)
    cs.add_member(db, con, three_children[0], actor=None)
    db.commit()
    booking_service.cancel_shipment(db, three_children[0], reason="withdrew", actor=None)
    db.commit()
    # Re-open the membership by hand to simulate a stale row.
    row = db.query(ConsolidationMembership).filter_by(shipment_id=three_children[0].id).one()
    row.removed_at = None
    db.commit()
    with pytest.raises(ConflictError, match="no longer a confirmed booking"):
        cs.book_consolidation(db, con, actor=None)


# --- Routes and privacy ---------------------------------------------------------------------------


def test_the_staff_routes_run_the_whole_flow(as_admin, db, active_tariff, three_children):
    created = as_admin.post(
        "/api/v1/consolidations",
        json={
            "solaris_service": "air_standard",
            "origin": "HCM",
            "vendor_reference": "AAAAA",
            "actual_weight_kg": "21",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["public_id"] == "MST-000001" and body["member_count"] == 0
    cid = body["id"]
    for shipment in three_children:
        added = as_admin.post(
            f"/api/v1/consolidations/{cid}/members", json={"shipment_id": shipment.id}
        )
        assert added.status_code == 200, added.text
    detail = as_admin.get(f"/api/v1/consolidations/{cid}").json()
    assert detail["member_count"] == 3 and len(detail["members"]) == 3
    assert detail["members"][0]["customer_public_id"].startswith("STCA-")

    removed = as_admin.post(
        f"/api/v1/consolidations/{cid}/members/{three_children[2].id}/remove",
        json={"reason": "wrong flight"},
    )
    assert removed.status_code == 200 and removed.json()["member_count"] == 2

    booked = as_admin.post(f"/api/v1/consolidations/{cid}/book")
    assert booked.status_code == 200, booked.text
    assert booked.json()["state"] == "booked" and booked.json()["chargeable_weight_kg"] == "21.000"
    assert booked.json()["vendor_product_code"] == "AIR-CAD"

    event = as_admin.post(
        f"/api/v1/consolidations/{cid}/events",
        json={
            "event_type": "departed_origin",
            "occurred_at": "2026-10-19T10:00:00",
            "location_label": "SGN",
        },
    )
    assert event.status_code == 201, event.text
    assert len(event.json()["applied"]) == 2

    listed = as_admin.get("/api/v1/consolidations", params={"state": "booked"}).json()
    assert listed["total"] == 1

    shipment_page = as_admin.get(f"/api/v1/shipments/{three_children[0].id}").json()
    assert shipment_page["consolidation"]["public_id"] == "MST-000001"
    assert shipment_page["consolidation"]["vendor_reference"] == "AAAAA"
    assert shipment_page["payer"] is None

    completed = as_admin.post(f"/api/v1/consolidations/{cid}/complete")
    assert completed.status_code == 200 and completed.json()["state"] == "completed"


def test_roles_marketing_and_read_only_cannot_write_and_operations_can(api_for, db, three_children):
    operations = api_for(Role.OPERATIONS)
    created = operations.post(
        "/api/v1/consolidations", json={"solaris_service": "air_standard", "origin": "HCM"}
    )
    assert created.status_code == 201
    cid = created.json()["id"]
    assert (
        operations.post(
            f"/api/v1/consolidations/{cid}/members", json={"shipment_id": three_children[0].id}
        ).status_code
        == 200
    )
    assert (
        operations.post(
            f"/api/v1/consolidations/{cid}/events", json={"event_type": "departed_origin"}
        ).status_code
        == 201
    )
    # A consolidation carries the vendor's reference and billed weight, so reading one needs
    # tariff:read as well (DEC-0172): Marketing and the read-only manager get 403 on reads too.
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        client = api_for(role)
        assert (
            client.post(
                "/api/v1/consolidations", json={"solaris_service": "air_standard", "origin": "HCM"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/v1/consolidations/{cid}/events", json={"event_type": "departed_origin"}
            ).status_code
            == 403
        )
        assert client.get("/api/v1/consolidations").status_code == 403
        assert client.get(f"/api/v1/consolidations/{cid}").status_code == 403
        # The shipment page still shows which master it rides in, without the vendor's number.
        page = client.get(f"/api/v1/shipments/{three_children[0].id}")
        if page.status_code == 200:
            assert page.json()["consolidation"]["public_id"].startswith("MST-")
            assert page.json()["consolidation"]["vendor_reference"] is None


def test_the_vendor_reference_and_the_master_never_reach_the_public_tracking_page(
    client, db, active_tariff, three_children
):
    """Directive v2.1 tests 1 and 2: Solaris branding, no vendor reference, no other customer."""
    con = _consolidation(db, vendor_reference="KANGO-AWB-77")
    for shipment in three_children:
        cs.add_member(db, con, shipment, actor=None)
    db.commit()
    cs.book_consolidation(db, con, actor=None)
    cs.record_master_event(
        db,
        con,
        {
            "event_type": "departed_origin",
            "is_public_update": True,
            "public_update_text": "On its way to Canada",
        },
        actor=None,
    )
    db.commit()
    client.cookies.clear()
    response = client.get(f"/api/v1/public/track/{three_children[0].public_id}")
    assert response.status_code == 200, response.text
    text = response.text
    assert "On its way to Canada" in text
    for forbidden in (
        "KANGO-AWB-77",
        "MST-000001",
        "consolidation",
        "vendor",
        three_children[1].public_id,
    ):
        assert forbidden not in text, forbidden
