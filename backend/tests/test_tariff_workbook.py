"""The Kango workbook reader and the strict price-text parser (Phase 13A).

Two fixtures. ``kango_canada_rates_2026-10-12_sanitized.xlsx`` is the vendor's 12 October
2026 workbook with its staff-directory sheet removed and its corporate header blanked
(``scripts/sanitize_kango_workbook.py``); every rate, zone, postal code and surcharge row is
as the vendor wrote it. ``kango_reference_v15.json`` is the v1.5 prototype's snapshot of
the same workbook, audited value-for-value against it (`docs/b2c_merge/02_KANGO_WORKBOOK_AUDIT.md`)
and kept here as an independent regression oracle.

The golden rows below are the issue register's: every defect the v1.5 parser had is a
test the new one must pass (`docs/b2c_merge/04_ISSUE_REGISTER.md` H-01 … H-09, M-08, L-05).
"""

from __future__ import annotations

import io
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from app.core.enums import SurchargeBasis, SurchargePricingStatus, SurchargeSection
from app.pricing import kango_semantics as semantics
from app.pricing.kango_workbook import (
    ParsedWorkbook,
    WorkbookLayoutError,
    dedupe_beyond_rates,
    parse_workbook,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
WORKBOOK = FIXTURES / "kango_canada_rates_2026-10-12_sanitized.xlsx"
REFERENCE = FIXTURES / "kango_reference_v15.json"


@pytest.fixture(scope="module")
def parsed() -> ParsedWorkbook:
    return parse_workbook(WORKBOOK.read_bytes())


@pytest.fixture(scope="module")
def reference() -> dict:
    return json.loads(REFERENCE.read_text(encoding="utf-8"))


# --- Shape --------------------------------------------------------------------------------


def test_counts_match_the_audit(parsed):
    assert parsed.counts() == {
        "products": 10,
        "rate_brackets": 616,  # 2 origins × (41 bands + 4 tiers) × 6 + 2 × 6 tiers × 6 + 4 trucking
        "zone_fsas": 1674,
        "beyond_postal_codes": 16200,
        "beyond_rates": 40,  # the same 8-row table printed on five sheets
        "surcharge_rows": 85,
        "surcharge_advisory_rows": 2,
        "anomalies": 39,  # 42 before the owner confirmed the three Express 16 kg drops
    }
    assert parsed.fixed_fx_vnd_per_cad == Decimal("19500")


def test_the_ten_products_and_which_waive_customs_surcharges(parsed):
    codes = Counter(p.code for p in parsed.products)
    assert codes == {
        "AIR-CAD": 2,
        "AIR-CAD EXPRESS": 2,
        "KSN-SEA-CAD-PURO": 2,
        "KSN-SEA-CAD-PURO-BH": 2,
        "KSN-SEA-CAD-TRUCKING": 2,
    }
    waived = {p.code for p in parsed.products if p.customs_surcharges_waived}
    assert waived == {"KSN-SEA-CAD-PURO-BH"}


def test_hanoi_sheet_offset_does_not_shift_the_bands(parsed):
    """HN-AIR-CAD has no hub-split row, so its table starts one row higher (audit §1)."""
    first_hcm = next(
        b
        for b in parsed.brackets
        if b.origin.value == "HCM"
        and b.product_code == "AIR-CAD"
        and b.kind == "per_bill"
        and b.zone == 1
    )
    first_han = next(
        b
        for b in parsed.brackets
        if b.origin.value == "HAN"
        and b.product_code == "AIR-CAD"
        and b.kind == "per_bill"
        and b.zone == 1
    )
    assert (first_hcm.label, first_hcm.cell) == ("0.5", "B8")
    assert (first_han.label, first_han.cell) == ("0.5", "B7")
    assert first_hcm.price_vnd == Decimal("306575.2")
    assert first_han.price_vnd == Decimal("297405.2")


# --- Equality with the independent snapshot ------------------------------------------------


def _price_map(parsed):
    out: dict[tuple[str, str, str, str], dict[int, Decimal]] = {}
    for b in parsed.brackets:
        out.setdefault((b.origin.value, b.product_code, b.kind, b.label), {})[b.zone] = b.price_vnd
    return out


def test_every_rate_cell_equals_the_v15_snapshot(parsed, reference):
    prices = _price_map(parsed)
    checked = 0
    for json_key, rows in reference["rates"].items():
        origin = "HCM" if json_key.startswith("HCM") else "HAN"
        sea = "SEA" in json_key
        kind = "per_kg" if (sea or "TIERS" in json_key) else "per_bill"
        ground, express = (
            ("KSN-SEA-CAD-PURO", "KSN-SEA-CAD-PURO-BH") if sea else ("AIR-CAD", "AIR-CAD EXPRESS")
        )
        for row in rows:
            label = str(row[0])
            if kind == "per_bill":
                value = float(label)
                label = str(int(value)) if value.is_integer() else label
            g = prices[(origin, ground, kind, label)]
            x = prices[(origin, express, kind, label)]
            ours = [g[1], g[2], g[3], x[1], x[2], x[3]]
            for mine, theirs in zip(ours, row[1:], strict=True):
                assert abs(mine - Decimal(str(theirs))) <= Decimal("0.01"), (json_key, label)
                checked += 1
    assert checked == 612


def test_zones_beyond_and_surcharge_text_equal_the_v15_snapshot(parsed, reference):
    zones = {z.fsa: [z.ground_zone, z.express_zone, z.province] for z in parsed.zone_fsas}
    assert zones == reference["zones"]
    beyond = {p.postal_code: p.beyond_code for p in parsed.beyond_postal_codes}
    assert beyond == {k: str(v) for k, v in reference["beyond"].items()}
    rates = {
        r.beyond_code: [float(r.base_cad), float(r.per_lb_cad)] for r in dedupe_beyond_rates(parsed)
    }
    assert rates == reference["beyondRates"]
    for theirs, mine in zip(reference["surcharges"], parsed.surcharge_rows, strict=True):
        assert theirs["name"].strip() == mine.name
        assert theirs["rule"].strip() == mine.price_text
        assert (theirs["note"] or "").strip() == (mine.note or "")


# --- Anomalies the reader must flag, not fix --------------------------------------------------


def test_anomalies_are_the_audits(parsed):
    codes = Counter(a.code for a in parsed.anomalies)
    assert codes == {
        "express_zone_below_ground": 35,
        "trucking_pallet_fees_not_imported": 2,
        "duplicate_fsa": 1,  # K1A, QC and ON (V-09)
        "beyond_code_without_rate": 1,  # code 180, 123 postal codes (V-05)
    }
    gap = next(a for a in parsed.anomalies if a.code == "beyond_code_without_rate")
    assert "180" in gap.message and "123 postal codes" in gap.message


def test_owner_confirmed_express_16kg_drops_are_informational_not_anomalies(parsed):
    """D-07 answered (Louis Tong, 2026-10-21, DEC-0222): follow the vendor sheet exactly."""
    assert not [a for a in parsed.anomalies if a.code == "price_falls_with_weight"]
    steps = {(s.sheet, s.cell): s for s in parsed.confirmed_price_steps}
    assert set(steps) == {
        ("HCM-AIR-CAD", "F39"),
        ("HN-AIR-CAD", "F38"),
        ("HN-AIR-CAD", "G38"),
    }
    for step in steps.values():
        assert step.product_code == "AIR-CAD EXPRESS" and step.label == "16"
        assert "DEC-0222" in step.reference and "cheaper than" in step.message
    # The band is still stored at the printed price (no smoothing).
    f39 = next(b for b in parsed.brackets if (b.sheet, b.cell) == ("HCM-AIR-CAD", "F39"))
    before = next(
        b
        for b in parsed.brackets
        if b.sheet == "HCM-AIR-CAD"
        and b.product_code == f39.product_code
        and b.kind == "per_bill"
        and b.zone == f39.zone
        and b.weight_to_kg == f39.weight_to_kg - Decimal("0.5")
    )
    assert f39.price_vnd < before.price_vnd


def test_an_unconfirmed_price_drop_is_still_an_anomaly():
    workbook = openpyxl.load_workbook(WORKBOOK)
    sheet = workbook["HCM-AIR-CAD"]
    # Ground zone 1 at 1.0 kg made cheaper than 0.5 kg: not on the confirmed list.
    sheet["B9"] = 1
    buffer = io.BytesIO()
    workbook.save(buffer)

    parsed = parse_workbook(buffer.getvalue())

    falls = [a for a in parsed.anomalies if a.code == "price_falls_with_weight"]
    assert [(a.sheet, a.cell) for a in falls] == [("HCM-AIR-CAD", "B9")]
    assert len(parsed.confirmed_price_steps) == 3


def test_a_confirmed_cell_that_changes_meaning_is_an_anomaly_again(monkeypatch):
    from app.pricing import kango_workbook

    moved = dict(kango_workbook.CONFIRMED_PRICE_STEPS)
    step = moved[("HCM-AIR-CAD", "F39")]
    moved[("HCM-AIR-CAD", "F39")] = kango_workbook.ConfirmedPriceStep(
        step.sheet, step.cell, step.product_code, step.zone, "15.5", step.reference
    )
    monkeypatch.setattr(kango_workbook, "CONFIRMED_PRICE_STEPS", moved)

    parsed = parse_workbook(WORKBOOK.read_bytes())

    falls = [a for a in parsed.anomalies if a.code == "price_falls_with_weight"]
    assert [(a.sheet, a.cell) for a in falls] == [("HCM-AIR-CAD", "F39")]


def test_a_different_drop_at_a_confirmed_cell_is_an_anomaly_again():
    """The confirmation pins the printed price: a new drop at the same cell is reviewed."""
    workbook = openpyxl.load_workbook(WORKBOOK)
    sheet = workbook["HCM-AIR-CAD"]
    sheet["F39"] = sheet["F39"].value - 1000  # still a drop, but not the confirmed price
    buffer = io.BytesIO()
    workbook.save(buffer)

    parsed = parse_workbook(buffer.getvalue())

    falls = [a for a in parsed.anomalies if a.code == "price_falls_with_weight"]
    assert ("HCM-AIR-CAD", "F39") in [(a.sheet, a.cell) for a in falls]
    assert {s.cell for s in parsed.confirmed_price_steps} == {"F38", "G38"}
    clean = parse_workbook(WORKBOOK.read_bytes())
    assert {s.as_dict()["price_vnd"] for s in clean.confirmed_price_steps} == {
        "5051007.30",
        "4757567.30",
        "4881875.75",
    }


def test_duplicate_fsa_keeps_the_later_row(parsed):
    k1a = [z for z in parsed.zone_fsas if z.fsa == "K1A"]
    assert len(k1a) == 1 and k1a[0].province == "ON"


# --- The staff directory is never read ----------------------------------------------------------


def test_a_staff_directory_sheet_is_skipped_by_name_and_never_read():
    workbook = openpyxl.load_workbook(WORKBOOK)
    sheet = workbook.create_sheet("DS SDT NV VẬN HÀNH")
    sheet["A1"] = "STT"
    sheet["B2"] = "A Person"
    sheet["E2"] = "0900000000"
    buffer = io.BytesIO()
    workbook.save(buffer)

    parsed = parse_workbook(buffer.getvalue())

    assert parsed.skipped_sheets == ["DS SDT NV VẬN HÀNH"]
    everything = json.dumps(
        [a.as_dict() for a in parsed.anomalies]
        + [[r.sheet, r.cell, r.text] for r in parsed.rule_texts]
        + [[s.name, s.price_text, s.note] for s in parsed.surcharge_rows],
        ensure_ascii=False,
    )
    assert "A Person" not in everything and "0900000000" not in everything


def _workbook_with(edit) -> bytes:
    workbook = openpyxl.load_workbook(WORKBOOK)
    edit(workbook)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_a_row_the_reader_does_not_understand_between_the_bands_is_a_refusal():
    """Review finding 2: a stray text cell inside the 0.5–20.5 kg table must not silently
    drop every band after it."""

    def edit(workbook):
        workbook["HCM-AIR-CAD"]["A30"] = "10,5"  # a comma-decimal label the reader rejects

    with pytest.raises(WorkbookLayoutError, match="between the last weight band"):
        parse_workbook(_workbook_with(edit))


def test_a_gap_in_the_fsa_list_is_a_refusal():
    def edit(workbook):
        workbook["Zone CAD"]["N500"] = None

    with pytest.raises(WorkbookLayoutError, match="has a gap at row 500"):
        parse_workbook(_workbook_with(edit))


def test_a_repeated_row_number_within_a_surcharge_section_is_a_refusal():
    def edit(workbook):
        workbook["PHỤ THU"]["A12"] = 2  # row 12 is STT 3; now there are two STT 2

    with pytest.raises(WorkbookLayoutError, match="repeats within its section"):
        parse_workbook(_workbook_with(edit))


def test_a_workbook_without_the_expected_sheets_is_refused():
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "not a tariff"
    buffer = io.BytesIO()
    workbook.save(buffer)
    with pytest.raises(WorkbookLayoutError):
        parse_workbook(buffer.getvalue())
    with pytest.raises(WorkbookLayoutError):
        parse_workbook(b"not even a zip file")


# --- The strict price-text parser ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "status", "basis", "amount"),
    [
        ("30.000/Kg", SurchargePricingStatus.PRICED, SurchargeBasis.PER_KG, 30_000),
        ("300.000 / Kiện", SurchargePricingStatus.PRICED, SurchargeBasis.PER_PIECE, 300_000),
        ("1.200.000 / cái", SurchargePricingStatus.PRICED, SurchargeBasis.PER_UNIT, 1_200_000),
        ("50.000/Đôi", SurchargePricingStatus.PRICED, SurchargeBasis.PER_PAIR, 50_000),
        ("50.000đ/cặp", SurchargePricingStatus.PRICED, SurchargeBasis.PER_PAIR, 50_000),
        ("50.000/Hộp", SurchargePricingStatus.PRICED, SurchargeBasis.PER_BOX, 50_000),
        ("550.000/1 Lô Hàng", SurchargePricingStatus.PRICED, SurchargeBasis.PER_SHIPMENT, 550_000),
        ("5000/kg", SurchargePricingStatus.PRICED, SurchargeBasis.PER_KG, 5_000),
        ("10,000/kg", SurchargePricingStatus.PRICED, SurchargeBasis.PER_KG, 10_000),
        ("Miễn phụ thu", SurchargePricingStatus.FREE, SurchargeBasis.FREE, None),
    ],
)
def test_unambiguous_prices_parse(text, status, basis, amount):
    result = semantics.parse_price_text(text)
    assert (result.status, result.basis) == (status, basis)
    assert result.unit_price_vnd == (Decimal(amount) if amount is not None else None)


