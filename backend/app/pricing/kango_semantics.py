"""The reviewed meaning of the Kango tariff's prose: surcharge rules, fees in notes, product rules.

The workbook reader (``kango_workbook.py``) returns the vendor's text verbatim. This module
says what that text *means*, in two layers:

1. **A strict price-text parser.** ``parse_price_text`` turns ``"30.000/Kg"`` into
   30,000 VND per kilogram and ``"1.000.000/1 Kiện"`` into 1,000,000 per carton. It refuses
   -- returns ``unpriced`` -- for anything it cannot read without guessing: a range
   (``"300 - 700.000"``), an estimate (``"Dự kiến >"``), a compound (``"… + 50.000/Chai"``),
   "case by case", or a unit it does not know. The v1.5 prototype's parser priced five of
   these rows at 1 VND and two estimates as fixed amounts (`04_ISSUE_REGISTER.md` H-01,
   H-02); refusing is the fix.

2. **A curated table**, keyed by (section, row number), for the rows whose meaning lives
   in the *note* rather than the price cell: weight tiers, the per-bottle component, a
   route-dependent price, a route exclusion, a stated maximum, a conflict with the rate
   sheet. Every entry cites the cell it was read from. A curated entry wins over the
   parser, and ``semantics_source`` on the stored rule records which one applied.

Also here, because they are read from prose rather than tables: the vendor's accessorial
fees (Saturday delivery, address correction, oversized piece, storage, return …) and the
per-product rules (dimensional divisor, per-kg threshold, per-piece minimums) with the
cell each was taken from.

**This table is specific to the 12 October 2026 workbook's wording.** The importer
applies an entry only when the row's name still matches the ``name_contains`` check, and
records a ``curated_entry_unmatched`` anomaly when a future workbook has moved or
reworded the row, so a stale reading is a flagged review item rather than a silent
mis-price.

Open vendor questions are cited by their id in ``docs/b2c_merge/05_OPEN_DECISIONS.md``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal

from app.core.enums import (
    AccessorialBasis,
    SurchargeBasis,
    SurchargePricingStatus,
    SurchargeScope,
    SurchargeSection,
    TariffLastMile,
    TariffProductMode,
)

# --- Price text ---------------------------------------------------------------------

UNIT_BASIS: dict[str, SurchargeBasis] = {
    "kg": SurchargeBasis.PER_KG,
    "kien": SurchargeBasis.PER_PIECE,
    "thung": SurchargeBasis.PER_PIECE,
    "cai": SurchargeBasis.PER_UNIT,
    "may": SurchargeBasis.PER_UNIT,
    "con": SurchargeBasis.PER_UNIT,
    "doi": SurchargeBasis.PER_PAIR,
    "cap": SurchargeBasis.PER_PAIR,
    "hop": SurchargeBasis.PER_BOX,
    "chai": SurchargeBasis.PER_BOTTLE,
    "lo hang": SurchargeBasis.PER_SHIPMENT,
}

#: Words that mean the vendor has not committed to a number.
UNPRICED_MARKERS = ("case", "tuy", "du kien", ">", " to ", "lien he", "~")
PRICE_PATTERN = re.compile(
    r"^(?P<amount>\d[\d.,]*)\s*(?:d|đ|vnd|vnđ)?\s*/\s*(?:1\s*)?(?P<unit>[a-z ]+?)\s*(?:\(.*\))?$"
)
RANGE_PATTERN = re.compile(r"\d[\d.,]*\s*-\s*\d")
MIN_KG_PATTERN = re.compile(r"min\s*thu\s*(\d+(?:[.,]\d+)?)\s*kg")


def fold(text: str) -> str:
    """Lower-case, accent-stripped, single-spaced. For matching only; never stored."""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    stripped = stripped.replace("đ", "d").replace("Đ", "d")
    return re.sub(r"\s+", " ", stripped).strip().lower()


def parse_vnd_amount(raw: str) -> Decimal | None:
    """``300.000`` → 300000; ``10,000`` → 10000; ``5000`` → 5000; anything else → None.

    A bare number under 1,000 followed by nothing is accepted as written; ``"300"`` on its
    own in ``"300 - 700.000"`` never reaches here because the range check runs first.
    """
    raw = raw.strip().rstrip(".,")
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", raw):
        return Decimal(re.sub(r"[.,]", "", raw))
    if re.fullmatch(r"\d+", raw):
        return Decimal(raw)
    return None


@dataclass(frozen=True)
class ParsedPrice:
    status: SurchargePricingStatus
    basis: SurchargeBasis
    unit_price_vnd: Decimal | None = None
    min_charge_kg: Decimal | None = None
    reason: str | None = None


def parse_price_text(text: str) -> ParsedPrice:
    """Read the vendor's price cell strictly. See the module docstring for what is refused."""
    folded = fold(text)
    if "mien phu thu" in folded:
        return ParsedPrice(SurchargePricingStatus.FREE, SurchargeBasis.FREE)
    min_kg: Decimal | None = None
    min_match = MIN_KG_PATTERN.search(folded)
    if min_match:
        min_kg = Decimal(min_match.group(1).replace(",", "."))
        folded = MIN_KG_PATTERN.sub("", folded)
        folded = re.sub(r"\(\s*\)", "", folded).strip()
    if "+" in folded:
        return ParsedPrice(
            SurchargePricingStatus.UNPRICED_VENDOR_REVIEW,
            SurchargeBasis.COMPOUND,
            reason="compound price text; needs a reviewed reading",
        )
    if RANGE_PATTERN.search(folded) or any(marker in folded for marker in UNPRICED_MARKERS):
        return ParsedPrice(
            SurchargePricingStatus.UNPRICED_VENDOR_REVIEW,
            SurchargeBasis.UNPRICED,
            reason="the vendor gives a range, an estimate or 'case by case'",
        )
    match = PRICE_PATTERN.match(folded)
    if not match:
        return ParsedPrice(
            SurchargePricingStatus.UNPRICED_VENDOR_REVIEW,
            SurchargeBasis.UNPRICED,
            reason="price text not understood",
        )
    amount = parse_vnd_amount(match.group("amount"))
    unit = match.group("unit").strip()
    basis = UNIT_BASIS.get(unit)
    if amount is None or basis is None:
        return ParsedPrice(
            SurchargePricingStatus.UNPRICED_VENDOR_REVIEW,
            SurchargeBasis.UNPRICED,
            reason=f"amount or unit not understood ({unit!r})",
        )
    return ParsedPrice(SurchargePricingStatus.PRICED, basis, amount, min_kg)


