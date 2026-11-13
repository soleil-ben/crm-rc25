"""Item weights in the confirmed method (owner review, 2026-11-05; DEC-0275).

* A per-kg surcharge on the item (e.g. "Đông y, thuốc nam, thuốc bắc", 30,000 VND/kg) uses the
  weight entered on the item when the fee line has none.
* The battery rule ("Pin kèm thiết bị nhỏ") is banded on the battery item's own weight, not the
  customer's box: Kango charges it once per master piece; the customer with the battery pays
  the full fee (100%).
* A weight typed on the fee line still wins; the RC-UAT-25 engine ignores the item weight.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models import ShipmentPackage, TariffSurchargeRule
from app.services import pricing_service as ps
from app.services import shipment_item_service as items
from app.services import tariff_import_service as tis
from tests.test_method_v07_service import _master, nov  # noqa: F401  (fixture)

D = Decimal


def _rule(db, name_part: str) -> TariffSurchargeRule:
    from app.pricing.kango_semantics import fold

    rows = db.query(TariffSurchargeRule).filter_by(
        version_id=tis.active_version(db).id, section="hcm_air"
    )
    return next(r for r in rows if name_part in fold(r.name))


def _fee(est, shipment_id, stt):
    """(vendor fee, cost to this customer, quote to this customer) in VND for one rule."""
    detail = est.method_detail
    for line in detail["lines"]:
        if line["stt"] == stt:
            return line
    raise AssertionError(f"no line for row {stt}: {detail['lines']}")


def _set_box(db, shipment, kg):
    for package in db.query(ShipmentPackage).filter_by(shipment_id=shipment.id):
        package.weight_kg = package.weight_value = D(kg)
    db.commit()


def test_a_per_kg_item_surcharge_uses_the_item_weight(nov):  # noqa: F811
    db = nov
    con, kids = _master(db, kgs=(12, 4, 5))
    rule = _rule(db, "dong y")
    item = items.add_item(db, kids[0], {"description": "thuốc", "weight_kg": "3"}, actor=None)
    ps.add_fee_line(db, kids[0], {"item_id": item.id, "section": "hcm_air", "stt": rule.stt},
                    actor=None)  # fmt: skip
    db.commit()
    est, _ = ps.estimate_for(db, con)
    assert not [i for i in est.blocking if "kilogram" in i.message], est.blocking
    member = est.method_detail["members"][kids[0].id]
    assert member["own_surcharge_cost_vnd"] == D(90_000)  # 30,000 × 3 kg


def test_a_weight_typed_on_the_line_still_wins(nov):  # noqa: F811
    db = nov
    con, kids = _master(db, kgs=(12, 4, 5))
    rule = _rule(db, "dong y")
    item = items.add_item(db, kids[0], {"description": "thuốc", "weight_kg": "3"}, actor=None)
    ps.add_fee_line(
        db, kids[0], {"item_id": item.id, "section": "hcm_air", "stt": rule.stt, "weight_kg": "2"},
        actor=None,
    )  # fmt: skip
    db.commit()
    est, _ = ps.estimate_for(db, con)
    assert est.method_detail["members"][kids[0].id]["own_surcharge_cost_vnd"] == D(60_000)


def test_without_any_weight_the_line_still_asks_for_one(nov):  # noqa: F811
    db = nov
    con, kids = _master(db, kgs=(12, 4, 5))
    rule = _rule(db, "dong y")
    item = items.add_item(db, kids[0], {"description": "thuốc"}, actor=None)
    ps.add_fee_line(db, kids[0], {"item_id": item.id, "section": "hcm_air", "stt": rule.stt},
                    actor=None)  # fmt: skip
    db.commit()
    est, _ = ps.estimate_for(db, con)
    assert any("per kilogram" in i.message for i in est.blocking)


@pytest.mark.parametrize(("item_kg", "fee"), [("2", 300_000), ("3.6", 700_000)])
def test_the_battery_band_reads_the_battery_items_weight(nov, item_kg, fee):  # noqa: F811
    db = nov
    con, kids = _master(db, kgs=(12, 4, 5))
    rule = _rule(db, "pin kem thiet bi nho 1-3")
    item = items.add_item(
        db, kids[0], {"description": "sport items with battery", "weight_kg": item_kg}, actor=None
    )
    ps.add_fee_line(db, kids[0], {"item_id": item.id, "section": "hcm_air", "stt": rule.stt},
                    actor=None)  # fmt: skip
    db.commit()
    est, _ = ps.estimate_for(db, con)
    assert not [i for i in est.blocking if "tiers" in i.message or "battery" in i.message], (
        est.blocking
    )
    members = est.method_detail["members"]
    # 100% to the customer with the battery, cost and quote; nothing on the others.
    assert members[kids[0].id]["own_surcharge_cost_vnd"] == D(fee)
    assert members[kids[1].id]["own_surcharge_cost_vnd"] == 0
    battery = [f for f in est.fees if f.stt == rule.stt]
    assert len(battery) == 1 and battery[0].vendor_fee_vnd == D(fee)


def test_two_customers_with_batteries_in_one_piece_pay_kango_once(nov):  # noqa: F811
    db = nov
    con, kids = _master(db, kgs=(12, 4, 5))
    rule = _rule(db, "pin kem thiet bi nho 1-3")
    for kid, kg in ((kids[0], "2"), (kids[1], "3.6")):
        item = items.add_item(db, kid, {"description": "pin", "weight_kg": kg}, actor=None)
        ps.add_fee_line(db, kid, {"item_id": item.id, "section": "hcm_air", "stt": rule.stt},
                        actor=None)  # fmt: skip
    db.commit()
    est, _ = ps.estimate_for(db, con)
    battery = [f for f in est.fees if f.stt == rule.stt]
    # One piece: Kango charges once, band on the piece's battery kg (2 + 3.6 = 5.6 → 700,000;
    # DEC-0276).
    assert len(battery) == 1 and battery[0].vendor_fee_vnd == D(700_000)
    members = est.method_detail["members"]
    cost = (
        members[kids[0].id]["own_surcharge_cost_vnd"]
        + members[kids[1].id]["own_surcharge_cost_vnd"]
    )
    assert cost == D(700_000)
    # Each customer's quote is the full fee on its own battery item.
    quotes = est.method_detail["members"]
    assert quotes[kids[0].id]["own_surcharge_quote_vnd"] == D(300_000)
    assert quotes[kids[1].id]["own_surcharge_quote_vnd"] == D(700_000)


def test_a_battery_item_without_a_weight_is_asked_for_it(nov):  # noqa: F811
    db = nov
    con, kids = _master(db, kgs=(12, 4, 5))
    rule = _rule(db, "pin kem thiet bi nho 1-3")
    item = items.add_item(db, kids[0], {"description": "pin"}, actor=None)
    ps.add_fee_line(db, kids[0], {"item_id": item.id, "section": "hcm_air", "stt": rule.stt},
                    actor=None)  # fmt: skip
    db.commit()
    est, _ = ps.estimate_for(db, con)
    assert any("enter the item's weight" in i.message for i in est.blocking)


def test_the_rc25_engine_ignores_the_item_weight():
    from app.pricing import engine as pe

    line = pe.FeeLineInput(1, 2, "hcm_air", 32, D(1), None, item_kg=D(3))
    assert line.weight_kg is None  # nothing in the RC25 engine reads ``item_kg``
