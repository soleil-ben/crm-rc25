"""Independent golden tests for the air pricing engine, written from the owner's handoff
specification (SC-02 .. SC-09, OD-46, FX rules) and the owner's answers of 19 Oct 2026
(OD-50 .. OD-62), not from the engine's own output.

Every expected figure below is the business result stated in the specification, worked out
by hand. Where an assertion fails, the engine disagrees with the specification.
"""

from __future__ import annotations

import random
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from app.core.enums import (
    SurchargeBasis,
    SurchargePricingStatus,
    SurchargeScope,
    SurchargeSection,
    TariffLastMile,
    TariffOrigin,
    TariffProductMode,
)
from app.pricing.chargeable_weight import chargeable_weight, round_chargeable
from app.pricing.engine import (
    Bracket,
    DeliveryPoint,
    FeeLineInput,
    FxView,
    MasterInput,
    MemberInput,
    PackageInput,
    ProductView,
    RuleView,
    Settings,
    Tier,
    allocate,
    base_freight,
    estimate,
    quote_figures,
    tier_price,
)
from app.pricing.kango_semantics import CURATED_RULES, PRODUCT_RULES
from app.pricing.kango_workbook import parse_workbook

D = Decimal
CENT = D("0.01")
WORKBOOK = Path(__file__).parent / "fixtures" / "kango_canada_rates_2026-10-12_sanitized.xlsx"

HCM = "hcm_air"
HAN = "han_air"

# Hand-built tariff: per-kg price differs per zone so the zone choice is observable.
PER_KG_ZONE2 = D("100000")
PER_KG_ZONE3 = D("150000")

# FX: deliberately different buy and sell rates so the rate used is observable.
CASH_BUY = D("18000")
SELL = D("20000")

# Children of the core example: 3, 6 and 12 kg.
C1, C2, C3 = 101, 102, 103

# Issue codes that must never appear any more (OD-50 replaced the half-kg convention).
HALF_KG_CODES = {"customer_half_kg_rounding", "master_half_kg_rounding"}
PREFILLED = "manual_quote_prefilled_minimum"
PIECE_NOT_EVALUATED = "piece_minimum_not_evaluated"


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def issue_codes(est) -> set[str]:
    return {i.code for i in est.blocking} | {i.code for i in est.provisional}


# --- Fixture builders ------------------------------------------------------------------------------


def make_product(
    code: str = "AIR-STD",
    last_mile=TariffLastMile.PUROLATOR_GROUND,
    *,
    piece_fee: Decimal | None = None,
) -> ProductView:
    brackets = []
    for zone, price in ((2, PER_KG_ZONE2), (3, PER_KG_ZONE3)):
        brackets.append(Bracket("per_bill", zone, None, D("20.5"), D("1500000") + zone, "<=20.5"))
        brackets.append(Bracket("per_kg", zone, D("21"), D("44"), price, "21-44"))
        brackets.append(Bracket("per_kg", zone, D("45"), None, price - D("10000"), "45+"))
    return ProductView(
        code=code,
        last_mile=last_mile,
        dim_divisor=6000,
        per_kg_from_kg=D("21"),
        piece_min_weight_kg=D("12") if piece_fee is not None else None,
        piece_min_fee_vnd=piece_fee,
        piece_min_applies_above_kg=D("21") if piece_fee is not None else None,
        customs_surcharges_waived=False,
        brackets=tuple(brackets),
    )


def delivery_l5a3k6() -> DeliveryPoint:
    # OD-46: one fixed delivery point, ground zone 2, express zone 3, not beyond.
    return DeliveryPoint(
        postal_code="L5A3K6",
        ground_zone=2,
        express_zone=3,
        beyond_code=None,
        beyond_status=None,
        beyond_base_cad=None,
        beyond_per_lb_cad=None,
    )


def live_fx() -> FxView:
    return FxView(snapshot_id=7, cash_buy_vnd=CASH_BUY, sell_vnd=SELL, freshness="live")


def rule(
    stt: int,
    name: str,
    *,
    section: str = HCM,
    status=SurchargePricingStatus.PRICED,
    basis=SurchargeBasis.PER_KG,
    scope=SurchargeScope.FULL_CARTON,
    unit_price: Decimal | None = None,
    per_unit_price: Decimal | None = None,
    tiers: tuple[Tier, ...] = (),
    above_top_tier: str = "manual",
) -> RuleView:
    return RuleView(
        section=section,
        stt=stt,
        name=name,
        pricing_status=status,
        basis=basis,
        scope=scope,
        unit_price_vnd=unit_price,
        per_unit_price_vnd=per_unit_price,
        tiers=tiers,
        min_charge_kg=None,
        applies_to_canada=True,
        above_top_tier=above_top_tier,
    )


# OD-57: the tiers do not overlap: (0, 5] 300k, (5, 22] 500k, (22, 30] 700k; above 30 = top.
NAIL_TIERS = (
    Tier(D("0"), D("5"), D("300000")),
    Tier(D("5"), D("22"), D("500000")),
    Tier(D("22"), D("30"), D("700000")),
)
# OD-59: (0, 3.5] 300k, (3.5, 8] 700k; above 8 kg = manual quote.
BATTERY_TIERS = (
    Tier(D("0"), D("3.5"), D("300000")),
    Tier(D("3.5"), D("8"), D("700000")),
)

