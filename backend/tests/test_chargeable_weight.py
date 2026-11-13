"""The vendor's chargeable-weight rule (Phase 13B), including the handoff's 21 kg example."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.pricing import chargeable_weight as cw


def test_the_handoff_master_21_kg_in_a_60x40x40_carton():
    """Handoff section 5: master actual 21 kg, 60×40×40 cm, divisor 6000 → 16 kg volumetric,
    21 kg chargeable (the vendor's own worked example on the zone sheet uses this carton)."""
    result = cw.chargeable_weight(
        Decimal(21),
        length_cm=Decimal(60),
        width_cm=Decimal(40),
        height_cm=Decimal(40),
        divisor=6000,
    )
    assert result.volumetric_kg == Decimal(16)
    assert result.raw_kg == Decimal(21)
    assert result.chargeable_kg == Decimal(21)
    assert result.used_half_kg_convention is False


def test_volumetric_wins_when_the_carton_is_light_and_large():
    result = cw.chargeable_weight(
        Decimal(5), length_cm=Decimal(60), width_cm=Decimal(50), height_cm=Decimal(50), divisor=6000
    )
    assert result.volumetric_kg == Decimal(25)
    assert result.chargeable_kg == Decimal(25)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # The owner's rule for every weight, above 20.5 kg too (OD-50): x.0-x.1 -> x.0,
        # x.2-x.6 -> x.5, x.7-x.9 -> the next whole kilogram.
        (Decimal("5.0"), Decimal(5)),
        (Decimal("5.1"), Decimal(5)),
        (Decimal("5.2"), Decimal("5.5")),
        (Decimal("5.6"), Decimal("5.5")),
        (Decimal("5.7"), Decimal(6)),
        (Decimal("5.9"), Decimal(6)),
        (Decimal("21.2"), Decimal("21.5")),
        (Decimal("20.6"), Decimal("20.5")),
        (Decimal("20.7"), Decimal(21)),
        (Decimal("44.6"), Decimal("44.5")),
        (Decimal("44.8"), Decimal(45)),
        # Finer inputs go to tenths first, half up (DEC-0191): 5.15 -> 5.2 -> 5.5.
        (Decimal("5.15"), Decimal("5.5")),
        (Decimal("1.01"), Decimal(1)),
        # Never below the first band.
        (Decimal("0.1"), Decimal("0.5")),
        (Decimal("0.3"), Decimal("0.5")),
    ],
)
def test_rounding_follows_the_owners_rule_at_every_weight(raw, expected):
    assert cw.round_chargeable(raw) == (expected, False)


def test_volumetric_weight_with_the_air_divisor():
    # Divisor 6000 for every air product (OD-52). Quantized to three decimals, so memory
    # equals disk.
    assert cw.volumetric_weight(Decimal(100), Decimal(100), Decimal(100), 6000) == Decimal(
        "166.667"
    )


def test_missing_dimensions_mean_no_volumetric_weight_and_a_zero_weight_is_refused():
    assert cw.volumetric_weight(None, Decimal(1), Decimal(1), 6000) is None
    result = cw.chargeable_weight(Decimal("3.2"), divisor=6000)
    assert result.volumetric_kg is None and result.chargeable_kg == Decimal("3.5")
    with pytest.raises(ValueError):
        cw.chargeable_weight(Decimal(0), divisor=6000)
    with pytest.raises(ValueError):
        cw.volumetric_weight(Decimal(1), Decimal(1), Decimal(1), 0)