def default_scope(basis: SurchargeBasis) -> SurchargeScope:
    """The sheet's own rule: a per-kg surcharge is on the full carton (footer, B105)."""
    if basis == SurchargeBasis.PER_KG:
        return SurchargeScope.FULL_CARTON
    if basis == SurchargeBasis.PER_SHIPMENT:
        return SurchargeScope.PER_SHIPMENT
    return SurchargeScope.PER_UNIT


# --- Curated rule semantics -----------------------------------------------------------


@dataclass(frozen=True)
class Tier:
    weight_from_kg: Decimal
    weight_to_kg: Decimal | None
    price_vnd: Decimal


@dataclass(frozen=True)
class RuleSemantics:
    """A reviewed reading of one surcharge row. ``None`` fields defer to the parser."""

    source_cell: str
    name_contains: str
    note: str
    pricing_status: SurchargePricingStatus | None = None
    basis: SurchargeBasis | None = None
    scope: SurchargeScope | None = None
    unit_price_vnd: Decimal | None = None
    per_unit_price_vnd: Decimal | None = None
    per_unit_label: str | None = None
    tiers: tuple[Tier, ...] = ()
    min_charge_kg: Decimal | None = None
    max_kg_per_shipment: Decimal | None = None
    applies_to_canada: bool | None = None
    #: What a weight above the top tier gets: ``top`` (the top tier's price, OD-57 for nail
    #: polish and perfume) or ``manual`` (a manual quote, OD-59 for batteries over 8 kg).
    above_top_tier: str = "manual"
    #: For a route-dependent row, the route the curated value is for. Only
    #: :data:`PRICED_ROUTE` is ever priced; ``None`` means the row is not route-dependent.
    route: str | None = None


