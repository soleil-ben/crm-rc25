"""Surcharges Kango charges per master piece or per shipment (owner, 2026-11-06; DEC-0276).

* Banded per-piece fees (sơn móng tay HCM-01, nước hoa HCM-11, battery HCM-02/03): Kango charges
  once per master piece (kiện), the band on the **total kg of that item type in the piece**
  (OD-50 rounding first: 5.1 kg → 5.0; battery groups to 0.1 kg, OD-59). Each customer with the
  item is quoted the full fee, band on its own kg. The cost is shared by item kg.
* Flat per-piece fees (HCM-12, HCM-28, HAN-07/09/10): once per piece; each customer pays the
  full flat fee.
* Per shipment (HCM-47 fumigation, "lô hàng" = the whole shipment): 550,000 once; each customer
  with wooden items is billed 550,000.

Louis's two handwritten cases are the first two tests.
"""

from __future__ import annotations

from decimal import Decimal

from app.models import TariffSurchargeRule
from app.services import pricing_method_service as pms
from app.services import pricing_service as ps
from app.services import shipment_item_service as items
from app.services import tariff_import_service as tis
from tests.test_method_v07_service import _master, nov  # noqa: F401  (fixture)

D = Decimal


def _rule(db, stt: int, section: str = "hcm_air") -> TariffSurchargeRule:
    return db.query(TariffSurchargeRule).filter_by(
        version_id=tis.active_version(db).id, section=section, stt=stt
    ).one()  # fmt: skip


def _add(db, shipment, stt, kg=None, *, qty=None, name="item"):
    payload = {"description": name}
    if kg is not None:
        payload["weight_kg"] = str(kg)
    item = items.add_item(db, shipment, payload, actor=None)
    line = {"item_id": item.id, "section": "hcm_air", "stt": _rule(db, stt).stt}
    if qty is not None:
        line["quantity"] = str(qty)
    ps.add_fee_line(db, shipment, line, actor=None)


def _lines(est, stt):
    return [ln for ln in est.method_detail["lines"] if ln["stt"] == stt]


def _quotes(est, stt):
    out: dict[int, Decimal] = {}
    for ln in _lines(est, stt):
        for sid, v in ln["quote_vnd"].items():
            out[sid] = out.get(sid, D(0)) + v
    return out


def _estimate(db, con):
    db.commit()
    est, _ = ps.estimate_for(db, con)
    return est


# --- Louis's handwritten cases (master piece 60 × 50 × 40, 20 kg) --------------------------------


def test_case_1_one_customer_with_nail_polish(nov):  # noqa: F811
    db = nov
    con, kids = _master(db, kgs=(10, 7), actual="20")
    _add(db, kids[1], 1, "2", name="sơn móng tay")
    est = _estimate(db, con)
    assert not [i for i in est.blocking if i.code == "fee_unpriced"], est.blocking
    (line,) = _lines(est, 1)
    assert line["vendor_vnd"] == D(300_000)  # cost: band on 2 kg
    assert line["cost_alloc_vnd"] == {kids[1].id: D(300_000)}
    assert _quotes(est, 1) == {kids[1].id: D(300_000)}  # billed to Khách 2 only


def test_case_2_two_customers_pay_kango_once_on_the_total_kg(nov):  # noqa: F811
    db = nov
    con, kids = _master(db, kgs=(5, 8, 5), actual="20")
    _add(db, kids[1], 1, "3", name="sơn móng tay")
    _add(db, kids[2], 1, "4", name="sơn móng tay")
    est = _estimate(db, con)
    (line,) = _lines(est, 1)
    # COST: 3 + 4 = 7 kg in the piece → the 5–22 kg band, 500,000, once.
    assert line["vendor_vnd"] == D(500_000)
    # Shared by item kg: 3/7 and 4/7.
    alloc = line["cost_alloc_vnd"]
    assert sum(alloc.values()) == D(500_000)
    assert alloc[kids[1].id] == D("214285.71") and alloc[kids[2].id] == D("285714.29")
    # QUOTE: each on its own kg (3 kg, 4 kg) → 300,000 each; 100,000 surcharge margin.
    assert _quotes(est, 1) == {kids[1].id: D(300_000), kids[2].id: D(300_000)}


# --- Rounding (A3: OD-50 before the band) -------------------------------------------------------


def test_5_1_kg_of_nail_polish_is_the_first_band_and_5_2_kg_the_second(nov):  # noqa: F811
    db = nov
    con, kids = _master(db, kgs=(8, 8), actual="16")
    _add(db, kids[0], 1, "5.1")
    _add(db, kids[1], 1, "2.6")
    est = _estimate(db, con)
    (line,) = _lines(est, 1)
    assert line["vendor_vnd"] == D(500_000)  # 7.7 kg in the piece → 7.5 → second band
    assert _quotes(est, 1) == {kids[0].id: D(300_000), kids[1].id: D(300_000)}  # 5.1 → 5.0

    con2, kids2 = _master(db, kgs=(8,), actual="8")
    _add(db, kids2[0], 1, "5.2")
    est = _estimate(db, con2)
    assert _lines(est, 1)[0]["vendor_vnd"] == D(500_000)  # 5.2 → 5.5 → second band


# --- One charge per master piece ----------------------------------------------------------------