FAKE_CLOTHING = rule(14, "Fake clothing", unit_price=D("30000"))
PER_ITEM = rule(
    20, "Per item fee", basis=SurchargeBasis.PER_UNIT, scope=SurchargeScope.PER_UNIT,
    unit_price=D("50000"),
)  # fmt: skip
NAIL_POLISH = rule(
    1,
    "Nail polish",
    status=SurchargePricingStatus.TIERED,
    basis=SurchargeBasis.PER_PIECE,
    scope=SurchargeScope.PER_UNIT,
    tiers=NAIL_TIERS,
    above_top_tier="top",
)
PERFUME = rule(
    11,
    "Perfume",
    status=SurchargePricingStatus.TIERED,
    basis=SurchargeBasis.COMPOUND,
    scope=SurchargeScope.PER_UNIT,
    tiers=NAIL_TIERS,
    per_unit_price=D("50000"),
    above_top_tier="top",
)
BATTERY = rule(
    2,
    "Small device batteries",
    status=SurchargePricingStatus.TIERED,
    basis=SurchargeBasis.PER_PIECE,
    scope=SurchargeScope.PER_UNIT,
    tiers=BATTERY_TIERS,
    above_top_tier="manual",
)
# OD-56: manual-quote row; the file's figure is the prefilled minimum.
CAMERA = rule(
    10, "Camera with battery", status=SurchargePricingStatus.MANUAL_QUOTE,
    basis=SurchargeBasis.PER_UNIT, scope=SurchargeScope.PER_UNIT, unit_price=D("100000"),
)  # fmt: skip
# OD-58: pharmaceuticals priced 200,000 VND/kg on the full carton.
PHARMA = rule(39, "Pharmaceuticals", unit_price=D("200000"))
# A per-kg rule on the item's own weight (to observe OD-50 on a surcharge weight).
ITEM_KG = rule(97, "Item weight rule", scope=SurchargeScope.ITEM_WEIGHT, unit_price=D("100000"))
# Generic engine safety: a genuine conflict / vendor-review rule is never guessed.
DISPUTED = rule(99, "Disputed goods", status=SurchargePricingStatus.CONFLICT, unit_price=D("40000"))
CASE_BY_CASE = rule(
    98, "Case by case goods", status=SurchargePricingStatus.UNPRICED_VENDOR_REVIEW,
    basis=SurchargeBasis.UNPRICED, unit_price=None,
)  # fmt: skip
HN_EYELASHES = rule(
    3, "False eyelashes", section=HAN, status=SurchargePricingStatus.FREE,
    basis=SurchargeBasis.FREE, scope=SurchargeScope.FULL_CARTON,
)  # fmt: skip

ALL_RULES = {(r.section, r.stt): r for r in (
    FAKE_CLOTHING, PER_ITEM, NAIL_POLISH, PERFUME, BATTERY, CAMERA, PHARMA, ITEM_KG,
    DISPUTED, CASE_BY_CASE, HN_EYELASHES,
)}  # fmt: skip

_line_ids = iter(range(1000, 100000))


def line(
    r: RuleView,
    quantity: str = "1",
    weight_kg: str | None = None,
    manual: str | None = None,
) -> FeeLineInput:
    return FeeLineInput(
        fee_line_id=next(_line_ids),
        item_id=None,
        section=r.section,
        stt=r.stt,
        quantity=D(quantity),
        weight_kg=D(weight_kg) if weight_kg is not None else None,
        manual_unit_price_vnd=D(manual) if manual is not None else None,
    )


def member(sid: int, kg: str, *lines: FeeLineInput, dims: tuple[str, str, str] | None = None):
    ln, w, h = (D(x) for x in dims) if dims else (None, None, None)
    return MemberInput(
        shipment_id=sid,
        public_id=f"SX-{sid}",
        packages=(PackageInput(D(kg), ln, w, h),),
        fee_lines=tuple(lines),
    )


def carton(kg: str, dims: tuple[str, str, str] | None = None) -> PackageInput:
    ln, w, h = (D(x) for x in dims) if dims else (None, None, None)
    return PackageInput(D(kg), ln, w, h)


def measured_master(
    actual_kg: str,
    *,
    dims: tuple[str, str, str] | None = None,
    cartons: tuple[PackageInput, ...] = (),
    carton_count: int | None = None,
) -> MasterInput:
    """A master not yet booked: its chargeable weight is computed (OD-50), not stored."""
    ln, w, h = (D(x) for x in dims) if dims else (None, None, None)
    return MasterInput(
        actual_weight_kg=D(actual_kg),
        length_cm=ln,
        width_cm=w,
        height_cm=h,
        carton_count=carton_count if carton_count is not None else max(len(cartons), 1),
        stored_chargeable_kg=None,
        cartons=cartons,
    )


def run(
    members,
    *,
    master_kg: str = "21",
    master: MasterInput | None = None,
    product: ProductView | None = None,
    rule_section: str = HCM,
    fx: FxView | None | str = "live",
    settings: Settings | None = None,
):
    return estimate(
        product=product or make_product(),
        product_refusal=None,
        delivery=delivery_l5a3k6(),
        master=master
        or MasterInput(
            actual_weight_kg=D(master_kg),
            length_cm=None,
            width_cm=None,
            height_cm=None,
            carton_count=1,
            stored_chargeable_kg=D(master_kg),
        ),
        members=members,
        rules=ALL_RULES,
        rule_section=rule_section,
        policies={},
        fx=live_fx() if fx == "live" else fx,
        settings=settings or Settings(),
    )


def core_members(trigger_ids: set[int] = frozenset(), extra: dict[int, tuple] | None = None):
    extra = extra or {}
    out = []
    for sid, kg in ((C1, "3"), (C2, "6"), (C3, "12")):
        lines = [line(FAKE_CLOTHING)] if sid in trigger_ids else []
        lines.extend(extra.get(sid, ()))
        out.append(member(sid, kg, *lines))
    return out


def surcharge_cost(est, sid) -> Decimal:
    return est.members[sid].surcharge_cost_vnd


def surcharge_revenue(est, sid) -> Decimal:
    return est.members[sid].surcharge_revenue_cad


def master_fees(est, r: RuleView):
    return [f for f in est.fees if f.section == r.section and f.stt == r.stt]


# --- Core example: base freight allocation -------------------------------------------------------


def test_core_base_freight_allocated_3_6_12_and_sums_exactly():
    est = run(core_members())
    assert est.blocking == []
    b = PER_KG_ZONE2 * 21
    assert est.base_freight_vnd == b == D("2100000.00")
    parts = [est.members[s].base_cost_vnd for s in (C1, C2, C3)]
    assert parts == [D("300000.00"), D("600000.00"), D("1200000.00")]
    assert sum(parts) == b


def test_base_freight_cost_cad_uses_cash_buying_rate_and_reconciles():
    est = run(core_members())
    expected = cents(D("2100000") / CASH_BUY)  # 116.67
    assert est.base_freight_cad == expected == D("116.67")
    parts = [est.members[s].base_cost_cad for s in (C1, C2, C3)]
    assert sum(parts) == expected
    exact = [expected * k / 21 for k in (3, 6, 12)]
    for p, e in zip(parts, exact, strict=True):
        assert abs(p - e) < CENT


# --- SC-05: one trigger of three -----------------------------------------------------------------