#: The only route the tariff is used to price: Vietnam (HCM or Hà Nội) to Canada, by air.
PRICED_ROUTE = "VN-CA"


def _vnd(value: int) -> Decimal:
    return Decimal(value)


#: Nail polish and perfume share one tier text: "1–5 kg 300k, 5–22 kg 500k, 22–30 kg 700k"
#: (D10, D20). The bounds overlap at exactly 5 and 22 kg and nothing is said above 30 kg
#: (V-11); the tiers are stored as written and the engine applies the recorded convention.
NAIL_POLISH_TIERS = (
    Tier(_vnd(0), _vnd(5), _vnd(300_000)),
    Tier(_vnd(5), _vnd(22), _vnd(500_000)),
    Tier(_vnd(22), _vnd(30), _vnd(700_000)),
)

#: Batteries with a small device, rows 2 and 3 as one rule (OD-59): up to 3.5 kg the 1–3 kg
#: group, over 3.5 up to 8 kg the 4–8 kg group, above 8 kg a manual quote.
BATTERY_TIERS = (
    Tier(_vnd(0), Decimal("3.5"), _vnd(300_000)),
    Tier(Decimal("3.5"), _vnd(8), _vnd(700_000)),
)

S = SurchargeSection
PS = SurchargePricingStatus
B = SurchargeBasis
SC = SurchargeScope

