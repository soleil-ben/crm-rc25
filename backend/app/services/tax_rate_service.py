"""GST/HST by route (owner Ben, 2026-10-23; DEC-0227).

Replaces the RC-UAT-19 stand-in (every draft invoice at 13 % included):

* **International** -- one end of the shipment outside Canada (VN-CA, CA-VN, CA-US, ...):
  zero-rated, **0 %**.
* **Domestic** -- both ends in Canada: the tax is **included** in the price and backed out on
  the invoice (``tax = round_half_up(total * rate / (100 + rate))``, ``subtotal = total -
  tax``) at the **destination province's** rate, read from ``tax_rates``: ON 13 % HST; NS 14 %
  HST; NB, NL, PE 15 % HST; AB, BC, MB, QC, SK, NT, NU, YT 5 % GST.
* **Domestic, province unknown** (stand-in): no rate is suggested; staff must choose one before
  the draft can be saved, downloaded or sent.

The route is read from the shipment: the origin and destination countries (the shipment's
own codes, else the sender's and recipient's address codes, else its route group) and the
destination province from the delivery (recipient) address: its **postal code first** (the
first letter, Canada Post's map), its province text second -- a two-letter code matched
case-sensitively as a whole word ("Niagara on the Lake" is not ON), or a name or abbreviation
in English or French ("Nouvelle-Écosse", "Montréal (Québec)", "Alta.") as whole words anywhere
in the field. When the postal code and the text disagree, or the text names two provinces,
the province is unknown and staff choose (review, 2026-10-24).

``tax_rates`` holds the rates (seeded by migration ``f7c2d9e3a1b5``; Admin edits them on
Settings, audited ``tax_rate.update``). A province with no row reads the default below, so
a database built without the migration's seed (tests) behaves the same; reading never writes.
Rates are whole percents: ``invoice_drafts.tax_rate_percent`` is an integer.

The manual **Issue invoice** path (no draft) is unchanged (owner): it keeps its own 0 / 5 /
13 % picker and adds the tax on top (``finance_service.TAX_RATES``).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import RouteGroup
from app.core.time_utils import utcnow
from app.models import Shipment, TaxRate, User
from app.services import audit_service
from app.services.errors import NotFoundError, ValidationError

#: Owner, 2026-10-23. ``(rate_percent, tax_label)`` by province or territory code.
DEFAULT_RATES: dict[str, tuple[int, str]] = {
    "ON": (13, "HST"),
    "NS": (14, "HST"),
    "NB": (15, "HST"),
    "NL": (15, "HST"),
    "PE": (15, "HST"),
    "AB": (5, "GST"),
    "BC": (5, "GST"),
    "MB": (5, "GST"),
    "QC": (5, "GST"),
    "SK": (5, "GST"),
    "NT": (5, "GST"),
    "NU": (5, "GST"),
    "YT": (5, "GST"),
}
PROVINCES = tuple(DEFAULT_RATES)
PROVINCE_NAMES = {
    "ON": "Ontario",
    "NS": "Nova Scotia",
    "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador",
    "PE": "Prince Edward Island",
    "AB": "Alberta",
    "BC": "British Columbia",
    "MB": "Manitoba",
    "QC": "Quebec",
    "SK": "Saskatchewan",
    "NT": "Northwest Territories",
    "NU": "Nunavut",
    "YT": "Yukon",
}
#: The rates a draft invoice may carry regardless of the table (owner, 2026-10-23).
BASE_ALLOWED_RATES = (0, 5, 13, 14, 15)
TAX_LABELS = ("GST", "HST")
MAX_RATE = 30
ZERO_RATED = 0
INCLUDED = "included"

#: The first letter of a Canadian postal code names the province (Canada Post). X is shared:
#: X0A, X0B and X0C are Nunavut, the rest of X the Northwest Territories.
POSTAL_PROVINCES: dict[str, str] = {
    "A": "NL",
    "B": "NS",
    "C": "PE",
    "E": "NB",
    "G": "QC",
    "H": "QC",
    "J": "QC",
    "K": "ON",
    "L": "ON",
    "M": "ON",
    "N": "ON",
    "P": "ON",
    "R": "MB",
    "S": "SK",
    "T": "AB",
    "V": "BC",
    "X": "NT",
    "Y": "YT",
}
_NUNAVUT_FSA_PREFIXES = ("X0A", "X0B", "X0C")
_POSTAL = re.compile(r"^([ABCEGHJ-NPRSTVXY])(\d)([A-Z]) ?\d[A-Z]\d$")

#: Two-letter codes, matched **case-sensitively** as whole words ("Niagara on the Lake" is not
#: ON). PQ and NF are older codes still written.
_CODES: dict[str, str] = {code: code for code in DEFAULT_RATES} | {"PQ": "QC", "NF": "NL"}
_CODE_PATTERN = re.compile(r"(?<![A-Za-z])(" + "|".join(_CODES) + r")(?![A-Za-z])")

#: Names and abbreviations (English and French), as folded words: lower case, no accents,
#: "&" read as "and", full stops dropped ("P.E.I." -> "pei", "Alta." -> "alta").
_NAMES: dict[tuple[str, ...], str] = {
    ("ontario",): "ON",
    ("ont",): "ON",
    ("nova", "scotia"): "NS",
    ("nouvelle", "ecosse"): "NS",
    ("new", "brunswick"): "NB",
    ("nouveau", "brunswick"): "NB",
    ("newfoundland",): "NL",
    ("labrador",): "NL",
    ("nfld",): "NL",
    ("terre", "neuve"): "NL",
    ("prince", "edward", "island"): "PE",
    ("pei",): "PE",
    ("ile", "du", "prince", "edouard"): "PE",
    ("alberta",): "AB",
    ("alta",): "AB",
    ("british", "columbia"): "BC",
    ("colombie", "britannique"): "BC",
    ("manitoba",): "MB",
    ("man",): "MB",
    ("quebec",): "QC",
    ("que",): "QC",
    ("saskatchewan",): "SK",
    ("sask",): "SK",
    ("northwest", "territories"): "NT",
    ("territoires", "du", "nord", "ouest"): "NT",
    ("nwt",): "NT",
    ("nunavut",): "NU",
    ("yukon",): "YT",
}


def _words(value: str) -> list[str]:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = text.replace("&", " and ").replace(".", "")
    return [word for word in re.split(r"[^a-z0-9]+", text) if word]


def postal_province(postal_code: str | None) -> str | None:
    """The province a Canadian postal code belongs to, or None when it is not one."""
    text = " ".join((postal_code or "").upper().split())
    match = _POSTAL.match(text)
    if match is None:
        return None
    if text.replace(" ", "")[:3] in _NUNAVUT_FSA_PREFIXES:
        return "NU"
    return POSTAL_PROVINCES[match.group(1)]


def provinces_named(value: str | None) -> set[str]:
    """Every province the text names: codes (case-sensitive, whole words) and names or
    abbreviations (any case and accents, whole words, anywhere in the text)."""
    if not value or not value.strip():
        return set()
    found = {_CODES[code] for code in _CODE_PATTERN.findall(unicodedata.normalize("NFC", value))}
    words = _words(value)
    for name, code in _NAMES.items():
        size = len(name)
        if any(tuple(words[i : i + size]) == name for i in range(len(words) - size + 1)):
            found.add(code)
    return found


def province_code(value: str | None) -> str | None:
    """The province a text names, or None when it names none or more than one."""
    found = provinces_named(value)
    return found.pop() if len(found) == 1 else None


def destination_province(postal_code: str | None, text: str | None) -> str | None:
    """The delivery province (DEC-0227, review 2026-10-24): the postal code first, the
    province text second. Unknown (None, staff choose) when neither tells, when the text names
    two provinces, or when the postal code and the text disagree."""
    by_postal = postal_province(postal_code)
    named = provinces_named(text)
    if len(named) > 1:
        return None
    by_text = next(iter(named), None)
    if by_postal and by_text and by_postal != by_text:
        return None
    return by_postal or by_text


# --- The table ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rate:
    province_code: str
    rate_percent: int
    tax_label: str
    updated_at: datetime | None
    updated_by: str | None
    is_default: bool


def rate_table(db: Session) -> dict[str, Rate]:
    """Every province's rate: the stored row, else the default (reading never writes)."""
    rows = {row.province_code: row for row in db.scalars(select(TaxRate))}
    table: dict[str, Rate] = {}
    for code, (rate, label) in DEFAULT_RATES.items():
        row = rows.get(code)
        if row is None:
            table[code] = Rate(code, rate, label, None, None, True)
            continue
        editor = db.get(User, row.updated_by_user_id) if row.updated_by_user_id else None
        table[code] = Rate(
            code,
            row.rate_percent,
            row.tax_label,
            row.updated_at,
            editor.email if editor else None,
            False,
        )
    return table