def test_sc05_full_master_surcharge_single_trigger():
    est = run(core_members({C2}))
    assert est.blocking == []
    fees = master_fees(est, FAKE_CLOTHING)
    assert len(fees) == 1
    assert fees[0].vendor_fee_vnd == D("630000")  # 21 x 30,000, once
    assert [surcharge_cost(est, s) for s in (C1, C2, C3)] == [
        D("105000"), D("420000"), D("105000"),
    ]  # fmt: skip
    # Revenue: all to the trigger, at the BUY rate (OD-73), no markup by default in the pure engine.
    expected_rev = cents(D("630000") / CASH_BUY)
    assert expected_rev == D("35.00")
    assert surcharge_revenue(est, C2) == expected_rev
    assert surcharge_revenue(est, C1) == D("0")
    assert surcharge_revenue(est, C3) == D("0")
    assert fees[0].customer_total_cad == fees[0].customer_base_cad == expected_rev


def test_sc05_surcharge_cost_cad_at_cash_buying_rate():
    est = run(core_members({C2}))
    total = cents(D("630000") / CASH_BUY)  # 35.00
    costs = [est.members[s].surcharge_cost_cad for s in (C1, C2, C3)]
    assert sum(costs) == total == D("35.00")
    for got, share in zip(costs, (Fraction(1, 6), Fraction(2, 3), Fraction(1, 6)), strict=True):
        assert abs(Fraction(str(got)) - Fraction(35) * share) < Fraction(1, 100)


# --- SC-06: several triggers, N>3, single child ---------------------------------------------------


def test_sc06_two_triggers_cost_and_revenue_by_weight():
    est = run(core_members({C1, C2}))
    assert est.blocking == []
    assert len(master_fees(est, FAKE_CLOTHING)) == 1
    assert [surcharge_cost(est, s) for s in (C1, C2, C3)] == [
        D("210000"), D("420000"), D("0"),
    ]  # fmt: skip
    # 35.00 CAD split 1:2 between the triggers; child 3 pays nothing.
    assert surcharge_revenue(est, C1) == D("11.67")
    assert surcharge_revenue(est, C2) == D("23.33")
    assert surcharge_revenue(est, C3) == D("0")


def test_sc06_all_three_trigger():
    est = run(core_members({C1, C2, C3}))
    assert est.blocking == []
    assert [surcharge_cost(est, s) for s in (C1, C2, C3)] == [
        D("90000"), D("180000"), D("360000"),
    ]  # fmt: skip
    revenue = [surcharge_revenue(est, s) for s in (C1, C2, C3)]
    assert revenue == [D("5.00"), D("10.00"), D("20.00")]
    assert sum(revenue) == D("35.00")


def test_sc06_more_than_three_children_one_trigger():
    # Master 30 kg -> 900,000 VND; trigger 2/3 = 600,000; the other three 100,000 each.
    members = [
        member(1, "3"),
        member(2, "6", line(FAKE_CLOTHING)),
        member(3, "12"),
        member(4, "9"),
    ]
    est = run(members, master_kg="30")
    assert est.blocking == []
    assert master_fees(est, FAKE_CLOTHING)[0].vendor_fee_vnd == D("900000")
    assert [surcharge_cost(est, s) for s in (1, 2, 3, 4)] == [
        D("100000"), D("600000"), D("100000"), D("100000"),
    ]  # fmt: skip
    assert surcharge_revenue(est, 2) == cents(D("900000") / CASH_BUY) == D("50.00")
    assert all(surcharge_revenue(est, s) == 0 for s in (1, 3, 4))


def test_sc06_single_child_consolidation_takes_all():
    est = run([member(1, "21", line(FAKE_CLOTHING))])
    assert est.blocking == []
    assert surcharge_cost(est, 1) == D("630000")
    assert surcharge_revenue(est, 1) == D("35.00")
    assert est.members[1].base_cost_vnd == est.base_freight_vnd


# --- SC-07: Air Standard selling rate ------------------------------------------------------------


def test_sc07_base_revenue_at_18_cad_per_kg():
    est = run(core_members())
    figures = [quote_figures(est, s, D("18.00")) for s in (C1, C2, C3)]
    assert [f.base_revenue_cad for f in figures] == [D("54.00"), D("108.00"), D("216.00")]
    assert sum(f.base_revenue_cad for f in figures) == D("378.00")
    # No surcharge here: total revenue equals base revenue.
    assert [f.total_revenue_cad for f in figures] == [D("54.00"), D("108.00"), D("216.00")]


def test_sc07_quote_total_includes_trigger_surcharge():
    est = run(core_members({C2}))
    f2 = quote_figures(est, C2, D("18.00"))
    assert f2.base_revenue_cad == D("108.00")
    assert f2.surcharge_revenue_cad == D("35.00")
    assert f2.total_revenue_cad == D("143.00")
    assert quote_figures(est, C1, D("18.00")).total_revenue_cad == D("54.00")


# --- SC-08: bulky master ------------------------------------------------------------------------


@pytest.mark.parametrize("per_kg", [D("100000"), D("99999.99"), D("123456.78")])
def test_sc08_master_24kg_rated_on_24_allocated_3_6_12(per_kg):
    product = ProductView(
        code="AIR-STD",
        last_mile=TariffLastMile.PUROLATOR_GROUND,
        dim_divisor=6000,
        per_kg_from_kg=D("21"),
        piece_min_weight_kg=None,
        piece_min_fee_vnd=None,
        piece_min_applies_above_kg=None,
        customs_surcharges_waived=False,
        brackets=(Bracket("per_kg", 2, D("21"), D("44"), per_kg, "21-44"),),
    )
    est = run(core_members(), master_kg="24", product=product)
    assert est.blocking == []
    full = cents(per_kg * 24)
    assert est.master_chargeable_kg == D("24")
    assert est.base_freight_vnd == full
    parts = {s: est.members[s].base_cost_vnd for s in (C1, C2, C3)}
    assert sum(parts.values()) == full
    for sid, k in ((C1, 3), (C2, 6), (C3, 12)):
        exact = Fraction(str(full)) * k / 21
        assert abs(Fraction(str(parts[sid])) - exact) < Fraction(1, 100)
        assert parts[sid] == parts[sid].quantize(CENT)


# --- SC-09: no double charge; direct per-unit ----------------------------------------------------


def test_sc09_full_master_rule_from_two_children_charged_once():
    est = run(core_members({C1, C3}))
    fees = master_fees(est, FAKE_CLOTHING)
    assert len(fees) == 1
    assert fees[0].vendor_fee_vnd == D("630000")
    assert est.total_cost_vnd == est.base_freight_vnd + D("630000")
    assert sum(surcharge_cost(est, s) for s in (C1, C2, C3)) == D("630000")


def test_sc09_same_child_two_lines_same_full_master_rule_charged_once():
    members = core_members(extra={C2: (line(FAKE_CLOTHING), line(FAKE_CLOTHING))})
    est = run(members)
    fees = master_fees(est, FAKE_CLOTHING)
    assert len(fees) == 1
    assert fees[0].vendor_fee_vnd == D("630000")


