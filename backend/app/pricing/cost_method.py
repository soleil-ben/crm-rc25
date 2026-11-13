"""The owner's cost and quote method (Louis; ``cost-quote-method.md`` v0.7 of 2026-11-03: v0.5 of
2026-11-02 plus DEC-0253..0266). Version-neutral module name since DEC-0267 (was
``method_v05``); the estimate's detail is ``Estimate.method_detail`` (was ``v05``) and the
method document version is recorded as ``method_version``.

v0.6 on top of v0.5: the Kango piece fee is vendor cost only (lots of 21 kg and over, each
carton under 12 kg, split by weight among that carton's customers); per-box surcharge bands
read the OD-50 rounded box weight for cost and quote (Q6); Sea is the sea vendor's
60,000 VND/kg on the bill weight with no Kango sheet, no piece fee and only the vendor's two
surcharges (SEA ITEM + MIN: rate × item kg, minimum per package per type); a customer can be
placed in a package of its master; Air Express shows the Kango EXPRESS zone table for
reference only.

**Pure**, like ``engine.py``: dataclasses in, an ``engine.Estimate`` out, no database, no clock.
It reuses the RC-UAT-25 building blocks unchanged -- ``engine.base_freight`` (per-bill band /
per-kg tier), ``engine._line_vendor_fee`` (a rule's VND for one line), ``engine._cost_split``
(the 2/3 trigger rule), ``engine.allocate`` (largest-remainder cents), ``engine._piece_fee``
(the under-12 kg carton fee, OD-62) and ``chargeable_weight.round_chargeable`` (OD-50) -- and
changes only what the method changes:

* **Vendor bill weight** = Kango's rounding of Σ package CW (rate file B65: above 20.5 kg up to
  the next whole kg; at or below, the 0.5 kg band at or above). A booked master keeps the
  figure stored at booking.
* **Base freight** by the customer's rounded CW (OD-50); leftover (bill CW above Σ customer CW)
  spread by weight (default) or left unallocated.
* **Surcharges by allocation class** (``surcharge_allocation_classes``):
  ITEM (owner pays, cost = quote) · PARCEL (DEC-0276: cost once per master piece, band on
  the total kg of that item type in the piece, shared by item kg; quote: each customer with
  the item pays the full fee, band on its own kg) · LOT (per shipment, HCM-47: cost once for
  the shipment, quote the full fee to each customer with the item) · WHOLE_PACKAGE /
  WHOLE_MASTER (rate × whole package / bill CW once, 2/3 trigger rule; quote the same share,
  or triggers only) · CONFIRM (item, flagged) · NONE.
* **FX** per setting (Kango fixed 19,500 by default) for cost and for quote.
* **Selling rate**: Air Standard high / low by the customer's own rounded CW against the
  threshold; Sea flat; Air Express and UPS manual.
* **CAD cents**: each customer's cost is rounded half-up; the difference to the bill
  (Σ customer CAD + unallocated CAD = bill CAD) goes to the customer with the largest VND
  cost -- the rule the golden case study (``case_study_results.json``) was computed with.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from fractions import Fraction

from app.core.enums import (
    BeyondRateStatus,
    SolarisService,
    SurchargeBasis,
    SurchargePricingStatus,
    SurchargeScope,
    TariffLastMile,
)
from app.pricing import chargeable_weight as cw
from app.pricing import engine as pe

ZERO = Decimal(0)
#: The method document (``cost-quote-method.md``) version this engine implements; recorded on
#: every estimate and quote snapshot (``method_version``) since the switch value became the
#: version-neutral ``confirmed`` (DEC-0267).
METHOD_VERSION = "v0.7"
HALF = Decimal("0.5")
#: Services whose base cost is read from the Kango table (v0.6: Air Standard only).
#: Kango rate-sheet services (DEC-0271: Air Express is priced on Kango's Express table at the
#: warehouse's Express zone, no longer by hand).
TABLE_SERVICES = frozenset({SolarisService.AIR_STANDARD, SolarisService.AIR_EXPRESS})
#: Priced by hand: vendor cost and selling rate entered per master.
MANUAL_SERVICES = frozenset({SolarisService.UPS, SolarisService.AIR_CARGO})
SEA_VENDOR_SECTION = "sea_vendor"
CLASS_LABELS = {
    "ITEM": "Item · owner pays",
    "PARCEL": "Per master piece · Kango once per piece, quote each",
    "LOT": "Per shipment · Kango once, quote each",
    "WHOLE_PACKAGE": "Whole package · 2/3 rule",
    "WHOLE_MASTER": "Whole master · 2/3 rule",
    "CONFIRM": "Basis unconfirmed · owner pays",
    "SEA_ITEM_MIN": "Sea · item kg, minimum per package",
    "PIECE": "Piece fee · vendor cost only",
    "NONE": "No fee",
}


@dataclass(frozen=True)
class MethodSettings:
    """Settings › Pricing (method v0.5). Defaults are Louis's (2026-11-02)."""

    air_std_rate_high_cad: Decimal = Decimal("18.00")
    air_std_rate_low_cad: Decimal = Decimal("19.00")
    air_std_threshold_kg: Decimal = Decimal("21")
    threshold_basis: str = "customer"  # customer | package
    sea_rate_cad: Decimal = Decimal("8.00")
    markup_kind: str = "none"  # none | fixed_cad | percent
    markup_value: Decimal = ZERO
    fx_source_cost: str = "kango_fixed"  # kango_fixed | vcb_cash_buy | vcb_sell
    fx_source_quote: str = "kango_fixed"
    kango_fixed_rate_vnd: Decimal = Decimal("19500")
    residual_mode: str = "prorata"  # prorata | unallocated
    pkg_surcharge_billing: str = "same_as_cost"  # same_as_cost | triggers_only
    parcel_band_cost_basis: str = "box"  # box | parcel
    parcel_quote_mode: str = "each"  # each | share
    vendor_bill_rounding: str = "kango"  # kango | od50
    #: v0.6: the sea vendor's cost per kg (no Kango sea sheet).
    sea_cost_vnd_per_kg: Decimal = Decimal("60000")
    #: DEC-0271: Kango Air Express selling rate when staff enter none (Settings → Pricing,
    #: "Air Express default rate"); ``None`` = staff must enter one.
    air_express_rate_cad: Decimal | None = None


@dataclass(frozen=True)
class SeaRule:
    """A sea vendor surcharge (v0.6): VND per item kg, minimum per package per type."""

    rule_id: int
    code: str
    name: str
    rate_vnd_per_kg: Decimal
    min_vnd_per_package: Decimal


@dataclass(frozen=True)
class ManualPricing:
    """Per master: vendor cost and selling rate entered by staff. UPS and Air Cargo are priced
    this way; on a rate-sheet service (Kango Air Standard / Express, Sea) a cost here is an
    **override** of the table, with its reason (DEC-0271)."""

    cost_vnd_per_kg: Decimal | None = None
    cost_vnd_total: Decimal | None = None
    sell_cad_per_kg: Decimal | None = None
    reason: str | None = None

    @property
    def has_cost(self) -> bool:
        return self.cost_vnd_per_kg is not None or self.cost_vnd_total is not None


@dataclass(frozen=True)
class UpsBand:
    from_kg: Decimal
    to_kg: Decimal | None
    cost_vnd: Decimal | None
    sell_cad_per_kg: Decimal | None


# --- Small pure helpers --------------------------------------------------------------------


def kango_round(raw_kg: Decimal) -> Decimal:
    """Kango's own bill rounding (rate file B65): > 20.5 kg → up to the next whole kg;
    ≤ 20.5 kg → the 0.5 kg band at or above. The smallest bill is 0.5 kg."""
    if raw_kg <= 0:
        raise ValueError("chargeable weight must be positive")
    x = Decimal(raw_kg).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    if x > Decimal("20.5"):
        return x.to_integral_value(rounding=ROUND_CEILING)
    return max(HALF, (x * 2).to_integral_value(rounding=ROUND_CEILING) / 2)


