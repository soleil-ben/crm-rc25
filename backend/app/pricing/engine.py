"""The air pricing engine: vendor cost, allocation, FX and the customer quote (Phase 13C).

**Pure.** Dataclasses in, dataclasses out. No database, no clock, no settings import; the
service (``app/services/pricing_service.py``) loads the inputs and persists the result. Every
figure is ``Decimal``; amounts are quantized to 0.01 only at the line where a currency
amount is produced, and every split is a largest-remainder allocation so the parts always
add up to the whole (handoff section 5: "reconcile exactly with deterministic residual cent
handling").

What it computes, for one consolidation and its member shipments:

1. **Vendor base freight** at the master's chargeable weight, in the zone of the vendor's
   delivery point (OD-46: L5A 3K6 for every consolidation). Up to 20.5 kg the per-bill band;
   above it the per-kg tier times the weight.
2. **Vendor surcharges** from the fee lines staff attached to items (never from a keyword,
   handoff owner decision 4). A rule whose scope is the full carton, the full master or the
   whole shipment is **one vendor charge per consolidation** however many members trigger it
   (SC-09); a per-unit / per-piece / per-pair / per-box / per-bottle rule is charged on each
   triggering line.
3. **Cost allocation** to members: base freight by member chargeable-weight share; a
   master-wide surcharge by the trigger rule (one trigger of several: the configured share,
   2/3 by default, to the trigger and the rest split equally; two or more triggers: by weight
   among triggers; one member: all of it); a direct surcharge to its own shipment.
4. **FX**: cost at the bank's cash-buying rate, customer surcharge at the selling rate
   (handoff owner decision 10).
5. **Customer revenue**: billable weight × selling rate, plus each triggering shipment's
   share of the customer surcharge (one trigger: all of it; several: by weight among them),
   after the rule's markup (OD-44). Non-triggering shipments are never billed a surcharge.
   A line quoted case by case (``manual_amount``, DEC-0228) is billed at the customer price
   staff entered, with no conversion and no markup; its cost is the entered VND at the buy rate.

What it refuses, as **blocking issues** that stop finalisation, never as guesses: an
unpriced, conflicting (OD-47: pharmaceuticals) or Canada-excluded rule; a tier the weight
falls outside; a missing weight; a delivery postal code with no zone or no beyond rate; no
exchange-rate snapshot, or a stale one. What it assumes on the record, as **provisional
flags** that do not block: master weight used for a full-carton rule when the master has
several cartons, the piece-minimum fee not evaluated when per-carton weights are not
recorded, a manual-quote rule still at its prefilled minimum (OD-56), and the pending
pricing defaults (OD-48). Weights are rounded by the owner's rule (OD-50,
``chargeable_weight.round_chargeable``) for the master, each member, each carton and each
surcharge weight; the band matching the rounded weight sets the price (OD-51).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

from app.core.enums import (
    BeyondRateStatus,
    SurchargeBasis,
    SurchargePricingStatus,
    SurchargeScope,
    TariffLastMile,
)
from app.pricing import chargeable_weight as cw

CENT = Decimal("0.01")
ZERO = Decimal(0)

#: Scopes charged once per consolidation, allocated by the trigger rule.
MASTER_WIDE_SCOPES = frozenset(
    {SurchargeScope.FULL_CARTON, SurchargeScope.FULL_MASTER, SurchargeScope.PER_SHIPMENT}
)
#: Statuses the engine may put a number on.
PRICEABLE_STATUSES = frozenset(
    {
        SurchargePricingStatus.PRICED,
        SurchargePricingStatus.TIERED,
        SurchargePricingStatus.FREE,
        SurchargePricingStatus.MANUAL_QUOTE,
    }
)


# --- Inputs --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Bracket:
    kind: str  # per_bill | per_kg
    zone: int
    weight_from_kg: Decimal | None
    weight_to_kg: Decimal | None
    price_vnd: Decimal
    label: str


@dataclass(frozen=True)
class ProductView:
    code: str
    last_mile: TariffLastMile
    dim_divisor: int
    per_kg_from_kg: Decimal | None
    piece_min_weight_kg: Decimal | None
    piece_min_fee_vnd: Decimal | None
    piece_min_applies_above_kg: Decimal | None
    customs_surcharges_waived: bool
    brackets: tuple[Bracket, ...]


@dataclass(frozen=True)
class Tier:
    weight_from_kg: Decimal
    weight_to_kg: Decimal | None
    price_vnd: Decimal


@dataclass(frozen=True)
class RuleView:
    section: str
    stt: int
    name: str
    pricing_status: SurchargePricingStatus
    basis: SurchargeBasis
    scope: SurchargeScope
    unit_price_vnd: Decimal | None
    per_unit_price_vnd: Decimal | None
    tiers: tuple[Tier, ...]
    min_charge_kg: Decimal | None
    applies_to_canada: bool
    #: Above the top tier: ``top`` uses the top tier (OD-57), ``manual`` needs a quote (OD-59).
    above_top_tier: str = "manual"
    #: Method v0.5 allocation class (``surcharge_allocation_classes``); None = derive from the
    #: rule's basis and scope. Read only by ``app/pricing/cost_method.py``.
    allocation_class: str | None = None


@dataclass(frozen=True)
class RulePolicy:
    """The owner's commercial policy for one rule (OD-44). Absent = default markup, tariff scope."""

    #: pass_through | fixed_cad | percent | default (the default markup, OD-74, with this
    #: rule's own scope)
    markup_kind: str = "pass_through"
    markup_value: Decimal = ZERO
    scope_override: SurchargeScope | None = None