def test_sc09_direct_per_unit_rule_charged_per_item_to_its_child_only():
    members = core_members(
        extra={C1: (line(PER_ITEM, quantity="3"),), C3: (line(PER_ITEM, quantity="2"),)}
    )
    est = run(members)
    assert est.blocking == []
    assert surcharge_cost(est, C1) == D("150000")
    assert surcharge_cost(est, C2) == D("0")
    assert surcharge_cost(est, C3) == D("100000")
    assert sum(f.vendor_fee_vnd for f in master_fees(est, PER_ITEM)) == D("250000")
    assert surcharge_revenue(est, C1) == cents(D("150000") / CASH_BUY) == D("8.33")
    assert surcharge_revenue(est, C2) == D("0")
    assert surcharge_revenue(est, C3) == cents(D("100000") / CASH_BUY) == D("5.56")


# --- OD-50: chargeable-weight rounding ----------------------------------------------------------

# (raw kg, rounded kg): first to 0.1 kg half-up, then x.0-x.1 -> x.0, x.2-x.6 -> x.5,
# x.7-x.9 -> next whole kg; minimum 0.5 kg. The same rule above 20.5 kg.
OD50_CASES = [
    ("0.01", "0.5"),
    ("0.1", "0.5"),
    ("0.2", "0.5"),
    ("0.5", "0.5"),
    ("0.7", "1"),
    ("1.0", "1"),
    ("1.1", "1"),
    ("5.1", "5"),
    ("5.2", "5.5"),
    ("5.3", "5.5"),
    ("5.5", "5.5"),
    ("5.6", "5.5"),
    ("5.7", "6"),
    ("5.8", "6"),
    ("5.9", "6"),
    ("5.0", "5"),
    ("5.149", "5"),  # 5.1
    ("5.15", "5.5"),  # 5.2
    ("5.649", "5.5"),  # 5.6
    ("5.65", "6"),  # 5.7
    ("5.96", "6"),  # 6.0
    ("20.6", "20.5"),
    ("20.65", "21"),  # 20.7
    ("20.7", "21"),
    ("21.0", "21"),
    ("21.1", "21"),
    ("21.2", "21.5"),
    ("21.6", "21.5"),
    ("21.7", "22"),
    ("44.6", "44.5"),
    ("44.8", "45"),
    ("99.6", "99.5"),
    ("99.7", "100"),
]


@pytest.mark.parametrize(("raw", "expected"), OD50_CASES)
def test_od50_round_chargeable(raw, expected):
    figure, convention = round_chargeable(D(raw))
    assert figure == D(expected)
    assert convention is False


@pytest.mark.parametrize(("raw", "expected"), OD50_CASES)
def test_od50_chargeable_weight_actual(raw, expected):
    cw = chargeable_weight(D(raw), divisor=6000)
    assert cw.chargeable_kg == D(expected)
    assert cw.used_half_kg_convention is False


@pytest.mark.parametrize(
    ("dims", "expected"),
    [
        # 40 x 30 x 26 / 6000 = 5.2 -> 5.5
        (("40", "30", "26"), "5.5"),
        # 50 x 40 x 40 / 6000 = 13.333 -> 13.3 -> 13.5
        (("50", "40", "40"), "13.5"),
        # 60 x 50 x 45 / 6000 = 22.5 -> 22.5
        (("60", "50", "45"), "22.5"),
        # 40 x 40 x 44 / 6000 = 11.733 -> 11.7 -> 12
        (("40", "40", "44"), "12"),
    ],
)
def test_od50_od52_volumetric_rounded_with_divisor_6000(dims, expected):
    ln, w, h = (D(x) for x in dims)
    cw = chargeable_weight(D("1"), length_cm=ln, width_cm=w, height_cm=h, divisor=6000)
    assert cw.chargeable_kg == D(expected)
    assert cw.used_half_kg_convention is False


@pytest.mark.parametrize(("raw", "expected"), [("5.1", "5"), ("5.2", "5.5"), ("5.7", "6")])
def test_od50_member_billable_kg_rounded(raw, expected):
    est = run([member(1, raw), member(2, "15")])
    assert est.members[1].billable_kg == D(expected)
    assert not (issue_codes(est) & HALF_KG_CODES)


def test_od50_member_volumetric_billable_kg_rounded():
    est = run([member(1, "1", dims=("40", "30", "26")), member(2, "15")])
    assert est.members[1].billable_kg == D("5.5")


@pytest.mark.parametrize(
    ("actual", "rounded", "base"),
    [
        ("20.7", "21", PER_KG_ZONE2 * 21),
        ("21.2", "21.5", PER_KG_ZONE2 * D("21.5")),
        ("21.7", "22", PER_KG_ZONE2 * 22),
        ("44.6", "44.5", PER_KG_ZONE2 * D("44.5")),
        ("44.8", "45", (PER_KG_ZONE2 - 10000) * 45),
    ],
)
def test_od50_od51_measured_master_rounded_and_band(actual, rounded, base):
    est = run([member(1, actual)], master=measured_master(actual))
    assert est.blocking == []
    assert est.master_chargeable_kg == D(rounded)
    assert est.base_freight_vnd == cents(base)
    assert not (issue_codes(est) & HALF_KG_CODES)


def test_od50_measured_master_volumetric_rounded():
    # 60 x 50 x 45 / 6000 = 22.5 kg beats 15 kg actual.
    est = run([member(1, "15")], master=measured_master("15", dims=("60", "50", "45")))
    assert est.master_chargeable_kg == D("22.5")
    assert est.base_freight_vnd == PER_KG_ZONE2 * D("22.5")


def test_od50_master_wide_per_kg_surcharge_on_rounded_master():
    # Master 21.2 kg -> 21.5 kg; 21.5 x 30,000 = 645,000.
    members = [member(1, "10", line(FAKE_CLOTHING)), member(2, "11.2")]
    est = run(members, master=measured_master("21.2"))
    assert est.blocking == []
    assert master_fees(est, FAKE_CLOTHING)[0].vendor_fee_vnd == D("645000")


@pytest.mark.parametrize(("kg", "fee"), [("2.3", "250000"), ("2.1", "200000"), ("2.7", "300000")])
def test_od50_item_weight_per_kg_surcharge_rounded(kg, fee):
    est = run(core_members(extra={C2: (line(ITEM_KG, weight_kg=kg),)}))
    assert est.blocking == []
    assert surcharge_cost(est, C2) == D(fee)
    assert surcharge_cost(est, C1) == surcharge_cost(est, C3) == D("0")


