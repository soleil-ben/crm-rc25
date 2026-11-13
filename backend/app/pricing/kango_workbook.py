"""Read a Kango Canada tariff workbook into typed rows, each with its source cell.

**Pure.** Takes bytes, returns dataclasses. No database, no clock, no logging of cell
contents. The importer service decides what to do with the result.

**Anchored on labels, not row numbers.** The Hà Nội air sheet is the HCM sheet shifted up
one row (it has no hub-split line), so a reader that hard-coded rows would price Hà Nội
off by one band. Every table here is found by the header text the vendor uses -- the
``WEIGHT (KGS)`` row, the ``Từ 21 Kgs`` line, the ``Beyond Code`` header, the ``STT``
header -- and read until the data stops. A sheet whose anchors cannot be found is a
refusal (``WorkbookLayoutError``), not a best effort.

**Cached values only.** The workbook is opened with ``data_only=True``; no formula is
evaluated. The zone sheet's calculator block (a few thousand formulas over empty inputs,
most of them ``#VALUE!``) is never read.

**The staff directory is never read.** Any sheet whose name starts with ``DS SDT`` is
excluded by name from every table the reader looks at (openpyxl still parses the file's
sheets into memory when it opens the workbook; this module never touches that sheet's
cells), and the corporate contact block in cell ``B1`` of the rate sheets is never read
either. Nothing this module returns can carry a person's name or telephone number.

**What is read:** the two air rate sheets (per-bill bands, per-kg tiers, beyond table,
fixed FX, and the rule text the semantics module interprets), the two sea rate sheets
(per-kg tiers for the two Purolator products and the trucking per-kg pair), the zone
sheet (FSA zones, beyond postal codes, beyond rates), and the surcharge sheet (every
priced row with its section, number, name, price text and note). The compensation policy
sheet is prose and is not read.

**What is flagged, not fixed:** a price column that goes down as weight goes up, a
duplicate FSA, a beyond code with postal codes but no rate, an Express zone below the
Ground zone. These are the vendor's numbers; the importer stores them as written and
records the anomaly for review (`docs/b2c_merge/05_OPEN_DECISIONS.md`, V-05 to V-09).
A price drop the owner has confirmed as intended (the Express 16 kg step, D-07, DEC-0222) is
listed in :data:`CONFIRMED_PRICE_STEPS` and reported as a confirmed step, not an anomaly.
"""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

from app.core.enums import (
    SurchargeSection,
    TariffLastMile,
    TariffOrigin,
    TariffProductMode,
)

#: Sheets never opened. Name prefix, case-insensitive. The vendor's operations staff
#: directory with personal mobile numbers lives behind this prefix.
NEVER_READ_SHEET_PREFIXES = ("DS SDT",)

AIR_SHEET = re.compile(r"^(HCM|HN)-AIR-CAD$")
SEA_SHEET = re.compile(r"^(HCM|HN)-SEA-CAD$")
ZONE_SHEET_NAME = "Zone CAD"
SURCHARGE_SHEET_HINT = "PHỤ THU"

ORIGIN_BY_SHEET_PREFIX = {"HCM": TariffOrigin.HCM, "HN": TariffOrigin.HAN}

PER_BILL_BAND_STEP = Decimal("0.5")
TIER_LABEL = re.compile(r"^(\d+)\s*-\s*(\d+)$")
OPEN_TIER_LABEL = re.compile(r"^(\d+)\s*(?:KGS?|kG)?\s*\+$", re.IGNORECASE)
SECTION_TITLE = re.compile(r"^(\d)/\s*(.+)$")
FIXED_FX = re.compile(r"1\s*\$?CAD\s*=\s*([\d.,]+)")
FIXED_FX_LOOSE = re.compile(r"CAD\s*~+\s*([\d.,]+)")

#: Section order on the surcharge sheet. The importer checks the heading text agrees.
SECTION_BY_INDEX = {
    1: SurchargeSection.HCM_AIR,
    2: SurchargeSection.HAN_AIR,
    3: SurchargeSection.SEA_CA_AU_UK_EU,
    4: SurchargeSection.SEA_USA,
}
SECTION_HEADING_HINTS = {
    SurchargeSection.HCM_AIR: ("BAY", "HCM"),
    SurchargeSection.HAN_AIR: ("BAY", "NỘI"),
    SurchargeSection.SEA_CA_AU_UK_EU: ("BIỂN", "CANADA"),
    SurchargeSection.SEA_USA: ("BIỂN", "USA"),
}