def test_the_same_item_in_two_master_pieces_is_charged_once_per_piece(nov):  # noqa: F811
    db = nov
    con, kids = _master(db, kgs=(10, 10), actual="20")
    ps.replace_cartons(db, con, [{"weight_kg": "10"}, {"weight_kg": "10"}], actor=None)
    pms.set_package_member(db, con.id, kids[0].id, 1, actor=None)
    pms.set_package_member(db, con.id, kids[1].id, 2, actor=None)
    _add(db, kids[0], 1, "3")
    _add(db, kids[1], 1, "4")
    est = _estimate(db, con)
    lines = _lines(est, 1)
    assert sorted(ln["vendor_vnd"] for ln in lines) == [D(300_000), D(300_000)]
    assert _quotes(est, 1) == {kids[0].id: D(300_000), kids[1].id: D(300_000)}


def test_a_customer_not_placed_in_a_piece_counts_the_master_as_one_piece(nov):  # noqa: F811
    db = nov
    con, kids = _master(db, kgs=(10, 10), actual="20")
    ps.replace_cartons(db, con, [{"weight_kg": "10"}, {"weight_kg": "10"}], actor=None)
    _add(db, kids[0], 1, "3")
    _add(db, kids[1], 1, "4")
    est = _estimate(db, con)
    (line,) = _lines(est, 1)
    assert line["vendor_vnd"] == D(500_000)
    assert "piece_not_recorded" in {i.code for i in est.provisional}


# --- Battery (A1: total battery kg in the piece) ----------------------------------------------


def test_battery_cost_is_banded_on_the_total_battery_kg_in_the_piece(nov):  # noqa: F811
    db = nov
    con, kids = _master(db, kgs=(6, 6), actual="12")
    _add(db, kids[0], 2, "2", name="pin")
    _add(db, kids[1], 2, "2", name="pin")
    est = _estimate(db, con)
    (line,) = _lines(est, 2)
    assert line["vendor_vnd"] == D(700_000)  # 2 + 2 = 4 kg → 3.5–8 kg group
    assert _quotes(est, 2) == {kids[0].id: D(300_000), kids[1].id: D(300_000)}


def test_battery_groups_still_read_the_weight_to_0_1_kg(nov):  # noqa: F811
    db = nov
    con, kids = _master(db, kgs=(6,), actual="6")
    _add(db, kids[0], 2, "3.6", name="pin")
    est = _estimate(db, con)
    assert _lines(est, 2)[0]["vendor_vnd"] == D(700_000)  # OD-59: 3.6 kg → 700,000


# --- Flat per piece (A5) and fumigation per shipment (A4) ----------------------------------------


def test_a_flat_per_piece_fee_is_charged_once_and_billed_to_each(nov):  # noqa: F811
    db = nov
    con, kids = _master(db, kgs=(6, 4), actual="10")
    _add(db, kids[0], 12, name="xịt")
    _add(db, kids[1], 12, name="xịt")
    est = _estimate(db, con)
    (line,) = _lines(est, 12)
    flat = _rule(db, 12).unit_price_vnd
    assert line["vendor_vnd"] == flat
    assert sum(line["cost_alloc_vnd"].values()) == flat
    assert _quotes(est, 12) == {kids[0].id: flat, kids[1].id: flat}


def test_fumigation_one_customer_pays_the_550000(nov):  # noqa: F811
    db = nov
    con, kids = _master(db, kgs=(6, 4), actual="10")
    _add(db, kids[0], 47, name="đồ gỗ")
    est = _estimate(db, con)
    (line,) = _lines(est, 47)
    assert line["vendor_vnd"] == D(550_000)
    assert line["cost_alloc_vnd"] == {kids[0].id: D(550_000)}
    assert _quotes(est, 47) == {kids[0].id: D(550_000)}


def test_fumigation_two_customers_cost_once_and_each_is_billed_550000(nov):  # noqa: F811
    db = nov
    con, kids = _master(db, kgs=(6, 4, 5), actual="15")
    ps.replace_cartons(db, con, [{"weight_kg": "10"}, {"weight_kg": "5"}], actor=None)
    pms.set_package_member(db, con.id, kids[0].id, 1, actor=None)
    pms.set_package_member(db, con.id, kids[1].id, 1, actor=None)
    pms.set_package_member(db, con.id, kids[2].id, 2, actor=None)
    _add(db, kids[0], 47, name="đồ gỗ")
    _add(db, kids[2], 47, name="đồ gỗ")
    est = _estimate(db, con)
    (line,) = _lines(est, 47)  # once for the whole shipment, across both pieces
    assert line["vendor_vnd"] == D(550_000)
    assert sum(line["cost_alloc_vnd"].values()) == D(550_000)
    assert kids[1].id not in line["cost_alloc_vnd"]
    assert _quotes(est, 47) == {kids[0].id: D(550_000), kids[2].id: D(550_000)}


# --- Edge cases ----------------------------------------------------------------------------------


def test_more_than_30_kg_of_one_item_in_a_piece_is_flagged(nov):  # noqa: F811
    db = nov
    con, kids = _master(db, kgs=(20, 15), actual="35")
    _add(db, kids[0], 1, "18")
    _add(db, kids[1], 1, "14")
    est = _estimate(db, con)
    assert "piece_type_over_top_band" in {i.code for i in est.provisional}


def test_nail_polish_without_an_item_weight_asks_for_it(nov):  # noqa: F811
    db = nov
    con, kids = _master(db, kgs=(6,), actual="6")
    _add(db, kids[0], 1, name="sơn móng tay")
    est = _estimate(db, con)
    assert any("enter the item's weight" in i.message for i in est.blocking)
