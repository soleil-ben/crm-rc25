"""Method v0.5 golden case study (Louis, 2026-11-02): scenarios S1–S5 of
``cost-quote-method.md`` v0.5 §10, reproduced to the cent from ``case_study_results.json``.

**Kept as a regression on the 30-Oct rates.** Since v0.6 (DEC-0253) the engine is the v0.6
method; on the 2026-10-30 sheet's figures it still reproduces every v0.5 row, which shows the
v0.6 figures (``test_method_v06_golden.py``) differ from v0.5 by the rate sheet only. A master
booked under an older sheet keeps that sheet's rates (``test_method_v06_service.py``).

Pure engine level, like ``test_pricing_engine.py``: the inputs are built here, the expected
figures are read from the fixture exactly as exported by the mockup engine. VND figures in the
fixture are whole dong (the export rounds); the engine keeps cents (OD-60), so VND is compared
after rounding half-up to the dong. Every CAD figure is compared exactly.

**Rate table.** The case study's base rates (zone 2: 21-44 kg 249,000 VND/kg, C50; 5 kg per-bill
band 1,577,138.1 VND, C17) come from the mockup's rate table, not from the 2026-10-12 workbook
fixture in this repository (243,000 and 1,515,006.4). The brackets below are the mockup's.
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from app.core.enums import (
    SolarisService,
    SurchargeBasis,
    SurchargePricingStatus,
    SurchargeScope,
    TariffLastMile,
)
from app.pricing import cost_method as mv
from app.pricing import engine as pe
from app.pricing import kango_semantics

FIXTURE = Path(__file__).parent / "fixtures" / "method_v05_case_study_results.json"
GOLDEN = json.loads(FIXTURE.read_text(encoding="utf-8"))
D = Decimal

#: The mockup's HCM AIR-CAD zone 2 figures used by S1–S5 (C17 and C50–C53).
PRODUCT = pe.ProductView(
    code="AIR-CAD",
    last_mile=TariffLastMile.PUROLATOR_GROUND,
    dim_divisor=6000,
    per_kg_from_kg=D(21),
    piece_min_weight_kg=D(12),
    piece_min_fee_vnd=D(300_000),
    piece_min_applies_above_kg=D(21),
    customs_surcharges_waived=False,
    brackets=(
        pe.Bracket("per_bill", 2, D("4.5"), D(5), D("1577138.1"), "5.0"),
        pe.Bracket("per_kg", 2, D(21), D(44), D(249_000), "21-44"),
        pe.Bracket("per_kg", 2, D(45), D(99), D(244_000), "45-99"),
        pe.Bracket("per_kg", 2, D(100), D(299), D(239_000), "100-299"),
        pe.Bracket("per_kg", 2, D(300), None, D(234_000), "300KGS+"),
    ),
)
DELIVERY = pe.DeliveryPoint("L5A3K6", 2, 3, None, None, None, None)
SECTION = "hcm_air"
NAIL_POLISH = pe.RuleView(
    section=SECTION,
    stt=1,
    name="Sơn móng tay",
    pricing_status=SurchargePricingStatus.TIERED,
    basis=SurchargeBasis.PER_PIECE,
    scope=SurchargeScope.PER_UNIT,
    unit_price_vnd=None,
    per_unit_price_vnd=None,
    tiers=tuple(
        pe.Tier(t.weight_from_kg, t.weight_to_kg, t.price_vnd)
        for t in kango_semantics.NAIL_POLISH_TIERS
    ),
    min_charge_kg=None,
    applies_to_canada=True,
    above_top_tier="top",
    allocation_class="PARCEL",
)
FAKE_CLOTHES = pe.RuleView(
    section=SECTION,
    stt=14,
    name="Fake thương hiệu (QUẦN ÁO)",
    pricing_status=SurchargePricingStatus.PRICED,
    basis=SurchargeBasis.PER_KG,
    scope=SurchargeScope.FULL_CARTON,
    unit_price_vnd=D(30_000),
    per_unit_price_vnd=None,
    tiers=(),
    min_charge_kg=None,
    applies_to_canada=True,
    allocation_class="WHOLE_PACKAGE",
)
RULES = {(SECTION, 1): NAIL_POLISH, (SECTION, 14): FAKE_CLOTHES}

#: Customers' small boxes (cm, kg), as in the mockup sample booking.
BOXES = {
    "STCA-000201": (25, 20, 15, 3),
    "STCA-000202": (35, 25, 20, 6),
    "STCA-000203": (40, 35, 30, 12),
    "STCA-000204": (20, 15, 12, 2),
    "STCA-000205": (25, 20, 15, 3),
}
#: Who carries fake / branded clothing (HCM-14) in each of S1–S4.
FAKE = {
    "S1": set(),
    "S2": {"STCA-000201", "STCA-000202", "STCA-000203"},
    "S3": {"STCA-000201", "STCA-000202"},
    "S4": {"STCA-000202"},
}
NAIL = {
    "S1": {"STCA-000201"},
    "S2": {"STCA-000201"},
    "S3": {"STCA-000201"},
    "S4": {"STCA-000201"},
    "S5": {"STCA-000204", "STCA-000205"},
}


def _member(sid: int, public_id: str, scenario: str) -> pe.MemberInput:
    length, width, height, kg = BOXES[public_id]
    lines = []
    line_id = sid * 10
    if public_id in NAIL[scenario]:
        lines.append(
            pe.FeeLineInput(
                line_id + 1, None, SECTION, 1, D(1), None, box_ref=sid * 100, box_kg=D(kg)
            )
        )
    if public_id in FAKE.get(scenario, set()):
        lines.append(pe.FeeLineInput(line_id + 2, None, SECTION, 14, D(1), D("0.6")))
    return pe.MemberInput(
        sid, public_id, (pe.PackageInput(D(kg), D(length), D(width), D(height)),), tuple(lines)
    )


def run(scenario: str, method: mv.MethodSettings | None = None) -> pe.Estimate:
    if scenario == "S5":
        ids = ["STCA-000204", "STCA-000205"]
        master = pe.MasterInput(
            D(5),
            D(30),
            D(25),
            D(20),
            1,
            None,
            (pe.PackageInput(D(5), D(30), D(25), D(20), packed_as_one_box=True),),
        )
    else:
        ids = ["STCA-000201", "STCA-000202", "STCA-000203"]
        master = pe.MasterInput(D(21), D(45), D(40), D(35), 1)
    return mv.estimate_method(
        service=SolarisService.AIR_STANDARD,
        product=PRODUCT,
        product_refusal=None,
        delivery=DELIVERY,
        master=master,
        members=[_member(i + 1, pid, scenario) for i, pid in enumerate(ids)],
        rules=RULES,
        rule_section=SECTION,
        policies={},
        fx=None,
        settings=pe.Settings(Fraction(2, 3), True, None),
        method=method or mv.MethodSettings(),
    )


def _vnd(value: Decimal) -> int:
    return int(value.quantize(D(1), rounding=ROUND_HALF_UP))


def _cad(value) -> Decimal:
    return D(str(value)).quantize(D("0.01"))


ROWS = [(g["scenario"], g["customer"], g) for g in GOLDEN]


@pytest.mark.parametrize(
    ("scenario", "customer", "gold"), ROWS, ids=[f"{s}-{c}" for s, c, _ in ROWS]
)
def test_golden_case_study(scenario: str, customer: str, gold: dict) -> None:
    est = run(scenario)
    assert est.blocking == [], est.blocking
    v = est.method_detail
    assert v["fx"]["cost_rate_vnd"] == v["fx"]["quote_rate_vnd"] == D(gold["fx_cad_vnd"])
    if customer.startswith("MASTER"):
        assert v["bill_kg"] == D(str(gold["cw_kg"]))
        assert _vnd(v["bill_vnd"]) == gold["cost_vnd"]
        assert v["totals"]["cost_cad"] == _cad(gold["cost_cad"])
        assert v["totals"]["quote_cad"] == _cad(gold["quote_cad"])
        assert v["totals"]["surcharge_margin_cad"] == _cad(gold["surcharge_margin_cad"])
        assert v["totals"]["profit_cad"] == _cad(gold["profit_cad"])
        assert v["reconciled"] is True
        return
    row = next(m for m in v["members"].values() if m["public_id"] == customer)
    assert row["cw_kg"] == D(str(gold["cw_kg"]))
    assert _vnd(row["base_vnd"]) == gold["base_vnd"]
    assert _vnd(row["own_surcharge_cost_vnd"]) == gold["own_surcharge_cost_vnd"]
    assert _vnd(row["own_surcharge_quote_vnd"]) == gold["own_surcharge_quote_vnd"]
    assert _vnd(row["package_surcharge_vnd"]) == gold["package_surcharge_vnd"]
    assert _vnd(row["cost_vnd"]) == gold["cost_vnd"]
    assert row["cost_cad"] == _cad(gold["cost_cad"])
    assert row["rate_cad_kg"] == _cad(gold["rate_cad_kg"])
    assert row["freight_cad"] == _cad(gold["freight_cad"])
    assert row["surcharge_quote_cad"] == _cad(gold["surcharge_quote_cad"])
    assert row["quote_cad"] == _cad(gold["quote_cad"])
    assert row["surcharge_margin_cad"] == _cad(gold["surcharge_margin_cad"])
    assert row["profit_cad"] == _cad(gold["profit_cad"])


@pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5"])
def test_quote_figures_match_the_v05_detail(scenario: str) -> None:
    """The figures a quote version stores (``quote_figures``) are the v0.5 figures."""
    est = run(scenario)
    for sid, row in est.method_detail["members"].items():
        q = pe.quote_figures(est, sid, row["rate_cad_kg"])
        assert q.total_revenue_cad == row["quote_cad"]
        assert q.allocated_cost_cad == row["cost_cad"]
        assert q.gross_profit_cad == row["profit_cad"]
        # Quote lines add up: base line + each surcharge line = total.
        lines = sum((f.revenue_alloc_cad.get(sid, D(0)) for f in est.fees), D(0))
        assert q.base_revenue_cad + lines == q.total_revenue_cad
        costs = sum((f.cost_alloc_cad.get(sid, D(0)) for f in est.fees), D(0))
        assert est.members[sid].base_cost_cad + costs == row["cost_cad"]


def test_s5_kango_charges_once_and_each_customer_is_quoted_in_full() -> None:
    est = run("S5")
    (line,) = [ln for ln in est.method_detail["lines"] if ln["stt"] == 1]
    assert line["vendor_vnd"] == D(300_000)
    assert sorted(line["cost_alloc_vnd"].values()) == [D(120_000), D(180_000)]
    assert sorted(line["quote_vnd"].values()) == [D(300_000), D(300_000)]


def test_s5_without_the_packed_flag_kango_still_charges_once_per_master_piece() -> None:
    """DEC-0276 (Louis 2026-11-06) supersedes §10's per-small-box reading: the master piece is
    the kiện. Both customers' nail polish (2 + 3 = 5 kg) is in one piece: Kango charges
    300,000 once; each customer is quoted 300,000; the flag no longer changes anything."""
    est = run("S5")
    flagless = mv.estimate_method(
        service=SolarisService.AIR_STANDARD,
        product=PRODUCT,
        product_refusal=None,
        delivery=DELIVERY,
        master=pe.MasterInput(
            D(5), D(30), D(25), D(20), 1, None, (pe.PackageInput(D(5), D(30), D(25), D(20)),)
        ),
        members=[_member(1, "STCA-000204", "S5"), _member(2, "STCA-000205", "S5")],
        rules=RULES,
        rule_section=SECTION,
        policies={},
        fx=None,
        settings=pe.Settings(Fraction(2, 3), True, None),
        method=mv.MethodSettings(),
    )
    per_box = [ln for ln in flagless.method_detail["lines"] if ln["stt"] == 1]
    assert [ln["vendor_vnd"] for ln in per_box] == [D(300_000)]  # once for the piece
    assert sorted(per_box[0]["quote_vnd"].values()) == [D(300_000), D(300_000)]
    assert flagless.method_detail["totals"]["surcharge_margin_cad"] == D("15.38")
    assert est.method_detail["totals"]["surcharge_margin_cad"] == D("15.38")


def test_customer_rate_threshold_is_the_customers_own_weight() -> None:
    method = mv.MethodSettings(air_std_threshold_kg=D(6))
    est = run("S1", method)
    rates = {m["public_id"]: m["rate_cad_kg"] for m in est.method_detail["members"].values()}
    assert rates == {"STCA-000201": D(19), "STCA-000202": D(18), "STCA-000203": D(18)}


def test_triggers_only_billing_keeps_the_rc25_quote_rule_available() -> None:
    est = run("S4", mv.MethodSettings(pkg_surcharge_billing="triggers_only"))
    quotes = {
        m["public_id"]: m["surcharge_quote_cad"] for m in est.method_detail["members"].values()
    }
    # Only STCA-000202 triggers HCM-14: it is quoted the whole 630,000; the others only their own.
    assert quotes["STCA-000202"] == D("32.31")
    assert quotes["STCA-000203"] == D("0.00")


def test_unallocated_residual_option() -> None:
    est = mv.estimate_method(
        service=SolarisService.AIR_STANDARD,
        product=PRODUCT,
        product_refusal=None,
        delivery=DELIVERY,
        master=pe.MasterInput(D(25), D(45), D(40), D(35), 1),
        members=[
            _member(1, "STCA-000201", "S1"),
            _member(2, "STCA-000202", "S1"),
            _member(3, "STCA-000203", "S1"),
        ],
        rules=RULES,
        rule_section=SECTION,
        policies={},
        fx=None,
        settings=pe.Settings(Fraction(2, 3), True, None),
        method=mv.MethodSettings(residual_mode="unallocated"),
    )
    v = est.method_detail
    assert v["bill_kg"] == D(25)
    assert v["unallocated_vnd"] == D(4 * 249_000)
    assert v["reconciled"] is True
    spread = run("S1")  # same customers, bill 21 kg: nothing left over
    assert spread.method_detail["unallocated_vnd"] == D(0)


def test_markup_percent_and_fixed() -> None:
    pct = run("S1", mv.MethodSettings(markup_kind="percent", markup_value=D(10)))
    row = next(m for m in pct.method_detail["members"].values() if m["public_id"] == "STCA-000201")
    assert row["surcharge_quote_cad"] == D("16.92")  # 330,000 / 19,500
    fixed = run("S1", mv.MethodSettings(markup_kind="fixed_cad", markup_value=D(2)))
    row = next(
        m for m in fixed.method_detail["members"].values() if m["public_id"] == "STCA-000201"
    )
    assert row["surcharge_quote_cad"] == D("17.38")


def test_vietcombank_source_needs_a_fresh_snapshot() -> None:
    method = mv.MethodSettings(fx_source_cost="vcb_cash_buy", fx_source_quote="vcb_sell")
    est = run("S1", method)
    assert {i.code for i in est.blocking} == {"fx_missing"}


def test_kango_rounding() -> None:
    assert mv.kango_round(D("21.2")) == D(22)
    assert mv.kango_round(D("20.5")) == D("20.5")
    assert mv.kango_round(D("20.51")) == D(21)
    assert mv.kango_round(D("4.6")) == D(5)
    assert mv.kango_round(D("0.1")) == D("0.5")


def test_box_band_follows_the_rounding_rule_for_cost_and_quote() -> None:
    """A 5.1 kg box (Louis Q6, 2026-11-03; DEC-0256): the band reads the OD-50 rounded box
    weight, 5.0 kg, for cost and quote → 300,000 both; no negative margin. Kango may bill
    500,000; that is an estimate-vs-actual variance on the vendor bill."""
    member = pe.MemberInput(
        1,
        "STCA-X",
        (pe.PackageInput(D("5.1"), D(20), D(20), D(20)),),
        (pe.FeeLineInput(11, None, SECTION, 1, D(1), None, box_ref=1, box_kg=D("5.1")),),
    )
    est = mv.estimate_method(
        service=SolarisService.AIR_STANDARD,
        product=PRODUCT,
        product_refusal=None,
        delivery=DELIVERY,
        master=pe.MasterInput(D(5), D(20), D(20), D(20), 1),  # the 5 kg band is on file
        members=[member],
        rules=RULES,
        rule_section=SECTION,
        policies={},
        fx=None,
        settings=pe.Settings(Fraction(2, 3), True, None),
        method=mv.MethodSettings(),
    )
    (line,) = [ln for ln in est.method_detail["lines"] if ln["stt"] == 1]
    assert line["vendor_vnd"] == D(300_000)
    assert line["quote_vnd"] == {1: D(300_000)}
    assert est.method_detail["members"][1]["surcharge_margin_cad"] == D(0)