def allowed_rates(db: Session) -> tuple[int, ...]:
    """The rates a draft invoice may carry: 0, 5, 13, 14, 15 and whatever the table holds."""
    rates = set(BASE_ALLOWED_RATES)
    rates.update(rate.rate_percent for rate in rate_table(db).values())
    return tuple(sorted(rates))


def update_rate(db: Session, code: str, payload: dict[str, Any], *, actor: User | None) -> Rate:
    """Admin edits one province's rate or label. Audited ``tax_rate.update`` with from/to."""
    code = (code or "").strip().upper()
    if code not in DEFAULT_RATES:
        raise NotFoundError("That province or territory is not in the GST/HST table.")
    current = rate_table(db)[code]
    rate, label = current.rate_percent, current.tax_label
    if payload.get("rate_percent") is not None:
        value = payload["rate_percent"]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError("A rate is a whole percent.", field="rate_percent")
        if not 0 <= value <= MAX_RATE:
            raise ValidationError(
                f"A rate is between 0 and {MAX_RATE} percent.", field="rate_percent"
            )
        rate = value
    if payload.get("tax_label") is not None:
        label = str(payload["tax_label"]).strip().upper()
        if label not in TAX_LABELS:
            raise ValidationError("The tax is GST or HST.", field="tax_label")
    if (rate, label) == (current.rate_percent, current.tax_label):
        # Nothing changed: no write, no audit entry.
        return current
    now = utcnow()
    row = db.get(TaxRate, code)
    if row is None:
        row = TaxRate(province_code=code)
        db.add(row)
    row.rate_percent = rate
    row.tax_label = label
    row.updated_at = now
    row.updated_by_user_id = actor.id if actor else None
    db.flush()
    changes = {}
    if rate != current.rate_percent:
        changes["rate_percent"] = {"from": current.rate_percent, "to": rate}
    if label != current.tax_label:
        changes["tax_label"] = {"from": current.tax_label, "to": label}
    audit_service.record_audit(
        db,
        action="tax_rate.update",
        entity_type="tax_rate",
        entity_id=code,
        summary=f"Set the GST/HST rate of {code} to {rate} % {label}",
        actor=actor,
        detail={"province_code": code, "changes": changes},
    )
    return rate_table(db)[code]


