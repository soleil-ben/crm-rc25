"""Chargeable weight, as the vendor computes it (Phase 13B; rounding per OD-50, Phase 13C).

Pure functions over Decimals.

* volumetric weight = length × width × height (cm) / 6000 (OD-52: one divisor for
  everything);
* chargeable weight = the greater of actual and volumetric, **per shipment** (OD-50);
* rounding, the owner's answer to V-01/V-02 (OD-50), applied to every weight including
  those above 20.5 kg, on the first decimal: x.0–x.1 → x.0; x.2–x.6 → x.5; x.7–x.9 → x+1
  (5.1 → 5, 5.2–5.6 → 5.5, 5.7–5.9 → 6).

One recorded assumption (DEC-0191): a weight with more than one decimal is first rounded
half-up to one decimal (5.15 → 5.2 → 5.5), because the owner's table is stated on the first
decimal. And the smallest result is 0.5 kg, the vendor's smallest band: a 0.1 kg parcel is not
free (OD-51: the band matching the rounded weight applies, no separate minimum bill).

``used_half_kg_convention`` is kept for the callers written in Phase 13B and is now always
False: the rule is the owner's, not a convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

HALF_KG = Decimal("0.5")
TENTH = Decimal("0.1")
ONE = Decimal(1)


@dataclass(frozen=True)
class ChargeableWeight:
    actual_kg: Decimal
    volumetric_kg: Decimal | None
    #: max(actual, volumetric) before rounding.
    raw_kg: Decimal
    #: What the vendor bills.
    chargeable_kg: Decimal
    divisor: int
    #: True when the sub-20.5 kg half-kilogram convention decided the figure (V-01).
    used_half_kg_convention: bool


def volumetric_weight(
    length_cm: Decimal | None, width_cm: Decimal | None, height_cm: Decimal | None, divisor: int
) -> Decimal | None:
    """``L × W × H / divisor``; ``None`` when any dimension is missing."""
    if length_cm is None or width_cm is None or height_cm is None:
        return None
    if divisor <= 0:
        raise ValueError("the dimensional divisor must be positive")
    # Quantized to the precision the database stores (Numeric(8,3)), so the figure in
    # memory is the figure on disk.
    volume = Decimal(length_cm) * Decimal(width_cm) * Decimal(height_cm)
    return (volume / Decimal(divisor)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def round_chargeable(raw_kg: Decimal) -> tuple[Decimal, bool]:
    """Apply the owner's rounding (OD-50). Returns the figure and False (no convention)."""
    if raw_kg <= 0:
        raise ValueError("chargeable weight must be positive")
    tenths = Decimal(raw_kg).quantize(TENTH, rounding=ROUND_HALF_UP)
    whole = tenths.to_integral_value(rounding=ROUND_FLOOR)
    digit = int((tenths - whole) * 10)
    if digit <= 1:
        rounded = whole
    elif digit <= 6:
        rounded = whole + HALF_KG
    else:
        rounded = whole + ONE
    return max(rounded, HALF_KG), False


def chargeable_weight(
    actual_kg: Decimal,
    *,
    length_cm: Decimal | None = None,
    width_cm: Decimal | None = None,
    height_cm: Decimal | None = None,
    divisor: int,
) -> ChargeableWeight:
    actual = Decimal(actual_kg)
    if actual <= 0:
        raise ValueError("actual weight must be positive")
    volumetric = volumetric_weight(length_cm, width_cm, height_cm, divisor)
    raw = max(actual, volumetric) if volumetric is not None else actual
    rounded, convention = round_chargeable(raw)
    return ChargeableWeight(
        actual_kg=actual,
        volumetric_kg=volumetric,
        raw_kg=raw,
        chargeable_kg=rounded,
        divisor=divisor,
        used_half_kg_convention=convention,
    )