class WorkbookLayoutError(ValueError):
    """The workbook is not laid out the way the reader expects. Nothing is guessed."""


@dataclass(frozen=True)
class Anomaly:
    code: str
    message: str
    sheet: str | None = None
    cell: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "sheet": self.sheet, "cell": self.cell}


@dataclass(frozen=True)
class ParsedProduct:
    code: str
    origin: TariffOrigin
    mode: TariffProductMode
    last_mile: TariffLastMile
    sheet: str
    transit_text: str | None
    customs_surcharges_waived: bool


@dataclass(frozen=True)
class ParsedBracket:
    product_code: str
    origin: TariffOrigin
    kind: str  # RateBracketKind value
    zone: int
    label: str
    weight_from_kg: Decimal | None
    weight_to_kg: Decimal | None
    price_vnd: Decimal
    sheet: str
    cell: str


@dataclass(frozen=True)
class ParsedZoneFsa:
    fsa: str
    province: str | None
    ground_zone: int
    express_zone: int
    row: int


@dataclass(frozen=True)
class ParsedBeyondPostalCode:
    postal_code: str
    city: str | None
    province: str | None
    beyond_code: str
    row: int


@dataclass(frozen=True)
class ParsedBeyondRate:
    beyond_code: str
    base_cad: Decimal
    per_lb_cad: Decimal
    sheet: str
    cell: str


@dataclass(frozen=True)
class ParsedSurchargeRow:
    section: SurchargeSection
    section_label: str
    stt: int
    name: str
    price_text: str
    note: str | None
    sheet: str
    row: int


@dataclass(frozen=True)
class RuleText:
    """A prose cell the semantics module interprets. Kept with its address."""

    sheet: str
    cell: str
    text: str


@dataclass
class ParsedWorkbook:
    source_sha256: str
    sheet_names: list[str]
    skipped_sheets: list[str]
    products: list[ParsedProduct] = field(default_factory=list)
    brackets: list[ParsedBracket] = field(default_factory=list)
    zone_fsas: list[ParsedZoneFsa] = field(default_factory=list)
    beyond_postal_codes: list[ParsedBeyondPostalCode] = field(default_factory=list)
    beyond_rates: list[ParsedBeyondRate] = field(default_factory=list)
    surcharge_rows: list[ParsedSurchargeRow] = field(default_factory=list)
    #: Advisory rows on the surcharge sheet (a number, a sentence, no price). Counted so a
    #: reviewer can see they were seen and deliberately not priced.
    surcharge_advisory_rows: list[tuple[str, int, str]] = field(default_factory=list)
    rule_texts: list[RuleText] = field(default_factory=list)
    fixed_fx_vnd_per_cad: Decimal | None = None
    anomalies: list[Anomaly] = field(default_factory=list)
    #: Price drops the owner has confirmed as the vendor's intended rate (informational).
    confirmed_price_steps: list[ConfirmedPriceStep] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {
            "products": len(self.products),
            "rate_brackets": len(self.brackets),
            "zone_fsas": len(self.zone_fsas),
            "beyond_postal_codes": len(self.beyond_postal_codes),
            "beyond_rates": len(self.beyond_rates),
            "surcharge_rows": len(self.surcharge_rows),
            "surcharge_advisory_rows": len(self.surcharge_advisory_rows),
            "anomalies": len(self.anomalies),
        }


# --- Small helpers ---------------------------------------------------------------


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _fold(value: str) -> str:
    """Upper-case, accent-stripped, for anchor matching only. Never stored."""
    decomposed = unicodedata.normalize("NFD", value)
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return stripped.replace("đ", "d").replace("Đ", "D").upper()


def _decimal(value: Any, *, sheet: str, cell: str) -> Decimal:
    """A cell that must hold a number. Vietnamese thousands separators are accepted."""
    if isinstance(value, bool) or value is None:
        raise WorkbookLayoutError(f"{sheet}!{cell}: expected a number, found {value!r}")
    if isinstance(value, int | float | Decimal):
        return Decimal(str(value))
    raw = _text(value).replace(" ", "")
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", raw):
        raw = re.sub(r"[.,]", "", raw)
    else:
        raw = raw.replace(",", ".")
    try:
        return Decimal(raw)
    except InvalidOperation as error:
        raise WorkbookLayoutError(f"{sheet}!{cell}: expected a number, found {value!r}") from error