def vendor_bill_weight(
    master: pe.MasterInput, divisor: int, rounding: str = "kango"
) -> tuple[Decimal | None, Decimal | None]:
    """The vendor bill weight (method §6): Σ of the recorded packages' CW (the greater of
    actual and L × W × H / divisor each), else the master's own CW; then Kango's rounding
    (above 20.5 kg up to the whole kg), or OD-50 when that setting is chosen. Returns
    (raw kg, bill kg). Booking stores exactly this figure (DEC-0265)."""
    raw: Decimal | None = None
    rows = []
    for carton in master.cartons:
        vol = cw.volumetric_weight(carton.length_cm, carton.width_cm, carton.height_cm, divisor)
        rows.append(
            max(carton.weight_kg, vol)
            if carton.weight_kg is not None and vol is not None
            else carton.weight_kg
        )
    if rows and all(rows):
        raw = sum(rows, ZERO)
    elif master.actual_weight_kg is not None and master.actual_weight_kg > 0:
        raw = cw.chargeable_weight(
            master.actual_weight_kg,
            length_cm=master.length_cm,
            width_cm=master.width_cm,
            height_cm=master.height_cm,
            divisor=divisor,
        ).raw_kg
    if raw is None:
        return None, None
    billed = cw.round_chargeable(raw)[0] if rounding == "od50" else kango_round(raw)
    return raw, billed


def allocation_class(rule: pe.RuleView, policy: pe.RulePolicy | None) -> str:
    """The rule's class: an owner scope override first, then the loaded class, else derived
    from the RC-UAT-25 basis and scope."""
    if policy is not None and policy.scope_override is not None:
        if policy.scope_override == SurchargeScope.FULL_CARTON:
            return "WHOLE_PACKAGE"
        if policy.scope_override in {SurchargeScope.FULL_MASTER, SurchargeScope.PER_SHIPMENT}:
            return "WHOLE_MASTER"
    if rule.allocation_class:
        return rule.allocation_class
    if rule.pricing_status == SurchargePricingStatus.FREE or rule.basis == SurchargeBasis.FREE:
        return "NONE"
    if rule.basis == SurchargeBasis.PER_SHIPMENT or rule.scope in {
        SurchargeScope.FULL_MASTER,
        SurchargeScope.PER_SHIPMENT,
    }:
        return "WHOLE_MASTER"
    if rule.scope == SurchargeScope.FULL_CARTON:
        return "WHOLE_PACKAGE"
    if rule.pricing_status == SurchargePricingStatus.TIERED or rule.basis in {
        SurchargeBasis.PER_PIECE,
        SurchargeBasis.COMPOUND,
    }:
        return "PARCEL"
    return "ITEM"


def _frac(value: Decimal) -> Fraction:
    return Fraction(str(value))


def _by_weight(total: Decimal, ids: Sequence[int], kg: dict[int, Decimal]) -> dict[int, Decimal]:
    if not ids:
        return {}
    if len(ids) == 1:
        return {ids[0]: total}
    return pe.allocate(total, list(ids), [_frac(kg[i]) for i in ids])


def _fx_rate(source: str, method: MethodSettings, fx: pe.FxView | None) -> Decimal | None:
    if source == "kango_fixed":
        return method.kango_fixed_rate_vnd
    if fx is None:
        return None
    return fx.cash_buy_vnd if source == "vcb_cash_buy" else fx.sell_vnd


# --- The estimate ------------------------------------------------------------------------------