@dataclass(frozen=True)
class FeeLineInput:
    fee_line_id: int
    item_id: int | None
    section: str
    stt: int
    quantity: Decimal
    #: Carton weight for a tiered rule; kilograms for an item-weight rule.
    weight_kg: Decimal | None
    #: The vendor's quoted price for a manual-quote rule (OD-56), or for a carton above a
    #: rule's top tier where the rule says manual (OD-59). None = the prefilled minimum.
    manual_unit_price_vnd: Decimal | None = None
    #: The customer price (CAD) staff entered for a ``manual_amount`` line (owner 2026-10-23,
    #: DEC-0228; ``fee_line_manual_prices``). The line's customer charge is exactly this.
    customer_price_cad: Decimal | None = None
    #: Method v0.5 only: the customer's small box holding the item (its package id) and that
    #: box's raw chargeable weight, for a per-box surcharge priced on the box Kango sees.
    box_ref: int | None = None
    box_kg: Decimal | None = None
    #: The weight staff entered on the item the line is attached to (workspace, DEC-0275). The
    #: confirmed method uses it when the line has no weight of its own; RC-UAT-25 ignores it.
    item_kg: Decimal | None = None


@dataclass(frozen=True)
class PackageInput:
    weight_kg: Decimal | None
    length_cm: Decimal | None
    width_cm: Decimal | None
    height_cm: Decimal | None
    #: Method v0.5, master cartons only: "packed as one box for Kango".
    packed_as_one_box: bool = False


@dataclass(frozen=True)
class MemberInput:
    shipment_id: int
    public_id: str
    packages: tuple[PackageInput, ...]
    fee_lines: tuple[FeeLineInput, ...]


@dataclass(frozen=True)
class MasterInput:
    actual_weight_kg: Decimal | None
    length_cm: Decimal | None
    width_cm: Decimal | None
    height_cm: Decimal | None
    carton_count: int
    #: The figure stored at booking, when booked. Used as is; never recomputed.
    stored_chargeable_kg: Decimal | None = None
    #: Per-carton weights and dimensions, when recorded (OD-62: the under-12 kg piece fee).
    cartons: tuple[PackageInput, ...] = ()


@dataclass(frozen=True)
class DeliveryPoint:
    postal_code: str
    ground_zone: int | None
    express_zone: int | None
    beyond_code: str | None
    beyond_status: BeyondRateStatus | None
    beyond_base_cad: Decimal | None
    beyond_per_lb_cad: Decimal | None


@dataclass(frozen=True)
class FxView:
    snapshot_id: int
    cash_buy_vnd: Decimal
    sell_vnd: Decimal
    freshness: str  # live | stale


@dataclass(frozen=True)
class Settings:
    trigger_share: Fraction = Fraction(2, 3)
    defaults_owner_confirmed: bool = False
    #: The markup on a surcharge with no policy of its own (owner, 2026-10-20: 2 %).
    default_policy: RulePolicy | None = None


# --- Outputs -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    shipment_id: int | None = None
    fee_line_id: int | None = None


@dataclass
class VendorFee:
    """One vendor charge instance: a master-wide rule once, or a direct line."""

    key: str
    section: str
    stt: int
    name: str
    scope: SurchargeScope
    master_wide: bool
    vendor_fee_vnd: Decimal | None
    #: shipment_id → fee line ids that triggered it.
    triggers: dict[int, list[int]] = field(default_factory=dict)
    cost_alloc_vnd: dict[int, Decimal] = field(default_factory=dict)
    cost_alloc_cad: dict[int, Decimal] = field(default_factory=dict)
    customer_base_cad: Decimal | None = None
    customer_total_cad: Decimal | None = None
    revenue_alloc_cad: dict[int, Decimal] = field(default_factory=dict)
    markup_kind: str = "pass_through"
    markup_value: Decimal = ZERO
    quantity: Decimal = ZERO
    #: A ``manual_amount`` line's customer price as staff entered it (DEC-0228): the customer
    #: charge is exactly this, with no conversion and no markup.
    customer_price_cad: Decimal | None = None


