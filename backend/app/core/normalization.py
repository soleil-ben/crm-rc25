"""Contact normalization used for validation, matching, and consent lookup.

Both the value the staff member entered and the normalized value are stored
(CRM.md section 4). Normalization never rewrites what the user typed.
"""

from __future__ import annotations

import re
import unicodedata

import phonenumbers
from email_validator import EmailNotValidError, validate_email

_WHITESPACE = re.compile(r"\s+")


def collapse_whitespace(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _WHITESPACE.sub(" ", value).strip()
    return cleaned or None


def normalize_name(value: str) -> str:
    """Trim and collapse whitespace while preserving accents and original spelling."""
    cleaned = collapse_whitespace(unicodedata.normalize("NFC", value))
    if not cleaned:
        raise ValueError("Name cannot be empty")
    return cleaned


def name_match_key(value: str | None) -> str | None:
    """Accent-folded, lowercase key used only for duplicate candidate matching."""
    if not value:
        return None
    decomposed = unicodedata.normalize("NFD", value)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    stripped = re.sub(r"[^0-9a-zA-Z ]+", " ", stripped)
    return collapse_whitespace(stripped.lower())


#: The SQL name `search_fold` is registered under on every SQLite connection
#: (`app.core.db`), so a query can fold a column the same way Python folds a keyword.
SEARCH_FOLD_SQL_NAME = "solaris_search_fold"


def search_fold(value: str | None) -> str | None:
    """Case- and accent-free text for a keyword search (DEC-0156).

    "Đà Nẵng", "da nang" and "DA NANG" fold to one string, and so do the NFC and NFD
    spellings a phone keyboard may send. ``đ`` is a letter of its own rather than ``d`` plus
    a mark, so it is mapped by hand. Applied to the keyword in Python and to the column in
    SQL, so the two sides cannot fold differently. Whitespace is collapsed; nothing else is
    removed, so ``-`` in a Solaris Shipment ID still has to be typed as ``-``.
    """
    if value is None:
        return None
    decomposed = unicodedata.normalize("NFD", value)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    stripped = stripped.replace("đ", "d").replace("Đ", "D")
    return _WHITESPACE.sub(" ", stripped.casefold()).strip()


#: The one sentence for an email address that is not an address, on every form that takes
#: one: staff customer forms, registration and recovery (UAT round 5). The browser checks
#: the same shape first (`frontend/src/shared/email.js`); this is the authority.
INVALID_EMAIL_MESSAGE = "Enter a valid email address, like name@example.com."


def normalize_email(value: str | None) -> tuple[str | None, str | None]:
    """Return ``(entered, normalized)``.

    Syntax is validated; deliverability is explicitly not checked (CRM.md section 4).
    """
    entered = collapse_whitespace(value)
    if not entered:
        return None, None
    try:
        result = validate_email(entered, check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValueError(f"Email is not valid: {exc}") from exc
    return entered, result.normalized.lower()


def normalize_phone(
    value: str | None, country_code: str | None = None
) -> tuple[str | None, str | None, str | None]:
    """Return ``(entered, e164, region)`` using country-aware parsing.

    Unusual international numbers are accepted: when a number cannot be parsed into
    E.164 the entered value is preserved and a digit-only fallback key is used so the
    record is still creatable (CRM.md section 4).
    """
    entered = collapse_whitespace(value)
    if not entered:
        return None, None, None
    region = (country_code or "").upper() or None
    try:
        parsed = phonenumbers.parse(entered, region)
    except phonenumbers.NumberParseException:
        return entered, None, None
    if not phonenumbers.is_possible_number(parsed):
        return entered, None, None
    e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    detected_region = phonenumbers.region_code_for_number(parsed)
    return entered, e164, detected_region


def phone_match_key(entered: str | None, e164: str | None) -> str | None:
    """Matching key: E.164 when available, otherwise the last 9 significant digits."""
    if e164:
        return e164
    if not entered:
        return None
    digits = re.sub(r"\D", "", entered)
    if len(digits) < 7:
        return None
    return digits[-9:]


#: Leading characters a spreadsheet may treat as the start of a formula rather than as
#: text. The first four are the documented formula introducers; the last three are
#: whitespace that several importers strip *before* deciding, so ``"\n=cmd|..."`` reaches
#: the formula parser as ``=cmd|...`` (DEC-0081).
CSV_FORMULA_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r", "\n")


def escape_csv_value(value: object) -> str:
    """Neutralize spreadsheet formula injection in exported text (CRM.md section 13).

    The value is *prefixed*, never stripped or rewritten. Stripping would silently alter a
    Vietnamese address whose first character is legitimately whitespace, and a negative
    number written as text is still readable with a leading apostrophe.
    """
    text = "" if value is None else str(value)
    if text[:1] in CSV_FORMULA_PREFIXES:
        return "'" + text
    return text
