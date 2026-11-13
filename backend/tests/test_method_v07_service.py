"""Method v0.7 through the database and the API (Louis, 2026-11-03 PM; DEC-0260..0264).

* "Packed as one box for Kango" only on a master with exactly one package.
* Surcharge rows for other routes are excluded (Vietnam → Canada only).
* The sea minimum: no customer ↔ package record → whole master, a warning, not a block.
* The admin "Import Kango rate sheet": upload → draft + diff (nothing changes) → confirm →
  history → rollback; quotes keep the version they were priced with.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.enums import RouteGroup
from app.core.time_utils import utcnow
from app.models import QuoteVersion, ShipmentPackage, TariffSurchargeRule
from app.services import consolidation_service as cs
from app.services import fx_service
from app.services import pricing_method_service as pms
from app.services import pricing_service as ps
from app.services import rate_sheet_service as rss
from app.services import shipment_item_service as items
from app.services import tariff_import_service as tis
from app.services.errors import ConflictError, ValidationError
from tests.conftest import booked_shipment, make_customer, see_committed_changes
from tests.test_fx_service import SAMPLE_XML
from tests.test_quotes import WORKBOOK as OCT_12

D = Decimal
NOV_03 = Path(__file__).parent / "fixtures" / "kango_canada_rates_2026-11-03_sanitized.xlsx"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _load(db, path: Path, effective: date, *, activate=True):
    version = tis.import_workbook(
        db, path.read_bytes(), file_name=path.name, effective_from=effective, label=None,
        actor=None,
    )  # fmt: skip
    if activate:
        tis.activate_version(db, version, actor=None)
    db.commit()
    return version


@pytest.fixture
def nov(db):
    _load(db, NOV_03, date(2026, 11, 3))
    fx_service.sync_once(db, fetcher=lambda _u: SAMPLE_XML, clock=utcnow, worker_name="t")
    db.commit()
    return db


def _master(db, kgs=(3, 6, 12), *, service="air_standard", origin="HCM", actual="21"):
    kids = []
    for kg in kgs:
        shipment = booked_shipment(
            db, make_customer(db, email=f"v07-{len(kids)}-{kg}@demo.example.com"), RouteGroup.VCA
        )
        for package in db.query(ShipmentPackage).filter_by(shipment_id=shipment.id):
            package.weight_kg = package.weight_value = D(kg)
            package.length_cm = package.width_cm = package.height_cm = None
        kids.append(shipment)
    db.commit()
    con = cs.create_consolidation(
        db,
        {"solaris_service": service, "origin": origin, "vendor_reference": "V07",
         "actual_weight_kg": actual},
        actor=None,
    )  # fmt: skip
    for shipment in kids:
        cs.add_member(db, con, shipment, actor=None)
    db.commit()
    return con, kids


# --- Packed as one box: single-package masters only -------------------------------------------


def test_packed_as_one_box_is_refused_on_a_master_with_several_packages(nov):
    db = nov
    con, _kids = _master(db)
    with pytest.raises(ValidationError, match="one package"):
        ps.replace_cartons(
            db, con, [{"weight_kg": "10", "packed_as_one_box": True}, {"weight_kg": "11"}],
            actor=None,
        )  # fmt: skip
    db.rollback()
    ps.replace_cartons(db, con, [{"weight_kg": "21", "packed_as_one_box": True}], actor=None)
    db.commit()
    assert pms.package_flags(db, con.id) == {1: True}
    # Two packages now: the flag is cleared, and cannot be set again.
    ps.replace_cartons(db, con, [{"weight_kg": "10"}, {"weight_kg": "11"}], actor=None)
    db.commit()
    assert pms.package_flags(db, con.id) == {1: False}
    with pytest.raises(ValidationError, match="one package"):
        pms.set_package_flag(db, con.id, 1, True, actor=None)


# --- Vietnam → Canada only ----------------------------------------------------------------------


@pytest.mark.parametrize(("section", "stt"), [("hcm_air", 44), ("han_air", 8)])
def test_rows_for_other_routes_are_excluded(nov, section, stt):
    db = nov
    rule = (
        db.query(TariffSurchargeRule)
        .filter_by(version_id=tis.active_version(db).id, section=section, stt=stt)
        .one()
    )
    assert rule.applies_to_canada is False
    con, kids = _master(db, origin="HCM" if section == "hcm_air" else "HAN")
    item = items.add_item(db, kids[0], {"description": "Cây"}, actor=None)
    db.commit()
    with pytest.raises(ConflictError, match="does not apply to Canada"):
        ps.add_fee_line(
            db, kids[0], {"item_id": item.id, "section": section, "stt": stt, "weight_kg": "1"},
            actor=None,
        )  # fmt: skip


def test_the_diff_lists_every_excluded_row_and_meat_keeps_the_canada_rate(nov):
    db = nov
    diff = rss.sheet_diff(db, tis.active_version(db))
    excluded = {(r["section"], r["stt"]) for r in diff["surcharges_excluded_non_canada"]}
    assert {("hcm_air", 44), ("han_air", 8), ("sea_usa", 12), ("sea_usa", 13)} <= excluded
    assert not {k for k in excluded if k[0] in ("hcm_air", "han_air")} - {
        ("hcm_air", 44),
        ("han_air", 8),
    }
    meat = (
        db.query(TariffSurchargeRule)
        .filter_by(version_id=tis.active_version(db).id, section="hcm_air", stt=41)
        .one()
    )
    assert meat.unit_price_vnd == D(20_000)  # "all other AIR routes"; 10,000 / USA ignored


# --- Sea: package record optional -----------------------------------------------------------------


def test_a_sea_master_with_several_packages_and_no_record_prices_with_a_warning(nov):
    db = nov
    con, kids = _master(db, (10, 15, 5), service="sea", actual="30")
    ps.replace_cartons(db, con, [{"weight_kg": "15"}, {"weight_kg": "15"}], actor=None)
    for shipment, kg in ((kids[0], "2"), (kids[1], "3")):
        item = items.add_item(db, shipment, {"description": "Khô"}, actor=None)
        ps.add_fee_line(
            db, shipment, {"item_id": item.id, "section": "sea_vendor", "stt": 1, "weight_kg": kg},
            actor=None,
        )  # fmt: skip
    db.commit()
    est, _ = ps.estimate_for(db, con)
    assert not est.blocking, est.blocking
    assert "sea_package_unknown" in {i.code for i in est.provisional}
    (food,) = [ln for ln in est.method_detail["lines"] if ln["class"] == "SEA_ITEM_MIN"]
    assert food["vendor_vnd"] == D(400_000)
    assert food["cost_alloc_vnd"] == {kids[0].id: D(160_000), kids[1].id: D(240_000)}
    assert food["quote_vnd"] == {kids[0].id: D(400_000), kids[1].id: D(400_000)}


# --- Admin: import Kango rate sheet -------------------------------------------------------------


def _upload(api, path: Path, effective: str):
    with path.open("rb") as handle:
        return api.post(
            "/api/v1/tariffs/rate-sheet/import",
            files={"file": (path.name, handle, XLSX)},
            data={"effective_from": effective},
        )


def test_import_diff_confirm_history_and_rollback(as_admin, db, admin_is_tariff_approver):
    old = _load(db, OCT_12, date(2026, 10, 12))
    fx_service.sync_once(db, fetcher=lambda _u: SAMPLE_XML, clock=utcnow, worker_name="t")
    db.commit()
    con, kids = _master(db)

    # 1. Upload: a draft and its diff; nothing changes yet.
    response = _upload(as_admin, NOV_03, "2026-11-03")
    assert response.status_code == 201, response.text
    body = response.json()
    draft_id = body["version"]["id"]
    assert body["version"]["status"] == "draft" and body["next_step"] == "confirm"
    diff = body["diff"]
    group = next(
        g
        for g in diff["bracket_groups"]
        if (g["origin"], g["product_code"], g["zone"], g["kind"]) == ("HCM", "AIR-CAD", 2, "per_kg")
    )
    assert group["changed"] == 4 and group["delta_min_vnd"] == group["delta_max_vnd"] == "17000.00"
    han = next(
        g
        for g in diff["bracket_groups"]
        if (g["origin"], g["product_code"], g["zone"], g["kind"])
        == ("HAN", "AIR-CAD", 2, "per_bill")
    )
    assert han["changed"] == 41
    assert diff["fx"] == {"old_vnd_per_cad": "19500.00", "new_vnd_per_cad": "19500.00",
                          "changed": False}  # fmt: skip
    assert diff["piece_fees_changed"] == []
    assert diff["warehouse_zone"] == {"fsa": "L5A", "ground_zone": 2, "express_zone": 3}
    assert diff["source_file_name"] == NOV_03.name and len(diff["source_sha256"]) == 64
    see_committed_changes(db)
    assert tis.active_version(db).id == old.id
    est, _ = ps.estimate_for(db, con)
    assert est.method_detail["rate_per_kg_vnd"] == D(243_000)

    # 2. Confirm: the approver activates it; new masters price at 260,000.
    assert as_admin.post(f"/api/v1/tariffs/versions/{draft_id}/approve").status_code == 200
    see_committed_changes(db)
    est, _ = ps.estimate_for(db, con)
    assert est.method_detail["rate_per_kg_vnd"] == D(260_000)
    ps.confirm_rate(db, kids[0], rate=None, reason=None, actor=None)
    priced = ps.finalize(db, kids[0], negative_margin_reason=None, actor=None)
    db.commit()
    assert priced.tariff_version_id == draft_id

    # 3. History: both versions, newest first, with file, hash and events.
    history = as_admin.get("/api/v1/tariffs/rate-sheet/history").json()["versions"]
    assert [v["id"] for v in history][:2] == [draft_id, old.id]
    assert [v["status"] for v in history][:2] == ["active", "superseded"]
    assert history[0]["source_sha256"] and history[0]["source_file_name"] == NOV_03.name
    assert "tariff_version.approved" in {e["action"] for e in history[0]["events"]}

    # 4. Rollback to 12-Oct; the finalised quote keeps the version it was priced with.
    rolled = as_admin.post(f"/api/v1/tariffs/versions/{old.id}/rollback")
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["status"] == "active"
    see_committed_changes(db)
    assert tis.active_version(db).id == old.id
    est, _ = ps.estimate_for(db, con)
    assert est.method_detail["rate_per_kg_vnd"] == D(243_000)
    assert db.get(QuoteVersion, priced.id).tariff_version_id == draft_id
    events = as_admin.get("/api/v1/tariffs/rate-sheet/history").json()["versions"]
    assert "tariff_version.rolled_back" in {
        e["action"] for v in events if v["id"] == old.id for e in v["events"]
    }
    # Only a superseded version can be rolled back to.
    again = as_admin.post(f"/api/v1/tariffs/versions/{old.id}/rollback")
    assert again.status_code == 409


def test_rollback_needs_the_approver(api_for, db):
    from app.core.enums import Role

    old = _load(db, OCT_12, date(2026, 10, 12))
    _load(db, NOV_03, date(2026, 11, 3))
    response = api_for(Role.OPERATIONS).post(f"/api/v1/tariffs/versions/{old.id}/rollback")
    assert response.status_code == 403
    response = api_for(Role.ADMIN).post(f"/api/v1/tariffs/versions/{old.id}/rollback")
    assert response.status_code == 403  # the Admin is not the designated approver here
    see_committed_changes(db)
    assert tis.active_version(db).effective_from == date(2026, 11, 3)


def test_the_demo_seed_loads_the_2026_11_03_sheet():
    from app import seed_pricing

    assert seed_pricing.WORKBOOK.name == "kango_canada_rates_2026-11-03_sanitized.xlsx"
    assert seed_pricing.WORKBOOK.exists()


# --- v0.6 fixes: booking Sea / UPS, the bill weight at booking (DEC-0265) -----------------------


def _food(db, shipment, kg, rule=1):
    item = items.add_item(db, shipment, {"description": "Khô bò"}, actor=None)
    ps.add_fee_line(
        db, shipment, {"item_id": item.id, "section": "sea_vendor", "stt": rule, "weight_kg": kg},
        actor=None,
    )  # fmt: skip


def _sea_master(db, scenario):
    if scenario == "S6":
        kgs, cartons, packages = (10, 20, 30), ("30", "30"), (1, 1, 2)
        lines = {0: [("3", 1)], 1: [("15", 2)]}
    else:
        kgs, cartons, packages = (10, 15, 5, 12, 10), ("30", "22"), (1, 1, 1, 2, 2)
        lines = {0: [("2", 1)], 1: [("3", 1)], 3: [("8", 1)], 4: [("6", 1)]}
    con, kids = _master(db, kgs, service="sea", actual=str(sum(int(c) for c in cartons)))
    ps.replace_cartons(db, con, [{"weight_kg": c} for c in cartons], actor=None)
    for kid, pkg in zip(kids, packages, strict=True):
        pms.set_package_member(db, con.id, kid.id, pkg, actor=None)
    for index, entries in lines.items():
        for kg, rule in entries:
            _food(db, kids[index], kg, rule)
    db.commit()
    return con, kids


@pytest.mark.parametrize(
    ("scenario", "cost", "quote", "profit", "margin"),
    [
        ("S6", D("235.90"), D("531.28"), D("295.38"), D("0.00")),
        ("S7", D("202.05"), D("498.04"), D("295.99"), D("39.98")),
    ],
)
def test_a_sea_master_books_without_a_kango_product_and_keeps_its_figures(
    nov, scenario, cost, quote, profit, margin
):
    db = nov
    con, _kids = _sea_master(db, scenario)
    before, _ = ps.estimate_for(db, con)
    assert not before.blocking, before.blocking
    cs.book_consolidation(db, con, actor=None)
    db.commit()
    assert con.state == "booked" and con.tariff_product_id is None and con.dim_divisor == 6000
    after, _ = ps.estimate_for(db, con)
    assert not after.blocking, after.blocking
    totals = after.method_detail["totals"]
    assert (totals["cost_cad"], totals["quote_cad"], totals["profit_cad"]) == (cost, quote, profit)
    assert totals["surcharge_margin_cad"] == margin
    assert after.method_detail["bill_kg"] == before.method_detail["bill_kg"]
    assert after.method_detail["members"] == before.method_detail["members"]


def test_a_ups_master_books_and_is_priced_manually(nov):
    db = nov
    con, _kids = _master(db, service="ups")
    cs.book_consolidation(db, con, actor=None)
    db.commit()
    assert con.tariff_product_id is None
    est, _ = ps.estimate_for(db, con)
    assert "ups_cost_missing" in {i.code for i in est.blocking}


@pytest.mark.parametrize("cartons", [None, ["20.4", "20.9"]])
def test_booking_keeps_the_kango_bill_weight(nov, cartons):
    """Customers 20 + 21 kg, master 41.3 kg: Kango rounds the bill up to 42 kg (§6), so
    42 × 260,000 = 10,920,000 before and after booking (not OD-50's 41.5 kg)."""
    db = nov
    con, _kids = _master(db, (20, 21), actual="41.3")
    if cartons:
        ps.replace_cartons(db, con, [{"weight_kg": c} for c in cartons], actor=None)
        db.commit()
    before, _ = ps.estimate_for(db, con)
    assert before.method_detail["bill_kg"] == D(42) and before.method_detail["base_vnd"] == D(
        10_920_000
    )
    cs.book_consolidation(db, con, actor=None)
    db.commit()
    assert con.chargeable_weight_kg == D(42)
    after, _ = ps.estimate_for(db, con)
    assert after.method_detail["bill_kg"] == D(42) and after.method_detail["base_vnd"] == D(
        10_920_000
    )
    assert after.method_detail["members"] == before.method_detail["members"]
    assert after.method_detail["totals"] == before.method_detail["totals"]


# --- v0.6 fixes: routes for the method's inputs (DEC-0266) --------------------------------------


def test_manual_pricing_route_unblocks_an_express_master(as_admin, nov, api_for):
    from app.core.enums import Role

    db = nov
    con, _kids = _master(db, service="air_express")
    blocked = as_admin.get(f"/api/v1/consolidations/{con.id}/pricing").json()["estimate"]
    # DEC-0271: the cost comes from the rate sheet (Express zone 3).
    assert "express_manual_cost_missing" not in {i["code"] for i in blocked["blocking"]}
    assert D(blocked["method_detail"]["base_vnd"]) == D(21 * 246_000)
    url = f"/api/v1/consolidations/{con.id}/manual-pricing"
    no_reason = as_admin.patch(url, json={"manual_cost_vnd_per_kg": "330000"})
    assert no_reason.status_code == 422 and "reason" in no_reason.text
    response = as_admin.patch(
        url,
        json={
            "manual_cost_vnd_per_kg": "330000",
            "manual_sell_cad_per_kg": "25",
            "reason": "Special rate from Kango",
        },
    )
    assert response.status_code == 200, response.text
    assert D(response.json()["manual_cost_vnd_per_kg"]) == D(330_000)
    estimate = as_admin.get(f"/api/v1/consolidations/{con.id}/pricing").json()["estimate"]
    assert estimate["blocking"] == []
    assert D(estimate["method_detail"]["base_vnd"]) == D(21 * 330_000)
    both = as_admin.patch(url, json={"manual_cost_vnd_per_kg": "1", "manual_cost_vnd_total": "2"})
    assert both.status_code == 422
    assert (
        api_for(Role.MARKETING).patch(url, json={"manual_sell_cad_per_kg": "1"}).status_code == 403
    )


def test_method_settings_route(as_admin, db, api_for):
    from app.core.enums import Role

    body = as_admin.get("/api/v1/pricing/method-settings").json()
    assert body["pricing_method"] == "confirmed" and D(body["sea_cost_vnd_per_kg"]) == D(60_000)
    assert D(body["air_std_rate_low_cad"]) == D(19) and D(body["air_std_rate_high_cad"]) == D(18)
    for alias in ("v0_5", "v0_6", "v0_7"):
        changed = as_admin.patch("/api/v1/pricing/method-settings", json={"pricing_method": alias})
        assert changed.status_code == 200 and changed.json()["pricing_method"] == "confirmed"
    rc25 = as_admin.patch("/api/v1/pricing/method-settings", json={"pricing_method": "rc25"})
    assert rc25.json()["pricing_method"] == "rc25"
    bad = as_admin.patch("/api/v1/pricing/method-settings", json={"fx_source_cost": "ecb"})
    assert bad.status_code == 422
    sea = as_admin.post(
        "/api/v1/pricing/sea-cost",
        json={"sea_cost_vnd_per_kg": "65000", "effective_from": "2027-01-01"},
    )
    assert sea.status_code == 201, sea.text
    assert [r["effective_from"] for r in sea.json()["sea_cost_history"]][-1] == "2027-01-01"
    ops = api_for(Role.OPERATIONS)
    assert (
        ops.patch("/api/v1/pricing/method-settings", json={"markup_kind": "none"}).status_code
        == 403
    )


def test_packed_flag_route(as_admin, nov):
    db = nov
    con, _kids = _master(db)
    url = f"/api/v1/consolidations/{con.id}/packages/1/packed"
    ok = as_admin.patch(url, json={"packed_as_one_box": True})
    assert ok.status_code == 200, ok.text
    assert ok.json()["packed"] == {"1": True}
    ps.replace_cartons(db, con, [{"weight_kg": "10"}, {"weight_kg": "11"}], actor=None)
    db.commit()
    refused = as_admin.patch(url, json={"packed_as_one_box": True})
    assert refused.status_code == 422