CURATED_RULES: dict[tuple[SurchargeSection, int], RuleSemantics] = {
    (S.HCM_AIR, 1): RuleSemantics(
        "D10",
        "son mong",
        "Per carton, tiered by the carton's weight to 0.1 kg: up to 5 kg 300k, over 5–22 kg 500k, "
        "over 22 kg 700k. The tiers do not overlap and above 30 kg the top tier applies (OD-57).",
        PS.TIERED,
        B.PER_PIECE,
        SC.PER_UNIT,
        tiers=NAIL_POLISH_TIERS,
        above_top_tier="top",
    ),
    (S.HCM_AIR, 2): RuleSemantics(
        "C11",
        "pin kem thiet bi nho 1-3",
        "Battery with a small device, by the carton's weight: up to 3.5 kg 300k, 3.6–8 kg 700k, "
        "above 8 kg a manual quote (OD-59). Rows 2 and 3 are one battery rule.",
        PS.TIERED,
        B.PER_PIECE,
        SC.PER_UNIT,
        tiers=BATTERY_TIERS,
        above_top_tier="manual",
    ),
    (S.HCM_AIR, 3): RuleSemantics(
        "C12",
        "pin kem thiet bi nho 4-8",
        "Battery with a small device, by the carton's weight: up to 3.5 kg 300k, 3.6–8 kg 700k, "
        "above 8 kg a manual quote (OD-59). Rows 2 and 3 are one battery rule.",
        PS.TIERED,
        B.PER_PIECE,
        SC.PER_UNIT,
        tiers=BATTERY_TIERS,
        above_top_tier="manual",
    ),
    (S.HCM_AIR, 4): RuleSemantics(
        "C13",
        "pin kem thiet bi lon",
        "Manual quote per carton, prefilled with the file's minimum, 700,000 (OD-56).",
        PS.MANUAL_QUOTE,
        B.PER_PIECE,
        SC.PER_UNIT,
        unit_price_vnd=_vnd(700_000),
    ),
    (S.HCM_AIR, 5): RuleSemantics(
        "C14",
        "loa binh thuong",
        "Manual quote per speaker, prefilled with the file's minimum, 500,000 (OD-56).",
        PS.MANUAL_QUOTE,
        B.PER_UNIT,
        SC.PER_UNIT,
        unit_price_vnd=_vnd(500_000),
    ),
    (S.HCM_AIR, 10): RuleSemantics(
        "C19",
        "camera co pin",
        "Manual quote per camera, prefilled with the file's minimum, 100,000 (OD-56).",
        PS.MANUAL_QUOTE,
        B.PER_UNIT,
        SC.PER_UNIT,
        unit_price_vnd=_vnd(100_000),
    ),
    (S.HCM_AIR, 11): RuleSemantics(
        "C20",
        "nuoc hoa",
        "Per carton, the nail-polish weight tiers (no overlap; above 30 kg the top tier), plus "
        "50,000 VND per bottle customs fee (D20, OD-57).",
        PS.TIERED,
        B.COMPOUND,
        SC.PER_UNIT,
        tiers=NAIL_POLISH_TIERS,
        per_unit_price_vnd=_vnd(50_000),
        per_unit_label="bottle",
        above_top_tier="top",
    ),
    (S.HCM_AIR, 13): RuleSemantics(
        "C22",
        "chat long",
        "Manual quote per carton (security surcharge), prefilled with the file's minimum, "
        "100,000 (OD-56).",
        PS.MANUAL_QUOTE,
        B.PER_PIECE,
        SC.PER_UNIT,
        unit_price_vnd=_vnd(100_000),
    ),
    (S.HCM_AIR, 14): RuleSemantics(
        "D23",
        "fake thuong hieu",
        "Charged on the full carton weight, not the item's own kilograms (D23).",
        scope=SC.FULL_CARTON,
    ),
    (S.HCM_AIR, 23): RuleSemantics(
        "D32",
        "hang yen",
        "At most 1 kg of bird's nest per bill; silver zip bag required (D32).",
        max_kg_per_shipment=Decimal(1),
    ),
    (S.HCM_AIR, 27): RuleSemantics(
        "C36",
        "my ky",
        "Quoted case by case (B36): staff enter the vendor's quoted amount in VND for the "
        "line, converted and marked up like any surcharge; no kilogram basis, no master-wide "
        "share, no prefilled minimum. A line without an amount blocks finalising "
        "(owner, 2026-10-22, DEC-0225).",
        PS.MANUAL_QUOTE,
        B.MANUAL_AMOUNT,
        SC.PER_UNIT,
    ),
    (S.HCM_AIR, 31): RuleSemantics(
        "C40",
        "may moc",
        "Manual quote per machine, prefilled with the file's minimum, 500,000 (OD-56).",
        PS.MANUAL_QUOTE,
        B.PER_UNIT,
        SC.PER_UNIT,
        unit_price_vnd=_vnd(500_000),
    ),
    (S.HCM_AIR, 33): RuleSemantics(
        "C42",
        "may y te",
        "Manual quote per machine, prefilled with the file's minimum, 1,000,000 (OD-56).",
        PS.MANUAL_QUOTE,
        B.PER_UNIT,
        SC.PER_UNIT,
        unit_price_vnd=_vnd(1_000_000),
    ),
    (S.HCM_AIR, 34): RuleSemantics(
        "D43",
        "may anh",
        "Manual quote per camera, prefilled with the file's minimum, 200,000 (the battery "
        "variant is 500k–700k) (OD-56).",
        PS.MANUAL_QUOTE,
        B.PER_UNIT,
        SC.PER_UNIT,
        unit_price_vnd=_vnd(200_000),
    ),
    (S.HCM_AIR, 39): RuleSemantics(
        "C48",
        "thuoc tay",
        "Pharmaceuticals are carried and charged at the surcharge sheet's 200,000 VND/kg on the "
        "item's own kilograms, not the full carton (OD-58, OD-70).",
        PS.PRICED,
        B.PER_KG,
        SC.ITEM_WEIGHT,
        unit_price_vnd=_vnd(200_000),
    ),
    (S.HCM_AIR, 41): RuleSemantics(
        "D50",
        "thit, trung, sua",
        "Route-dependent (D50): 10,000/kg is for AU, UK and Singapore air; 'all other AIR "
        "routes' are 20,000/kg. This value is for route VN-CA (Vietnam to Canada air): 20,000 "
        "VND/kg on the full carton (owner decision, Louis Tong, 2026-10-21, DEC-0222).",
        PS.PRICED,
        B.PER_KG,
        SC.FULL_CARTON,
        unit_price_vnd=_vnd(20_000),
        route=PRICED_ROUTE,
    ),
    (S.HCM_AIR, 44): RuleSemantics(
        "D53",
        "cay xanh",
        "Applies only to the EU and UK frozen routes (D53). Not applicable to Canada.",
        PS.NOT_APPLICABLE_CANADA,
        applies_to_canada=False,
    ),
    (S.HCM_AIR, 45): RuleSemantics(
        "C54",
        "labubu",
        "Manual quote per figure, prefilled with the file's minimum, 50,000 (OD-56).",
        PS.MANUAL_QUOTE,
        B.PER_UNIT,
        SC.PER_UNIT,
        unit_price_vnd=_vnd(50_000),
    ),
    (S.HCM_AIR, 47): RuleSemantics(
        "C56",
        "hun trung",
        "Fumigation of wooden goods, once per shipment, air only (D56).",
        PS.PRICED,
        B.PER_SHIPMENT,
        SC.PER_SHIPMENT,
        unit_price_vnd=_vnd(550_000),
    ),
    (S.HAN_AIR, 1): RuleSemantics(
        "D64",
        "thuoc tay",
        "Charged on the Hà Nội → Canada direct duty-paid route (D64), 200,000 VND/kg, minimum "
        "1 kg (OD-58, superseding OD-47).",
        PS.PRICED,
        B.PER_KG,
        SC.ITEM_WEIGHT,
        unit_price_vnd=_vnd(200_000),
        min_charge_kg=Decimal(1),
    ),
    (S.HAN_AIR, 3): RuleSemantics(
        "D66",
        "yen sao",
        "At most 1 kg per bill; silver zip bag (D66).",
        max_kg_per_shipment=Decimal(1),
    ),
    (S.HAN_AIR, 6): RuleSemantics(
        "C69",
        "long mi",
        "Explicitly exempt on the Hà Nội tariff (C69). The HCM rate must never be applied to "
        "a Hà Nội shipment.",
        PS.FREE,
        B.FREE,
    ),
    (S.HAN_AIR, 8): RuleSemantics(
        "D71",
        "cay xanh",
        "UK and EU frozen routes only (D71). Not applicable to Canada.",
        PS.NOT_APPLICABLE_CANADA,
        applies_to_canada=False,
    ),
    (S.SEA_CA_AU_UK_EU, 6): RuleSemantics(
        "D83",
        "labubu",
        "On the chargeable weight of the whole shipment (D83), not one carton.",
        scope=SC.FULL_MASTER,
    ),
}