def test_od50_no_half_kg_flags_on_sub_20_5_master():
    est = run([member(1, "5.2")], master=measured_master("5.2"))
    assert est.master_chargeable_kg == D("5.5")
    assert not (issue_codes(est) & HALF_KG_CODES)


# --- OD-51 / OD-60: band of the rounded weight, no minimum bill, cents kept ---------------------


@pytest.fixture(scope="module")
def workbook():
    return parse_workbook(WORKBOOK.read_bytes())


def _hcm_air(workbook, last_mile=TariffLastMile.PUROLATOR_GROUND, piece_fee=None) -> ProductView:
    products = [
        p
        for p in workbook.products
        if p.origin == TariffOrigin.HCM
        and p.mode == TariffProductMode.AIR
        and p.last_mile == last_mile
    ]
    assert len(products) == 1
    code = products[0].code
    brackets = tuple(
        Bracket(b.kind, b.zone, b.weight_from_kg, b.weight_to_kg, b.price_vnd, b.label)
        for b in workbook.brackets
        if b.product_code == code and b.origin == TariffOrigin.HCM
    )
    return ProductView(
        code=code,
        last_mile=last_mile,
        dim_divisor=6000,
        per_kg_from_kg=D("21"),
        piece_min_weight_kg=D("12") if piece_fee is not None else None,
        piece_min_fee_vnd=piece_fee,
        piece_min_applies_above_kg=D("21") if piece_fee is not None else None,
        customs_surcharges_waived=False,
        brackets=brackets,
    )


def _hcm_air_ground(workbook) -> ProductView:
    return _hcm_air(workbook)


def _per_bill(workbook, code, zone, label) -> Decimal:
    rows = [
        b
        for b in workbook.brackets
        if b.product_code == code
        and b.origin == TariffOrigin.HCM
        and b.kind == "per_bill"
        and b.zone == zone
        and b.label == label
    ]
    assert len(rows) == 1, rows
    return rows[0].price_vnd


def _per_kg(workbook, code, zone, label) -> Decimal:
    rows = [
        b
        for b in workbook.brackets
        if b.product_code == code
        and b.origin == TariffOrigin.HCM
        and b.kind == "per_kg"
        and b.zone == zone
        and b.label == label
    ]
    assert len(rows) == 1, rows
    return rows[0].price_vnd


@pytest.mark.parametrize(
    ("actual", "row"),
    [
        ("0.1", "0.5"),  # minimum 0.5 kg; the 0.5 kg row, no separate minimum bill
        ("0.4", "0.5"),
        ("2.04", "2"),
        ("2.25", "2.5"),  # 2.3 -> 2.5
        ("5.1", "5"),
        ("5.2", "5.5"),
        ("5.6", "5.5"),
        ("5.7", "6"),
        ("20.6", "20.5"),
    ],
)
def test_od51_workbook_per_bill_row_of_rounded_weight(workbook, actual, row):
    product = _hcm_air_ground(workbook)
    price = _per_bill(workbook, product.code, 2, row)
    est = run([member(1, actual)], master=measured_master(actual), product=product)
    assert est.blocking == []
    assert est.master_chargeable_kg == D(row)
    # OD-60: VND kept to cents, never rounded to whole dong.
    assert est.base_freight_vnd == cents(price)


@pytest.mark.parametrize(
    ("actual", "rounded", "band"),
    [
        ("20.7", "21", "21-44"),
        ("21.2", "21.5", "21-44"),
        ("44.6", "44.5", "21-44"),
        ("44.8", "45", "45-99"),
        ("99.6", "99.5", "45-99"),
        ("99.7", "100", "100-299"),
    ],
)
def test_od51_workbook_per_kg_band_of_rounded_weight(workbook, actual, rounded, band):
    product = _hcm_air_ground(workbook)
    per_kg = _per_kg(workbook, product.code, 2, band)
    est = run([member(1, actual)], master=measured_master(actual), product=product)
    assert est.blocking == []
    assert est.master_chargeable_kg == D(rounded)
    assert est.base_freight_vnd == cents(per_kg * D(rounded))


def test_od60_vnd_amounts_keep_cents():
    # 99,999.99 x 21.5 = 2,149,999.785 -> 2,149,999.79 (not 2,150,000).
    product = ProductView(
        code="AIR-STD",
        last_mile=TariffLastMile.PUROLATOR_GROUND,
        dim_divisor=6000,
        per_kg_from_kg=D("21"),
        piece_min_weight_kg=None,
        piece_min_fee_vnd=None,
        piece_min_applies_above_kg=None,
        customs_surcharges_waived=False,
        brackets=(Bracket("per_kg", 2, D("21"), D("44"), D("99999.99"), "21-44"),),
    )
    est = run([member(1, "21.2")], master=measured_master("21.2"), product=product)
    assert est.base_freight_vnd == D("2149999.79")
    assert est.members[1].base_cost_vnd == D("2149999.79")


# --- OD-52: divisor 6000 ----------------------------------------------------------------------


def test_od52_air_products_use_divisor_6000():
    air = [k for k in PRODUCT_RULES if k[0].startswith("AIR-")]
    assert air, "air product rules must exist"
    for key in air:
        assert PRODUCT_RULES[key].dim_divisor == 6000, key


# --- SC-03 / OD-57: nail polish and perfume tiers ------------------------------------------------


@pytest.mark.parametrize(
    ("kg", "expected"),
    [
        ("0.5", "300000"),
        ("1", "300000"),
        ("3", "300000"),
        ("5.0", "300000"),
        ("5.1", "500000"),
        ("12", "500000"),
        ("22.0", "500000"),
        ("22.1", "700000"),
        ("30", "700000"),
        ("30.1", "700000"),
        ("31", "700000"),
        ("45", "700000"),
    ],
)
def test_od57_tier_price_top_above_30(kg, expected):
    assert tier_price(NAIL_TIERS, D(kg), above_top_tier="top") == D(expected)


@pytest.mark.parametrize(
    ("kg", "expected"),
    [
        ("1", "300000"),
        ("5.0", "300000"),
        ("5.01", "300000"),  # 0.1 kg quantization: 5.0
        ("5.04", "300000"),
        ("5.05", "500000"),  # 5.1
        ("5.1", "500000"),
        ("5.2", "500000"),  # NOT half-kg rounded to 5.5 (still 500k either way)
        ("12", "500000"),
        ("22.0", "500000"),
        ("22.04", "500000"),
        ("22.1", "700000"),
        ("30", "700000"),
        ("31", "700000"),
        ("45", "700000"),
    ],
)
def test_od57_nail_polish_in_estimate(kg, expected):
    nail = line(NAIL_POLISH, weight_kg=kg)
    est = run(core_members(extra={C1: (nail,)}))
    assert est.blocking == []
    assert surcharge_cost(est, C1) == D(expected)
    assert surcharge_cost(est, C2) == surcharge_cost(est, C3) == D("0")


