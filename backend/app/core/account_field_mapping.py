"""Where each registration proposal field lands when a person approves it.

`app.core.account_fields` says what a customer may *submit*. This module says where an
approved submission *goes*, and it is the second half of the same allowlist: a key with no
row in ``FIELD_MAP`` reaches no canonical column, and a canonical column not named here is
never written by an approval. `PROJECT_STATUS.md` section 19.6 is this table in prose, and
`tests/test_account_field_mapping.py` asserts the two agree key by key.

**Nothing here writes anything.** These functions turn a proposal into the *payloads* that
``customer_service.create_customer`` and ``customer_address_service.create_address``
accept. The writing happens in those services, which is the instruction's requirement and
also the only way the existing validation, normalization and audit apply to a customer
created this way exactly as they apply to one a staff member types in.

**The three gaps, resolved.** `FIELD_MATRIX.md` section 6 named a display name, a legal
name distinct from it, and a billing address role. Phase 10 added
``customers.legal_name``, ``customers.display_name`` and ``AddressRole.BILLING``, and the
precedence between the four name-ish concepts is decided here once:

* ``customers.full_name`` is **unchanged**: the name of the person to talk to. Required,
  and the only name any existing query reads.
* An **individual** supplies ``legal_name``; it becomes both ``customers.legal_name`` and
  ``customers.full_name``. ``primary_contact_name`` is the fallback for ``full_name`` when
  no legal name was given, and otherwise becomes the billing address ``contact_name``.
* A **business** supplies ``legal_name``; it becomes ``customers.legal_name`` and
  ``customers.business_name``. ``primary_contact_name`` becomes ``customers.full_name``,
  because for a business the person to talk to is the contact, not the company.
* ``display_name`` is presentation only. It feeds no match key, no duplicate rule and no
  constraint, so nothing downstream changes behaviour because it is set.

A submission that supplies neither a legal name nor a contact name has no name to put in a
required column, and `resolve_customer_payload` refuses it rather than inventing one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.account_fields import MAX_PICKUP_ADDRESSES
from app.core.enums import AddressRole, CustomerCategory
from app.models import Customer

#: Bumped when the mapping changes shape in a way that would make an old preview mean
#: something different. Part of the preview fingerprint, so an acknowledgement taken under
#: an earlier mapping stops matching rather than silently applying the new one.
FIELD_MAPPING_VERSION = "field-map-v1"


@dataclass(frozen=True)
class CanonicalTarget:
    """Where one proposal key lands, for the staff-facing mapping table and its tests."""

    field_key: str
    #: ``customers``, ``customer_addresses`` or ``consent_events``.
    table: str
    #: The column, or a short phrase where one key feeds several (a phone does).
    column: str
    #: ``individual``, ``business`` or ``both``.
    applies_to: str = "both"
    #: True when approving this key creates an address row rather than setting a column.
    creates_child_row: bool = False


#: The table `PROJECT_STATUS.md` section 19.6 prints. Declared so a test can compare the
#: two rather than a reviewer comparing them by eye, and so "which canonical column can a
#: registration reach?" has one answer that is code.
FIELD_MAP: tuple[CanonicalTarget, ...] = (
    CanonicalTarget("customer_type", "customers", "category"),
    CanonicalTarget("business_type", "customers", "business_type", applies_to="business"),
    CanonicalTarget("legal_name", "customers", "legal_name, business_name or full_name"),
    CanonicalTarget("display_name", "customers", "display_name"),
    CanonicalTarget("primary_contact_name", "customers", "full_name"),
    CanonicalTarget("email", "customers", "email_entered, email_normalized"),
    CanonicalTarget("phone", "customers", "phone_entered, phone_e164, phone_region"),
    CanonicalTarget("phone_country_code", "customers", "country_code (fallback)"),
    CanonicalTarget("preferred_language", "customers", "preferred_language"),
    CanonicalTarget("marketing_consent", "consent_events", "status", creates_child_row=True),
    *(
        CanonicalTarget(
            f"billing_address.{part}", "customer_addresses", part, creates_child_row=True
        )
        for part in (
            "address_line1",
            "address_line2",
            "city",
            "province_state",
            "postal_code",
            "country_code",
        )
    ),
    *(
        CanonicalTarget(
            f"pickup_address.{index}.{part}",
            "customer_addresses",
            part,
            creates_child_row=True,
        )
        for index in range(1, MAX_PICKUP_ADDRESSES + 1)
        for part in (
            "address_line1",
            "address_line2",
            "city",
            "province_state",
            "postal_code",
            "country_code",
            "contact_name",
            "delivery_note",
            "phone",
        )
    ),
)

#: Every key the mapping knows. A proposal field outside it is carried, shown to the
#: reviewer and **not applied** -- which is what happens to a key added to
#: `account_fields` without a decision about where it lands.
MAPPED_FIELD_KEYS: frozenset[str] = frozenset(target.field_key for target in FIELD_MAP)

#: The canonical columns of ``customers`` an approval may set, and nothing else. Used by
#: the difference calculation and asserted against `FIELD_MAP`.
CUSTOMER_COLUMNS: tuple[str, ...] = (
    "full_name",
    "legal_name",
    "display_name",
    "business_name",
    "category",
    "business_type",
    "email_entered",
    "phone_entered",
    "preferred_language",
    "city",
    "province_state",
    "country_code",
)

_ADDRESS_PARTS = (
    "address_line1",
    "address_line2",
    "city",
    "province_state",
    "postal_code",
    "country_code",
)


class MappingRefused(ValueError):
    """The proposal cannot become a canonical customer, and says which field is missing.

    A *shape* error about the submission, raised before anything is written. It never
    reports whether another record exists, because this module performs no lookup.
    """

    def __init__(self, message: str, *, field_key: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field_key = field_key


@dataclass
class AddressPayload:
    """One address row an approval will create, already shaped for the address service."""

    role: str
    contact_name: str
    values: dict[str, Any] = field(default_factory=dict)
    is_default_sender: bool = False


@dataclass
class MappedProposal:
    """A proposal turned into the payloads the existing services accept.

    ``applied_field_keys`` is what the approval marks ``applied = true`` on. A key that is
    carried but has no canonical home stays false, which is the per-field flag OD-28 asks
    for, used for its actual purpose rather than as a formality.
    """

    customer: dict[str, Any]
    addresses: list[AddressPayload]
    #: ``True`` only when the customer explicitly chose it. Absent is **not** consent.
    marketing_consent: bool
    marketing_address: str | None
    applied_field_keys: list[str]


def values_by_key(fields: list[Any]) -> dict[str, str]:
    """``{field_key: proposed_value}`` for a list of ``CustomerDataProposalField`` rows."""
    return {row.field_key: row.proposed_value for row in fields if row.proposed_value is not None}


def normalized_by_key(fields: list[Any]) -> dict[str, str]:
    """``{field_key: proposed_value_normalized}``, which is what duplicate review compares."""
    return {
        row.field_key: row.proposed_value_normalized
        for row in fields
        if row.proposed_value_normalized is not None
    }


def _address_values(entered: dict[str, str], prefix: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for part in _ADDRESS_PARTS:
        value = entered.get(f"{prefix}.{part}")
        if value:
            values[part] = value
    return values


def resolve_customer_payload(entered: dict[str, str]) -> MappedProposal:
    """Turn the submitted values into create-customer and create-address payloads.

    ``entered`` is what the person typed, keyed by allowlisted field key -- the ``entered``
    form rather than the normalized one, because ``customer_service.create_customer``
    normalizes for itself and handing it a match key instead of a name would store the
    match key. The normalized forms exist for duplicate review and for difference
    detection, which is what they are used for elsewhere in this phase.
    """
    category = entered.get("customer_type") or CustomerCategory.INDIVIDUAL.value
    is_business = category == CustomerCategory.BUSINESS.value

    legal_name = entered.get("legal_name")
    contact_name = entered.get("primary_contact_name")
    display_name = entered.get("display_name")

    # For a business the person to talk to is the contact; for an individual it is the
    # individual. Each falls back to the other so a submission carrying only one of them
    # still produces a record.
    full_name = (contact_name or legal_name) if is_business else (legal_name or contact_name)

    if not full_name:
        raise MappingRefused(
            "This registration has no name to put on a customer record. "
            "It needs a legal name or a primary contact name.",
            field_key="legal_name",
        )

    applied: list[str] = []

    def mark(*keys: str) -> None:
        applied.extend(key for key in keys if key in entered)

    customer: dict[str, Any] = {"full_name": full_name, "category": category}
    mark("customer_type")
    if legal_name:
        customer["legal_name"] = legal_name
        mark("legal_name")
    if display_name:
        customer["display_name"] = display_name
        mark("display_name")
    if contact_name:
        mark("primary_contact_name")
    if is_business:
        if legal_name:
            customer["business_name"] = legal_name
        if entered.get("business_type"):
            customer["business_type"] = entered["business_type"]
            mark("business_type")
    if entered.get("email"):
        customer["email"] = entered["email"]
        mark("email")
    if entered.get("preferred_language"):
        customer["preferred_language"] = entered["preferred_language"]
        mark("preferred_language")

    # Location first from the billing address, then from the first pickup address, then
    # from the phone's country code. `customers.country_code` is not decoration: it is the
    # region a later phone edit parses against, so leaving it null would make the record
    # behave differently from one a staff member typed.
    billing = _address_values(entered, "billing_address")
    pickup_one = _address_values(entered, "pickup_address.1")
    location_source = billing or pickup_one
    for column in ("city", "province_state", "country_code"):
        if location_source.get(column):
            customer[column] = location_source[column]
    if not customer.get("country_code") and entered.get("phone_country_code"):
        customer["country_code"] = entered["phone_country_code"]
        mark("phone_country_code")

    if entered.get("phone"):
        customer["phone"] = entered["phone"]
        mark("phone")

    addresses: list[AddressPayload] = []
    if billing:
        addresses.append(
            AddressPayload(
                role=AddressRole.BILLING.value,
                # The billing row's contact is the person, not the company: a courier
                # never sees this row, but an invoice is addressed to somebody.
                contact_name=contact_name or full_name,
                values=billing,
            )
        )
        mark(*(f"billing_address.{part}" for part in _ADDRESS_PARTS))

    for index in range(1, MAX_PICKUP_ADDRESSES + 1):
        prefix = f"pickup_address.{index}"
        values = _address_values(entered, prefix)
        if not values:
            continue
        phone = entered.get(f"{prefix}.phone")
        if phone:
            values["phone"] = phone
        note = entered.get(f"{prefix}.delivery_note")
        if note:
            values["delivery_note"] = note
        addresses.append(
            AddressPayload(
                role=AddressRole.SENDER.value,
                contact_name=entered.get(f"{prefix}.contact_name") or full_name,
                values=values,
                # The first pickup address submitted becomes the default sender, which is
                # what a booking screen offers first. The second and third do not.
                is_default_sender=not any(address.is_default_sender for address in addresses),
            )
        )
        mark(
            *(f"{prefix}.{part}" for part in _ADDRESS_PARTS),
            f"{prefix}.contact_name",
            f"{prefix}.phone",
            f"{prefix}.delivery_note",
        )

    # Unchecked by default, and the absence is the answer (OD-38). Only the literal
    # ``"true"`` the field allowlist produces counts as a choice.
    marketing_consent = entered.get("marketing_consent") == "true"
    if marketing_consent:
        mark("marketing_consent")

    return MappedProposal(
        customer=customer,
        addresses=addresses,
        marketing_consent=marketing_consent,
        marketing_address=entered.get("email"),
        applied_field_keys=sorted(set(applied)),
    )


def canonical_snapshot(customer: Customer) -> dict[str, str | None]:
    """The mapped columns of an existing customer, for the link-existing preview.

    Exactly `CUSTOMER_COLUMNS` and nothing else -- not the notes, not the owner, not the
    lifecycle, not the tags, not the merge state. A reviewer deciding whether to link an
    account to this record needs the values the registration proposed against, and a
    wider snapshot would be a wider disclosure to build a screen on later.
    """
    return {column: getattr(customer, column, None) for column in CUSTOMER_COLUMNS}


def proposed_snapshot(entered: dict[str, str]) -> dict[str, str | None]:
    """The same shape as `canonical_snapshot`, computed from a proposal.

    Produced by running the proposal through `resolve_customer_payload` and reading the
    columns back, so the preview shows what an approval would actually set rather than a
    second opinion about it. A proposal too incomplete to map has no proposed snapshot;
    the caller reports the refusal instead.
    """
    mapped = resolve_customer_payload(entered)
    payload = mapped.customer
    snapshot: dict[str, str | None] = dict.fromkeys(CUSTOMER_COLUMNS)
    for column in CUSTOMER_COLUMNS:
        if column in payload:
            snapshot[column] = payload[column]
    # ``create_customer`` takes ``email`` and ``phone`` and writes the ``*_entered``
    # columns, so the snapshot reads them from the payload's input names.
    snapshot["email_entered"] = payload.get("email")
    snapshot["phone_entered"] = payload.get("phone")
    return snapshot


def differences(
    proposed: dict[str, str | None], current: dict[str, str | None]
) -> list[dict[str, str | None]]:
    """Mapped columns whose proposed value differs from the customer's current one.

    Only the mapped columns, only when the proposal actually supplied something, and
    compared case-insensitively on whitespace-collapsed text -- a difference of casing in
    a name is not a difference a reviewer should be asked to adjudicate.

    **This is a report, not an instruction.** Nothing in the link-existing path reads it
    to decide what to write, because the link-existing path writes no canonical value at
    all (OD-28: proposal values differing from an existing customer must not silently
    overwrite it).
    """
    rows: list[dict[str, str | None]] = []
    for column in CUSTOMER_COLUMNS:
        new = proposed.get(column)
        old = current.get(column)
        if new is None:
            continue
        if _comparable(new) == _comparable(old):
            continue
        rows.append({"field": column, "proposed": new, "current": old})
    return rows


def _comparable(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).split()).casefold()