#: Section-wide defaults. The USA sea section is never applicable to a Canada shipment.
SECTION_APPLIES_TO_CANADA: dict[SurchargeSection, bool] = {
    S.HCM_AIR: True,
    S.HAN_AIR: True,
    S.SEA_CA_AU_UK_EU: True,
    S.SEA_USA: False,
}


# --- Accessorial fees written in the notes ----------------------------------------------


@dataclass(frozen=True)
class AccessorialSpec:
    key: str
    description: str
    amount: Decimal | None
    currency: str
    basis: AccessorialBasis
    modes: tuple[TariffProductMode, ...]
    sheet: str
    cell: str


AIR = (TariffProductMode.AIR,)
SEA = (TariffProductMode.SEA,)
BOTH = (TariffProductMode.AIR, TariffProductMode.SEA)
AB = AccessorialBasis

ACCESSORIALS: tuple[AccessorialSpec, ...] = (
    AccessorialSpec(
        "saturday_delivery",
        "Saturday delivery (Purolator)",
        Decimal("21"),
        "CAD",
        AB.PER_SHIPMENT,
        BOTH,
        "HCM-AIR-CAD",
        "B78",
    ),
    AccessorialSpec(
        "address_change_in_transit",
        "Delivery address changed in transit; re-rated if the zone changes",
        Decimal("5"),
        "CAD",
        AB.PER_SHIPMENT,
        BOTH,
        "HCM-AIR-CAD",
        "B79",
    ),
    AccessorialSpec(
        "redelivery",
        "Second and each later delivery attempt",
        Decimal("5"),
        "CAD",
        AB.PER_SHIPMENT,
        BOTH,
        "HCM-AIR-CAD",
        "B80",
    ),
    AccessorialSpec(
        "address_correction",
        "Address correction by the carrier",
        Decimal("10"),
        "CAD",
        AB.PER_SHIPMENT,
        BOTH,
        "HCM-AIR-CAD",
        "B81",
    ),
    AccessorialSpec(
        "signature_required_residential",
        "Signature required, residential",
        Decimal("3"),
        "CAD",
        AB.PER_SHIPMENT,
        BOTH,
        "HCM-AIR-CAD",
        "B82",
    ),
    AccessorialSpec(
        "additional_handling",
        "Special handling: irregular shape",
        Decimal("6"),
        "CAD",
        AB.PER_PIECE,
        BOTH,
        "HCM-AIR-CAD",
        "B83",
    ),
    AccessorialSpec(
        "oversized",
        "Special handling: gross weight over 22 kg up to 32 kg, or longest side 120–270 cm",
        Decimal("9"),
        "CAD",
        AB.PER_PIECE,
        BOTH,
        "HCM-AIR-CAD",
        "B84",
    ),
    AccessorialSpec(
        "residential_heavyweight",
        "Special handling: gross weight over 32 kg up to 68 kg (sheet text is garbled; V-07)",
        Decimal("40"),
        "CAD",
        AB.PER_PIECE,
        BOTH,
        "HCM-AIR-CAD",
        "B85",
    ),
    AccessorialSpec(
        "large_package",
        "Special handling: girth 330–410 cm, girth = L + 2 × (W + H)",
        Decimal("35"),
        "CAD",
        AB.PER_PIECE,
        BOTH,
        "HCM-AIR-CAD",
        "B86",
    ),
    AccessorialSpec(
        "return_redelivery_ground",
        "Returned to the vendor warehouse and redelivered, AIR-CAD",
        Decimal("700000"),
        "VND",
        AB.PER_PIECE,
        AIR,
        "HCM-AIR-CAD",
        "B88",
    ),
    AccessorialSpec(
        "return_redelivery_express",
        "Returned to the vendor warehouse and redelivered, AIR-CAD EXPRESS",
        Decimal("2000000"),
        "VND",
        AB.PER_PIECE,
        AIR,
        "HCM-AIR-CAD",
        "B88",
    ),
    AccessorialSpec(
        "destruction",
        "Destruction of a returned piece instead of redelivery",
        Decimal("500000"),
        "VND",
        AB.PER_PIECE,
        BOTH,
        "HCM-AIR-CAD",
        "B88",
    ),
    AccessorialSpec(
        "return_storage_weekly",
        "Storage of a returned piece after two free weeks, per week",
        Decimal("650000"),
        "VND",
        AB.PER_PIECE_PER_WEEK,
        BOTH,
        "HCM-AIR-CAD",
        "B89",
    ),
    AccessorialSpec(
        "recipient_name_correction",
        "Customs name correction for an incomplete recipient name ('$5'; currency not stated, "
        "V-07)",
        Decimal("5"),
        "CAD",
        AB.PER_PIECE,
        SEA,
        "HCM-SEA-CAD",
        "B71",
    ),
    AccessorialSpec(
        "cbsa_random_examination",
        "CBSA random examination",
        Decimal("100"),
        "CAD",
        AB.PER_PIECE,
        SEA,
        "HCM-SEA-CAD",
        "B72",
    ),
    AccessorialSpec(
        "wooden_pallet_fumigation",
        "Fumigation of a wooden pallet, trucking ('$10/Bill'; currency not stated, V-07)",
        Decimal("10"),
        "CAD",
        AB.PER_BILL,
        SEA,
        "HCM-SEA-CAD",
        "B88",
    ),
)