# --- The route ---------------------------------------------------------------------------------

_ROUTE_GROUP_COUNTRIES: dict[str, tuple[str | None, str | None]] = {
    RouteGroup.VCA: ("VN", "CA"),
    RouteGroup.CAV: ("CA", "VN"),
    RouteGroup.CAD: ("CA", "CA"),
    # US cross border: either direction, always one end in the US.
    RouteGroup.XUS: (None, "US"),
}


@dataclass(frozen=True)
class RouteTax:
    """The GST/HST a shipment's draft invoice starts at."""

    #: international | domestic
    route_band: str
    origin_country_code: str | None
    destination_country_code: str | None
    destination_province: str | None
    #: None when staff must choose (domestic, province unknown).
    rate_percent: int | None
    tax_label: str | None
    mode: str

    @property
    def rate_required(self) -> bool:
        return self.rate_percent is None


def _country(value: str | None) -> str | None:
    text = (value or "").strip().upper()
    return text if len(text) == 2 and text.isalpha() else None


def route_tax(db: Session, shipment: Shipment) -> RouteTax:
    """The rate and mode a new draft invoice for ``shipment`` auto-fills (DEC-0227)."""
    fallback = _ROUTE_GROUP_COUNTRIES.get(shipment.route_group, (None, None))
    origin = (
        _country(shipment.origin_country_code)
        or _country(shipment.sender_country_code)
        or fallback[0]
    )
    destination = (
        _country(shipment.destination_country_code)
        or _country(shipment.recipient_country_code)
        or fallback[1]
    )
    domestic = (origin, destination) == ("CA", "CA") or (
        shipment.route_group == RouteGroup.CAD and None in (origin, destination)
    )
    if not domestic:
        return RouteTax("international", origin, destination, None, ZERO_RATED, None, INCLUDED)
    province = destination_province(
        shipment.recipient_postal_code, shipment.recipient_province_state
    )
    if province is None:
        return RouteTax("domestic", origin, destination, None, None, None, INCLUDED)
    rate = rate_table(db)[province]
    return RouteTax(
        "domestic", origin, destination, province, rate.rate_percent, rate.tax_label, INCLUDED
    )