def _is_number(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, int | float | Decimal):
        return True
    return bool(re.fullmatch(r"\d+(\.\d+)?", _text(value)))


def _refuse_trailing_rows(
    ws: Worksheet, *, column: int, start: int, what: str, lookahead: int = 50
) -> None:
    """A list that stopped must really have ended.

    A blank cell followed by more data means the reader stopped early, and stopping early
    silently is the one thing it must not do.
    """
    for row in range(start, min(start + lookahead, ws.max_row) + 1):
        if _text(ws.cell(row, column).value):
            raise WorkbookLayoutError(
                f"{ws.title}: the {what} has a gap at row {start} but continues at row {row}"
            )


def _find_row(
    ws: Worksheet, column: int, predicate, *, start: int = 1, stop: int | None = None
) -> int:
    stop = stop or ws.max_row
    for row in range(start, stop + 1):
        if predicate(_text(ws.cell(row, column).value)):
            return row
    raise WorkbookLayoutError(f"{ws.title}: anchor not found in column {column}")


# --- Air sheets -------------------------------------------------------------------


def _read_air_sheet(ws: Worksheet, parsed: ParsedWorkbook) -> None:
    sheet = ws.title
    origin = ORIGIN_BY_SHEET_PREFIX[AIR_SHEET.match(sheet).group(1)]

    header_row = _find_row(ws, 1, lambda t: _fold(t).startswith("WEIGHT"))
    if header_row < 4:
        raise WorkbookLayoutError(
            f"{sheet}: the weight header sits at row {header_row}; the product, zone and "
            "last-mile rows above it are missing"
        )
    code_row = header_row - 2
    zone_row = header_row - 1
    lastmile_row = header_row - 3
    ground_code = _text(ws.cell(code_row, 2).value)
    express_code = _text(ws.cell(code_row, 5).value)
    if not ground_code or not express_code:
        raise WorkbookLayoutError(f"{sheet}: product codes not found above the weight header")

    products = (
        (ground_code, 2, TariffLastMile.PUROLATOR_GROUND, _text(ws.cell(lastmile_row, 2).value)),
        (express_code, 5, TariffLastMile.PUROLATOR_EXPRESS, _text(ws.cell(lastmile_row, 5).value)),
    )
    for code, _col, last_mile, transit in products:
        parsed.products.append(
            ParsedProduct(
                code=code,
                origin=origin,
                mode=TariffProductMode.AIR,
                last_mile=last_mile,
                sheet=sheet,
                transit_text=transit or None,
                customs_surcharges_waived=False,
            )
        )

    zones: dict[int, int] = {}
    for col in range(2, 8):
        zones[col] = int(
            _decimal(
                ws.cell(zone_row, col).value, sheet=sheet, cell=ws.cell(zone_row, col).coordinate
            )
        )

    # Per-bill bands: from the row after the header while column A is numeric.
    row = header_row + 1
    previous_bound: Decimal | None = None
    band_count = 0
    while _is_number(ws.cell(row, 1).value):
        bound = _decimal(ws.cell(row, 1).value, sheet=sheet, cell=f"A{row}")
        for code, col0, _lm, _t in products:
            for offset in range(3):
                col = col0 + offset
                cell = ws.cell(row, col)
                parsed.brackets.append(
                    ParsedBracket(
                        product_code=code,
                        origin=origin,
                        kind="per_bill",
                        zone=zones[col],
                        label=_text(ws.cell(row, 1).value),
                        weight_from_kg=previous_bound,
                        weight_to_kg=bound,
                        price_vnd=_decimal(cell.value, sheet=sheet, cell=cell.coordinate),
                        sheet=sheet,
                        cell=cell.coordinate,
                    )
                )
        previous_bound = bound
        band_count += 1
        row += 1
    if band_count == 0:
        raise WorkbookLayoutError(f"{sheet}: no per-bill weight bands found")

    # Per-kg tiers: after the "Từ 21 Kgs" line, while column A looks like a tier label.
    tier_intro = _find_row(ws, 1, lambda t: _fold(t).startswith("TU 21"), start=row)
    if tier_intro != row:
        raise WorkbookLayoutError(
            f"{sheet}: rows {row}-{tier_intro - 1} between the last weight band and the "
            "21 kg line were not understood"
        )
    row = tier_intro + 1
    tier_count = 0
    while True:
        label = _text(ws.cell(row, 1).value)
        bounds = _tier_bounds(label)
        if bounds is None:
            break
        for code, col0, _lm, _t in products:
            for offset in range(3):
                col = col0 + offset
                cell = ws.cell(row, col)
                parsed.brackets.append(
                    ParsedBracket(
                        product_code=code,
                        origin=origin,
                        kind="per_kg",
                        zone=zones[col],
                        label=label,
                        weight_from_kg=bounds[0],
                        weight_to_kg=bounds[1],
                        price_vnd=_decimal(cell.value, sheet=sheet, cell=cell.coordinate),
                        sheet=sheet,
                        cell=cell.coordinate,
                    )
                )
        tier_count += 1
        row += 1
    if tier_count == 0:
        raise WorkbookLayoutError(f"{sheet}: no per-kg tiers found after the 21 kg line")

    # Rule text the semantics module interprets: the piece-minimum line right after the
    # tiers, and every "-" / "+" note line in column B.
    piece_rule = _text(ws.cell(row, 1).value)
    if piece_rule:
        parsed.rule_texts.append(RuleText(sheet, f"A{row}", piece_rule))
    for r in range(row, ws.max_row + 1):
        marker = _text(ws.cell(r, 1).value)
        body = _text(ws.cell(r, 2).value)
        if marker in {"-", "+"} and body:
            parsed.rule_texts.append(RuleText(sheet, f"B{r}", body))
        title = _text(ws.cell(r, 1).value)
        fx = _parse_fixed_fx(title)
        if fx is not None:
            _record_fixed_fx(parsed, fx, sheet, f"A{r}")

    _read_beyond_rate_table(ws, parsed, start=row)


