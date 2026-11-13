"""Method v0.7 golden case study (Louis, 2026-11-03): S1–S7 of ``cost-quote-method.md`` v0.7
§10, reproduced to the cent from ``case_study_results_v0.7.json`` (every customer and master
row: cost VND, cost CAD, quote CAD, surcharge margin CAD, profit CAD and the parts). S1–S6 are
the v0.6 figures unchanged; S7 changed in v0.7 (sea minimum: quote per customer, cost per
package).

Pure engine level. The base rates are **read from the 2026-11-03 Kango sheet** committed as
``fixtures/kango_canada_rates_2026-11-03_sanitized.xlsx`` (HCM-AIR-CAD, AIR-CAD zone 2), at the
two decimals the database stores (``tariff_rate_brackets.price_vnd`` is Numeric(14, 2)), so the
golden figures are tied to the sheet itself, not to numbers typed here. FX is Kango's fixed
19,500 VND/CAD. VND is compared after rounding half-up to the dong (the export's rounding);
every CAD figure exactly.

S1–S4 (master AAAAA, 21 kg, HCM Air Standard) and S5 (BBBBB, 5 kg package packed as one box)
are the v0.5 scenarios on the new sheet. S6 (CCCCC) and S7 (DDDDD) are Sea: the sea vendor's
60,000 VND/kg, sell CAD 8/kg, and the vendor's food / functional-food surcharges: our cost
applies the vendor minimum once per package (kiện) per type, split by item kg (S7 PKG-01); the
customer quote applies the minimum per customer per type (S7: 400,000 to each of four).
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from functools import cache
from pathlib import Path

import pytest

from app.core.enums import SolarisService, TariffLastMile
from app.pricing import cost_method as mv
from app.pricing import engine as pe
from app.pricing.kango_workbook import parse_workbook
from tests.test_method_v05_golden import BOXES, FAKE, NAIL, RULES, SECTION

FIXTURES = Path(__file__).parent / "fixtures"
SHEET = FIXTURES / "kango_canada_rates_2026-11-03_sanitized.xlsx"
GOLDEN = json.loads((FIXTURES / "method_v07_case_study_results.json").read_text(encoding="utf-8"))
GOLDEN_CSV = FIXTURES / "method_v07_case_study_results.csv"
D = Decimal
CENT = D("0.01")
DELIVERY = pe.DeliveryPoint("L5A3K6", 2, 3, None, None, None, None)
SEA_RULES = {
    1: mv.SeaRule(1, "SEA-FOOD", "Hàng thực phẩm", D(30_000), D(400_000)),
    2: mv.SeaRule(2, "SEA-FUNCFOOD", "Hàng thực phẩm chức năng", D(40_000), D(500_000)),
}


@cache
def parsed():
    return parse_workbook(SHEET.read_bytes())


def product(origin: str = "HCM", code: str = "AIR-CAD") -> pe.ProductView:
    """The sheet's product, every zone, prices at the database's two decimals."""
    brackets = tuple(
        pe.Bracket(b.kind, b.zone, b.weight_from_kg, b.weight_to_kg, b.price_vnd.quantize(CENT), b.label)
        for b in parsed().brackets
        if b.origin.value == origin and b.product_code == code
    )  # fmt: skip
    express = code.endswith("EXPRESS")
    return pe.ProductView(
        code=code,
        last_mile=TariffLastMile.PUROLATOR_EXPRESS if express else TariffLastMile.PUROLATOR_GROUND,
        dim_divisor=6000,
        per_kg_from_kg=D(21),
        piece_min_weight_kg=D(12),
        piece_min_fee_vnd=D(700_000) if express else D(300_000),
        piece_min_applies_above_kg=D(21),
        customs_surcharges_waived=False,
        brackets=brackets,
    )


def _air_member(sid: int, public_id: str, scenario: str) -> pe.MemberInput:
    length, width, height, kg = BOXES[public_id]
    lines = []
    if public_id in NAIL[scenario]:
        lines.append(
            pe.FeeLineInput(sid * 10 + 1, None, SECTION, 1, D(1), None, box_ref=sid, box_kg=D(kg))
        )
    if public_id in FAKE.get(scenario, set()):
        lines.append(pe.FeeLineInput(sid * 10 + 2, None, SECTION, 14, D(1), D("0.6")))
    return pe.MemberInput(
        sid, public_id, (pe.PackageInput(D(kg), D(length), D(width), D(height)),), tuple(lines)
    )


#: Sea: customer → (package, box kg, [(sea rule, item kg)]). Boxes carry no dimensions, so
#: CW = actual; packages are 30 kg with small dimensions (actual > volumetric).
SEA = {
    "S6": {
        "STCA-000206": (1, 10, [(1, 3)]),
        "STCA-000207": (1, 20, [(2, 15)]),
        "STCA-000208": (2, 30, []),
    },
    "S7": {
        "STCA-000209": (1, 10, [(1, 2)]),
        "STCA-000210": (1, 15, [(1, 3)]),
        "STCA-000211": (1, 5, []),
        "STCA-000212": (2, 12, [(1, 8)]),
        "STCA-000213": (2, 10, [(1, 6)]),
    },
}
SEA_PACKAGES = {"S6": (D(30), D(30)), "S7": (D(30), D(22))}


def run(scenario: str, method: mv.MethodSettings | None = None, **extra) -> pe.Estimate:
    common = {
        "product_refusal": None,
        "delivery": DELIVERY,
        "rules": RULES,
        "policies": {},
        "fx": None,
        "settings": pe.Settings(Fraction(2, 3), True, None),
        "method": method or mv.MethodSettings(),
    }
    if scenario in SEA:
        members, packages = [], {}
        for sid, (public_id, (pkg, kg, lines)) in enumerate(SEA[scenario].items(), start=1):
            packages[sid] = pkg
            fee_lines = tuple(
                pe.FeeLineInput(sid * 10 + i, None, mv.SEA_VENDOR_SECTION, rule, D(1), D(item_kg))
                for i, (rule, item_kg) in enumerate(lines, start=1)
            )
            members.append(
                pe.MemberInput(
                    sid, public_id, (pe.PackageInput(D(kg), None, None, None),), fee_lines
                )
            )
        cartons = tuple(
            pe.PackageInput(kg, D(40), D(40), D(40)) for kg in SEA_PACKAGES[scenario]
        )  # 40 × 40 × 40 / 6000 = 10.67 kg volumetric < actual
        total = sum((c.weight_kg for c in cartons), D(0))
        return mv.estimate_method(
            service=SolarisService.SEA,
            product=None,
            master=pe.MasterInput(total, None, None, None, len(cartons), None, cartons),
            members=members,
            rule_section="sea_ca_au_uk_eu",
            sea_rules=SEA_RULES,
            **{**common, "member_packages": packages, **extra},
        )
    if scenario == "S5":
        ids = ["STCA-000204", "STCA-000205"]
        master = pe.MasterInput(
            D(5), D(30), D(25), D(20), 1, None,
            (pe.PackageInput(D(5), D(30), D(25), D(20), packed_as_one_box=True),),
        )  # fmt: skip
    else:
        ids = ["STCA-000201", "STCA-000202", "STCA-000203"]
        master = pe.MasterInput(D(21), D(45), D(40), D(35), 1)
    return mv.estimate_method(
        service=SolarisService.AIR_STANDARD,
        product=product(),
        master=master,
        members=[_air_member(i + 1, pid, scenario) for i, pid in enumerate(ids)],
        rule_section=SECTION,
        **{**common, **extra},
    )


def _vnd(value: Decimal) -> int:
    return int(value.quantize(D(1), rounding=ROUND_HALF_UP))


def _cad(value) -> Decimal:
    return D(str(value)).quantize(CENT)


def _d(value) -> Decimal:
    return D(str(value))


ROWS = [(g["scenario"], g["customer"], g) for g in GOLDEN]


def test_the_fixture_covers_s1_to_s7_with_a_master_row_each() -> None:
    assert sorted({g["scenario"] for g in GOLDEN}) == [f"S{i}" for i in range(1, 8)]
    assert sum(g["customer"].startswith("MASTER") for g in GOLDEN) == 7
    assert len(GOLDEN) == 29  # 4 × 4 (S1–S4) + 3 (S5) + 4 (S6) + 6 (S7)


def test_the_json_and_the_csv_agree() -> None:
    import csv

    rows = list(csv.DictReader(GOLDEN_CSV.open(encoding="utf-8")))
    assert len(rows) == len(GOLDEN)
    for row, gold in zip(rows, GOLDEN, strict=True):
        for key in ("scenario", "customer", "cost_vnd", "cost_cad", "quote_cad", "profit_cad"):
            assert (row[key] == str(gold[key])) or _d(row[key]) == _d(gold[key]), (key, row)


@pytest.mark.parametrize(
    ("scenario", "customer", "gold"), ROWS, ids=[f"{s}-{c}" for s, c, _ in ROWS]
)
def test_golden_case_study_v07(scenario: str, customer: str, gold: dict) -> None:
    est = run(scenario)
    assert est.blocking == [], est.blocking
    v = est.method_detail
    assert est.method == v["method"] == "confirmed" and v["method_version"] == "v0.7"
    assert v["fx"]["cost_rate_vnd"] == v["fx"]["quote_rate_vnd"] == D(gold["fx_cad_vnd"])
    if customer.startswith("MASTER"):
        assert v["bill_kg"] == _d(gold["cw_kg"])
        assert v["base_vnd"] == _d(gold["base_vnd"])
        assert _vnd(v["bill_vnd"]) == _vnd(_d(gold["cost_vnd"]))
        assert v["totals"]["cost_cad"] == _cad(gold["cost_cad"])
        assert v["totals"]["quote_cad"] == _cad(gold["quote_cad"])
        assert v["totals"]["surcharge_margin_cad"] == _cad(gold["surcharge_margin_cad"])
        assert v["totals"]["profit_cad"] == _cad(gold["profit_cad"])
        assert v["reconciled"] is True
        assert v["piece_vnd"] == D(0)
        return
    row = next(m for m in v["members"].values() if m["public_id"] == customer)
    assert row["cw_kg"] == _d(gold["cw_kg"])
    assert _vnd(row["base_vnd"]) == int(gold["base_vnd"])
    assert _vnd(row["own_surcharge_cost_vnd"]) == int(gold["own_surcharge_cost_vnd"])
    assert _vnd(row["own_surcharge_quote_vnd"]) == int(gold["own_surcharge_quote_vnd"])
    assert _vnd(row["package_surcharge_vnd"]) == int(gold["package_surcharge_vnd"])
    assert _vnd(row["cost_vnd"]) == int(gold["cost_vnd"])
    assert row["cost_cad"] == _cad(gold["cost_cad"])
    assert row["rate_cad_kg"] == _cad(gold["rate_cad_kg"])
    assert row["freight_cad"] == _cad(gold["freight_cad"])
    assert row["surcharge_quote_cad"] == _cad(gold["surcharge_quote_cad"])
    assert row["quote_cad"] == _cad(gold["quote_cad"])
    assert row["surcharge_margin_cad"] == _cad(gold["surcharge_margin_cad"])
    assert row["profit_cad"] == _cad(gold["profit_cad"])


@pytest.mark.parametrize("scenario", [f"S{i}" for i in range(1, 8)])
def test_quote_lines_add_up(scenario: str) -> None:
    est = run(scenario)
    for sid, row in est.method_detail["members"].items():
        q = pe.quote_figures(est, sid, row["rate_cad_kg"])
        assert q.total_revenue_cad == row["quote_cad"]
        assert q.allocated_cost_cad == row["cost_cad"]
        lines = sum((f.revenue_alloc_cad.get(sid, D(0)) for f in est.fees), D(0))
        assert q.base_revenue_cad + lines == q.total_revenue_cad
        costs = sum((f.cost_alloc_cad.get(sid, D(0)) for f in est.fees), D(0))
        assert est.members[sid].base_cost_cad + costs == row["cost_cad"]


# --- The rates on the sheet ---------------------------------------------------------------------


def test_the_engine_reads_the_2026_11_03_sheet() -> None:
    hcm, han = product("HCM"), product("HAN")
    assert pe.base_freight(hcm, 2, D(21)) == (D(21 * 260_000), None)
    assert pe.base_freight(hcm, 2, D(5)) == (D("1629138.10"), None)
    assert pe.base_freight(han, 2, D(21)) == (D(21 * 268_000), None)
    tiers = {(b.zone, b.label): b.price_vnd for b in hcm.brackets if b.kind == "per_kg"}
    assert [tiers[(2, t)] for t in ("21-44", "45-99", "100-299", "300KGS+")] == [
        D(260_000), D(255_000), D(250_000), D(245_000)
    ]  # fmt: skip
    tiers = {(b.zone, b.label): b.price_vnd for b in han.brackets if b.kind == "per_kg"}
    assert [tiers[(2, t)] for t in ("21-44", "45-99", "100-299", "300KGS+")] == [
        D(268_000), D(263_000), D(258_000), D(253_000)
    ]  # fmt: skip
    assert parsed().fixed_fx_vnd_per_cad == D(19_500)


def test_s7_cost_minimum_per_package_and_quote_minimum_per_customer() -> None:
    est = run("S7")
    food = {ln["key"]: ln for ln in est.method_detail["lines"] if ln["class"] == "SEA_ITEM_MIN"}
    pkg1, pkg2 = food["S:1:1"], food["S:1:2"]
    # COST: 5 kg × 30,000 = 150,000 < 400,000 → 400,000 once, split by item kg.
    assert pkg1["vendor_vnd"] == D(400_000)
    assert sorted(pkg1["cost_alloc_vnd"].values()) == [D(160_000), D(240_000)]
    # COST: 14 kg × 30,000 = 420,000 ≥ 400,000 → actual.
    assert pkg2["vendor_vnd"] == D(420_000)
    assert sorted(pkg2["cost_alloc_vnd"].values()) == [D(180_000), D(240_000)]
    # QUOTE: each customer max(own kg × 30,000, 400,000) = 400,000.
    assert sorted(pkg1["quote_vnd"].values()) == [D(400_000), D(400_000)]
    assert sorted(pkg2["quote_vnd"].values()) == [D(400_000), D(400_000)]
    # The leftover cent goes to the largest-cost customer, STCA-000210 (58.46 → 58.47).
    row = next(m for m in est.method_detail["members"].values() if m["public_id"] == "STCA-000210")
    assert row["cost_cad"] == D("58.47")
    assert est.method_detail["totals"]["surcharge_margin_cad"] == D("39.98")


def test_a_customer_above_the_minimum_is_quoted_its_own_amount() -> None:
    """Functional food in S6: 15 kg × 40,000 = 600,000 ≥ 500,000 → quoted 600,000."""
    est = run("S6")
    (func,) = [ln for ln in est.method_detail["lines"] if ln["key"] == "S:2:1"]
    assert list(func["quote_vnd"].values()) == [D(600_000)] == list(func["cost_alloc_vnd"].values())


def test_sea_without_a_package_record_is_one_package_with_a_warning() -> None:
    est = run("S7", member_packages={})
    assert est.blocking == []
    assert "sea_package_unknown" in {i.code for i in est.provisional}
    (food,) = [ln for ln in est.method_detail["lines"] if ln["class"] == "SEA_ITEM_MIN"]
    # Whole master: 19 kg × 30,000 = 570,000 ≥ 400,000 → actual; quote still 400,000 each.
    assert food["key"] == "S:1:0" and food["vendor_vnd"] == D(570_000)
    assert sorted(food["quote_vnd"].values()) == [D(400_000)] * 4


def test_sea_refuses_kango_ocean_surcharges_and_has_no_piece_fee() -> None:
    est = run("S6")
    assert est.method_detail["piece_vnd"] == D(0) and est.method_detail["base_vnd"] == D(
        60 * 60_000
    )
    kango = pe.MemberInput(
        9, "STCA-X", (pe.PackageInput(D(5), None, None, None),),
        (pe.FeeLineInput(91, None, "sea_ca_au_uk_eu", 6, D(1), None),),
    )  # fmt: skip
    est = mv.estimate_method(
        service=SolarisService.SEA, product=None, product_refusal=None, delivery=DELIVERY,
        master=pe.MasterInput(D(5), None, None, None, 1), members=[kango], rules=RULES,
        rule_section="sea_ca_au_uk_eu", policies={}, fx=None,
        settings=pe.Settings(Fraction(2, 3), True, None), method=mv.MethodSettings(),
    )  # fmt: skip
    assert {i.code for i in est.blocking} == {"kango_sea_surcharge_inactive"}
    # Any weight: 5 kg × 60,000, no 21 kg minimum.
    assert est.method_detail["base_vnd"] == D(300_000)


def test_sea_cost_is_a_setting() -> None:
    est = run("S6", mv.MethodSettings(sea_cost_vnd_per_kg=D(65_000)))
    assert est.method_detail["base_vnd"] == D(60 * 65_000)


# --- Piece fee (Louis Q4) -----------------------------------------------------------------------


def _piece_run(cartons, packages=None, service=SolarisService.AIR_STANDARD, code="AIR-CAD"):
    members = [_air_member(i + 1, pid, "S1") for i, pid in enumerate(BOXES) if i < 3]
    total = sum((c.weight_kg for c in cartons), D(0))
    return mv.estimate_method(
        service=service, product=product(code=code), product_refusal=None, delivery=DELIVERY,
        master=pe.MasterInput(total, None, None, None, len(cartons), None, tuple(cartons)),
        members=members, rules=RULES, rule_section=SECTION, policies={}, fx=None,
        settings=pe.Settings(Fraction(2, 3), True, None), method=mv.MethodSettings(),
        manual=mv.ManualPricing(cost_vnd_per_kg=D(300_000), sell_cad_per_kg=D(25)),
        member_packages=packages or {},
    )  # fmt: skip


def test_piece_fee_from_21_kg_inclusive_is_vendor_cost_only() -> None:
    # 21 kg lot: a 9 kg carton (customers 1 and 2) and a 12 kg carton (customer 3).
    cartons = [pe.PackageInput(D(9), None, None, None), pe.PackageInput(D(12), None, None, None)]
    est = _piece_run(cartons, {1: 1, 2: 1, 3: 2})
    assert est.method_detail["bill_kg"] == D(21) and est.method_detail["piece_vnd"] == D(300_000)
    (piece,) = [ln for ln in est.method_detail["lines"] if ln["key"] == "PIECE"]
    # Split by weight among that carton's customers (3 kg and 6 kg), never quoted.
    assert piece["cost_alloc_vnd"] == {1: D(100_000), 2: D(200_000), 3: D(0)}
    assert piece["quote_vnd"] == {}
    rows = est.method_detail["members"]
    assert rows[1]["quote_cad"] == D("57.00") + rows[1]["surcharge_quote_cad"]
    assert est.method_detail["reconciled"] is True


def test_piece_fee_does_not_apply_under_21_kg() -> None:
    cartons = [
        pe.PackageInput(D(9), None, None, None),
        pe.PackageInput(D("11.5"), None, None, None),
    ]
    assert _piece_run(cartons, {1: 1, 2: 1, 3: 2}).method_detail["piece_vnd"] == D(0)


def test_piece_fee_on_express_is_700000() -> None:
    cartons = [pe.PackageInput(D(9), None, None, None), pe.PackageInput(D(12), None, None, None)]
    est = _piece_run(cartons, {1: 1, 2: 1, 3: 2}, SolarisService.AIR_EXPRESS, "AIR-CAD EXPRESS")
    assert est.method_detail["piece_vnd"] == D(700_000)


def test_piece_fee_without_a_package_record_spreads_over_the_master() -> None:
    cartons = [pe.PackageInput(D(9), None, None, None), pe.PackageInput(D(12), None, None, None)]
    est = _piece_run(cartons)
    (piece,) = [ln for ln in est.method_detail["lines"] if ln["key"] == "PIECE"]
    assert sum(piece["cost_alloc_vnd"].values()) == D(300_000) and piece["cost_alloc_vnd"][3] > 0
    assert "piece_fee_package_members_unknown" in {i.code for i in est.provisional}


# --- Express reference (Louis Q9) and the zone ------------------------------------------------


def test_express_cost_is_manual_and_zone_3_is_reference_only() -> None:
    cartons = [pe.PackageInput(D(21), None, None, None)]
    est = _piece_run(cartons, None, SolarisService.AIR_EXPRESS, "AIR-CAD EXPRESS")
    ref = est.method_detail["express_reference"]
    assert ref == {
        "product": "AIR-CAD EXPRESS", "zone": 3, "bill_kg": D(21),
        "vnd": D(21 * 246_000), "used_for_cost": False,
    }  # fmt: skip
    assert est.method_detail["base_vnd"] == D(21 * 300_000)  # the manual cost, not the table


def test_air_standard_prices_on_zone_2() -> None:
    est = run("S1")
    assert est.zone == 2 and est.method_detail["rate_per_kg_vnd"] == D(260_000)


# --- Q6: x.1 kg boxes follow the rounding rule ----------------------------------------------------


def test_a_5_1_kg_box_uses_the_1_to_5_kg_band_for_cost_and_quote() -> None:
    member = pe.MemberInput(
        1, "STCA-X", (pe.PackageInput(D("5.1"), None, None, None),),
        (pe.FeeLineInput(11, None, SECTION, 1, D(1), None, box_ref=1, box_kg=D("5.1")),),
    )  # fmt: skip
    est = mv.estimate_method(
        service=SolarisService.AIR_STANDARD, product=product(), product_refusal=None,
        delivery=DELIVERY, master=pe.MasterInput(D(5), None, None, None, 1), members=[member],
        rules=RULES, rule_section=SECTION, policies={}, fx=None,
        settings=pe.Settings(Fraction(2, 3), True, None), method=mv.MethodSettings(),
    )  # fmt: skip
    (line,) = [ln for ln in est.method_detail["lines"] if ln["stt"] == 1]
    assert line["vendor_vnd"] == D(300_000) and line["quote_vnd"] == {1: D(300_000)}
    assert est.method_detail["members"][1]["surcharge_margin_cad"] == D(0)