@pytest.mark.parametrize(
    "text",
    [
        "10.000/1kg",  # H-01: v1.5 read the "1" before the unit as the rate
        "100.000/1kg",
        "1.000.000/1 Kiện",
        "500.000 /1 Kiện",
        "20,000/1kg",
    ],
)
def test_a_one_before_the_unit_is_not_the_price(text):
    """Issue H-01. Five rules were priced at 1 VND by the prototype."""
    result = semantics.parse_price_text(text)
    assert result.status == SurchargePricingStatus.PRICED
    assert result.unit_price_vnd >= Decimal(10_000)


@pytest.mark.parametrize(
    "text",
    [
        "Dự kiến >700.000/kiện",  # H-02: an estimate is not a price
        "Dự kiến >100.000/ cái",
        "300 - 700.000/Kiện ",  # a range
        "500.000-1.000.000/Cái",
        "100 - 300.000/Kiện ( Case by case)",
        "100-300.000/Kg",
        "500 - 1.000.000/Máy",
        "1 - 2.000.000/Máy",
        "50.000 to 500.000/ Con",
    ],
)
def test_ranges_and_estimates_are_refused(text):
    result = semantics.parse_price_text(text)
    assert result.status == SurchargePricingStatus.UNPRICED_VENDOR_REVIEW
    assert result.unit_price_vnd is None