def _tier_bounds(label: str) -> tuple[Decimal, Decimal | None] | None:
    match = TIER_LABEL.match(label)
    if match:
        return Decimal(match.group(1)), Decimal(match.group(2))
    match = OPEN_TIER_LABEL.match(label)
    if match:
        return Decimal(match.group(1)), None
    return None


def _parse_fixed_fx(text: str) -> Decimal | None:
    if not text:
        return None
    for pattern in (FIXED_FX, FIXED_FX_LOOSE):
        match = pattern.search(text)
        if match:
            raw = match.group(1).rstrip(".,")
            return _decimal(raw, sheet="", cell="")
    return None


def _record_fixed_fx(parsed: ParsedWorkbook, value: Decimal, sheet: str, cell: str) -> None:
    if parsed.fixed_fx_vnd_per_cad is None:
        parsed.fixed_fx_vnd_per_cad = value
    elif parsed.fixed_fx_vnd_per_cad != value:
        parsed.anomalies.append(
            Anomaly(
                "fixed_fx_disagrees",
                f"fixed CAD rate {value} differs from {parsed.fixed_fx_vnd_per_cad} read earlier",
                sheet,
                cell,
            )
        )


def _read_beyond_rate_table(ws: Worksheet, parsed: ParsedWorkbook, *, start: int) -> None:
    """The ``Beyond Code / Base Beyond Rate / Số lb x giá`` table, wherever it sits."""
    try:
        header = _find_row(ws, 2, lambda t: _fold(t) == "BEYOND CODE", start=start)
    except WorkbookLayoutError:
        return
    row = header + 1
    while _is_number(ws.cell(row, 2).value):
        code = str(int(_decimal(ws.cell(row, 2).value, sheet=ws.title, cell=f"B{row}")))
        parsed.beyond_rates.append(
            ParsedBeyondRate(
                beyond_code=code,
                base_cad=_decimal(ws.cell(row, 3).value, sheet=ws.title, cell=f"C{row}"),
                per_lb_cad=_decimal(ws.cell(row, 4).value, sheet=ws.title, cell=f"D{row}"),
                sheet=ws.title,
                cell=f"B{row}",
            )
        )
        row += 1


# --- Sea sheets -------------------------------------------------------------------


