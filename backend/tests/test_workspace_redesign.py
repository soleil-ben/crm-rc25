"""Workspace redesign (owner, 2026-11-04; DEC-0271 / DEC-0272).

* Kango Air Express is priced on Kango's Express table at the warehouse's zone (L5A = 3).
* A rate-sheet base cost can be overridden only with a reason, and the estimate says so.
* Air Cargo is a new service, priced by hand like UPS.
* Staff names say "Kango"; customer-facing names never do.
* Last-mile tracking per master piece; adding a customer from the workspace books, joins and
  places the shipment in one step, and leaves nothing behind when refused.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.enums import SOLARIS_SERVICE_LABELS, STAFF_SERVICE_LABELS
from app.models import ConsolidationMembership, Shipment
from app.services import pricing_method_service as pms
from app.services import pricing_service as ps
from app.services import workspace_service as ws
from app.services.errors import ConflictError, ValidationError
from tests.conftest import make_customer
from tests.test_method_v07_service import _master, nov  # noqa: F401  (fixture)

D = Decimal


def test_kango_air_express_is_priced_on_the_express_zone_3_table(nov):  # noqa: F811
    con, _kids = _master(nov, service="air_express")
    est, _ = ps.estimate_for(nov, con)
    detail = est.method_detail
    assert est.zone == 3
    assert detail["base_vnd"] == D(21 * 246_000)
    assert detail["express_reference"]["used_for_cost"] is True
    assert "express_manual_cost_missing" not in {i.code for i in est.blocking}


def test_the_express_default_rate_is_the_selling_rate_unless_staff_enter_one(nov):  # noqa: F811
    con, _kids = _master(nov, service="air_express")
    ps.update_settings(nov, {"air_express_default_rate_cad": "25.00"}, actor=None)
    nov.commit()
    est, _ = ps.estimate_for(nov, con)
    assert {m["rate_cad_kg"] for m in est.method_detail["members"].values()} == {D(25)}
    pms.set_manual_pricing(nov, con.id, {"manual_sell_cad_per_kg": "27"}, actor=None)
    nov.commit()
    est, _ = ps.estimate_for(nov, con)
    assert {m["rate_cad_kg"] for m in est.method_detail["members"].values()} == {D(27)}


def test_overriding_a_rate_sheet_cost_needs_a_reason_and_is_flagged(nov):  # noqa: F811
    con, _kids = _master(nov)
    before, _ = ps.estimate_for(nov, con)
    with pytest.raises(ValidationError, match="reason"):
        pms.set_manual_pricing(nov, con.id, {"manual_cost_vnd_total": "5000000"}, actor=None)
    nov.rollback()
    pms.set_manual_pricing(
        nov, con.id, {"manual_cost_vnd_total": "5000000", "reason": "Kango special"}, actor=None
    )
    nov.commit()
    after, _ = ps.estimate_for(nov, con)
    assert after.method_detail["base_vnd"] == D(5_000_000)
    assert before.method_detail["base_vnd"] != after.method_detail["base_vnd"]
    flagged = [i for i in after.provisional if i.code == "base_cost_overridden"]
    assert flagged and "Kango special" in flagged[0].message


def test_air_cargo_is_priced_by_hand(nov):  # noqa: F811
    con, _kids = _master(nov, service="air_cargo")
    est, _ = ps.estimate_for(nov, con)
    assert "air_cargo_cost_missing" in {i.code for i in est.blocking}
    # No reason needed: Air Cargo has no rate sheet to override.
    pms.set_manual_pricing(
        nov,
        con.id,
        {"manual_cost_vnd_per_kg": "200000", "manual_sell_cad_per_kg": "20"},
        actor=None,
    )
    nov.commit()
    est, _ = ps.estimate_for(nov, con)
    assert not est.blocking, est.blocking
    assert est.method_detail["base_vnd"] == D(21 * 200_000)
    assert {m["rate_cad_kg"] for m in est.method_detail["members"].values()} == {D(20)}


def test_staff_names_say_kango_and_customer_names_never_do():
    assert STAFF_SERVICE_LABELS["air_standard"] == "Kango Air Standard"
    assert STAFF_SERVICE_LABELS["air_express"] == "Kango Air Express"
    assert STAFF_SERVICE_LABELS["air_cargo"] == "Air Cargo"
    assert not any("kango" in label.lower() for label in SOLARIS_SERVICE_LABELS.values())


def test_the_master_api_returns_the_staff_name(as_admin, nov):  # noqa: F811
    con, _kids = _master(nov, service="air_express")
    body = as_admin.get(f"/api/v1/consolidations/{con.id}").json()
    assert body["solaris_service_label"] == "Kango Air Express"


# --- Piece tracking ------------------------------------------------------------------------------


def test_piece_tracking_is_optional_may_repeat_and_clears(as_admin, nov):  # noqa: F811
    con, _kids = _master(nov)
    ps.replace_cartons(nov, con, [{"weight_kg": "10"}, {"weight_kg": "11"}], actor=None)
    nov.commit()
    url = f"/api/v1/consolidations/{con.id}/packages"
    assert as_admin.get(url).json()["tracking"] == {}
    for seq in (1, 2):
        r = as_admin.patch(f"{url}/{seq}/tracking", json={"last_mile_tracking": "PUR123"})
        assert r.status_code == 200, r.text
    assert as_admin.get(url).json()["tracking"] == {"1": "PUR123", "2": "PUR123"}
    cleared = as_admin.patch(f"{url}/2/tracking", json={"last_mile_tracking": "  "})
    assert cleared.json()["tracking"] == {"1": "PUR123"}
    too_long = as_admin.patch(f"{url}/1/tracking", json={"last_mile_tracking": "X" * 61})
    assert too_long.status_code == 422


def test_piece_tracking_is_refused_on_a_cancelled_master(nov):  # noqa: F811
    con, _kids = _master(nov)
    con.state = "cancelled"
    nov.commit()
    with pytest.raises(ConflictError):
        ws.set_piece_tracking(nov, con, 1, "PUR1", actor=None)


# --- Add a customer from the workspace -------------------------------------------------------------


def _payload(customer_id, **extra):
    return {
        "customer_id": customer_id,
        "carton_sequence": 2,
        "reference_code": "REF-9",
        "weight_kg": "7.5",
        "length_cm": "30",
        "width_cm": "20",
        "height_cm": "10",
        "contents_description": "Clothes",
        "sender": {"name": "Demo Sender", "country_code": "VN"},
        "recipient": {"name": "Demo Receiver", "city": "Toronto", "country_code": "CA"},
        **extra,
    }


def test_add_customer_books_joins_and_places_in_the_piece(as_admin, nov):  # noqa: F811
    con, kids = _master(nov)
    ps.replace_cartons(nov, con, [{"weight_kg": "10"}, {"weight_kg": "11"}], actor=None)
    nov.commit()
    customer = make_customer(nov, email="ws-new@demo.example.com")
    nov.commit()
    r = as_admin.post(f"/api/v1/consolidations/{con.id}/customers", json=_payload(customer.id))
    assert r.status_code == 201, r.text
    members = r.json()["members"]
    assert len(members) == len(kids) + 1
    added = next(m for m in members if m["shipment_id"] not in {k.id for k in kids})
    shipment = nov.get(Shipment, added["shipment_id"])
    assert shipment.booking_state == "confirmed" and shipment.public_id
    assert shipment.booking_reference == "REF-9"
    assert pms.package_members(nov, con.id)[shipment.id] == 2


def test_a_refused_add_customer_leaves_no_draft_behind(as_admin, nov):  # noqa: F811
    con, _kids = _master(nov)
    customer = make_customer(nov, email="ws-refused@demo.example.com")
    nov.commit()
    count = nov.query(Shipment).filter_by(customer_id=customer.id).count()
    # No recipient city: the booking cannot be confirmed.
    bad = _payload(customer.id, carton_sequence=None, recipient={"name": "R", "country_code": "CA"})
    r = as_admin.post(f"/api/v1/consolidations/{con.id}/customers", json=bad)
    assert r.status_code == 422, r.text
    nov.expire_all()
    assert nov.query(Shipment).filter_by(customer_id=customer.id).count() == count
    # An unknown piece is refused before anything is written.
    r = as_admin.post(
        f"/api/v1/consolidations/{con.id}/customers", json=_payload(customer.id, carton_sequence=9)
    )
    assert r.status_code == 422
    nov.expire_all()
    assert nov.query(Shipment).filter_by(customer_id=customer.id).count() == count
    active = nov.query(ConsolidationMembership).filter_by(consolidation_id=con.id, removed_at=None)
    assert active.count() == 3


def test_add_customer_needs_an_open_master_and_write_permission(as_admin, nov, api_for):  # noqa: F811
    from app.core.enums import Role

    con, _kids = _master(nov)
    customer = make_customer(nov, email="ws-perm@demo.example.com")
    nov.commit()
    url = f"/api/v1/consolidations/{con.id}/customers"
    con.state = "booked"
    nov.commit()
    r = as_admin.post(url, json=_payload(customer.id, carton_sequence=None))
    assert r.status_code == 409
    # The marketing role signs in last: ``api_for`` replaces the shared client's session.
    assert api_for(Role.MARKETING).post(url, json=_payload(customer.id)).status_code == 403


# --- Round 2 (owner review, 2026-11-05; DEC-0273) ---------------------------------------------


def test_add_customer_takes_items_and_builds_the_contents_from_them(as_admin, nov):  # noqa: F811
    from app.models import ShipmentItem

    con, kids = _master(nov)
    customer = make_customer(nov, email="ws-items@demo.example.com")
    nov.commit()
    payload = _payload(customer.id, carton_sequence=None)
    payload.pop("contents_description")
    payload["items"] = [
        {"description": "Mỹ phẩm", "quantity": "2", "weight_kg": "1.5"},
        {"description": "Áo thun"},
    ]
    r = as_admin.post(f"/api/v1/consolidations/{con.id}/customers", json=payload)
    assert r.status_code == 201, r.text
    added = next(m for m in r.json()["members"] if m["shipment_id"] not in {k.id for k in kids})
    shipment = nov.get(Shipment, added["shipment_id"])
    assert shipment.contents_description == "Mỹ phẩm ×2, Áo thun"
    items = (
        nov.query(ShipmentItem).filter_by(shipment_id=shipment.id).order_by(ShipmentItem.sequence)
    )
    assert [(i.description, i.quantity) for i in items] == [("Mỹ phẩm", D(2)), ("Áo thun", D(1))]


def test_add_customer_needs_an_item_when_no_contents_is_given(as_admin, nov):  # noqa: F811
    con, _kids = _master(nov)
    customer = make_customer(nov, email="ws-noitem@demo.example.com")
    nov.commit()
    payload = _payload(customer.id, carton_sequence=None)
    payload.pop("contents_description")
    r = as_admin.post(f"/api/v1/consolidations/{con.id}/customers", json=payload)
    assert r.status_code == 422 and "item" in r.text


def test_edit_customer_reference_weight_and_piece(as_admin, nov):  # noqa: F811
    from app.models import ShipmentPackage

    con, kids = _master(nov)
    ps.replace_cartons(nov, con, [{"weight_kg": "10"}, {"weight_kg": "11"}], actor=None)
    nov.commit()
    url = f"/api/v1/consolidations/{con.id}/customers/{kids[0].id}"
    r = as_admin.patch(
        url, json={"reference_code": "NEW-REF", "weight_kg": "4.5", "carton_sequence": 2}
    )
    assert r.status_code == 200, r.text
    nov.expire_all()
    assert nov.get(Shipment, kids[0].id).booking_reference == "NEW-REF"
    package = nov.query(ShipmentPackage).filter_by(shipment_id=kids[0].id).one()
    assert package.weight_value == D("4.5")
    assert pms.package_members(nov, con.id)[kids[0].id] == 2
    assert as_admin.patch(url, json={"carton_sequence": 9}).status_code == 422


def test_editing_weights_follows_the_master_lock_but_the_reference_does_not(as_admin, nov):  # noqa: F811
    con, kids = _master(nov)
    con.state = "booked"
    nov.commit()
    url = f"/api/v1/consolidations/{con.id}/customers/{kids[0].id}"
    locked = as_admin.patch(url, json={"weight_kg": "4"})
    assert locked.status_code == 409 and "locked" in locked.text
    ok = as_admin.patch(url, json={"reference_code": "LABEL-ONLY"})
    assert ok.status_code == 200, ok.text


def test_editing_a_shipment_outside_the_master_is_refused(as_admin, nov):  # noqa: F811
    con, _kids = _master(nov)
    other, other_kids = _master(nov, kgs=(5,))
    r = as_admin.patch(
        f"/api/v1/consolidations/{con.id}/customers/{other_kids[0].id}",
        json={"reference_code": "X"},
    )
    assert r.status_code == 404