def estimate_method(
    *,
    service: str,
    product: pe.ProductView | None,
    product_refusal: str | None,
    delivery: pe.DeliveryPoint,
    master: pe.MasterInput,
    members: Sequence[pe.MemberInput],
    rules: dict[tuple[str, int], pe.RuleView],
    rule_section: str,
    policies: dict[tuple[str, int], pe.RulePolicy],
    fx: pe.FxView | None,
    settings: pe.Settings,
    method: MethodSettings,
    manual: ManualPricing | None = None,
    ups_bands: Sequence[UpsBand] = (),
    sea_rules: dict[int, SeaRule] | None = None,
    member_packages: dict[int, int] | None = None,
) -> pe.Estimate:
    blocking: list[pe.Issue] = []
    provisional: list[pe.Issue] = []
    if not settings.defaults_owner_confirmed:  # the OD-48 flag, as under RC-UAT-25
        provisional.append(
            pe.Issue(
                "pricing_defaults_pending_owner_confirmation",
                "The Air Standard default rate and the full-master trigger share are configurable "
                "defaults pending owner confirmation (OD-48).",
            )
        )
    manual = manual or ManualPricing()
    sea_rules = sea_rules or {}
    member_packages = member_packages or {}
    is_sea = service == SolarisService.SEA
    uses_table = service in TABLE_SERVICES
    divisor = product.dim_divisor if product is not None else 6000
    if uses_table and product is None:
        blocking.append(
            pe.Issue("no_vendor_product", product_refusal or "No vendor product is mapped.")
        )

    # --- Customer weights (OD-50 on Σ of the customer's boxes) ---------------------------------
    result_members: dict[int, pe.MemberResult] = {}
    billable: dict[int, Decimal] = {}
    for member in members:
        raw = pe.member_raw_weight(member, divisor)
        rounded = None
        if raw is None:
            blocking.append(
                pe.Issue(
                    "member_weight_missing",
                    f"{member.public_id}: every active package needs a weight before pricing.",
                    shipment_id=member.shipment_id,
                )
            )
        else:
            rounded = cw.round_chargeable(raw)[0]
            billable[member.shipment_id] = rounded
        result_members[member.shipment_id] = pe.MemberResult(
            member.shipment_id, member.public_id, raw, rounded
        )
    if not members:
        blocking.append(pe.Issue("no_members", "The consolidation has no shipments."))
    member_ids = [m.shipment_id for m in members]
    weights_known = bool(member_ids) and len(billable) == len(member_ids)

    # --- Packages and the vendor bill weight -----------------------------------------------------
    package_rows: list[dict] = []
    if master.cartons:
        for seq, carton in enumerate(master.cartons, start=1):
            vol = cw.volumetric_weight(carton.length_cm, carton.width_cm, carton.height_cm, divisor)
            raw = (
                max(carton.weight_kg, vol)
                if carton.weight_kg is not None and vol is not None
                else carton.weight_kg
            )
            package_rows.append(
                {"sequence": seq, "raw_kg": raw, "packed_as_one_box": carton.packed_as_one_box}
            )
    master_raw, computed_bill = vendor_bill_weight(master, divisor, method.vendor_bill_rounding)
    bill_kg: Decimal | None = master.stored_chargeable_kg
    if bill_kg is None:
        if master_raw is None:
            blocking.append(pe.Issue("master_weight_missing", "Enter the master's actual weight."))
        bill_kg = computed_bill
    if not package_rows:
        package_rows = [{"sequence": 1, "raw_kg": master_raw, "packed_as_one_box": False}]
    for p in package_rows:
        p["billed_kg"] = kango_round(p["raw_kg"]) if p["raw_kg"] else None
        # Q6: a surcharge band reads the OD-50 rounded weight (5.1 kg → 5.0).
        p["band_kg"] = cw.round_chargeable(p["raw_kg"])[0] if p["raw_kg"] else None
    single_package = len(package_rows) == 1
    sequences = {p["sequence"] for p in package_rows}

    def package_of(sid: int) -> int | None:
        """The package a customer rides in: recorded, or the only one."""
        if single_package:
            return package_rows[0]["sequence"]
        seq = member_packages.get(sid)
        return seq if seq in sequences else None

    for p in package_rows:
        p["members"] = [
            m.shipment_id for m in members if package_of(m.shipment_id) == p["sequence"]
        ]
    packages_known = all(package_of(m.shipment_id) is not None for m in members)
    package_kg = package_rows[0]["billed_kg"] if single_package else bill_kg
    if single_package and len(master.cartons) == 0:
        package_kg = bill_kg
    if not single_package and any(p["packed_as_one_box"] for p in package_rows):
        provisional.append(
            pe.Issue(
                "packed_flag_needs_package_members",
                "A package is marked 'packed as one box for Kango', but the master has "
                f"{len(package_rows)} packages; 'packed as one box' is applied to one-package "
                "masters only for now, so per-box surcharges are costed per small box.",
            )
        )

    # --- Zone and delivery point (table services only) -----------------------------------------
    zone: int | None = None
    if uses_table and product is not None:
        zone = (
            delivery.express_zone
            if product.last_mile == TariffLastMile.PUROLATOR_EXPRESS
            else delivery.ground_zone
        )
        if zone is None:
            blocking.append(
                pe.Issue(
                    "delivery_zone_unknown",
                    f"The tariff has no zone for the delivery point {delivery.postal_code}.",
                )
            )
        if delivery.beyond_code is not None and delivery.beyond_status == BeyondRateStatus.NO_RATE:
            blocking.append(
                pe.Issue(
                    "delivery_beyond_no_rate",
                    f"The delivery point {delivery.postal_code} is beyond-area code "
                    f"{delivery.beyond_code}, which has no rate (V-05).",
                )
            )

    # --- Base freight ---------------------------------------------------------------------------
    base_vnd: Decimal | None = None
    base_basis = ""
    base_overridden = False
    if bill_kg is not None:
        if service not in MANUAL_SERVICES and manual.has_cost:
            # DEC-0271: staff overrode the rate-sheet base cost for this master, with a reason.
            if manual.cost_vnd_total is not None:
                base_vnd = pe.to_cents(manual.cost_vnd_total)
            else:
                base_vnd = pe.to_cents(manual.cost_vnd_per_kg * bill_kg)
            base_overridden = True
            base_basis = f"Base cost entered by staff on {bill_kg} kg (overrides the rate sheet)"
            provisional.append(
                pe.Issue(
                    "base_cost_overridden",
                    "The vendor base cost was entered by staff instead of the rate sheet"
                    + (f": {manual.reason}" if manual.reason else "."),
                )
            )
        elif uses_table and product is not None and zone is not None:
            base_vnd, refusal = pe.base_freight(product, zone, bill_kg)
            if refusal:
                blocking.append(pe.Issue("base_freight_unpriced", refusal))
            base_basis = f"{product.code} zone {zone} on {bill_kg} kg"
        elif is_sea:
            # v0.6: the sea vendor's rate on the bill weight, any weight; no Kango sea sheet.
            base_vnd = pe.to_cents(method.sea_cost_vnd_per_kg * bill_kg)
            base_basis = f"Sea vendor {method.sea_cost_vnd_per_kg} VND/kg on {bill_kg} kg"
        elif service == SolarisService.UPS:
            band = next(
                (
                    b
                    for b in ups_bands
                    if bill_kg >= b.from_kg and (b.to_kg is None or bill_kg <= b.to_kg)
                ),
                None,
            )
            if manual.cost_vnd_total is not None:
                base_vnd = pe.to_cents(manual.cost_vnd_total)
            elif manual.cost_vnd_per_kg is not None:
                base_vnd = pe.to_cents(manual.cost_vnd_per_kg * bill_kg)
            elif band is not None and band.cost_vnd is not None:
                base_vnd = pe.to_cents(band.cost_vnd)
            else:
                blocking.append(
                    pe.Issue(
                        "ups_cost_missing",
                        "UPS has no rate table yet: enter the vendor cost for this master.",
                    )
                )
            base_basis = f"UPS cost on package CW {bill_kg} kg"
        elif service == SolarisService.AIR_CARGO:
            if manual.cost_vnd_total is not None:
                base_vnd = pe.to_cents(manual.cost_vnd_total)
            elif manual.cost_vnd_per_kg is not None:
                base_vnd = pe.to_cents(manual.cost_vnd_per_kg * bill_kg)
            else:
                blocking.append(
                    pe.Issue(
                        "air_cargo_cost_missing",
                        "Air Cargo is priced manually: enter the vendor cost (VND per kg or a "
                        "total) for this master.",
                    )
                )
            base_basis = f"Air Cargo manual cost on {bill_kg} kg"
    # Express: what Kango's Express table says, kept beside an override for comparison.
    express_reference = None
    if service == SolarisService.AIR_EXPRESS and product is not None and bill_kg is not None:
        ref_zone = delivery.express_zone
        if ref_zone is not None:
            ref_vnd, _ref_refusal = pe.base_freight(product, ref_zone, bill_kg)
            express_reference = {
                "product": product.code,
                "zone": ref_zone,
                "bill_kg": bill_kg,
                "vnd": ref_vnd,
                "used_for_cost": not base_overridden,
            }
    piece_by_package: list[tuple[int, Decimal]] = []
    if (
        product is not None
        and bill_kg is not None
        and service in {SolarisService.AIR_STANDARD, SolarisService.AIR_EXPRESS}
    ):
        piece_by_package = _piece_fees(product, master, bill_kg, divisor, provisional)
    piece_vnd = sum((amount for _seq, amount in piece_by_package), ZERO)

    # --- Base allocation (VND, cents) ---------------------------------------------------------
    base_alloc: dict[int, Decimal] = dict.fromkeys(member_ids, ZERO)
    unallocated_vnd = ZERO
    rate_per_kg = base_vnd / bill_kg if base_vnd is not None and bill_kg else None
    if base_vnd is not None and weights_known:
        if method.residual_mode == "unallocated":
            for sid in member_ids:
                base_alloc[sid] = pe.to_cents(rate_per_kg * billable[sid])
            unallocated_vnd = base_vnd - sum(base_alloc.values(), ZERO)
            if unallocated_vnd < 0:
                provisional.append(
                    pe.Issue(
                        "customer_weight_above_bill",
                        "The customers' rounded weights add up to more than the vendor bill "
                        "weight; the unallocated line is negative.",
                    )
                )
        else:
            base_alloc = _by_weight(base_vnd, member_ids, billable)
    # The piece fee: vendor cost only (Louis Q4), split by weight among the customers in
    # that carton; when the carton's customers are not recorded, among all customers.
    piece_alloc: dict[int, Decimal] = dict.fromkeys(member_ids, ZERO)
    if piece_vnd > 0 and weights_known:
        for seq, amount in piece_by_package:
            inside = (
                [s for s in member_ids if package_of(s) == seq] if packages_known else member_ids
            )
            if not packages_known:
                provisional.append(
                    pe.Issue(
                        "piece_fee_package_members_unknown",
                        f"The piece fee of package {seq} is split over every customer of the "
                        "master: which customers are in which package is not recorded.",
                    )
                )
            if not inside:
                inside = member_ids
            for sid, share in _by_weight(amount, inside, billable).items():
                piece_alloc[sid] += share

    # --- Surcharges ------------------------------------------------------------------------------
    fees: dict[str, pe.VendorFee] = {}
    quote_vnd: dict[str, dict[int, Decimal]] = {}  # fee key -> member -> quoted VND
    why: dict[str, dict[int, str]] = {}
    classes: dict[str, str] = {}
    lines_by_rule: dict[tuple[str, int], list[tuple[pe.MemberInput, pe.FeeLineInput]]] = {}
    #: Lines of a rule the engine may not price: kept as an unpriced fee, as RC-UAT-25 does.
    blocked: list[tuple[pe.MemberInput, pe.FeeLineInput, pe.RuleView]] = []
    sea_lines: list[tuple[pe.MemberInput, pe.FeeLineInput, SeaRule]] = []
    for member in members:
        for line in member.fee_lines:
            line = _with_item_weight(line, rules.get((line.section, line.stt)))
            if line.section == SEA_VENDOR_SECTION:
                sea_rule = sea_rules.get(line.stt)
                if not is_sea or sea_rule is None:
                    blocking.append(
                        pe.Issue(
                            "fee_rule_wrong_service",
                            f"{member.public_id}: sea vendor surcharge {line.stt} applies only "
                            "to an active sea rule on a Sea master.",
                            member.shipment_id,
                            line.fee_line_id,
                        )
                    )
                    continue
                sea_lines.append((member, line, sea_rule))
                continue
            if is_sea:
                # v0.6: the Kango ocean surcharge list is inactive for sea.
                blocking.append(
                    pe.Issue(
                        "kango_sea_surcharge_inactive",
                        f"{member.public_id}: Kango's ocean surcharges are not used for sea "
                        "(v0.6); use the sea vendor's surcharges.",
                        member.shipment_id,
                        line.fee_line_id,
                    )
                )
                continue
            rule = rules.get((line.section, line.stt))
            if rule is None:
                blocking.append(
                    pe.Issue(
                        "fee_rule_missing",
                        f"{member.public_id}: surcharge {line.section} row {line.stt} is not in "
                        "the active tariff.",
                        member.shipment_id,
                        line.fee_line_id,
                    )
                )
                continue
            if rule.section != rule_section:
                blocking.append(
                    pe.Issue(
                        "fee_rule_wrong_origin",
                        f"{member.public_id}: '{rule.name}' belongs to another tariff section.",
                        member.shipment_id,
                        line.fee_line_id,
                    )
                )
                continue
            if (
                not rule.applies_to_canada
                or rule.pricing_status == SurchargePricingStatus.NOT_APPLICABLE_CANADA
            ):
                blocking.append(
                    pe.Issue(
                        "fee_rule_not_canada",
                        f"{member.public_id}: '{rule.name}' does not apply to Canada.",
                        member.shipment_id,
                        line.fee_line_id,
                    )
                )
                continue
            if rule.pricing_status not in pe.PRICEABLE_STATUSES:
                blocking.append(
                    pe.Issue(
                        f"fee_rule_{rule.pricing_status}",
                        f"{member.public_id}: '{rule.name}' is priced case by case by the vendor; "
                        "no price is guessed.",
                        member.shipment_id,
                        line.fee_line_id,
                    )
                )
                blocked.append((member, line, rule))
                continue
            lines_by_rule.setdefault((rule.section, rule.stt), []).append((member, line))

    waived = product is not None and product.customs_surcharges_waived
    explicit: dict[str, tuple[str, Decimal]] = {}

    def new_fee(key: str, rule: pe.RuleView, master_wide: bool, cls: str) -> pe.VendorFee:
        policy = policies.get((rule.section, rule.stt))
        # A rule's own markup policy wins; "default" (or none) means the v0.5 setting -- never
        # the RC-UAT-25 default markup row.
        markup = (
            policy
            if policy is not None and policy.markup_kind in {"pass_through", "fixed_cad", "percent"}
            else None
        )
        if markup is not None:
            explicit[key] = (markup.markup_kind, markup.markup_value)
        fee = pe.VendorFee(
            key=key,
            section=rule.section,
            stt=rule.stt,
            name=rule.name,
            scope=pe._effective_scope(rule, policy),
            master_wide=master_wide,
            vendor_fee_vnd=ZERO,
            markup_kind=markup.markup_kind if markup else method.markup_kind,
            markup_value=markup.markup_value if markup else method.markup_value,
        )
        fees[key] = fee
        quote_vnd[key] = {}
        why[key] = {}
        classes[key] = cls
        return fee

    def unpriced(fee: pe.VendorFee) -> None:
        """A fee the engine could not price: kept with its triggers and no amount."""
        fee.vendor_fee_vnd = None
        fee.cost_alloc_vnd = {}
        quote_vnd[fee.key] = {}

    for member, line, rule in blocked:
        fee = new_fee(f"D:{line.fee_line_id}", rule, False, "ITEM")
        fee.triggers[member.shipment_id] = [line.fee_line_id]
        fee.quantity = line.quantity
        unpriced(fee)

    for (section, stt), entries in lines_by_rule.items():
        rule = rules[(section, stt)]
        policy = policies.get((section, stt))
        cls = allocation_class(rule, policy)
        whole = cls in {"WHOLE_PACKAGE", "WHOLE_MASTER"}
        if whole and rule.basis not in {SurchargeBasis.PER_KG, SurchargeBasis.PER_SHIPMENT}:
            provisional.append(
                pe.Issue(
                    "allocation_class_basis_mismatch",
                    f"'{rule.name}' is classed {cls} but the tariff charges it "
                    f"{rule.basis}; priced per line, owner pays.",
                )
            )
            cls, whole = "ITEM", False

        if cls in {"ITEM", "CONFIRM", "NONE"}:
            for member, line in entries:
                fee = new_fee(f"D:{line.fee_line_id}", rule, False, cls)
                fee.triggers.setdefault(member.shipment_id, []).append(line.fee_line_id)
                fee.quantity += line.quantity
                if cls == "NONE" or waived:
                    amount = ZERO
                else:
                    amount, refusal = pe._line_vendor_fee(
                        rule, line, False, bill_kg, 1, provisional
                    )
                    if refusal:
                        blocking.append(
                            pe.Issue(
                                "fee_unpriced",
                                f"{member.public_id}: {refusal}",
                                member.shipment_id,
                                line.fee_line_id,
                            )
                        )
                        unpriced(fee)
                        continue
                if cls == "CONFIRM":
                    provisional.append(
                        pe.Issue(
                            "allocation_basis_unconfirmed",
                            f"'{rule.name}': Kango does not say whether it charges the item or "
                            "the parcel; charged to the item owner until confirmed.",
                            member.shipment_id,
                            line.fee_line_id,
                        )
                    )
                fee.vendor_fee_vnd = amount
                fee.cost_alloc_vnd = {member.shipment_id: amount}
                quote_vnd[fee.key] = {member.shipment_id: amount}
                why[fee.key] = {member.shipment_id: "item owner: 100%"}
                if (
                    rule.basis == SurchargeBasis.MANUAL_AMOUNT
                    and line.customer_price_cad is not None
                ):
                    fee.customer_price_cad = pe.to_cents(line.customer_price_cad)
                    fee.markup_kind, fee.markup_value = pe.MANUAL_PRICE_KIND, ZERO
            continue

        if whole and cls == "WHOLE_PACKAGE" and not single_package and packages_known:
            # One charge per package that holds a trigger, on that package's weight, shared
            # (2/3 rule) among that package's customers.
            for p in package_rows:
                inside = [
                    (m, ln) for m, ln in entries if package_of(m.shipment_id) == p["sequence"]
                ]
                if not inside:
                    continue
                fee = new_fee(f"M:{section}:{stt}:{p['sequence']}", rule, True, cls)
                for member, line in inside:
                    fee.triggers.setdefault(member.shipment_id, []).append(line.fee_line_id)
                amount, refusal = (
                    (ZERO, None)
                    if waived
                    else pe._line_vendor_fee(
                        rule, inside[0][1], True, p["billed_kg"], 1, provisional
                    )
                )
                if refusal:
                    blocking.append(
                        pe.Issue(
                            "fee_unpriced",
                            f"{inside[0][0].public_id}: {refusal}",
                            inside[0][0].shipment_id,
                            inside[0][1].fee_line_id,
                        )
                    )
                    unpriced(fee)
                    continue
                fee.vendor_fee_vnd = amount
                if weights_known:
                    ids = p["members"]
                    fee.cost_alloc_vnd = pe._cost_split(
                        fee, ids, {s: _frac(billable[s]) for s in ids}, settings.trigger_share
                    )
                    triggers = [s for s in ids if s in fee.triggers]
                    for sid in fee.cost_alloc_vnd:
                        why[fee.key][sid] = f"package {p['sequence']}: " + (
                            "only customer: 100%"
                            if len(ids) == 1
                            else "2/3 rule: sole trigger"
                            if len(triggers) == 1 and sid in triggers
                            else f"2/3 rule: not a trigger, 1/3 ÷ {len(ids) - 1} equally"
                            if len(triggers) == 1
                            else f"{len(triggers)} triggers: by weight"
                        )
                    quote_vnd[fee.key] = (
                        _by_weight(amount, triggers, billable)
                        if method.pkg_surcharge_billing == "triggers_only"
                        else dict(fee.cost_alloc_vnd)
                    )
            continue

        if cls == "WHOLE_MASTER" and rule.basis == SurchargeBasis.PER_SHIPMENT and not is_sea:
            # Per lot (HCM-47 fumigation; DEC-0276, Louis 2026-11-06): Kango charges once for
            # the whole shipment (every master piece); every customer with the item is billed
            # the full fee. The cost is shared among those customers by weight.
            fee = new_fee(f"M:{section}:{stt}", rule, True, "LOT")
            for member, line in entries:
                fee.triggers.setdefault(member.shipment_id, []).append(line.fee_line_id)
            triggers = [s for s in member_ids if s in fee.triggers]
            amount = ZERO if waived else pe.to_cents(rule.unit_price_vnd or ZERO)
            fee.vendor_fee_vnd = amount
            fee.quantity = Decimal(1)
            if weights_known:
                fee.cost_alloc_vnd = _by_weight(amount, triggers, billable)
            quote_vnd[fee.key] = dict.fromkeys(triggers, amount)
            for sid in triggers:
                why[fee.key][sid] = (
                    "Kango once for the whole shipment"
                    + (
                        f", cost shared by weight among {len(triggers)} customers"
                        if len(triggers) > 1
                        else ", 100% this customer"
                    )
                    + " | quote: full fee to each customer with the item"
                )
            continue

        if whole:
            fee = new_fee(f"M:{section}:{stt}", rule, True, cls)
            for member, line in entries:
                fee.triggers.setdefault(member.shipment_id, []).append(line.fee_line_id)
            on_kg = package_kg if cls == "WHOLE_PACKAGE" else bill_kg
            if cls == "WHOLE_PACKAGE" and not single_package:
                provisional.append(
                    pe.Issue(
                        "full_carton_uses_master_weight",
                        f"'{rule.name}' is charged on the whole package; the master has "
                        f"{len(package_rows)} packages and which customers are in which is not "
                        "recorded, so the master's bill weight is used.",
                    )
                )
            if waived:
                amount, refusal = ZERO, None
            else:
                amount, refusal = pe._line_vendor_fee(
                    rule, entries[0][1], True, on_kg, 1, provisional
                )
            if refusal:
                first_member, first_line = entries[0]
                blocking.append(
                    pe.Issue(
                        "fee_unpriced",
                        f"{first_member.public_id}: {refusal}",
                        first_member.shipment_id,
                        first_line.fee_line_id,
                    )
                )
                unpriced(fee)
                continue
            fee.vendor_fee_vnd = amount
            if weights_known:
                fee.cost_alloc_vnd = pe._cost_split(
                    fee,
                    member_ids,
                    {s: _frac(billable[s]) for s in member_ids},
                    settings.trigger_share,
                )
                triggers = [s for s in member_ids if s in fee.triggers]
                for sid in fee.cost_alloc_vnd:
                    if len(member_ids) == 1:
                        why[fee.key][sid] = "only customer: 100%"
                    elif len(triggers) == 1:
                        why[fee.key][sid] = (
                            "2/3 rule: sole trigger"
                            if sid in triggers
                            else f"2/3 rule: not a trigger, 1/3 ÷ {len(member_ids) - 1} equally"
                        )
                    else:
                        why[fee.key][sid] = f"{len(triggers)} triggers: by weight"
                if method.pkg_surcharge_billing == "triggers_only":
                    quote_vnd[fee.key] = _by_weight(amount, triggers, billable)
                else:
                    quote_vnd[fee.key] = dict(fee.cost_alloc_vnd)
            continue

        # PARCEL (DEC-0276, Louis 2026-11-06): Kango charges once per master piece (kiện)
        # that holds the item type, the band on the total kg of that type in the piece; each
        # customer with the item is quoted the full fee, band on its own kg of that type.
        # Batteries (HCM rows 2-3) work the same way (replaces DEC-0275's heaviest item).
        _price_per_piece(
            rule, entries, cls, waived, bill_kg, provisional, blocking, package_of,
            single_package, billable, new_fee, unpriced, quote_vnd, why, method,
        )  # fmt: skip
        continue

    # Sea vendor surcharges (v0.7, Louis 2026-11-03 PM; DEC-0260). COST: the vendor's minimum
    # once per package per type, max(Σ rate × item kg of that type's owners in the package,
    # minimum), split among them by item kg. QUOTE: per customer per type, max(rate × own
    # item kg, minimum). Quote − cost is surcharge margin. A customer whose package is not
    # recorded on a master with several packages: the whole master counts as one package
    # (package 0), with a warning.
    by_package: dict[tuple[int, int | None], list[tuple[pe.MemberInput, pe.FeeLineInput]]] = {}
    for member, line, sea_rule in sea_lines:
        if line.weight_kg is None or line.weight_kg <= 0:
            blocking.append(
                pe.Issue(
                    "fee_unpriced",
                    f"{member.public_id}: '{sea_rule.name}' is charged per item kilogram; enter "
                    "the item's weight.",
                    member.shipment_id,
                    line.fee_line_id,
                )
            )
            continue
        seq = package_of(member.shipment_id)
        if seq is None:
            seq = 0
            if not any(i.code == "sea_package_unknown" for i in provisional):
                provisional.append(
                    pe.Issue(
                        "sea_package_unknown",
                        "Which package each sea customer is in is not recorded: the sea "
                        "surcharge minimum is applied once for the whole master as one package.",
                    )
                )
        by_package.setdefault((sea_rule.rule_id, seq), []).append((member, line))
    for (rule_id, seq), entries in sorted(by_package.items()):
        sea_rule = sea_rules[rule_id]
        fee = pe.VendorFee(
            key=f"S:{rule_id}:{seq}",
            section=SEA_VENDOR_SECTION,
            stt=rule_id,
            name=sea_rule.name,
            scope=SurchargeScope.FULL_CARTON,
            master_wide=False,
            vendor_fee_vnd=ZERO,
            markup_kind=method.markup_kind,
            markup_value=method.markup_value,
        )
        fees[fee.key] = fee
        classes[fee.key] = "SEA_ITEM_MIN"
        why[fee.key] = {}
        kg: dict[int, Decimal] = {}
        for member, line in entries:
            fee.triggers.setdefault(member.shipment_id, []).append(line.fee_line_id)
            fee.quantity += line.quantity
            kg[member.shipment_id] = kg.get(member.shipment_id, ZERO) + line.weight_kg
        owners = [s for s in member_ids if s in kg]
        total_kg = sum(kg.values(), ZERO)
        total = pe.to_cents(sea_rule.rate_vnd_per_kg * total_kg)
        where = f"package {seq}" if seq else "whole master (package not recorded)"
        minimum = pe.to_cents(sea_rule.min_vnd_per_package)
        if total >= minimum:
            alloc = {s: pe.to_cents(sea_rule.rate_vnd_per_kg * kg[s]) for s in owners}
            fee.vendor_fee_vnd = sum(alloc.values(), ZERO)
            reason = (
                f"{where}: COST {total_kg} kg × {sea_rule.rate_vnd_per_kg} = {total} ≥ min "
                f"{minimum} → actual"
            )
        else:
            fee.vendor_fee_vnd = minimum
            alloc = _by_weight(minimum, owners, kg)
            reason = (
                f"{where}: COST {total_kg} kg × {sea_rule.rate_vnd_per_kg} = {total} < min "
                f"{minimum} → minimum once, split by item kg"
            )
        fee.cost_alloc_vnd = alloc
        quoted: dict[int, Decimal] = {}
        for sid in owners:
            own = pe.to_cents(sea_rule.rate_vnd_per_kg * kg[sid])
            quoted[sid] = max(own, minimum)
            why[fee.key][sid] = (
                f"{reason}, share {kg[sid]} / {total_kg} kg = {alloc[sid]} | QUOTE own "
                f"{kg[sid]} kg × {sea_rule.rate_vnd_per_kg} = {own}"
                + (f" < min → {minimum}" if own < minimum else f" ≥ min → {own}")
            )
        quote_vnd[fee.key] = quoted  # at cost, minimum per customer (markup 0)

    # Piece fee as its own line: vendor cost only, never quoted (Louis Q4).
    if piece_vnd > 0:
        piece = pe.VendorFee(
            key="PIECE",
            section="piece",
            stt=0,
            name="Piece fee: carton under the minimum weight",
            scope=SurchargeScope.FULL_MASTER,
            master_wide=True,
            vendor_fee_vnd=piece_vnd,
        )
        piece.cost_alloc_vnd = piece_alloc
        fees["PIECE"] = piece
        quote_vnd["PIECE"] = {}
        why["PIECE"] = {
            s: "piece fee (vendor cost only): carton under the minimum, by weight"
            for s, v in piece_alloc.items()
            if v > 0
        }
        classes["PIECE"] = "PIECE"

    # --- FX -------------------------------------------------------------------------------------
    for source in {method.fx_source_cost, method.fx_source_quote}:
        if source != "kango_fixed":
            if fx is None:
                blocking.append(pe.Issue("fx_missing", "No verified Vietcombank rate is on file."))
            elif fx.freshness != "live":
                blocking.append(
                    pe.Issue(
                        "fx_stale",
                        "The latest Vietcombank rate is stale; finalising waits for a fresh one.",
                    )
                )
    fx_cost = _fx_rate(method.fx_source_cost, method, fx)
    fx_quote = _fx_rate(method.fx_source_quote, method, fx)

    # --- Per customer: cost, quote, profit --------------------------------------------------------
    fee_cost: dict[int, Decimal] = dict.fromkeys(member_ids, ZERO)
    for fee in fees.values():
        for sid, amount in fee.cost_alloc_vnd.items():
            fee_cost[sid] += amount
    cost_vnd = {sid: base_alloc[sid] + fee_cost[sid] for sid in member_ids}
    for sid in member_ids:
        result_members[sid].base_cost_vnd = base_alloc[sid]
        result_members[sid].surcharge_cost_vnd = fee_cost[sid]
    bill_vnd = (
        base_vnd + sum((f.vendor_fee_vnd or ZERO for f in fees.values()), ZERO)
        if base_vnd is not None
        else None
    )

    details: dict[int, dict] = {}
    totals = {"cost_cad": None, "quote_cad": None, "profit_cad": None, "surcharge_margin_cad": None}
    bill_cad = unallocated_cad = None
    if fx_cost is not None and bill_vnd is not None and weights_known:
        cost_cad = {sid: pe.to_cents(cost_vnd[sid] / fx_cost) for sid in member_ids}
        bill_cad = pe.to_cents(bill_vnd / fx_cost)
        unallocated_cad = pe.to_cents(unallocated_vnd / fx_cost)
        diff = bill_cad - unallocated_cad - sum(cost_cad.values(), ZERO)
        if diff and member_ids:
            biggest = max(member_ids, key=lambda s: (cost_vnd[s], -member_ids.index(s)))
            cost_cad[biggest] += diff
        for fee in fees.values():
            if not fee.cost_alloc_vnd:
                continue
            total = pe.to_cents((fee.vendor_fee_vnd or ZERO) / fx_cost)
            positive = [k for k, v in fee.cost_alloc_vnd.items() if v > 0]
            fee.cost_alloc_cad = (
                pe.allocate(total, positive, [_frac(fee.cost_alloc_vnd[k]) for k in positive])
                if positive and total > 0
                else {}
            )
            for k in fee.cost_alloc_vnd:
                fee.cost_alloc_cad.setdefault(k, ZERO)

        for sid in member_ids:
            res = result_members[sid]
            w = billable[sid] if method.threshold_basis == "customer" else (bill_kg or ZERO)
            rate: Decimal | None
            if service == SolarisService.AIR_STANDARD:
                high = w >= method.air_std_threshold_kg
                rate = method.air_std_rate_high_cad if high else method.air_std_rate_low_cad
                sign = "≥" if high else "<"
                rate_why = (
                    f"{method.threshold_basis} {w} kg {sign} {method.air_std_threshold_kg} kg"
                )
            elif service == SolarisService.SEA:
                rate, rate_why = method.sea_rate_cad, "Sea rate (Settings)"
            elif service == SolarisService.UPS:
                band = next(
                    (b for b in ups_bands if w >= b.from_kg and (b.to_kg is None or w <= b.to_kg)),
                    None,
                )
                rate = manual.sell_cad_per_kg or (band.sell_cad_per_kg if band else None)
                rate_why = "UPS: entered manually (table to come)"
            elif service == SolarisService.AIR_CARGO:
                rate, rate_why = manual.sell_cad_per_kg, "Air Cargo: entered manually"
            elif manual.sell_cad_per_kg is not None:
                rate, rate_why = manual.sell_cad_per_kg, "Kango Air Express: entered by staff"
            else:
                rate = method.air_express_rate_cad
                rate_why = "Kango Air Express: default rate (Settings → Pricing)"
            freight_cad = pe.to_cents(billable[sid] * rate) if rate is not None else None

            weighted_vnd = Fraction(0)
            fixed_cad = ZERO
            manual_cad = ZERO
            line_weights: dict[str, Fraction] = {}
            own_cost = own_quote = pkg_cost = ZERO
            for key, fee in fees.items():
                if sid not in quote_vnd.get(key, {}) and sid not in fee.cost_alloc_vnd:
                    continue
                q = quote_vnd.get(key, {}).get(sid, ZERO)
                if classes[key] in {"WHOLE_PACKAGE", "WHOLE_MASTER", "PIECE"}:
                    pkg_cost += fee.cost_alloc_vnd.get(sid, ZERO)
                else:
                    own_cost += fee.cost_alloc_vnd.get(sid, ZERO)
                    own_quote += q
                if fee.customer_price_cad is not None:
                    manual_cad += fee.customer_price_cad
                    continue
                kind, value = _line_markup(key, explicit, method)
                factor = Fraction(1) + (_frac(value) / 100 if kind == "percent" else 0)
                billed_line = (
                    sid in fee.triggers
                    or method.pkg_surcharge_billing != "triggers_only"
                    or classes[key] not in {"WHOLE_PACKAGE", "WHOLE_MASTER"}
                )
                if kind == "fixed_cad" and key != "PIECE" and billed_line and q >= 0:
                    fixed_cad += value
                weighted_vnd += _frac(q) * factor
                line_weights[key] = _frac(q) * factor / _frac(fx_quote) + (
                    _frac(value) if kind == "fixed_cad" and key != "PIECE" and billed_line else 0
                )
            surcharge_quote_cad = None
            if fx_quote is not None:
                surcharge_quote_cad = (
                    pe.to_cents(
                        Decimal(weighted_vnd.numerator)
                        / Decimal(weighted_vnd.denominator)
                        / fx_quote
                    )
                    + fixed_cad
                    + manual_cad
                )
                # Spread the customer's surcharge quote over its lines (QuoteLine revenue).
                spread_total = surcharge_quote_cad - manual_cad
                keys = [k for k, wgt in line_weights.items() if wgt > 0]
                alloc = (
                    pe.allocate(spread_total, keys, [line_weights[k] for k in keys])
                    if keys and spread_total > 0
                    else {}
                )
                for key, fee in fees.items():
                    if (
                        sid in fee.triggers
                        or sid in fee.cost_alloc_vnd
                        or sid in quote_vnd.get(key, {})
                    ):
                        if fee.customer_price_cad is not None:
                            fee.revenue_alloc_cad[sid] = fee.customer_price_cad
                        else:
                            fee.revenue_alloc_cad[sid] = alloc.get(key, ZERO)
            surcharge_cost_exact = (own_cost + pkg_cost) / fx_cost
            quote_cad = (
                freight_cad + surcharge_quote_cad
                if freight_cad is not None and surcharge_quote_cad is not None
                else None
            )
            res.surcharge_cost_cad = sum(
                (f.cost_alloc_cad.get(sid, ZERO) for f in fees.values()), ZERO
            )
            res.base_cost_cad = cost_cad[sid] - res.surcharge_cost_cad
            res.surcharge_revenue_cad = surcharge_quote_cad
            details[sid] = {
                "public_id": res.public_id,
                "cw_kg": billable[sid],
                "base_vnd": base_alloc[sid],
                "own_surcharge_cost_vnd": own_cost,
                "own_surcharge_quote_vnd": own_quote,
                "package_surcharge_vnd": pkg_cost,
                "cost_vnd": cost_vnd[sid],
                "cost_cad": cost_cad[sid],
                "rate_cad_kg": rate,
                "rate_why": rate_why,
                "freight_cad": freight_cad,
                "surcharge_quote_cad": surcharge_quote_cad,
                "quote_cad": quote_cad,
                "surcharge_margin_cad": (
                    pe.to_cents(surcharge_quote_cad - surcharge_cost_exact) + ZERO  # no "-0.00"
                    if surcharge_quote_cad is not None
                    else None
                ),
                "profit_cad": quote_cad - cost_cad[sid] if quote_cad is not None else None,
                "rules": [
                    f"{fees[k].section}:{fees[k].stt} {classes[k]}: {why[k][sid]}"
                    for k in fees
                    if sid in why.get(k, {})
                ],
            }
        # Per fee: the customer charge before and after markup (the RC-UAT-25 fields).
        for key, fee in fees.items():
            if fee.customer_price_cad is not None:
                fee.customer_base_cad = fee.customer_total_cad = fee.customer_price_cad
            elif fee.vendor_fee_vnd is None:
                fee.revenue_alloc_cad = {}
            elif fx_quote is not None:
                quoted = sum(quote_vnd.get(key, {}).values(), ZERO)
                fee.customer_base_cad = pe.to_cents(quoted / fx_quote)
                fee.customer_total_cad = sum(fee.revenue_alloc_cad.values(), ZERO)
        if all(d["quote_cad"] is not None for d in details.values()):
            totals["quote_cad"] = sum((d["quote_cad"] for d in details.values()), ZERO)
            totals["profit_cad"] = totals["quote_cad"] - bill_cad
        totals["cost_cad"] = bill_cad
        if all(d["surcharge_margin_cad"] is not None for d in details.values()):
            totals["surcharge_margin_cad"] = sum(
                (d["surcharge_margin_cad"] for d in details.values()), ZERO
            )

    reconciled = None
    if bill_vnd is not None and weights_known:
        reconciled = sum(cost_vnd.values(), ZERO) + unallocated_vnd == bill_vnd and (
            bill_cad is None
            or sum((d["cost_cad"] for d in details.values()), ZERO) + unallocated_cad == bill_cad
        )
        if not reconciled:
            blocking.append(
                pe.Issue(
                    "allocation_not_reconciled", "Σ customer costs do not equal the vendor bill."
                )
            )

    method_detail = {
        "method": "confirmed",
        "method_version": METHOD_VERSION,
        "service": service,
        "fx": {
            "cost_source": method.fx_source_cost,
            "cost_rate_vnd": fx_cost,
            "quote_source": method.fx_source_quote,
            "quote_rate_vnd": fx_quote,
            "vcb_snapshot_id": fx.snapshot_id if fx is not None else None,
        },
        "bill_kg": bill_kg,
        "bill_rounding": method.vendor_bill_rounding,
        "packages": package_rows,
        "base_vnd": base_vnd,
        "base_basis": base_basis,
        "rate_per_kg_vnd": rate_per_kg,
        "piece_vnd": piece_vnd,
        "piece_by_package": [{"sequence": q, "vnd": a} for q, a in piece_by_package],
        "express_reference": express_reference,
        "packages_known": packages_known,
        "unallocated_vnd": unallocated_vnd,
        "unallocated_cad": unallocated_cad,
        "bill_vnd": bill_vnd,
        "bill_cad": bill_cad,
        "lines": [
            {
                "key": k,
                "section": f.section,
                "stt": f.stt,
                "name": f.name,
                "class": classes[k],
                "class_label": CLASS_LABELS.get(classes[k], classes[k]),
                "vendor_vnd": f.vendor_fee_vnd,
                "cost_alloc_vnd": dict(f.cost_alloc_vnd),
                "quote_vnd": dict(quote_vnd.get(k, {})),
                "why": dict(why.get(k, {})),
            }
            for k, f in fees.items()
        ],
        "members": details,
        "totals": totals,
        "reconciled": reconciled,
        "settings": {
            "residual_mode": method.residual_mode,
            "pkg_surcharge_billing": method.pkg_surcharge_billing,
            "parcel_band_cost_basis": method.parcel_band_cost_basis,
            "parcel_quote_mode": method.parcel_quote_mode,
            "markup_kind": method.markup_kind,
            "markup_value": method.markup_value,
            "threshold_basis": method.threshold_basis,
        },
    }
    uses_vcb = method.fx_source_cost != "kango_fixed" or method.fx_source_quote != "kango_fixed"
    return pe.Estimate(
        product_code=product.code if product is not None else None,
        zone=zone,
        delivery_postal_code=delivery.postal_code,
        master_chargeable_kg=bill_kg,
        base_freight_vnd=base_vnd,
        base_freight_cad=pe.to_cents(base_vnd / fx_cost)
        if base_vnd is not None and fx_cost
        else None,
        fees=list(fees.values()),
        members=result_members,
        fx_snapshot_id=fx.snapshot_id if fx is not None and uses_vcb else None,
        blocking=blocking,
        provisional=provisional,
        piece_fee_vnd=ZERO,
        method="confirmed",
        method_detail=method_detail,
    )