@pytest.mark.parametrize(
    ("r", "kg", "expected"),
    [
        # OD-50 rounding would take 5.1 -> 5 (300k), 22.1 -> 22 (500k), 3.6 -> 3.5 (300k).
        (NAIL_POLISH, "5.1", "500000"),
        (NAIL_POLISH, "22.1", "700000"),
        (BATTERY, "3.6", "700000"),
    ],
)
def test_tier_lookup_uses_0_1kg_not_od50_rounding(r, kg, expected):
    est = run(core_members(extra={C1: (line(r, weight_kg=kg),)}))
    assert est.blocking == []
    assert surcharge_cost(est, C1) == D(expected)


@pytest.mark.parametrize(
    ("kg", "bottles", "expected"),
    [
        ("5.0", "3", "450000"),  # 300k + 3 x 50k
        ("5.01", "1", "350000"),  # 5.0 -> 300k + 50k
        ("12", "4", "700000"),  # 500k + 4 x 50k
        ("22.1", "2", "800000"),  # 700k + 2 x 50k
        ("35", "2", "800000"),  # above 30 -> top tier 700k + 2 x 50k
    ],
)
def test_od57_perfume_tier_plus_50k_per_bottle(kg, bottles, expected):
    perfume = line(PERFUME, quantity=bottles, weight_kg=kg)
    est = run(core_members(extra={C2: (perfume,)}))
    assert est.blocking == []
    assert surcharge_cost(est, C2) == D(expected)
    assert surcharge_cost(est, C1) == surcharge_cost(est, C3) == D("0")


def test_od57_curated_nail_polish_and_perfume_tiers_top_above_30():
    for stt in (1, 11):
        sem = CURATED_RULES[(SurchargeSection.HCM_AIR, stt)]
        assert sem.above_top_tier == "top"
        assert [(t.weight_from_kg, t.weight_to_kg, t.price_vnd) for t in sem.tiers] == [
            (D(0), D(5), D(300000)),
            (D(5), D(22), D(500000)),
            (D(22), D(30), D(700000)),
        ]
    assert CURATED_RULES[(SurchargeSection.HCM_AIR, 11)].per_unit_price_vnd == D(50000)


# --- OD-59: batteries -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kg", "expected"),
    [
        ("0.1", "300000"),
        ("3.0", "300000"),
        ("3.5", "300000"),
        ("3.6", "700000"),
        ("3.9", "700000"),
        ("8.0", "700000"),
        ("8.1", None),
        ("12", None),
    ],
)
def test_od59_battery_tier_price(kg, expected):
    got = tier_price(BATTERY_TIERS, D(kg), above_top_tier="manual")
    assert got == (D(expected) if expected is not None else None)


@pytest.mark.parametrize(
    ("kg", "expected"),
    [
        ("3.0", "300000"),
        ("3.5", "300000"),
        ("3.54", "300000"),  # 0.1 kg -> 3.5
        ("3.55", "700000"),  # 0.1 kg -> 3.6
        ("3.6", "700000"),
        ("3.9", "700000"),
        ("8.0", "700000"),
        ("8.04", "700000"),  # 0.1 kg -> 8.0
    ],
)
def test_od59_battery_in_estimate(kg, expected):
    est = run(core_members(extra={C1: (line(BATTERY, weight_kg=kg),)}))
    assert est.blocking == []
    assert surcharge_cost(est, C1) == D(expected)


@pytest.mark.parametrize("kg", ["8.05", "8.1", "9", "31"])
def test_od59_battery_above_8kg_blocks_without_manual_price(kg):
    bat = line(BATTERY, weight_kg=kg)
    est = run(core_members(extra={C1: (bat,)}))
    assert est.blocking, "a battery carton above 8 kg needs a manual quote"
    assert any(i.fee_line_id == bat.fee_line_id for i in est.blocking)
    for fee in master_fees(est, BATTERY):
        assert fee.vendor_fee_vnd is None
    assert surcharge_cost(est, C1) == D("0")


def test_od59_battery_above_8kg_uses_manual_price():
    bat = line(BATTERY, weight_kg="9", manual="900000")
    est = run(core_members(extra={C1: (bat,)}))
    assert est.blocking == []
    assert surcharge_cost(est, C1) == D("900000")
    assert surcharge_revenue(est, C1) == cents(D("900000") / CASH_BUY) == D("50.00")


def test_od59_curated_battery_tiers_manual_above_8():
    for stt in (2, 3):
        sem = CURATED_RULES[(SurchargeSection.HCM_AIR, stt)]
        assert sem.above_top_tier == "manual"
        assert [(t.weight_from_kg, t.weight_to_kg, t.price_vnd) for t in sem.tiers] == [
            (D(0), D("3.5"), D(300000)),
            (D("3.5"), D(8), D(700000)),
        ]


# --- SC-02: Hà Nội free rule, wrong origin -------------------------------------------------------


def test_sc02_hanoi_false_eyelashes_free_not_blocking():
    members = core_members(extra={C2: (line(HN_EYELASHES),)})
    est = run(members, rule_section=HAN)
    assert est.blocking == []
    fees = master_fees(est, HN_EYELASHES)
    assert fees and all(f.vendor_fee_vnd == 0 for f in fees)
    assert all(surcharge_cost(est, s) == 0 for s in (C1, C2, C3))
    assert all(surcharge_revenue(est, s) == 0 for s in (C1, C2, C3))


def test_sc02_hcm_rule_on_hanoi_consolidation_is_blocking_and_unpriced():
    wrong = line(FAKE_CLOTHING)
    members = core_members(extra={C2: (wrong,)})
    est = run(members, rule_section=HAN)
    assert est.blocking
    assert any(i.fee_line_id == wrong.fee_line_id for i in est.blocking)
    assert all(f.vendor_fee_vnd in (None, 0) for f in master_fees(est, FAKE_CLOTHING))
    assert all(surcharge_cost(est, s) == 0 for s in (C1, C2, C3))
    assert est.total_cost_vnd == est.base_freight_vnd


# --- OD-56: manual-quote rows -----------------------------------------------------------------