#: The ``markup_kind`` recorded for a line billed at a price staff entered (DEC-0228).
MANUAL_PRICE_KIND = "manual_price"


@dataclass
class MemberResult:
    shipment_id: int
    public_id: str
    raw_chargeable_kg: Decimal | None
    billable_kg: Decimal | None
    base_cost_vnd: Decimal = ZERO
    base_cost_cad: Decimal | None = None
    surcharge_cost_vnd: Decimal = ZERO
    surcharge_cost_cad: Decimal | None = None
    surcharge_revenue_cad: Decimal | None = None


@dataclass
class Estimate:
    product_code: str | None
    zone: int | None
    delivery_postal_code: str | None
    master_chargeable_kg: Decimal | None
    base_freight_vnd: Decimal | None
    base_freight_cad: Decimal | None
    fees: list[VendorFee]
    members: dict[int, MemberResult]
    fx_snapshot_id: int | None
    blocking: list[Issue]
    provisional: list[Issue]
    #: The under-12 kg piece fee on lots of 21 kg and over (OD-62); allocated with base freight.
    piece_fee_vnd: Decimal = ZERO
    #: ``rc25`` (this module's ``estimate``) or ``v0_5`` (``cost_method.estimate_method``).
    method: str = "rc25"
    #: Method v0.5 detail (per-customer cost / quote / profit, allocation rows, FX used,
    #: reconciliation); None on the RC-UAT-25 method.
    method_detail: dict | None = None

    @property
    def total_cost_vnd(self) -> Decimal | None:
        if self.base_freight_vnd is None:
            return None
        return (
            self.base_freight_vnd
            + self.piece_fee_vnd
            + sum((f.vendor_fee_vnd for f in self.fees if f.vendor_fee_vnd is not None), ZERO)
        )


@dataclass(frozen=True)
class QuoteFigures:
    shipment_id: int
    selling_rate_cad: Decimal | None
    billable_kg: Decimal | None
    base_revenue_cad: Decimal | None
    surcharge_revenue_cad: Decimal | None
    total_revenue_cad: Decimal | None
    allocated_cost_cad: Decimal | None
    gross_profit_cad: Decimal | None
    negative_margin_fees: tuple[str, ...]


# --- Arithmetic --------------------------------------------------------------------------------