def test_a_compound_price_is_refused_by_the_parser_and_supplied_by_review():
    """Issue H-03. ``300.000/Kiện + 50.000/Chai`` lost its per-bottle half in v1.5."""
    result = semantics.parse_price_text("300.000/Kiện + 50.000/Chai")
    assert result.status == SurchargePricingStatus.UNPRICED_VENDOR_REVIEW
    assert result.basis == SurchargeBasis.COMPOUND
    curated = semantics.CURATED_RULES[(SurchargeSection.HCM_AIR, 11)]
    assert curated.per_unit_price_vnd == Decimal(50_000)
    assert curated.per_unit_label == "bottle"
    assert [t.price_vnd for t in curated.tiers] == [
        Decimal(300_000),
        Decimal(500_000),
        Decimal(700_000),
    ]


def test_a_minimum_charge_is_read_from_the_price_text():
    result = semantics.parse_price_text("200.000/ Kg ( Min thu 1Kg )")
    assert result.status == SurchargePricingStatus.PRICED
    assert result.unit_price_vnd == Decimal(200_000)
    assert result.min_charge_kg == Decimal(1)


def test_every_price_string_in_the_workbook_is_either_parsed_or_curated(parsed):
    """No row may fall through as 'price text not understood'. Either the parser reads it,
    the parser refuses it for a stated reason, or the curated table covers it."""
    for row in parsed.surcharge_rows:
        result = semantics.parse_price_text(row.price_text)
        curated = (row.section, row.stt) in semantics.CURATED_RULES
        assert result.reason != "price text not understood" or curated, (
            row.section,
            row.stt,
            row.price_text,
        )
