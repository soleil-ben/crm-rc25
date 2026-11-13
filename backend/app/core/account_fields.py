"""The registration field allowlist: which keys exist, what type each one is, how it normalizes.

`FIELD_MATRIX.md` section 2 lists the only fields a registration form may accept, and says
plainly: "a registration form field not in this table is a defect." This module is that
table, as code. A key not declared here is refused at the API boundary before a row exists,
which is what makes the allowlist a boundary rather than a comment.

**Typed, not a blob.** `customer_data_proposal_fields` stores one row per field with the
type the boundary enforced. The alternative -- a JSON column holding whatever the client
sent -- accepts anything, which is the same as having no allowlist at all, and pushes the
question of what a value *is* to whoever reads it in Phase 10.

**Normalized alongside entered.** Each field carries both what the person typed and what
`app.core.normalization` made of it, exactly as a staff-entered customer record does
(CRM.md section 4). Reusing that module rather than reimplementing it is what makes "the
same customer" mean the same thing on both surfaces, and the normalized form is what later
duplicate review compares. What this surface may never do is *report* the result: a score, a
match or a count is staff-facing only (T-02).

**No canonical column is implied by any key here.** `legal_name`, `display_name` and the
billing address have no canonical home yet -- `FIELD_MATRIX.md` section 6 names all three as
gaps, and the owner's Phase 9 instruction says to carry them in the proposal representation
until their canonical treatment is implemented (DEC-0096). A key in this module is a
statement about what a customer may *submit*, never about where it lands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from app.core.countries import normalize_country_code
from app.core.enums import BusinessType, CustomerCategory, PreferredLanguage
from app.core.normalization import (
    INVALID_EMAIL_MESSAGE,
    collapse_whitespace,
    name_match_key,
    normalize_email,
    normalize_phone,
)


class FieldType(StrEnum):
    """What the boundary enforced, recorded on the row so Phase 10 does not have to guess."""

    STRING = "string"
    ENUM = "enum"
    EMAIL = "email"
    PHONE = "phone"
    COUNTRY = "country"
    BOOLEAN = "boolean"


class FieldRejected(ValueError):
    """A submitted value is not of the declared type, or is outside its bound.

    A *format* error, and the caller must turn it into a format error only. "This is not an
    email address" is safe to say; "this email address is already registered" is the thing
    OD-23 forbids, and no exception in this module can carry that distinction because this
    module never looks anything up.
    """

    def __init__(self, field_key: str, message: str) -> None:
        super().__init__(message)
        self.field_key = field_key
        self.message = message


@dataclass(frozen=True)
class FieldSpec:
    """One allowlisted key: its type, its bound, and its vocabulary if it has one."""

    key: str
    type: FieldType
    max_length: int
    #: Legal values for an ENUM field. Free text against an enum is refused, never coerced.
    choices: frozenset[str] | None = None
    #: The key whose value supplies the region for phone parsing, if this is a PHONE field.
    region_from: str | None = None


#: Bound on any single submitted string, before its own `max_length` applies. A value longer
#: than this is not a long name, it is somebody testing what the endpoint does with 4 KB.
ABSOLUTE_MAX_VALUE_LENGTH = 1000

#: How many pickup/sender addresses a registration may carry. OD-27 says addresses, plural;
#: unbounded plural is a queue-flooding vector, so the plural is three.
MAX_PICKUP_ADDRESSES = 3

_ADDRESS_PART_SPECS: tuple[tuple[str, FieldType, int], ...] = (
    ("address_line1", FieldType.STRING, 255),
    ("address_line2", FieldType.STRING, 255),
    ("city", FieldType.STRING, 120),
    ("province_state", FieldType.STRING, 120),
    ("postal_code", FieldType.STRING, 30),
    ("country_code", FieldType.COUNTRY, 2),
)

_PICKUP_EXTRA_SPECS: tuple[tuple[str, FieldType, int], ...] = (
    ("contact_name", FieldType.STRING, 200),
    ("delivery_note", FieldType.STRING, 400),
)


def _build_specs() -> dict[str, FieldSpec]:
    specs: dict[str, FieldSpec] = {}

    def add(key: str, type_: FieldType, max_length: int, **kwargs: object) -> None:
        specs[key] = FieldSpec(key=key, type=type_, max_length=max_length, **kwargs)  # type: ignore[arg-type]

    # --- Identity-bearing scalars (FIELD_MATRIX.md section 2) ---------------
    add(
        "customer_type",
        FieldType.ENUM,
        20,
        choices=frozenset(value.value for value in CustomerCategory),
    )
    add(
        "business_type",
        FieldType.ENUM,
        30,
        choices=frozenset(value.value for value in BusinessType),
    )
    # No canonical column for either of these today (FIELD_MATRIX.md section 6, DEC-0096).
    add("legal_name", FieldType.STRING, 200)
    add("display_name", FieldType.STRING, 200)
    add("primary_contact_name", FieldType.STRING, 200)
    add("email", FieldType.EMAIL, 320)
    add("phone_country_code", FieldType.COUNTRY, 2)
    add("phone", FieldType.PHONE, 60, region_from="phone_country_code")
    add(
        "preferred_language",
        FieldType.ENUM,
        8,
        choices=frozenset(value.value for value in PreferredLanguage),
    )
    # The explicit, separate, unchecked-by-default marketing choice (OD-27, OD-38). Recorded
    # as a *proposal field*: a `consent_events` row is written at approval, through the
    # existing consent service, never at registration.
    add("marketing_consent", FieldType.BOOLEAN, 5)

    # --- Billing address. No `billing` AddressRole exists yet (DEC-0096) ----
    for part, type_, length in _ADDRESS_PART_SPECS:
        add(f"billing_address.{part}", type_, length)

    # --- Pickup / sender addresses, bounded ---------------------------------
    for index in range(1, MAX_PICKUP_ADDRESSES + 1):
        for part, type_, length in (*_ADDRESS_PART_SPECS, *_PICKUP_EXTRA_SPECS):
            key = f"pickup_address.{index}.{part}"
            if type_ is FieldType.PHONE:  # pragma: no cover - none today; kept honest
                add(key, type_, length, region_from=f"pickup_address.{index}.country_code")
            else:
                add(key, type_, length)
        add(
            f"pickup_address.{index}.phone",
            FieldType.PHONE,
            60,
            region_from=f"pickup_address.{index}.country_code",
        )

    return specs


#: The allowlist. Every key a registration may carry, and nothing else.
FIELD_SPECS: dict[str, FieldSpec] = _build_specs()

#: The set, for the boundary check and for the tests that assert it has not quietly grown.
ALLOWED_FIELD_KEYS: frozenset[str] = frozenset(FIELD_SPECS)

#: Longest key in the allowlist, asserted against the column width so a future key that does
#: not fit fails a test rather than a database write.
FIELD_KEY_COLUMN_LENGTH = 60

#: The lenient shape a typed postal code must have, for the two countries whose codes have
#: one (UAT round 12, DEC-0165). Canada: letter, digit, letter, an optional space, digit,
#: letter, digit, in any case. The United States: five digits, or ZIP+4 with a hyphen.
#: Checked after whitespace is collapsed, so spaces around the code never matter. A blank
#: postal code is never checked (it is optional, DEC-0159), and Vietnam's is not checked.
#: The registration form checks the same shapes (``RegisterPage.jsx``).
POSTAL_CODE_SHAPES: dict[str, re.Pattern[str]] = {
    "CA": re.compile(r"[A-Za-z][0-9][A-Za-z] ?[0-9][A-Za-z][0-9]"),
    "US": re.compile(r"[0-9]{5}(?:-[0-9]{4})?"),
}

_POSTAL_SUFFIX = "postal_code"


def postal_code_format_message(country_code: str, *, billing: bool) -> str:
    """The sentence shown beside a postal code of the wrong shape (UAT round 12, DEC-0165).

    The registration form says the same words. It names the shape, and says the field may
    be left blank, because it is optional.
    """
    which = "billing " if billing else ""
    if country_code == "US":
        return f"Enter the {which}ZIP code as 12345 or 12345-6789, or leave it blank."
    return f"Enter the {which}postal code as A1A 1A1, or leave it blank."


def _check_postal_code(key: str, entered: str, context: dict[str, str]) -> None:
    """Refuse a typed postal code whose shape does not fit its own address's country."""
    country_key = f"{key[: -len(_POSTAL_SUFFIX)]}country_code"
    country = normalize_country_code(str(context.get(country_key) or ""))
    shape = POSTAL_CODE_SHAPES.get(country or "")
    if shape is not None and not shape.fullmatch(entered):
        raise FieldRejected(
            key,
            postal_code_format_message(country, billing=key.startswith("billing_address.")),
        )