def test_od56_curated_manual_quote_rows():
    manual = {
        stt
        for (section, stt), sem in CURATED_RULES.items()
        if section == SurchargeSection.HCM_AIR
        and sem.pricing_status == SurchargePricingStatus.MANUAL_QUOTE
    }
    assert manual == {4, 5, 10, 13, 27, 31, 33, 34, 45}
    # Row 27 (costume jewellery) is quoted case by case with no prefill since the owner's
    # answer of 2026-10-22 (DEC-0225): staff enter the line's amount.
    for stt in manual - {27}:
        assert CURATED_RULES[(SurchargeSection.HCM_AIR, stt)].unit_price_vnd is not None
    assert CURATED_RULES[(SurchargeSection.HCM_AIR, 27)].unit_price_vnd is None


def test_od56_manual_quote_prefilled_minimum_is_provisional_not_blocking():
    cam = line(CAMERA, quantity="2")
    est = run(core_members(extra={C2: (cam,)}))
    assert est.blocking == []
    assert surcharge_cost(est, C2) == D("200000")  # 2 x 100,000 file minimum
    assert surcharge_cost(est, C1) == surcharge_cost(est, C3) == D("0")
    assert any(i.code == PREFILLED and i.fee_line_id == cam.fee_line_id for i in est.provisional)
    assert surcharge_revenue(est, C2) == cents(D("200000") / CASH_BUY) == D("11.11")


def test_od56_manual_quote_uses_entered_price():
    cam = line(CAMERA, quantity="2", manual="180000")
    est = run(core_members(extra={C2: (cam,)}))
    assert est.blocking == []
    assert surcharge_cost(est, C2) == D("360000")
    assert not any(
        i.code == PREFILLED and i.fee_line_id == cam.fee_line_id for i in est.provisional
    )


# --- OD-58: pharmaceuticals priced; generic unpriceable safety ------------------------------------


def test_od58_curated_pharma_priced_200k_per_kg():
    sem = CURATED_RULES[(SurchargeSection.HCM_AIR, 39)]
    assert sem.pricing_status == SurchargePricingStatus.PRICED
    assert sem.basis == SurchargeBasis.PER_KG
    assert sem.unit_price_vnd == D(200000)


def test_od58_pharma_priced_not_blocking():
    est = run(core_members(extra={C2: (line(PHARMA),)}))
    assert est.blocking == []
    fees = master_fees(est, PHARMA)
    assert len(fees) == 1
    assert fees[0].vendor_fee_vnd == D("4200000")  # 21 kg x 200,000
    # As SC-05: 2/3 to the trigger; the remaining 1/3 shared equally by the others.
    assert [surcharge_cost(est, s) for s in (C1, C2, C3)] == [
        D("700000"), D("2800000"), D("700000"),
    ]  # fmt: skip
    assert surcharge_revenue(est, C2) == cents(D("4200000") / CASH_BUY) == D("233.33")


@pytest.mark.parametrize("r", [DISPUTED, CASE_BY_CASE], ids=["conflict", "unpriced_review"])
def test_unpriceable_rule_blocks_with_no_guessed_price(r):
    bad = line(r, weight_kg="6")
    est = run(core_members(extra={C2: (bad,)}))
    assert est.blocking
    assert any(i.fee_line_id == bad.fee_line_id for i in est.blocking)
    for fee in master_fees(est, r):
        assert fee.vendor_fee_vnd is None
    assert all(surcharge_cost(est, s) == 0 for s in (C1, C2, C3))
    assert est.total_cost_vnd == est.base_freight_vnd


# --- OD-46: zone from the fixed delivery point ---------------------------------------------------


def test_od46_ground_product_uses_ground_zone_2():
    est = run(core_members(), product=make_product("AIR-STD", TariffLastMile.PUROLATOR_GROUND))
    assert est.delivery_postal_code == "L5A3K6"
    assert est.zone == 2
    assert est.base_freight_vnd == PER_KG_ZONE2 * 21


def test_od46_express_product_uses_express_zone_3():
    est = run(core_members(), product=make_product("AIR-EXP", TariffLastMile.PUROLATOR_EXPRESS))
    assert est.zone == 3
    assert est.base_freight_vnd == PER_KG_ZONE3 * 21


def test_od46_workbook_express_zone_3_at_rounded_weight(workbook):
    product = _hcm_air(workbook, TariffLastMile.PUROLATOR_EXPRESS)
    per_kg = _per_kg(workbook, product.code, 3, "21-44")
    est = run([member(1, "21.2")], master=measured_master("21.2"), product=product)
    assert est.blocking == []
    assert est.zone == 3
    assert est.delivery_postal_code == "L5A3K6"
    assert est.base_freight_vnd == cents(per_kg * D("21.5"))


# --- FX / OD-54 --------------------------------------------------------------------------------


def test_fx_live_snapshot_is_not_blocking():
    est = run(core_members({C2}))
    assert est.blocking == []
    assert est.fx_snapshot_id == 7


def test_fx_missing_snapshot_blocks():
    est = run(core_members({C2}), fx=None)
    assert est.blocking


def test_fx_stale_snapshot_blocks():
    stale = FxView(snapshot_id=8, cash_buy_vnd=CASH_BUY, sell_vnd=SELL, freshness="stale")
    est = run(core_members({C2}), fx=stale)
    assert est.blocking


def test_fx_cost_and_customer_surcharge_both_at_cash_buy():
    """OD-73 (owner, 2026-10-20): VND -> CAD at the buy rate for cost and for the customer
    surcharge, so a pass-through surcharge recovers exactly its cost."""
    # Realistic, non-round rates.
    fx = FxView(snapshot_id=9, cash_buy_vnd=D("18520"), sell_vnd=D("19105"), freshness="live")
    est = run(core_members({C2}), fx=fx)
    assert est.blocking == []
    assert est.base_freight_cad == cents(D("2100000") / D("18520"))  # 113.39
    fee = master_fees(est, FAKE_CLOTHING)[0]
    assert sum(est.members[s].surcharge_cost_cad for s in (C1, C2, C3)) == cents(
        D("630000") / D("18520")
    )
    assert surcharge_revenue(est, C2) == cents(D("630000") / D("18520")) == D("34.02")
    assert fee.customer_total_cad == D("34.02")


