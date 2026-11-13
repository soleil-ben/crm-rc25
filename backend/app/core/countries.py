"""ISO 3166-1 alpha-2 country handling.

Validation uses normalized ISO codes so route rules cannot be fooled by spelling, while
the value the staff member actually typed is preserved separately for display
(CRM.md section 7).

The valid-code set comes from ``phonenumbers.SUPPORTED_REGIONS``, which is already a
dependency and tracks ISO 3166-1 alpha-2 regions. The name map covers the launch lanes
and the handful of spellings staff realistically type; anything else must be entered as
a two-letter code rather than guessed at.
"""

from __future__ import annotations

import unicodedata

import phonenumbers

# Region codes phonenumbers knows about, plus a few ISO codes it has no dialling plan
# for. A country without a phone plan is still a valid shipping destination.
VALID_COUNTRY_CODES: frozenset[str] = frozenset(
    set(phonenumbers.SUPPORTED_REGIONS) | {"AQ", "BV", "HM", "TF", "UM", "GS", "EH", "PN"}
) - {"001"}

_NAME_TO_CODE: dict[str, str] = {
    "canada": "CA",
    "ca": "CA",
    "can": "CA",
    "vietnam": "VN",
    "viet nam": "VN",
    "vn": "VN",
    "vnm": "VN",
    "viet-nam": "VN",
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
    "us": "US",
    "u s a": "US",
    "america": "US",
}


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.lower().replace(".", " ").replace("-", " ").split())


def normalize_country_code(value: str | None) -> str | None:
    """Return an uppercase ISO 3166-1 alpha-2 code, or ``None`` for an empty value.

    Raises ``ValueError`` when a value was supplied but cannot be resolved, so an
    unrecognized country is a visible validation error rather than a silent ``None``
    that would let a route check pass.
    """
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None

    upper = raw.upper()
    if len(upper) == 2 and upper in VALID_COUNTRY_CODES:
        return upper

    folded = _fold(raw)
    mapped = _NAME_TO_CODE.get(folded)
    if mapped:
        return mapped

    raise ValueError(
        f"'{raw}' is not a recognized country. Enter a two-letter ISO country code such as CA."
    )


def country_label(code: str | None, entered: str | None = None) -> str | None:
    """Display value: what the staff member typed when present, otherwise the code."""
    if entered and entered.strip():
        return entered.strip()
    return code