_BOOLEAN_TRUE = frozenset({"true", "1", "yes", "on"})
_BOOLEAN_FALSE = frozenset({"false", "0", "no", "off", ""})

#: Control characters have no place in a name, an address or a phone number, and a value
#: carrying them is either a paste accident or an attempt to break something downstream.
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True)
class NormalizedField:
    """One accepted field: what was typed, what it normalizes to, and its declared type."""

    key: str
    value_type: FieldType
    entered: str
    normalized: str | None


def normalize_field(key: str, raw: object, *, context: dict[str, str]) -> NormalizedField | None:
    """Validate and normalize one submitted field. ``None`` means "submitted empty, skip it".

    ``context`` carries the other raw values of the same submission, so a phone can be
    parsed against the country code that arrived with it -- the country-aware parsing the
    Staff Portal already does, reused rather than reimplemented.

    Raises `FieldRejected` for a **format** problem and for nothing else. This function
    performs no lookup and therefore cannot leak whether anything exists.
    """
    spec = FIELD_SPECS.get(key)
    if spec is None:
        raise FieldRejected(key, "That field is not accepted here.")

    if raw is None:
        return None
    if isinstance(raw, bool):
        text = "true" if raw else "false"
    elif isinstance(raw, (int, float)):
        text = str(raw)
    elif isinstance(raw, str):
        text = raw
    else:
        raise FieldRejected(key, "Expected a text value.")

    if len(text) > ABSOLUTE_MAX_VALUE_LENGTH:
        raise FieldRejected(key, "That value is too long.")
    if _CONTROL_CHARACTERS.search(text):
        raise FieldRejected(key, "That value contains characters that are not allowed.")

    if spec.type is FieldType.BOOLEAN:
        lowered = text.strip().lower()
        if lowered in _BOOLEAN_TRUE:
            return NormalizedField(key, spec.type, "true", "true")
        if lowered in _BOOLEAN_FALSE:
            # An absent or false marketing choice is *no consent*, and no row. Unchecked by
            # default means the absence is the answer (OD-38).
            return NormalizedField(key, spec.type, "false", "false")
        raise FieldRejected(key, "Expected true or false.")

    entered = collapse_whitespace(text)
    if entered is None:
        return None
    if len(entered) > spec.max_length:
        raise FieldRejected(key, f"Use at most {spec.max_length} characters.")

    if spec.type is FieldType.ENUM:
        assert spec.choices is not None
        lowered = entered.lower()
        if lowered not in spec.choices:
            # The legal values are named: this is a format error about a closed vocabulary,
            # and hiding it would make a correct form impossible to fill in.
            raise FieldRejected(key, f"Choose one of: {', '.join(sorted(spec.choices))}.")
        return NormalizedField(key, spec.type, lowered, lowered)

    if spec.type is FieldType.EMAIL:
        try:
            typed, normalized = normalize_email(entered)
        except ValueError as exc:
            raise FieldRejected(key, INVALID_EMAIL_MESSAGE) from exc
        if typed is None or normalized is None:
            return None
        return NormalizedField(key, spec.type, typed, normalized)

    if spec.type is FieldType.COUNTRY:
        normalized = normalize_country_code(entered)
        if normalized is None:
            raise FieldRejected(key, "Enter a valid two-letter country code.")
        return NormalizedField(key, spec.type, entered, normalized)

    if spec.type is FieldType.PHONE:
        region = None
        if spec.region_from:
            region = normalize_country_code(str(context.get(spec.region_from) or "")) or None
        typed, e164, _ = normalize_phone(entered, region)
        if typed is None:
            return None
        # An unparseable international number is kept rather than refused, exactly as the
        # Staff Portal keeps it: the record must still be creatable (CRM.md section 4).
        return NormalizedField(key, spec.type, typed, e164)

    if key.endswith(f".{_POSTAL_SUFFIX}"):
        _check_postal_code(key, entered, context)

    # A plain string. The normalized form is the accent-folded match key, because that is
    # what later duplicate review compares -- and it is the only reason to store a second
    # form of a name at all.
    return NormalizedField(key, spec.type, entered, name_match_key(entered))