def is_battery_rule(rule: pe.RuleView | None) -> bool:
    """Kango's "Pin kèm thiết bị nhỏ" rows (battery with a small device, HCM rows 2 and 3, one
    rule with the OD-59 tiers). Priced per master piece like nail polish (DEC-0276); its
    groups read the weight to 0.1 kg (OD-59), not the OD-50 rounding."""
    if rule is None or rule.pricing_status != SurchargePricingStatus.TIERED:
        return False
    name = " ".join(pe_fold(rule.name).split())
    return "pin kem thiet bi nho" in name


def pe_fold(text: str) -> str:
    from app.pricing.kango_semantics import fold  # noqa: PLC0415

    return fold(text or "")


def _with_item_weight(line: pe.FeeLineInput, rule: pe.RuleView | None) -> pe.FeeLineInput:
    """A line with no weight of its own takes the weight entered on its item (owner,
    2026-11-05; DEC-0275) when the rule is charged per kilogram, is a sea vendor surcharge
    (per item kg), or is the battery rule (band on the battery item's weight). A weight typed
    on the line always wins."""
    if line.weight_kg is not None or line.item_kg is None or line.item_kg <= 0:
        return line
    if line.section == SEA_VENDOR_SECTION:
        return replace(line, weight_kg=line.item_kg)
    if rule is None:
        return line
    # Per-kg rules are charged on the item's kilograms under the confirmed method
    # (data/surcharge_allocation_rules.csv: "rate × item kg", ITEM_OWNER); a rule classed for
    # the whole package or master reads that weight instead and ignores the line's.
    if rule.basis == SurchargeBasis.PER_KG or rule.pricing_status == SurchargePricingStatus.TIERED:
        return replace(line, weight_kg=line.item_kg)
    return line