def _read_sea_sheet(ws: Worksheet, parsed: ParsedWorkbook) -> None:
    sheet = ws.title
    origin = ORIGIN_BY_SHEET_PREFIX[SEA_SHEET.match(sheet).group(1)]

    code_row = _find_row(ws, 1, lambda t: _fold(t).startswith("DICH VU TAO BILL"))
    puro_code = _text(ws.cell(code_row, 2).value)
    bh_code = _text(ws.cell(code_row, 5).value)
    trucking_code = _text(ws.cell(code_row, 8).value)
    if not (puro_code and bh_code and trucking_code):
        raise WorkbookLayoutError(f"{sheet}: three sea product codes expected on the bill row")

    transit_row = code_row + 3
    transit = " / ".join(
        t for t in (_text(ws.cell(transit_row, 2).value), _text(ws.cell(transit_row, 3).value)) if t
    )
    parsed.products.extend(
        [
            ParsedProduct(
                puro_code,
                origin,
                TariffProductMode.SEA,
                TariffLastMile.PUROLATOR_GROUND,
                sheet,
                transit or None,
                False,
            ),
            ParsedProduct(
                bh_code,
                origin,
                TariffProductMode.SEA,
                TariffLastMile.PUROLATOR_GROUND,
                sheet,
                transit or None,
                True,
            ),
            ParsedProduct(
                trucking_code,
                origin,
                TariffProductMode.SEA,
                TariffLastMile.TRUCKING,
                sheet,
                None,
                False,
            ),
        ]
    )

    # Per-kg tiers for the two Purolator products: rows after the transit line whose
    # column A is a tier label.
    row = transit_row + 1
    tier_count = 0
    while True:
        label = _text(ws.cell(row, 1).value)
        bounds = _tier_bounds(label)
        if bounds is None:
            break
        for code, col0 in ((puro_code, 2), (bh_code, 5)):
            for offset in range(3):
                cell = ws.cell(row, col0 + offset)
                parsed.brackets.append(
                    ParsedBracket(
                        code,
                        origin,
                        "per_kg",
                        offset + 1,
                        label,
                        bounds[0],
                        bounds[1],
                        _decimal(cell.value, sheet=sheet, cell=cell.coordinate),
                        sheet,
                        cell.coordinate,
                    )
                )
        tier_count += 1
        row += 1
    if tier_count == 0:
        raise WorkbookLayoutError(f"{sheet}: no sea per-kg tiers found")

    # Trucking: two per-kg prices on the row after the transit header, labelled on the
    # row above them ("100-299Kg … Min 100kg", "300-2000KG"). Zone 0 = not zoned.
    for col in (9, 10):
        label_cell = ws.cell(transit_row - 1, col)
        price_cell = ws.cell(transit_row, col)
        label = _text(label_cell.value).split("\n")[0].replace("Kg", "").replace("KG", "").strip()
        bounds = _tier_bounds(label)
        if bounds is None or not _is_number(price_cell.value):
            parsed.anomalies.append(
                Anomaly(
                    "trucking_tier_unreadable",
                    f"trucking tier label {label!r} not understood",
                    sheet,
                    label_cell.coordinate,
                )
            )
            continue
        parsed.brackets.append(
            ParsedBracket(
                trucking_code,
                origin,
                "per_kg",
                0,
                label,
                bounds[0],
                bounds[1],
                _decimal(price_cell.value, sheet=sheet, cell=price_cell.coordinate),
                sheet,
                price_cell.coordinate,
            )
        )
    parsed.anomalies.append(
        Anomaly(
            "trucking_pallet_fees_not_imported",
            "trucking pallet delivery fees (C$ by pallet count and area) are quoted per case "
            "and were not imported",
            sheet,
            f"K{transit_row}",
        )
    )

    # Rule text and fixed FX.
    piece_rule_row = row
    piece_rule = _text(ws.cell(piece_rule_row, 1).value)
    if piece_rule:
        parsed.rule_texts.append(RuleText(sheet, f"A{piece_rule_row}", piece_rule))
    for r in range(piece_rule_row, ws.max_row + 1):
        marker = _text(ws.cell(r, 1).value)
        body = _text(ws.cell(r, 2).value)
        if marker in {"-", "+"} and body:
            parsed.rule_texts.append(RuleText(sheet, f"B{r}", body))
        fx = _parse_fixed_fx(body) if _fold(marker) == "CANADA" else None
        if fx is not None:
            _record_fixed_fx(parsed, fx, sheet, f"B{r}")

    _read_beyond_rate_table(ws, parsed, start=piece_rule_row)


# --- Zone sheet -------------------------------------------------------------------


