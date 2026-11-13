"""Method v0.6 through the database (Louis, 2026-11-03).

The arithmetic is pinned by ``test_method_v06_golden.py``; this module covers the 2026-11-03
rate sheet loaded as an effective-dated tariff version (every Soleil-zone cell checked against
``rates_2026-11-03.json``), the warehouse zone, origin + service selecting the rate, old
masters keeping their rates, the sea vendor's surcharges on fee lines, the package note and
customer ↔ package record, the owner's per-kg rule, and the switch's new name.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.enums import RouteGroup
from app.core.time_utils import utcnow
from app.models import (
    AuditEvent,
    ShipmentPackage,
    TariffProduct,
    TariffRateBracket,
    TariffZoneFsa,
)
from app.pricing import allocation_classes
from app.pricing.kango_workbook import parse_workbook
from app.services import consolidation_service as cs
from app.services import fx_service
from app.services import pricing_method_service as pms
from app.services import pricing_service as ps
from app.services import shipment_item_service as items
from app.services import tariff_import_service as tis
from app.services.errors import ValidationError
from tests.conftest import booked_shipment, make_customer
from tests.test_fx_service import SAMPLE_XML
from tests.test_quotes import WORKBOOK as OCT_12

D = Decimal
FIXTURES = Path(__file__).parent / "fixtures"
NOV_03 = FIXTURES / "kango_canada_rates_2026-11-03_sanitized.xlsx"
RATES = json.loads((FIXTURES / "kango_rates_2026-11-03.json").read_text(encoding="utf-8"))


def _load(db, path: Path, effective: date):
    version = tis.import_workbook(
        db, path.read_bytes(), file_name=path.name, effective_from=effective, label=None,
        actor=None,
    )  # fmt: skip
    tis.activate_version(db, version, actor=None)
    db.commit()
    return version


@pytest.fixture
def nov_world(db):
    _load(db, NOV_03, date(2026, 11, 3))
    fx_service.sync_once(db, fetcher=lambda _u: SAMPLE_XML, clock=utcnow, worker_name="t")
    db.commit()
    return db


def _master(db, kgs=(3, 6, 12), *, service="air_standard", origin="HCM", actual="21"):
    kids = []
    for kg in kgs:
        shipment = booked_shipment(
            db, make_customer(db, email=f"v06-{len(kids)}-{kg}@demo.example.com"), RouteGroup.VCA
        )
        for package in db.query(ShipmentPackage).filter_by(shipment_id=shipment.id):
            package.weight_kg = package.weight_value = D(kg)
            package.length_cm = package.width_cm = package.height_cm = None
        kids.append(shipment)
    db.commit()
    con = cs.create_consolidation(
        db,
        {"solaris_service": service, "origin": origin, "vendor_reference": "V06",
         "actual_weight_kg": actual},
        actor=None,
    )  # fmt: skip
    for shipment in kids:
        cs.add_member(db, con, shipment, actor=None)
    db.commit()
    return con, kids


# --- The 2026-11-03 sheet in the database ------------------------------------------------------


def test_every_soleil_zone_cell_is_stored_exactly_as_the_sheet(nov_world):
    db = nov_world
    version = tis.active_version(db)
    assert version.effective_from == date(2026, 11, 3)
    checked = 0
    for origin in ("HCM", "HAN"):
        for key, code, zone in (
            ("air_standard", "AIR-CAD", 2),
            ("air_express_reference", "AIR-CAD EXPRESS", 3),
        ):
            product = (
                db.query(TariffProduct)
                .filter_by(version_id=version.id, code=code, origin=origin)
                .one()
            )
            table = RATES["air"][origin][key]
            for row in table["per_bill_bands"] + table["per_kg_tiers"]:
                sheet, cell = row["cell"].split("!")
                stored = (
                    db.query(TariffRateBracket)
                    .filter_by(product_id=product.id, zone=zone, source_cell=cell)
                    .one()
                )
                assert stored.source_sheet == sheet
                assert stored.price_vnd == D(str(row["new_vnd"])), row["cell"]
                checked += 1
    assert checked == 2 * 2 * (41 + 4)


def test_both_origins_both_services_all_zones_are_loaded(nov_world):
    db = nov_world
    version = tis.active_version(db)
    for origin in ("HCM", "HAN"):
        for code in ("AIR-CAD", "AIR-CAD EXPRESS"):
            product = (
                db.query(TariffProduct)
                .filter_by(version_id=version.id, code=code, origin=origin)
                .one()
            )
            for zone in (1, 2, 3):
                rows = db.query(TariffRateBracket).filter_by(product_id=product.id, zone=zone)
                kinds = [r.kind for r in rows]
                assert kinds.count("per_bill") == 41 and kinds.count("per_kg") == 4, (
                    origin, code, zone,
                )  # fmt: skip


# --- Zone check (Mississauga, ON, L5A 3K6) -------------------------------------------------------


def test_the_warehouse_is_zone_2_standard_and_zone_3_express(nov_world):
    """Zone CAD!N821:Q821 = L5A / ON / 2 / 3; the sheet's rule (I3): the first three
    characters of the postal code, spaces removed; column P unless the service is Express."""
    db = nov_world
    version = tis.active_version(db)
    row = db.query(TariffZoneFsa).filter_by(version_id=version.id, fsa="L5A").one()
    assert (row.province, row.ground_zone, row.express_zone) == ("ON", 2, 3)
    parsed = [z for z in parse_workbook(NOV_03.read_bytes()).zone_fsas if z.fsa == "L5A"]
    assert [(z.row, z.ground_zone, z.express_zone) for z in parsed] == [(821, 2, 3)]
    for postal in ("L5A3K6", "L5A 3K6", "l5a 3k6"):
        point = ps._delivery_point(db, version, postal)
        assert (point.ground_zone, point.express_zone, point.beyond_code) == (2, 3, None)

    con, _kids = _master(db)
    est, _ = ps.estimate_for(db, con)
    assert est.zone == 2 and est.method_detail["rate_per_kg_vnd"] == D(260_000)
    con.solaris_service = "air_express"
    db.commit()
    est, _ = ps.estimate_for(db, con)
    ref = est.method_detail["express_reference"]
    # DEC-0271: the Express zone-3 table is now the cost.
    assert (ref["zone"], ref["vnd"], ref["used_for_cost"]) == (3, D(21 * 246_000), True)
    assert est.zone == 3 and est.method_detail["base_vnd"] == D(21 * 246_000)
    assert "express_manual_cost_missing" not in {i.code for i in est.blocking}


# --- Origin + service select the rate -----------------------------------------------------------


def test_origin_and_service_are_required_at_creation(nov_world):
    db = nov_world
    with pytest.raises(ValidationError, match="service"):
        cs.create_consolidation(db, {"origin": "HCM", "actual_weight_kg": "21"}, actor=None)
    db.rollback()
    with pytest.raises(ValidationError, match="origin"):
        cs.create_consolidation(
            db, {"solaris_service": "air_standard", "actual_weight_kg": "21"}, actor=None
        )


@pytest.mark.parametrize(
    ("origin", "service", "base"),
    [
        ("HCM", "air_standard", D(21 * 260_000)),  # HCM-AIR-CAD!C50
        ("HAN", "air_standard", D(21 * 268_000)),  # HN-AIR-CAD!C49
        ("HCM", "sea", D(21 * 60_000)),
        ("HAN", "sea", D(21 * 60_000)),
    ],
)
def test_the_pair_selects_the_base_rate(nov_world, origin, service, base):
    con, _kids = _master(nov_world, service=service, origin=origin)
    est, _ = ps.estimate_for(nov_world, con)
    assert est.method_detail["base_vnd"] == base


def test_changing_origin_or_service_reprices(nov_world):
    db = nov_world
    con, kids = _master(db)
    ps.confirm_rate(db, kids[0], rate=None, reason=None, actor=None)
    db.commit()
    cs.update_consolidation(db, con, {"origin": "HAN"}, actor=None)
    db.commit()
    draft, est = ps.reprice(db, kids[0], actor=None)
    assert est.method_detail["base_vnd"] == D(21 * 268_000)
    assert est.method_detail["members"][kids[0].id]["cost_cad"] == D(
        "41.23"
    )  # 3 × 268,000 / 19,500
    # The customer's price (3 kg × CAD 19) did not move, so its confirmation stands; the
    # cost and the margin are re-priced live.
    assert draft.rate_confirmed_at is not None
    cs.update_consolidation(db, con, {"solaris_service": "sea"}, actor=None)
    db.commit()
    draft, est = ps.reprice(db, kids[0], actor=None)
    assert est.method_detail["base_vnd"] == D(21 * 60_000) and draft.default_rate_cad == D("8.00")
    assert draft.rate_confirmed_at is None  # the service moves the price: confirm again
    assert [e.action for e in db.query(AuditEvent)].count("consolidation.update") == 2


def test_a_master_booked_on_the_old_sheet_keeps_its_rates(db):
    _load(db, OCT_12, date(2026, 10, 12))
    fx_service.sync_once(db, fetcher=lambda _u: SAMPLE_XML, clock=utcnow, worker_name="t")
    db.commit()
    old, _kids = _master(db)
    cs.book_consolidation(db, old, actor=None)
    db.commit()
    _load(db, NOV_03, date(2026, 11, 3))
    est, _ = ps.estimate_for(db, old)
    assert est.method_detail["rate_per_kg_vnd"] == D(243_000)  # 12-Oct HCM-AIR-CAD!C50
    new, _kids = _master(db)
    est, _ = ps.estimate_for(db, new)
    assert est.method_detail["rate_per_kg_vnd"] == D(260_000)


# --- Sea through the service ---------------------------------------------------------------------


def _sea_line(db, shipment, rule, kg):
    item = items.add_item(db, shipment, {"description": "Khô bò"}, actor=None)
    line = ps.add_fee_line(
        db, shipment, {"item_id": item.id, "section": "sea_vendor", "stt": rule,
                       "weight_kg": kg}, actor=None,
    )  # fmt: skip
    db.commit()
    return line


def test_sea_food_minimum_through_fee_lines(nov_world):
    db = nov_world
    con, kids = _master(db, (10, 15, 5), service="sea", actual="30")
    _sea_line(db, kids[0], 1, "2")
    _sea_line(db, kids[1], 1, "3")
    est, _ = ps.estimate_for(db, con)
    assert not est.blocking, est.blocking
    (food,) = [ln for ln in est.method_detail["lines"] if ln["class"] == "SEA_ITEM_MIN"]
    assert food["vendor_vnd"] == D(400_000)
    assert food["cost_alloc_vnd"] == {kids[0].id: D(160_000), kids[1].id: D(240_000)}
    assert est.method_detail["base_vnd"] == D(30 * 60_000)
    with pytest.raises(ValidationError, match="weight"):
        item = items.add_item(db, kids[2], {"description": "Bánh"}, actor=None)
        ps.add_fee_line(
            db, kids[2], {"item_id": item.id, "section": "sea_vendor", "stt": 2}, actor=None
        )


def test_the_sea_cost_is_effective_dated(nov_world):
    db = nov_world
    pms.seed_sea_rules(db)
    assert pms.sea_cost_vnd_per_kg(db, date(2026, 11, 3)) == D(60_000)
    pms.set_sea_cost(db, "65000", date(2027, 1, 1), actor=None)
    db.commit()
    assert pms.sea_cost_vnd_per_kg(db, date(2026, 12, 31)) == D(60_000)
    assert pms.sea_cost_vnd_per_kg(db, date(2027, 1, 1)) == D(65_000)


# --- Packages: note and members ----------------------------------------------------------------


def test_package_note_and_members(nov_world):
    db = nov_world
    con, kids = _master(db)
    pms.set_package_note(db, con.id, 1, "STCA-000201, -202, -203", actor=None)
    pms.set_package_member(db, con.id, kids[0].id, 1, actor=None)
    db.commit()
    assert pms.package_notes(db, con.id) == {1: "STCA-000201, -202, -203"}
    assert pms.package_members(db, con.id) == {kids[0].id: 1}
    pms.set_package_note(db, con.id, 1, "  ", actor=None)
    pms.set_package_member(db, con.id, kids[0].id, None, actor=None)
    db.commit()
    assert pms.package_notes(db, con.id) == {} and pms.package_members(db, con.id) == {}
    actions = [e.action for e in db.query(AuditEvent)]
    assert "consolidation.package_note_set" in actions
    assert "consolidation.package_member_set" in actions
    with pytest.raises(ValidationError):
        pms.set_package_note(db, con.id, 1, "x" * 201, actor=None)


# --- Owner rule: per-kg rows with no special note are per item kg (Louis, 2026-11-03) -----------


def test_per_kg_rows_without_a_special_note_are_charged_on_the_items_own_kg():
    parsed = parse_workbook(NOV_03.read_bytes())
    classes = {(r[0], r[1]): r[3] for r in allocation_classes.ALLOCATION_ROWS}
    plain = []
    for row in parsed.surcharge_rows:
        if row.section.value not in ("hcm_air", "han_air") or (row.note or "").strip():
            continue
        if tis.resolve_rule(row, [])["basis"] == "per_kg":
            plain.append((row.section.value, row.stt))
            assert classes[(row.section.value, row.stt)] == "ITEM", row.stt
    assert ("hcm_air", 22) in plain and len(plain) >= 15
    assert classes[("hcm_air", 41)] == "ITEM"  # meat, Louis Q3
    assert classes[("hcm_air", 14)] == "WHOLE_PACKAGE"  # its note says full carton


def test_hcm_row_22_is_priced_on_the_item_kg(nov_world):
    db = nov_world
    con, kids = _master(db)
    item = items.add_item(db, kids[0], {"description": "Hàng 22"}, actor=None)
    ps.add_fee_line(
        db, kids[0], {"item_id": item.id, "section": "hcm_air", "stt": 22, "weight_kg": "2"},
        actor=None,
    )  # fmt: skip
    db.commit()
    est, _ = ps.estimate_for(db, con)
    (line,) = [ln for ln in est.method_detail["lines"] if ln["stt"] == 22]
    assert line["class"] == "ITEM" and line["vendor_vnd"] == D(2 * 15_000)


# --- The switch ------------------------------------------------------------------------------------


def test_the_method_is_confirmed_and_older_names_are_aliases(db):
    assert pms.get_method_settings(db).pricing_method == "confirmed"
    row = pms.update_method_settings(db, {"pricing_method": "rc25"}, actor=None)
    assert row.pricing_method == "rc25"
    row = pms.update_method_settings(db, {"pricing_method": "v0_5"}, actor=None)
    assert row.pricing_method == "confirmed" and pms.uses_confirmed_method(db)
    row = pms.update_method_settings(db, {"pricing_method": "v0_6"}, actor=None)
    assert row.pricing_method == "confirmed"
    with pytest.raises(ValidationError):
        pms.update_method_settings(db, {"pricing_method": "v0_9"}, actor=None)


def test_package_routes(as_admin, nov_world):
    db = nov_world
    con, kids = _master(db)
    note = as_admin.patch(
        f"/api/v1/consolidations/{con.id}/packages/1/note",
        json={"customer_note": "STCA-000201, -202"},
    )
    assert note.status_code == 200, note.text
    member = as_admin.patch(
        f"/api/v1/consolidations/{con.id}/members/{kids[1].id}/package",
        json={"carton_sequence": 1},
    )
    assert member.status_code == 200, member.text
    body = as_admin.get(f"/api/v1/consolidations/{con.id}/packages").json()
    assert body == {
        "notes": {"1": "STCA-000201, -202"},
        "members": {str(kids[1].id): 1},
        "packed": {},
        "tracking": {},  # DEC-0272: last-mile tracking per piece
    }
    stray = as_admin.patch(
        f"/api/v1/consolidations/{con.id}/members/999999/package", json={"carton_sequence": 1}
    )
    assert stray.status_code == 404


def test_the_rc25_default_markup_is_labelled_rc25_only(as_admin, db):
    body = as_admin.get("/api/v1/pricing/settings").json()
    assert body["default_markup_label"] == "RC25 method only (no effect under v0.7)"
    assert body["default_markup_in_effect"] is False
    pms.update_method_settings(db, {"pricing_method": "rc25"}, actor=None)
    db.commit()
    assert as_admin.get("/api/v1/pricing/settings").json()["default_markup_in_effect"] is True