def test_od54_no_fixed_19500_rate():
    fx = FxView(snapshot_id=10, cash_buy_vnd=D("17000"), sell_vnd=D("21000"), freshness="live")
    est = run(core_members({C2}), fx=fx)
    assert est.blocking == []
    assert est.base_freight_cad == cents(D("2100000") / D("17000")) == D("123.53")
    assert est.base_freight_cad != cents(D("2100000") / D("19500"))
    assert surcharge_revenue(est, C2) == cents(D("630000") / D("17000")) == D("37.06")


# --- OD-62: under-12 kg piece fee ----------------------------------------------------------------


def _piece_members():
    return [member(1, "10"), member(2, "20")]


def test_od62_ground_piece_fee_per_under_12kg_carton_allocated_with_base():
    # 11.6 -> 11.5 (under 12): fee; 11.7 -> 12 (not under): none; 6.7 -> 7: fee.
    cartons = (carton("11.6"), carton("11.7"), carton("6.7"))
    est = run(
        _piece_members(),
        master=measured_master("30", cartons=cartons),
        product=make_product(piece_fee=D("300000")),
    )
    assert est.blocking == []
    assert est.master_chargeable_kg == D("30")
    assert est.base_freight_vnd == PER_KG_ZONE2 * 30
    assert est.piece_fee_vnd == D("600000")
    parts = [est.members[s].base_cost_vnd for s in (1, 2)]
    assert sum(parts) == D("3600000")
    assert parts == [D("1200000"), D("2400000")]  # CW share 10 : 20
    assert est.total_cost_vnd == D("3600000")


def test_od62_express_piece_fee_700k():
    cartons = (carton("11.6"), carton("18.4"))
    est = run(
        _piece_members(),
        master=measured_master("30", cartons=cartons),
        product=make_product("AIR-EXP", TariffLastMile.PUROLATOR_EXPRESS, piece_fee=D("700000")),
    )
    assert est.piece_fee_vnd == D("700000")
    assert sum(est.members[s].base_cost_vnd for s in (1, 2)) == PER_KG_ZONE3 * 30 + D("700000")


def test_od62_carton_weight_is_rounded_max_of_actual_and_volumetric():
    cartons = (
        carton("5", ("50", "40", "40")),  # vol 13.33 -> 13.5: not under 12
        carton("11", ("40", "40", "44")),  # vol 11.73 -> 12: not under 12
        carton("14"),
    )
    est = run(
        _piece_members(),
        master=measured_master("30", cartons=cartons),
        product=make_product(piece_fee=D("300000")),
    )
    assert est.piece_fee_vnd == D("0")
    assert sum(est.members[s].base_cost_vnd for s in (1, 2)) == PER_KG_ZONE2 * 30


def test_od62_master_rounding_to_21_triggers_piece_fee():
    # Master 20.7 -> 21 kg (>= 21): both cartons under 12 kg pay.
    est = run(
        [member(1, "10"), member(2, "10.7")],
        master=measured_master("20.7", cartons=(carton("10"), carton("10.7"))),
        product=make_product(piece_fee=D("300000")),
    )
    assert est.master_chargeable_kg == D("21")
    assert est.piece_fee_vnd == D("600000")


def test_od62_master_under_21_no_piece_fee():
    # Master 20.6 -> 20.5 kg: no piece fee.
    est = run(
        [member(1, "10"), member(2, "10.6")],
        master=measured_master("20.6", cartons=(carton("10"), carton("10.6"))),
        product=make_product(piece_fee=D("300000")),
    )
    assert est.master_chargeable_kg == D("20.5")
    assert est.piece_fee_vnd == D("0")
    assert PIECE_NOT_EVALUATED not in issue_codes(est)


def test_od62_no_carton_rows_with_several_cartons_is_provisional():
    est = run(
        _piece_members(),
        master=measured_master("30", carton_count=2),
        product=make_product(piece_fee=D("300000")),
    )
    assert est.blocking == []
    assert est.piece_fee_vnd == D("0")
    assert PIECE_NOT_EVALUATED in {i.code for i in est.provisional}


def test_od62_single_carton_without_rows_not_flagged():
    est = run(
        [member(1, "30")],
        master=measured_master("30", carton_count=1),
        product=make_product(piece_fee=D("300000")),
    )
    assert est.piece_fee_vnd == D("0")
    assert PIECE_NOT_EVALUATED not in issue_codes(est)


# --- Real workbook: HCM AIR-CAD zone 2 at 21 kg -------------------------------------------------


def test_workbook_hcm_air_zone2_21kg_base_freight(workbook):
    product = _hcm_air_ground(workbook)
    rows = [
        b
        for b in workbook.brackets
        if b.product_code == product.code
        and b.origin == TariffOrigin.HCM
        and b.kind == "per_kg"
        and b.zone == 2
        and (b.weight_from_kg is None or b.weight_from_kg <= 21)
        and (b.weight_to_kg is None or b.weight_to_kg >= 21)
    ]
    assert len(rows) == 1, rows
    per_kg = rows[0].price_vnd
    assert per_kg > 0
    expected = cents(per_kg * 21)

    got, refusal = base_freight(product, 2, D("21"))
    assert refusal is None
    assert got == expected

    est = run(core_members(), product=product)
    assert est.blocking == []
    assert est.zone == 2
    assert est.base_freight_vnd == expected
    parts = [est.members[s].base_cost_vnd for s in (C1, C2, C3)]
    assert sum(parts) == expected
    for p, k in zip(parts, (3, 6, 12), strict=True):
        assert abs(Fraction(str(p)) - Fraction(str(expected)) * k / 21) < Fraction(1, 100)


# --- Property: allocation -----------------------------------------------------------------------


def test_allocate_property_random_vectors():
    rng = random.Random(20261019)
    for _ in range(2000):
        n = rng.randint(1, 12)
        weights = []
        for _ in range(n):
            kind = rng.random()
            if kind < 0.1:
                weights.append(Fraction(0))
            elif kind < 0.5:
                weights.append(Fraction(rng.randint(1, 5000)))
            else:
                weights.append(Fraction(rng.randint(1, 100000), rng.randint(1, 1000)))
        if sum(weights) == 0:
            weights[0] = Fraction(1)
        total = D(rng.randint(0, 10**10)) * CENT
        keys = list(range(n))
        parts = allocate(total, keys, weights)
        assert set(parts) == set(keys)
        assert sum(parts.values()) == total
        tw = sum(weights)
        for k, w in zip(keys, weights, strict=True):
            exact = Fraction(str(total)) * w / tw
            diff = abs(Fraction(str(parts[k])) - exact)
            assert diff < Fraction(1, 100), (total, weights, k, parts[k])
            assert parts[k] == parts[k].quantize(CENT)
            if w == 0:
                assert parts[k] == 0