def _read_zone_sheet(ws: Worksheet, parsed: ParsedWorkbook) -> None:
    sheet = ws.title
    header = 2
    expected = {14: "BA CHU SO DAU", 19: "CITY", 21: "POSTAL CODE", 24: "BEYOND CODE"}
    for col, hint in expected.items():
        if not _fold(_text(ws.cell(header, col).value)).startswith(hint):
            raise WorkbookLayoutError(
                f"{sheet}: header {hint!r} not found at row {header} column {col}"
            )

    seen_fsa: dict[str, int] = {}
    row = header + 1
    while _text(ws.cell(row, 14).value):
        fsa = _text(ws.cell(row, 14).value).upper()
        province = _text(ws.cell(row, 15).value).upper() or None
        ground = int(_decimal(ws.cell(row, 16).value, sheet=sheet, cell=f"P{row}"))
        express = int(_decimal(ws.cell(row, 17).value, sheet=sheet, cell=f"Q{row}"))
        if fsa in seen_fsa:
            parsed.anomalies.append(
                Anomaly(
                    "duplicate_fsa",
                    f"FSA {fsa} listed again (first at row {seen_fsa[fsa]}); the later row is kept",
                    sheet,
                    f"N{row}",
                )
            )
            parsed.zone_fsas = [z for z in parsed.zone_fsas if z.fsa != fsa]
        seen_fsa[fsa] = row
        if express < ground:
            parsed.anomalies.append(
                Anomaly(
                    "express_zone_below_ground",
                    f"FSA {fsa}: Express zone {express} is lower than Ground zone {ground}",
                    sheet,
                    f"Q{row}",
                )
            )
        parsed.zone_fsas.append(ParsedZoneFsa(fsa, province, ground, express, row))
        row += 1
    _refuse_trailing_rows(ws, column=14, start=row, what="FSA zone list")

    seen_postal: set[str] = set()
    row = header + 1
    while _text(ws.cell(row, 21).value):
        postal = _text(ws.cell(row, 21).value).upper().replace(" ", "")
        code = _text(ws.cell(row, 22).value)
        if _is_number(code):
            code = str(int(_decimal(code, sheet=sheet, cell=f"V{row}")))
        if postal in seen_postal:
            parsed.anomalies.append(
                Anomaly(
                    "duplicate_beyond_postal_code",
                    f"postal code {postal} listed twice",
                    sheet,
                    f"U{row}",
                )
            )
        else:
            seen_postal.add(postal)
            parsed.beyond_postal_codes.append(
                ParsedBeyondPostalCode(
                    postal,
                    _text(ws.cell(row, 19).value) or None,
                    _text(ws.cell(row, 20).value).upper() or None,
                    code,
                    row,
                )
            )
        row += 1
    _refuse_trailing_rows(ws, column=21, start=row, what="beyond postal code list")

    row = header + 1
    while _is_number(ws.cell(row, 24).value):
        code = str(int(_decimal(ws.cell(row, 24).value, sheet=sheet, cell=f"X{row}")))
        rate = ParsedBeyondRate(
            code,
            _decimal(ws.cell(row, 25).value, sheet=sheet, cell=f"Y{row}"),
            _decimal(ws.cell(row, 26).value, sheet=sheet, cell=f"Z{row}"),
            sheet,
            f"X{row}",
        )
        parsed.beyond_rates.append(rate)
        row += 1


# --- Surcharge sheet --------------------------------------------------------------


def _read_surcharge_sheet(ws: Worksheet, parsed: ParsedWorkbook) -> None:
    sheet = ws.title
    section: SurchargeSection | None = None
    section_label = ""
    for row in range(1, ws.max_row + 1):
        a = ws.cell(row, 1).value
        a_text = _text(a)
        title = SECTION_TITLE.match(a_text)
        if title and not _is_number(a):
            index = int(title.group(1))
            section = SECTION_BY_INDEX.get(index)
            if section is None:
                raise WorkbookLayoutError(f"{sheet}!A{row}: unexpected surcharge section {index}")
            folded = _fold(a_text)
            if not all(_fold(h) in folded for h in SECTION_HEADING_HINTS[section]):
                raise WorkbookLayoutError(
                    f"{sheet}!A{row}: section {index} heading does not read as expected"
                )
            section_label = a_text
            continue
        if section is None or not _is_number(a):
            continue
        stt = int(_decimal(a, sheet=sheet, cell=f"A{row}"))
        name = _text(ws.cell(row, 2).value)
        price = _text(ws.cell(row, 3).value)
        note = _text(ws.cell(row, 4).value) or None
        if not price:
            parsed.surcharge_advisory_rows.append((section.value, stt, name))
            continue
        if any(r.section == section and r.stt == stt for r in parsed.surcharge_rows):
            raise WorkbookLayoutError(
                f"{sheet}!A{row}: row number {stt} repeats within its section"
            )
        parsed.surcharge_rows.append(
            ParsedSurchargeRow(section, section_label, stt, name, price, note, sheet, row)
        )
    if not parsed.surcharge_rows:
        raise WorkbookLayoutError(f"{sheet}: no surcharge rows found")
    # The sheet's preamble and footer are rules in their own right.
    for row in (1, 2, 3, 4, 5, ws.max_row):
        for column, letter in ((1, "A"), (2, "B")):
            text = _text(ws.cell(row, column).value)
            if text and _fold(text) != "LUU Y":
                parsed.rule_texts.append(RuleText(sheet, f"{letter}{row}", text))