def _price_per_piece(
    rule, entries, cls, waived, bill_kg, provisional, blocking, package_of, single_package,
    billable, new_fee, unpriced, quote_vnd, why, method,
) -> None:  # fmt: skip
    """A fee Kango charges per master piece (kiện): DEC-0276, Louis 2026-11-06.

    COST: once per master piece that holds the item type. A banded fee (sơn móng tay, nước
    hoa, battery) picks its band on the **total kg of that item type in the piece**; a flat
    fee is the flat amount. The cost is shared among the customers with the item by their kg
    of that type. QUOTE: each customer with the item pays the full fee, the band on its own
    kg of that type. Weights are rounded by OD-50 before the band (5.1 kg → 5.0), except the
    battery rows, whose groups read the weight to 0.1 kg (OD-59: 3.6 kg → 700,000).

    The item kg is the weight on the fee line or its item; a line with no item (older
    bookings) reads the customer's small box holding it. A banded fee with neither asks for
    the item's weight (nothing is guessed). A flat fee needs no weight: its cost is then
    shared by the customers' billable weights.
    A customer not placed in a piece on a multi-piece master: the whole master counts as one
    piece (piece 0), with a warning.
    """
    tiered = rule.pricing_status == SurchargePricingStatus.TIERED
    battery = is_battery_rule(rule)
    compound = rule.basis == SurchargeBasis.COMPOUND
    manual_price = next(
        (ln.manual_unit_price_vnd for _m, ln in entries if ln.manual_unit_price_vnd is not None),
        None,
    )

    def refuse(member, line, reason):
        blocking.append(
            pe.Issue("fee_unpriced", f"{member.public_id}: {reason}", member.shipment_id,
                     line.fee_line_id)
        )  # fmt: skip

    def band_kg(kg: Decimal) -> Decimal:
        return kg if battery else cw.round_chargeable(kg)[0]

    def price(weight, quantity, template):
        if waived:
            return ZERO, None
        probe = replace(
            template,
            weight_kg=weight,
            quantity=quantity,
            manual_unit_price_vnd=template.manual_unit_price_vnd or manual_price,
        )
        return pe._line_vendor_fee(rule, probe, False, bill_kg, 1, provisional)

    groups: dict[int, list[tuple[pe.MemberInput, pe.FeeLineInput]]] = {}
    for member, line in entries:
        seq = package_of(member.shipment_id)
        if single_package:
            seq = 1
        elif seq is None:
            seq = 0
            if not any(i.code == "piece_not_recorded" for i in provisional):
                provisional.append(
                    pe.Issue(
                        "piece_not_recorded",
                        "A customer with a per-piece surcharge is not placed in a master piece: "
                        "the whole master is counted as one piece until it is placed.",
                        member.shipment_id,
                    )
                )
        groups.setdefault(seq, []).append((member, line))

    top = None
    if tiered and rule.tiers and all(t.weight_to_kg is not None for t in rule.tiers):
        top = max(t.weight_to_kg for t in rule.tiers)

    for seq, group in sorted(groups.items()):
        fee = new_fee(f"P:{rule.section}:{rule.stt}:{seq}", rule, False, cls)
        own: dict[int, Decimal] = {}
        qty: dict[int, Decimal] = {}
        first: dict[int, tuple[pe.MemberInput, pe.FeeLineInput]] = {}
        for member, line in group:
            sid = member.shipment_id
            fee.triggers.setdefault(sid, []).append(line.fee_line_id)
            first.setdefault(sid, (member, line))
            qty[sid] = qty.get(sid, ZERO) + line.quantity
            if line.weight_kg is not None and line.weight_kg > 0:
                own[sid] = own.get(sid, ZERO) + line.weight_kg
        for sid in first:
            if sid in own:
                continue
            # A line tied to an item asks for the item's weight; an older line with no item
            # keeps the v0.5 reading (the customer's small box holding it).
            boxes = [
                ln.box_kg
                for m, ln in group
                if m.shipment_id == sid and ln.box_kg and ln.item_id is None
            ]
            if boxes:
                own[sid] = max(boxes)
        triggers = list(first)
        fee.quantity = sum(qty.values(), ZERO) if compound else Decimal(1)
        missing = [s for s in triggers if s not in own]
        if tiered and missing:
            for sid in missing:
                refuse(*first[sid], f"'{rule.name}' is banded on the item's weight; enter the "
                       "item's weight (kg).")  # fmt: skip
            unpriced(fee)
            continue
        total_kg = sum(own.values(), ZERO) if own else None
        cost_kg = band_kg(total_kg) if tiered and total_kg else None
        if top is not None and cost_kg is not None and cost_kg > top:
            provisional.append(
                pe.Issue(
                    "piece_type_over_top_band",
                    f"'{rule.name}': {cost_kg} kg of this item in one master piece is above "
                    f"Kango's top band ({top} kg); confirm Kango's price, or pack it in "
                    "another piece.",
                )
            )
        template = first[triggers[0]][1]
        amount, failed = price(cost_kg, fee.quantity, template)
        if failed:
            refuse(first[triggers[0]][0], template, failed)
            unpriced(fee)
            continue
        fee.vendor_fee_vnd = amount
        fee.cost_alloc_vnd = (
            {triggers[0]: amount}
            if len(triggers) == 1
            else _by_weight(
                amount, triggers,
                own if len(own) == len(triggers) and all(own.values())
                else {s: billable.get(s, Decimal(1)) for s in triggers},
            )
        )  # fmt: skip
        where = f"piece {seq}" if seq else "the whole master (piece not recorded)"
        ok = True
        for sid in triggers:
            member, line = first[sid]
            if method.parcel_quote_mode == "share":
                quoted = fee.cost_alloc_vnd.get(sid, ZERO)
            else:
                mine_kg = band_kg(own[sid]) if tiered else None
                quoted, failed = price(mine_kg, qty[sid] if compound else Decimal(1), line)
                if failed:
                    refuse(member, line, failed)
                    ok = False
                    break
            quote_vnd[fee.key][sid] = quoted
            cost_part = f"band on {cost_kg} kg of this item in the piece" if tiered else "flat fee"
            why[fee.key][sid] = (
                f"Kango once for {where} ({cost_part})"
                + (
                    f", cost shared by item kg among {len(triggers)} customers"
                    if len(triggers) > 1
                    else ", 100% this customer"
                )
                + (
                    f" | quote: full fee, band on own {band_kg(own[sid])} kg"
                    if tiered
                    else " | quote: full fee"
                )
            )
        if not ok:
            unpriced(fee)