# --- Product rules written in the notes --------------------------------------------------


@dataclass(frozen=True)
class ProductRules:
    dim_divisor: int
    per_kg_from_kg: Decimal | None
    piece_min_weight_kg: Decimal | None
    piece_min_fee_vnd: Decimal | None
    piece_min_applies_above_kg: Decimal | None
    min_chargeable_kg: Decimal | None
    source_cells: tuple[str, ...] = field(default_factory=tuple)


AIR_PIECE_ABOVE = Decimal(21)
AIR_PIECE_MIN = Decimal(12)

PRODUCT_RULES: dict[tuple[str, TariffLastMile], ProductRules] = {
    # A54 (HCM) / A53 (HN): on lots over 21 kg, any piece under 12 kg pays 300,000 (Ground)
    # or 700,000 (Express). B65 / B63: divisor 6000; above 20.5 kg round up to whole kg.
    ("AIR-CAD", TariffLastMile.PUROLATOR_GROUND): ProductRules(
        6000, Decimal(21), AIR_PIECE_MIN, Decimal(300_000), AIR_PIECE_ABOVE, None, ("A54", "B65")
    ),
    ("AIR-CAD EXPRESS", TariffLastMile.PUROLATOR_EXPRESS): ProductRules(
        6000, Decimal(21), AIR_PIECE_MIN, Decimal(700_000), AIR_PIECE_ABOVE, None, ("A54", "B65")
    ),
    # A19: sea shipments of two or more pieces over 21 kg need 15 kg per piece, else 300,000
    # per piece. B27: divisor 6000.
    ("KSN-SEA-CAD-PURO", TariffLastMile.PUROLATOR_GROUND): ProductRules(
        6000, None, Decimal(15), Decimal(300_000), Decimal(21), None, ("A19", "B27")
    ),
    ("KSN-SEA-CAD-PURO-BH", TariffLastMile.PUROLATOR_GROUND): ProductRules(
        6000, None, Decimal(15), Decimal(300_000), Decimal(21), None, ("A19", "B27")
    ),
    # B28: trucking divisor 5000. I11: minimum 100 kg. B88 item 3: piece under 12 kg on a
    # lot over 21 kg pays 500,000.
    ("KSN-SEA-CAD-TRUCKING", TariffLastMile.TRUCKING): ProductRules(
        5000,
        None,
        AIR_PIECE_MIN,
        Decimal(500_000),
        AIR_PIECE_ABOVE,
        Decimal(100),
        ("B28", "I11", "B88"),
    ),
}

#: The rounding rule the pricing engine must codify (13C). Recorded in the import report so
#: a reviewer sees it next to the data it governs. Cells: HCM-AIR-CAD!B65, HN-AIR-CAD!B63,
#: HCM-SEA-CAD!B27.
ROUNDING_RULE = (
    "Chargeable weight is the greater of gross weight and L×W×H/6000, per shipment. Every "
    "weight, above 20.5 kg too, is rounded to 0.5 kg steps: x.0–x.1 → x.0, x.2–x.6 → x.5, "
    "x.7–x.9 → the next whole kilogram (owner, OD-50; the sheet's 21.2 → 22 is superseded)."
)

#: Pieces the vendor refuses outright. Not a fee; a refusal the engine must surface.
REFUSAL_RULE = "Gross weight over 68 kg or girth over 410 cm is refused (HCM-AIR-CAD!B87)."