# --- Cross-table checks -----------------------------------------------------------


@dataclass(frozen=True)
class ConfirmedPriceStep:
    """A per-bill price drop the owner has confirmed is the vendor's intended rate."""

    sheet: str
    cell: str
    product_code: str
    zone: int
    label: str
    reference: str
    message: str = ""
    #: The price the owner confirmed (VND, to the cent). A different drop at the same cell is
    #: an anomaly again (independent review).
    price_vnd: Decimal | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "sheet": self.sheet,
            "cell": self.cell,
            "product_code": self.product_code,
            "zone": self.zone,
            "label": self.label,
            "reference": self.reference,
            "message": self.message,
            "price_vnd": str(self.price_vnd) if self.price_vnd is not None else None,
        }


_EXPRESS_16KG_REFERENCE = (
    "Owner decision (Louis Tong, 2026-10-21), DEC-0222, answering D-07: the Express drop at "
    "16 kg is correct; price exactly as the vendor rate sheet prints it"
)

#: Owner-confirmed price drops, keyed by (sheet, cell). The product, zone and band must also
#: match, so a reworked sheet whose cell now means something else is an anomaly again. Any
#: drop not listed here stays a ``price_falls_with_weight`` anomaly.
CONFIRMED_PRICE_STEPS: dict[tuple[str, str], ConfirmedPriceStep] = {
    (s.sheet, s.cell): s
    for s in (
        ConfirmedPriceStep(
            "HCM-AIR-CAD",
            "F39",
            "AIR-CAD EXPRESS",
            2,
            "16",
            _EXPRESS_16KG_REFERENCE,
            price_vnd=Decimal("5051007.30"),
        ),
        ConfirmedPriceStep(
            "HN-AIR-CAD",
            "F38",
            "AIR-CAD EXPRESS",
            2,
            "16",
            _EXPRESS_16KG_REFERENCE,
            price_vnd=Decimal("4757567.30"),
        ),
        ConfirmedPriceStep(
            "HN-AIR-CAD",
            "G38",
            "AIR-CAD EXPRESS",
            3,
            "16",
            _EXPRESS_16KG_REFERENCE,
            price_vnd=Decimal("4881875.75"),
        ),
    )
}


def _confirmed_step(bracket: ParsedBracket) -> ConfirmedPriceStep | None:
    step = CONFIRMED_PRICE_STEPS.get((bracket.sheet, bracket.cell))
    if step is None:
        return None
    if (step.product_code, step.zone, step.label) != (
        bracket.product_code,
        bracket.zone,
        bracket.label,
    ):
        return None
    printed = Decimal(str(bracket.price_vnd)).quantize(Decimal("0.01"))
    if step.price_vnd is None or printed != step.price_vnd:
        return None  # the owner confirmed a different price: review it again
    return step