def _line_markup(
    key: str, explicit: dict[str, tuple[str, Decimal]], method: MethodSettings
) -> tuple[str, Decimal]:
    """A rule's own policy (pass_through / fixed_cad / percent) wins; otherwise the v0.5
    markup setting. The piece fee always takes the setting."""
    if key in explicit:
        kind, value = explicit[key]
        return ("none", ZERO) if kind == "pass_through" else (kind, value)
    return method.markup_kind, method.markup_value


def _piece_fees(
    product: pe.ProductView,
    master: pe.MasterInput,
    bill_kg: Decimal,
    divisor: int,
    provisional: list[pe.Issue],
) -> list[tuple[int, Decimal]]:
    """The Kango piece fee per carton (v0.6, Louis Q4): on a lot of 21 kg and over
    (inclusive), each carton whose rounded chargeable weight is under the minimum pays the
    product's fee (300,000 Ground / 700,000 Express). Same reading as ``engine._piece_fee``,
    with the carton each fee belongs to."""
    total = pe._piece_fee(product, master, bill_kg, divisor, provisional)
    if total <= 0 or product.piece_min_fee_vnd is None:
        return []
    out: list[tuple[int, Decimal]] = []
    for seq, carton in enumerate(master.cartons, start=1):
        if carton.weight_kg is None:
            continue
        vol = cw.volumetric_weight(carton.length_cm, carton.width_cm, carton.height_cm, divisor)
        weight = max(carton.weight_kg, vol) if vol is not None else carton.weight_kg
        if cw.round_chargeable(weight)[0] < product.piece_min_weight_kg:
            out.append((seq, product.piece_min_fee_vnd))
    return out