def to_cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def allocate(
    total: Decimal, keys: Sequence[int], weights: Sequence[Fraction]
) -> dict[int, Decimal]:
    """Split ``total`` (already at cent precision) in proportion to ``weights``.

    Largest remainder at one cent: every part is floored, then the leftover cents go to the
    parts with the largest remainders, ties to the earlier key. The parts sum to ``total``
    exactly. Zero weights receive zero.
    """
    if not keys:
        return {}
    total_weight = sum(weights, Fraction(0))
    if total_weight <= 0:
        raise ValueError("allocation weights must sum to more than zero")
    cents = int((total / CENT).to_integral_value())
    exact = [Fraction(cents) * w / total_weight for w in weights]
    floors = [int(x.numerator // x.denominator) for x in exact]
    leftover = cents - sum(floors)
    order = sorted(range(len(keys)), key=lambda i: (-(exact[i] - floors[i]), i))
    for i in order[:leftover]:
        floors[i] += 1
    return {k: Decimal(c) * CENT for k, c in zip(keys, floors, strict=True)}


def _fraction(value: Decimal) -> Fraction:
    return Fraction(str(value))


# --- Pieces ------------------------------------------------------------------------------------


def member_raw_weight(member: MemberInput, divisor: int) -> Decimal | None:
    """Σ max(actual, volumetric) over the member's active packages, unrounded. None if any
    package has no weight (a blocking issue the caller reports)."""
    if not member.packages:
        return None
    total = ZERO
    for package in member.packages:
        if package.weight_kg is None or package.weight_kg <= 0:
            return None
        volumetric = cw.volumetric_weight(
            package.length_cm, package.width_cm, package.height_cm, divisor
        )
        total += max(package.weight_kg, volumetric) if volumetric is not None else package.weight_kg
    return total


def base_freight(
    product: ProductView, zone: int, chargeable_kg: Decimal
) -> tuple[Decimal | None, str | None]:
    """The vendor's base price for the master. Returns (VND, refusal reason)."""
    per_kg_from = product.per_kg_from_kg or Decimal("21")
    if chargeable_kg < per_kg_from:
        bands = sorted(
            (b for b in product.brackets if b.kind == "per_bill" and b.zone == zone),
            key=lambda b: b.weight_to_kg or ZERO,
        )
        for band in bands:
            if band.weight_to_kg is not None and chargeable_kg <= band.weight_to_kg:
                # The workbook stores computed prices as floats (884913.6000000001); cents
                # are the stored precision, as on the per-kg path.
                return to_cents(band.price_vnd), None
        return None, f"No per-bill band covers {chargeable_kg} kg in zone {zone}."
    # The band matching the rounded weight (OD-51): the last tier whose lower bound the weight
    # reaches, so 44.5 kg is in 21-44 and 45 kg in 45-99. No separate minimum bill.
    chosen: Bracket | None = None
    for tier in sorted(
        (b for b in product.brackets if b.kind == "per_kg" and b.zone == zone),
        key=lambda b: b.weight_from_kg or ZERO,
    ):
        if chargeable_kg >= (tier.weight_from_kg or ZERO):
            chosen = tier
    if chosen is None:
        return None, f"No per-kg tier covers {chargeable_kg} kg in zone {zone}."
    # VND is not rounded to whole dong (OD-60); cents are the stored precision.
    return to_cents(chosen.price_vnd * chargeable_kg), None


def tier_price(
    tiers: Sequence[Tier], weight_kg: Decimal, above_top_tier: str = "manual"
) -> Decimal | None:
    """The tier a carton weight (to 0.1 kg) falls in. Tiers do not overlap (OD-57): a weight
    equal to a tier's upper bound is in that tier, so 5.0 kg is 1–5 and 5.1 kg is 5–22. Above
    the top bound: the top tier when the rule says ``top`` (nail polish, perfume), otherwise no
    price (batteries over 8 kg are a manual quote, OD-59)."""
    ordered = sorted(tiers, key=lambda t: t.weight_from_kg)
    if not ordered or weight_kg <= 0:
        return None
    for tier in ordered:
        if tier.weight_to_kg is None or weight_kg <= tier.weight_to_kg:
            return tier.price_vnd
    return ordered[-1].price_vnd if above_top_tier == "top" else None


def _effective_scope(rule: RuleView, policy: RulePolicy | None) -> SurchargeScope:
    if policy and policy.scope_override is not None:
        return policy.scope_override
    if rule.basis == SurchargeBasis.PER_SHIPMENT:
        return SurchargeScope.PER_SHIPMENT
    return rule.scope


_PASS = RulePolicy("pass_through", ZERO, None)


def _markup_policy(policy: RulePolicy | None, settings: Settings) -> RulePolicy:
    """The policy whose markup applies: the rule's own, else the default (OD-74)."""
    if policy is None or policy.markup_kind == "default":
        return settings.default_policy or _PASS
    return policy


def _markup(base_cad: Decimal, policy: RulePolicy | None) -> Decimal:
    if policy is None or policy.markup_kind == "pass_through":
        return base_cad
    if policy.markup_kind == "fixed_cad":
        return base_cad + policy.markup_value
    if policy.markup_kind == "percent":
        return base_cad * (Decimal(1) + policy.markup_value / Decimal(100))
    raise ValueError(f"unknown markup kind {policy.markup_kind!r}")


# --- The estimate ------------------------------------------------------------------------------


def estimate(
    *,
    product: ProductView | None,
    product_refusal: str | None,
    delivery: DeliveryPoint,
    master: MasterInput,
    members: Sequence[MemberInput],
    rules: dict[tuple[str, int], RuleView],
    rule_section: str,
    policies: dict[tuple[str, int], RulePolicy],
    fx: FxView | None,
    settings: Settings,
) -> Estimate:
    blocking: list[Issue] = []
    provisional: list[Issue] = []
    if not settings.defaults_owner_confirmed:
        provisional.append(
            Issue(
                "pricing_defaults_pending_owner_confirmation",
                "The Air Standard default rate and the full-master trigger share are configurable "
                "defaults pending owner confirmation (OD-48).",
            )
        )

    result_members: dict[int, MemberResult] = {}
    if product is None:
        blocking.append(
            Issue("no_vendor_product", product_refusal or "No vendor product is mapped.")
        )
        divisor = 6000
    else:
        divisor = product.dim_divisor

    # Member weights.
    raw: dict[int, Decimal] = {}
    for member in members:
        weight = member_raw_weight(member, divisor)
        billable: Decimal | None = None
        if weight is None:
            blocking.append(
                Issue(
                    "member_weight_missing",
                    f"{member.public_id}: every active package needs a weight before pricing.",
                    shipment_id=member.shipment_id,
                )
            )
        else:
            raw[member.shipment_id] = weight
            billable, _ = cw.round_chargeable(weight)
        result_members[member.shipment_id] = MemberResult(
            member.shipment_id, member.public_id, weight, billable
        )
    if not members:
        blocking.append(Issue("no_members", "The consolidation has no shipments."))

    # Master chargeable weight.
    master_kg: Decimal | None = master.stored_chargeable_kg
    if master_kg is None:
        if master.actual_weight_kg is None or master.actual_weight_kg <= 0:
            blocking.append(Issue("master_weight_missing", "Enter the master's actual weight."))
        else:
            computed = cw.chargeable_weight(
                master.actual_weight_kg,
                length_cm=master.length_cm,
                width_cm=master.width_cm,
                height_cm=master.height_cm,
                divisor=divisor,
            )
            master_kg = computed.chargeable_kg

    # Zone at the vendor's delivery point (OD-46).
    zone: int | None = None
    if product is not None:
        zone = (
            delivery.express_zone
            if product.last_mile == TariffLastMile.PUROLATOR_EXPRESS
            else delivery.ground_zone
        )
        if zone is None:
            blocking.append(
                Issue(
                    "delivery_zone_unknown",
                    f"The tariff has no zone for the delivery point {delivery.postal_code}.",
                )
            )
    if delivery.beyond_code is not None:
        if delivery.beyond_status == BeyondRateStatus.NO_RATE:
            blocking.append(
                Issue(
                    "delivery_beyond_no_rate",
                    f"The delivery point {delivery.postal_code} is beyond-area code "
                    f"{delivery.beyond_code}, which has no rate (V-05).",
                )
            )
        else:
            provisional.append(
                Issue(
                    "delivery_beyond_not_priced",
                    f"The delivery point {delivery.postal_code} is beyond-area code "
                    f"{delivery.beyond_code}; the per-piece beyond fee needs per-carton weights "
                    "and is not included.",
                )
            )

    # Base freight.
    base_vnd: Decimal | None = None
    piece_fee_vnd = ZERO
    if product is not None and zone is not None and master_kg is not None:
        base_vnd, refusal = base_freight(product, zone, master_kg)
        if refusal:
            blocking.append(Issue("base_freight_unpriced", refusal))
        piece_fee_vnd = _piece_fee(product, master, master_kg, divisor, provisional)

    # Surcharges.
    fees: dict[str, VendorFee] = {}
    for member in members:
        for line in member.fee_lines:
            rule = rules.get((line.section, line.stt))
            label = f"{line.section} row {line.stt}"
            if rule is None:
                blocking.append(
                    Issue(
                        "fee_rule_missing",
                        f"{member.public_id}: surcharge {label} is not in the active tariff.",
                        member.shipment_id,
                        line.fee_line_id,
                    )
                )
                continue
            if rule.section != rule_section:
                blocking.append(
                    Issue(
                        "fee_rule_wrong_origin",
                        f"{member.public_id}: '{rule.name}' belongs to another origin's tariff.",
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
                    Issue(
                        "fee_rule_not_canada",
                        f"{member.public_id}: '{rule.name}' does not apply to Canada.",
                        member.shipment_id,
                        line.fee_line_id,
                    )
                )
                continue
            policy = policies.get((rule.section, rule.stt))
            scope = _effective_scope(rule, policy)
            master_wide = scope in MASTER_WIDE_SCOPES and rule.basis in {
                SurchargeBasis.PER_KG,
                SurchargeBasis.PER_SHIPMENT,
            }
            key = f"M:{rule.section}:{rule.stt}" if master_wide else f"D:{line.fee_line_id}"
            fee = fees.get(key)
            if fee is None:
                fee = VendorFee(
                    key=key,
                    section=rule.section,
                    stt=rule.stt,
                    name=rule.name,
                    scope=scope,
                    master_wide=master_wide,
                    vendor_fee_vnd=None,
                    markup_kind=_markup_policy(policy, settings).markup_kind,
                    markup_value=_markup_policy(policy, settings).markup_value,
                )
                fees[key] = fee
            fee.triggers.setdefault(member.shipment_id, []).append(line.fee_line_id)

            if rule.pricing_status not in PRICEABLE_STATUSES:
                reason = (
                    "is unresolved with the vendor (pharmaceuticals, V-12, OD-47)"
                    if rule.pricing_status == SurchargePricingStatus.CONFLICT
                    else "is priced case by case by the vendor"
                )
                blocking.append(
                    Issue(
                        f"fee_rule_{rule.pricing_status}",
                        f"{member.public_id}: '{rule.name}' {reason}; no price is guessed.",
                        member.shipment_id,
                        line.fee_line_id,
                    )
                )
                continue
            if product is not None and product.customs_surcharges_waived:
                fee.vendor_fee_vnd = ZERO
                continue

            amount, refusal = _line_vendor_fee(
                rule, line, master_wide, master_kg, master.carton_count, provisional
            )
            if refusal:
                blocking.append(
                    Issue(
                        "fee_unpriced",
                        f"{member.public_id}: {refusal}",
                        member.shipment_id,
                        line.fee_line_id,
                    )
                )
                continue
            if master_wide:
                fee.vendor_fee_vnd = amount  # charged once, whoever triggered it
            else:
                fee.vendor_fee_vnd = (fee.vendor_fee_vnd or ZERO) + amount
                fee.quantity += line.quantity
            if rule.basis == SurchargeBasis.MANUAL_AMOUNT and line.customer_price_cad is not None:
                # Staff entered the customer price (DEC-0228): billed as is, no markup. A
                # manual_amount line is never master-wide, so the fee is this one line.
                fee.customer_price_cad = to_cents(line.customer_price_cad)
                fee.markup_kind, fee.markup_value = MANUAL_PRICE_KIND, ZERO

    # Allocation of cost (VND).
    member_ids = [m.shipment_id for m in members]
    weight_of = {sid: _fraction(raw[sid]) for sid in raw}
    weights_known = len(raw) == len(member_ids) and member_ids
    if base_vnd is not None and weights_known:
        alloc = allocate(base_vnd + piece_fee_vnd, member_ids, [weight_of[s] for s in member_ids])
        for sid, amount in alloc.items():
            result_members[sid].base_cost_vnd = amount
    for fee in fees.values():
        if fee.vendor_fee_vnd is None or not weights_known:
            continue
        fee.cost_alloc_vnd = _cost_split(fee, member_ids, weight_of, settings.trigger_share)
        for sid, amount in fee.cost_alloc_vnd.items():
            result_members[sid].surcharge_cost_vnd += amount

    # FX.
    base_cad: Decimal | None = None
    if fx is None:
        blocking.append(Issue("fx_missing", "No verified Vietcombank rate is on file."))
    else:
        if fx.freshness != "live":
            blocking.append(
                Issue(
                    "fx_stale",
                    "The latest Vietcombank rate is stale; finalising waits for a fresh one.",
                )
            )
        if base_vnd is not None:
            base_cad = to_cents((base_vnd + piece_fee_vnd) / fx.cash_buy_vnd)
            if weights_known:
                for sid, amount in allocate(
                    base_cad, member_ids, [weight_of[s] for s in member_ids]
                ).items():
                    result_members[sid].base_cost_cad = amount
        for fee in fees.values():
            if fee.vendor_fee_vnd is None or not fee.cost_alloc_vnd:
                continue
            total_cost_cad = to_cents(fee.vendor_fee_vnd / fx.cash_buy_vnd)
            fee.cost_alloc_cad = (
                allocate(
                    total_cost_cad,
                    list(fee.cost_alloc_vnd),
                    [_fraction(v) if v > 0 else Fraction(0) for v in fee.cost_alloc_vnd.values()],
                )
                if fee.vendor_fee_vnd > 0
                else dict.fromkeys(fee.cost_alloc_vnd, ZERO)
            )
            if fee.customer_price_cad is not None:
                # The customer price staff entered (DEC-0228): exactly that, no markup.
                fee.customer_base_cad = fee.customer_total_cad = fee.customer_price_cad
            else:
                policy = _markup_policy(policies.get((fee.section, fee.stt)), settings)
                # VND -> CAD at the buy rate (owner, 2026-10-20, OD-73): the vendor's VND
                # charge becomes the most CAD, so a pass-through surcharge recovers its cost.
                fee.customer_base_cad = to_cents(fee.vendor_fee_vnd / fx.cash_buy_vnd)
                fee.customer_total_cad = to_cents(_markup(fee.customer_base_cad, policy))
            triggers = list(fee.triggers)
            if fee.customer_total_cad > 0:
                fee.revenue_alloc_cad = allocate(
                    fee.customer_total_cad,
                    triggers,
                    [weight_of.get(s, Fraction(1)) for s in triggers],
                )
            else:
                fee.revenue_alloc_cad = dict.fromkeys(triggers, ZERO)
        for sid, result in result_members.items():
            result.surcharge_cost_cad = sum(
                (f.cost_alloc_cad.get(sid, ZERO) for f in fees.values()), ZERO
            )
            result.surcharge_revenue_cad = sum(
                (f.revenue_alloc_cad.get(sid, ZERO) for f in fees.values()), ZERO
            )

    return Estimate(
        product_code=product.code if product else None,
        zone=zone,
        delivery_postal_code=delivery.postal_code,
        master_chargeable_kg=master_kg,
        base_freight_vnd=base_vnd,
        base_freight_cad=base_cad,
        fees=list(fees.values()),
        members=result_members,
        fx_snapshot_id=fx.snapshot_id if fx else None,
        blocking=blocking,
        provisional=provisional,
        piece_fee_vnd=piece_fee_vnd,
    )


def _line_vendor_fee(
    rule: RuleView,
    line: FeeLineInput,
    master_wide: bool,
    master_kg: Decimal | None,
    carton_count: int,
    provisional: list[Issue],
) -> tuple[Decimal, str | None]:
    """VND for one fee line (or, master-wide, for the one consolidation charge)."""
    if rule.pricing_status == SurchargePricingStatus.FREE:
        return ZERO, None
    if master_wide:
        if rule.basis == SurchargeBasis.PER_SHIPMENT:
            return to_cents(rule.unit_price_vnd or ZERO), None
        if master_kg is None:
            return ZERO, "the master's chargeable weight is needed for this per-kilogram rule."
        if rule.scope == SurchargeScope.FULL_CARTON and carton_count > 1:
            provisional.append(
                Issue(
                    "full_carton_uses_master_weight",
                    f"'{rule.name}' is charged on the full carton; the master has {carton_count} "
                    "cartons and per-carton weights are not recorded, so the master's chargeable "
                    "weight is used.",
                    fee_line_id=line.fee_line_id,
                )
            )
        kg = max(master_kg, rule.min_charge_kg or ZERO)
        return to_cents((rule.unit_price_vnd or ZERO) * kg), None

    if rule.basis == SurchargeBasis.MANUAL_AMOUNT:
        # Quoted case by case (HCM air row 27, DEC-0225; owner 2026-10-23, DEC-0228): staff
        # enter both the vendor's cost (VND) and the customer price (CAD) for this line -- no
        # kilograms, no quantity, no prefilled value. Until both are entered the line blocks
        # finalising, naming what is missing.
        if line.manual_unit_price_vnd is not None and line.weight_kg is not None:
            # A line priced under an older reading of the rule (a price per kg on the item's
            # kilograms). Never reread silently as the line's amount: staff re-enter it (S-8).
            message = (
                f"'{rule.name}' was priced per kg under an earlier tariff; re-enter the quoted "
                "amount (VND) for this line for the new tariff."
            )
            if line.customer_price_cad is None:
                message += " Also enter the customer price (CAD)."
            return ZERO, message
        missing = [
            label
            for label, value in (
                ("the vendor's cost (VND)", line.manual_unit_price_vnd),
                ("the customer price (CAD)", line.customer_price_cad),
            )
            if value is None
        ]
        if missing:
            return ZERO, (
                f"'{rule.name}' is quoted case by case; enter {' and '.join(missing)} "
                "for this line."
            )
        return to_cents(line.manual_unit_price_vnd), None
    if rule.pricing_status == SurchargePricingStatus.MANUAL_QUOTE:
        price = line.manual_unit_price_vnd
        if price is None:
            price = rule.unit_price_vnd or ZERO
            provisional.append(
                Issue(
                    "manual_quote_prefilled_minimum",
                    f"'{rule.name}' is a manual quote; the file's minimum {price} VND is used "
                    "until staff enter the vendor's price (OD-56).",
                    fee_line_id=line.fee_line_id,
                )
            )
        if rule.basis == SurchargeBasis.PER_KG:
            if line.weight_kg is None:
                return ZERO, f"'{rule.name}' is charged per kilogram; enter the weight."
            return to_cents(price * cw.round_chargeable(line.weight_kg)[0]), None
        return to_cents(price * line.quantity), None
    if rule.pricing_status == SurchargePricingStatus.TIERED:
        if line.weight_kg is None:
            return ZERO, f"'{rule.name}' is priced by carton weight; enter the carton's weight."
        # Tier bounds are read on the weight to 0.1 kg, not the half-kilogram rounding: the
        # owner puts 3.6 kg in the 4-8 kg battery group (OD-59), which rounding to 3.5 would
        # undo (DEC-0192).
        weight = max(line.weight_kg.quantize(cw.TENTH, rounding=ROUND_HALF_UP), cw.TENTH)
        price = tier_price(rule.tiers, weight, rule.above_top_tier)
        if price is None:
            if line.manual_unit_price_vnd is not None:
                price = line.manual_unit_price_vnd
            else:
                return ZERO, (
                    f"'{rule.name}': a {weight} kg carton is above the vendor's tiers; enter "
                    "the vendor's quoted price (OD-59)."
                )
        # Per carton: ``quantity`` cartons of this weight each pay the tier. Compound
        # (perfume): one carton's tier plus the per-bottle fee on ``quantity`` bottles.
        if rule.basis == SurchargeBasis.COMPOUND and rule.per_unit_price_vnd is not None:
            amount = price + rule.per_unit_price_vnd * line.quantity
        elif rule.basis == SurchargeBasis.PER_PIECE:
            amount = price * line.quantity
        else:
            amount = price
        return to_cents(amount), None
    if rule.basis == SurchargeBasis.PER_KG:
        if line.weight_kg is None:
            return ZERO, f"'{rule.name}' is charged per kilogram; enter the weight it applies to."
        kg = max(cw.round_chargeable(line.weight_kg)[0], rule.min_charge_kg or ZERO)
        return to_cents((rule.unit_price_vnd or ZERO) * kg), None
    return to_cents((rule.unit_price_vnd or ZERO) * line.quantity), None


def _piece_fee(
    product: ProductView,
    master: MasterInput,
    master_kg: Decimal | None,
    divisor: int,
    provisional: list[Issue],
) -> Decimal:
    """The under-12 kg piece fee (OD-62): on a lot of 21 kg and over, each carton whose rounded
    chargeable weight (the greater of actual and volumetric) is under the minimum pays the fee;
    300,000 VND on Ground, 700,000 on Express, as the vendor sheet says."""
    if (
        product.piece_min_fee_vnd is None
        or product.piece_min_weight_kg is None
        or master_kg is None
        or master_kg < (product.per_kg_from_kg or Decimal("21"))
    ):
        return ZERO
    if not master.cartons:
        if master.carton_count > 1:
            provisional.append(
                Issue(
                    "piece_minimum_not_evaluated",
                    f"Lots of 21 kg and over pay {product.piece_min_fee_vnd} VND for each carton "
                    f"under {product.piece_min_weight_kg} kg; record the {master.carton_count} "
                    "cartons' weights to include it (OD-62).",
                )
            )
        return ZERO
    if len(master.cartons) != master.carton_count:
        provisional.append(
            Issue(
                "carton_count_mismatch",
                f"{len(master.cartons)} cartons are recorded but the master says "
                f"{master.carton_count}; the recorded cartons are used.",
            )
        )
    light = 0
    for carton in master.cartons:
        if carton.weight_kg is None:
            continue
        volumetric = cw.volumetric_weight(
            carton.length_cm, carton.width_cm, carton.height_cm, divisor
        )
        weight = max(carton.weight_kg, volumetric) if volumetric is not None else carton.weight_kg
        if cw.round_chargeable(weight)[0] < product.piece_min_weight_kg:
            light += 1
    return to_cents(product.piece_min_fee_vnd * light)


def _cost_split(
    fee: VendorFee, member_ids: list[int], weight_of: dict[int, Fraction], trigger_share: Fraction
) -> dict[int, Decimal]:
    """Who bears a vendor fee (handoff section 5, Example B)."""
    total = fee.vendor_fee_vnd or ZERO
    triggers = [s for s in member_ids if s in fee.triggers]
    if not fee.master_wide:
        # A direct line belongs to its own shipment.
        return {triggers[0]: total} if triggers else {}
    if len(member_ids) == 1:
        return {member_ids[0]: total}
    if len(triggers) == 1:
        others = [s for s in member_ids if s not in triggers]
        each_other = (Fraction(1) - trigger_share) / len(others)
        weights = [trigger_share if s in triggers else each_other for s in member_ids]
        return allocate(total, member_ids, weights)
    return allocate(total, triggers, [weight_of[s] for s in triggers])


# --- The customer quote ------------------------------------------------------------------------


def quote_figures(
    est: Estimate, shipment_id: int, selling_rate_cad: Decimal | None
) -> QuoteFigures:
    """One member's customer figures from the estimate and a selling rate."""
    member = est.members.get(shipment_id)
    if member is None:
        raise KeyError(shipment_id)
    base_rev = (
        to_cents(member.billable_kg * selling_rate_cad)
        if member.billable_kg is not None and selling_rate_cad is not None
        else None
    )
    surcharge_rev = member.surcharge_revenue_cad
    total = base_rev + surcharge_rev if base_rev is not None and surcharge_rev is not None else None
    cost = (
        member.base_cost_cad + member.surcharge_cost_cad
        if member.base_cost_cad is not None and member.surcharge_cost_cad is not None
        else None
    )
    negative = tuple(
        fee.name
        for fee in est.fees
        if shipment_id in fee.revenue_alloc_cad
        and fee.cost_alloc_cad
        and fee.revenue_alloc_cad[shipment_id] < fee.cost_alloc_cad.get(shipment_id, ZERO)
    )
    return QuoteFigures(
        shipment_id=shipment_id,
        selling_rate_cad=selling_rate_cad,
        billable_kg=member.billable_kg,
        base_revenue_cad=base_rev,
        surcharge_revenue_cad=surcharge_rev,
        total_revenue_cad=total,
        allocated_cost_cad=cost,
        gross_profit_cad=total - cost if total is not None and cost is not None else None,
        negative_margin_fees=negative,
    )


__all__ = [
    "Bracket",
    "DeliveryPoint",
    "Estimate",
    "FeeLineInput",
    "FxView",
    "Issue",
    "MasterInput",
    "MemberInput",
    "PackageInput",
    "ProductView",
    "QuoteFigures",
    "RulePolicy",
    "RuleView",
    "Settings",
    "Tier",
    "VendorFee",
    "allocate",
    "base_freight",
    "estimate",
    "quote_figures",
    "tier_price",
]