def _check_price_monotonicity(parsed: ParsedWorkbook) -> None:
    """Within one product and zone, a heavier band should never be cheaper.

    A drop the owner has confirmed (:data:`CONFIRMED_PRICE_STEPS`) is recorded in
    ``parsed.confirmed_price_steps`` instead of as an anomaly; it is priced as printed.
    """
    by_column: dict[tuple[str, TariffOrigin, str, int], list[ParsedBracket]] = {}
    for bracket in parsed.brackets:
        by_column.setdefault(
            (bracket.product_code, bracket.origin, bracket.kind, bracket.zone), []
        ).append(bracket)
    for key, rows in by_column.items():
        if key[2] != "per_bill":
            continue  # per-kg tiers legitimately fall as weight rises
        ordered = sorted(rows, key=lambda b: b.weight_to_kg or Decimal(0))
        for earlier, later in zip(ordered, ordered[1:], strict=False):
            if later.price_vnd < earlier.price_vnd:
                message = (
                    f"{key[0]} {key[1].value} zone {key[3]}: {later.label} kg "
                    f"({later.price_vnd}) is cheaper than {earlier.label} kg "
                    f"({earlier.price_vnd})"
                )
                confirmed = _confirmed_step(later)
                if confirmed is not None:
                    parsed.confirmed_price_steps.append(
                        ConfirmedPriceStep(
                            confirmed.sheet,
                            confirmed.cell,
                            confirmed.product_code,
                            confirmed.zone,
                            confirmed.label,
                            confirmed.reference,
                            message,
                            confirmed.price_vnd,
                        )
                    )
                    continue
                parsed.anomalies.append(
                    Anomaly("price_falls_with_weight", message, later.sheet, later.cell)
                )


def _check_beyond_codes(parsed: ParsedWorkbook) -> None:
    rated = {r.beyond_code for r in parsed.beyond_rates}
    used = {p.beyond_code for p in parsed.beyond_postal_codes}
    for code in sorted(used - rated):
        count = sum(1 for p in parsed.beyond_postal_codes if p.beyond_code == code)
        parsed.anomalies.append(
            Anomaly(
                "beyond_code_without_rate",
                f"beyond code {code} is assigned to {count} postal codes but has no rate row "
                "anywhere in the workbook",
                ZONE_SHEET_NAME,
                None,
            )
        )
    # The same table is printed on several sheets; they must agree.
    seen: dict[str, tuple[Decimal, Decimal, str]] = {}
    for rate in parsed.beyond_rates:
        previous = seen.get(rate.beyond_code)
        if previous and (previous[0], previous[1]) != (rate.base_cad, rate.per_lb_cad):
            parsed.anomalies.append(
                Anomaly(
                    "beyond_rate_disagrees",
                    f"beyond code {rate.beyond_code} differs between {previous[2]} and "
                    f"{rate.sheet}",
                    rate.sheet,
                    rate.cell,
                )
            )
        seen.setdefault(rate.beyond_code, (rate.base_cad, rate.per_lb_cad, rate.sheet))


def dedupe_beyond_rates(parsed: ParsedWorkbook) -> list[ParsedBeyondRate]:
    """One row per code, the first occurrence (the zone sheet is read last; the air sheets
    first). ``_check_beyond_codes`` has already flagged any disagreement."""
    out: dict[str, ParsedBeyondRate] = {}
    for rate in parsed.beyond_rates:
        out.setdefault(rate.beyond_code, rate)
    return list(out.values())


# --- Entry point -------------------------------------------------------------------


def parse_workbook(content: bytes) -> ParsedWorkbook:
    """Read every tariff table out of the workbook bytes. Raises ``WorkbookLayoutError``."""
    digest = hashlib.sha256(content).hexdigest()
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=False)
    except Exception as error:  # openpyxl raises several unrelated types for a bad file
        raise WorkbookLayoutError(
            f"not a readable .xlsx workbook: {type(error).__name__}"
        ) from error

    skipped = [n for n in workbook.sheetnames if n.upper().startswith(NEVER_READ_SHEET_PREFIXES)]
    parsed = ParsedWorkbook(
        source_sha256=digest, sheet_names=list(workbook.sheetnames), skipped_sheets=skipped
    )

    readable = [n for n in workbook.sheetnames if n not in skipped]
    air = [n for n in readable if AIR_SHEET.match(n)]
    sea = [n for n in readable if SEA_SHEET.match(n)]
    surcharge = [n for n in readable if SURCHARGE_SHEET_HINT in n.upper()]
    if not air or ZONE_SHEET_NAME not in workbook.sheetnames or len(surcharge) != 1:
        raise WorkbookLayoutError(
            "expected at least one *-AIR-CAD sheet, a 'Zone CAD' sheet and exactly one "
            "surcharge sheet"
        )

    for name in air:
        _read_air_sheet(workbook[name], parsed)
    for name in sea:
        _read_sea_sheet(workbook[name], parsed)
    _read_zone_sheet(workbook[ZONE_SHEET_NAME], parsed)
    _read_surcharge_sheet(workbook[surcharge[0]], parsed)

    _check_price_monotonicity(parsed)
    _check_beyond_codes(parsed)
    return parsed
