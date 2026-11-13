"""Shipment CSV import (RC-UAT-21 Phase A, DEC-0230; OD-15 stand-in).

Creates ordinary **air** shipments for **existing** customers from a CSV, one row per
shipment, with the customer import's discipline (``customer_import_service``):

* the file goes through ``csv_safety`` -- the same 2 MiB / 5,000-row limits (OD-14), binary
  and encoding refusals, strict quoting and header allow-list;
* a **dry run** validates every row and reports per row; it writes no shipment, no batch
  and no link -- only its own audit entry, which is the proof a commit later asks for;
* a **commit** needs the same bytes (digest), an explicit confirmation, and a matching dry
  run by the same operator (``bulk_import_common.require_matching_dry_run``). It re-parses
  and re-validates; nothing the browser concluded is trusted;
* shipments are created through ``booking_service`` (and confirmed through it when the row
  says ``confirmed``), packages through ``package_service``, items through
  ``shipment_item_service`` -- the same rules and audit a typed booking gets;
* **no quote, invoice, email or milestone notification is created by an import** (stand-in
  A-4). No event is recorded, so the notification outbox is never reached;
* a row whose external reference was already imported is **refused** as a duplicate (the
  unique ``shipment_import_links (source_system, external_reference)`` backs this);
* every created shipment is traceable to its batch and row through
  ``shipment_import_links`` and carries ``source_system`` / ``source_record_id``.

A customer is never created by this import: an unknown customer reference rejects the row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.countries import normalize_country_code
from app.core.enums import (
    DIRECTION_COUNTRIES,
    BookingState,
    RouteGroup,
    ServiceType,
    TransportMode,
)
from app.core.normalization import collapse_whitespace, normalize_email
from app.core.time_utils import utcnow
from app.models import (
    SHIPMENT_IMPORT_SOURCE,
    ImportBatch,
    ImportBatchRow,
    ShipmentImportLink,
    User,
)
from app.services import (
    audit_service,
    booking_service,
    csv_safety,
    package_service,
    shipment_item_service,
)
from app.services import bulk_import_common as common
from app.services.bulk_import_common import RowIssue
from app.services.errors import ConflictError, DomainError, ValidationError

KIND = "shipments"

FIELD_SYNONYMS: dict[str, tuple[str, ...]] = {
    "external_reference": ("external_reference", "external_ref", "reference", "ma_tham_chieu"),
    "customer_ref": ("customer_ref", "customer_id", "customer", "ma_khach_hang"),
    "route_group": ("route_group", "route", "tuyen"),
    "direction": ("direction",),
    "transport_mode": ("transport_mode", "mode"),
    "service_type": ("service_type", "service"),
    "booking_state": ("booking_state", "state"),
    "booking_date": ("booking_date", "booked_on"),
    "booking_reference": ("booking_reference", "customer_reference"),
    "sender_name": ("sender_name",),
    "sender_phone": ("sender_phone",),
    "sender_address_line1": ("sender_address_line1", "sender_address"),
    "sender_city": ("sender_city",),
    "sender_province_state": ("sender_province_state", "sender_province"),
    "sender_postal_code": ("sender_postal_code",),
    "sender_country_code": ("sender_country_code", "sender_country"),
    "recipient_name": ("recipient_name", "nguoi_nhan"),
    "recipient_company": ("recipient_company",),
    "recipient_phone": ("recipient_phone",),
    "recipient_email": ("recipient_email",),
    "recipient_address_line1": ("recipient_address_line1", "recipient_address"),
    "recipient_address_line2": ("recipient_address_line2",),
    "recipient_city": ("recipient_city",),
    "recipient_province_state": ("recipient_province_state", "recipient_province"),
    "recipient_postal_code": ("recipient_postal_code",),
    "recipient_country_code": ("recipient_country_code", "recipient_country"),
    "recipient_delivery_note": ("recipient_delivery_note", "delivery_note"),
    "contents_description": ("contents_description", "contents"),
    "package_weights_kg": ("package_weights_kg", "weights_kg", "weights"),
    "package_dimensions_cm": ("package_dimensions_cm", "dimensions_cm", "dimensions"),
    "items": ("items",),
    "declared_value": ("declared_value",),
    "declared_value_currency": ("declared_value_currency", "currency"),
    "internal_notes": ("internal_notes", "notes"),
}
KNOWN_HEADERS = common.synonyms_to_known(FIELD_SYNONYMS)

REQUIRED_FIELDS: tuple[str, ...] = (
    "external_reference",
    "customer_ref",
    "recipient_name",
    "recipient_city",
    "recipient_country_code",
    "contents_description",
    "package_weights_kg",
)

TEMPLATE_HEADERS: tuple[str, ...] = (
    "external_reference",
    "customer_ref",
    "route_group",
    "booking_state",
    "booking_date",
    "booking_reference",
    "sender_name",
    "sender_phone",
    "sender_city",
    "recipient_name",
    "recipient_phone",
    "recipient_email",
    "recipient_address_line1",
    "recipient_city",
    "recipient_province_state",
    "recipient_postal_code",
    "recipient_country_code",
    "contents_description",
    "package_weights_kg",
    "package_dimensions_cm",
    "items",
    "declared_value",
    "declared_value_currency",
    "internal_notes",
)

#: Friendly spellings for a route group.
ROUTE_ALIASES = {
    "vn-ca": RouteGroup.VCA,
    "vn ca": RouteGroup.VCA,
    "vietnam to canada": RouteGroup.VCA,
    "ca-vn": RouteGroup.CAV,
    "canada to vietnam": RouteGroup.CAV,
    "ca-ca": RouteGroup.CAD,
    "domestic canada": RouteGroup.CAD,
    "ca-us": RouteGroup.XUS,
    "us-ca": RouteGroup.XUS,
}
DEFAULT_ROUTE_GROUP = RouteGroup.VCA
IMPORTABLE_BOOKING_STATES = (BookingState.DRAFT, BookingState.CONFIRMED)

#: Longest accepted text per field; longer is a row error, never a silent truncation.
MAX_LENGTHS = {
    "sender_name": 200,
    "recipient_name": 200,
    "recipient_company": 200,
    "sender_address_line1": 255,
    "recipient_address_line1": 255,
    "recipient_address_line2": 255,
    "sender_city": 120,
    "recipient_city": 120,
    "sender_province_state": 120,
    "recipient_province_state": 120,
    "sender_postal_code": 30,
    "recipient_postal_code": 30,
    "recipient_delivery_note": 400,
    "contents_description": 400,
    "booking_reference": 60,
}
#: One package heavier than this is almost certainly a unit mistake (grams, pounds x 1000).
MAX_PACKAGE_WEIGHT_KG = Decimal("500")


@dataclass
class ShipmentPlan:
    row_number: int
    reference: str | None
    customer_id: int | None = None
    customer_public_id: str | None = None
    draft: dict[str, Any] = field(default_factory=dict)
    items: list[dict[str, Any]] = field(default_factory=list)
    booking_state: str = BookingState.DRAFT
    booking_date: datetime | None = None
    issues: list[RowIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.issues


# --- Template ----------------------------------------------------------------------


def template_csv() -> str:
    """Header row plus two clearly synthetic sample rows (example.com, 555 numbers)."""
    import csv
    import io

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(TEMPLATE_HEADERS)
    writer.writerow(
        [
            "SAMPLE-SHP-0001",
            "STCA-000001",
            "VCA",
            "draft",
            "",
            "PO-SAMPLE-1",
            "Nguyễn Văn Mẫu",
            "+84 28 5555 0101",
            "Thành phố Hồ Chí Minh",
            "Trần Thị Mẫu",
            "+1 416 555 0102",
            "sample.recipient@example.com",
            "1 Sample Street",
            "Toronto",
            "ON",
            "M5V 0A1",
            "CA",
            "Quà tặng gia đình (sample)",
            "12.5;8",
            "40x30x30;30x30x20",
            "Áo dài|2|piece|80;Cà phê|3|box|30",
            "110",
            "CAD",
            "Sample row - safe to delete",
        ]
    )
    writer.writerow(
        [
            "SAMPLE-SHP-0002",
            "STCA-000002",
            "VCA",
            "confirmed",
            "2026-10-01",
            "",
            "Sample Trading Co.",
            "",
            "Hà Nội",
            "Lê Văn Mẫu",
            "+1 604 555 0103",
            "",
            "2 Sample Avenue",
            "Vancouver",
            "BC",
            "V6B 0A2",
            "CA",
            "Sample documents",
            "2",
            "",
            "",
            "",
            "",
            "",
        ]
    )
    return "﻿" + buffer.getvalue()


# --- Row validation -------------------------------------------------------------------


def _text(values: dict[str, str], name: str, issues: list[RowIssue]) -> str | None:
    value = collapse_whitespace(values.get(name, ""))
    if not value:
        return None
    limit = MAX_LENGTHS.get(name)
    if limit and len(value) > limit:
        issues.append(RowIssue(name, "too_long", f"{name} is longer than {limit} characters."))
        return None
    return value


def _decimal(raw: str, name: str, issues: list[RowIssue], *, allow_zero: bool) -> Decimal | None:
    text = (raw or "").strip().replace(",", "")
    if not text:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        issues.append(RowIssue(name, "invalid_number", f"'{raw}' is not a number."))
        return None
    if not number.is_finite() or number < 0 or (number == 0 and not allow_zero):
        issues.append(
            RowIssue(name, "invalid_number", f"'{raw}' must be a number greater than zero.")
        )
        return None
    return number


def _route_group(raw: str, issues: list[RowIssue]) -> str | None:
    value = collapse_whitespace(raw or "")
    if not value:
        return DEFAULT_ROUTE_GROUP
    if value.upper() in set(RouteGroup):
        return value.upper()
    alias = ROUTE_ALIASES.get(value.casefold())
    if alias:
        return alias
    issues.append(
        RowIssue(
            "route_group",
            "unknown_value",
            f"'{value}' is not a route group. Use one of: {', '.join(RouteGroup)} "
            "(VCA = Vietnam to Canada, the default).",
        )
    )
    return None


def _packages(values: dict[str, str], issues: list[RowIssue]) -> list[dict[str, Any]]:
    weights_raw = [part.strip() for part in (values.get("package_weights_kg") or "").split(";")]
    weights_raw = [part for part in weights_raw if part]
    if not weights_raw:
        issues.append(
            RowIssue(
                "package_weights_kg",
                "missing_packages",
                "At least one package weight is required (kg; separate packages with ';').",
            )
        )
        return []
    if len(weights_raw) > package_service.MAX_PACKAGES_PER_SHIPMENT:
        issues.append(
            RowIssue(
                "package_weights_kg",
                "too_many_packages",
                f"A shipment supports at most {package_service.MAX_PACKAGES_PER_SHIPMENT} "
                "packages.",
            )
        )
        return []
    packages: list[dict[str, Any]] = []
    for raw in weights_raw:
        weight = _decimal(raw, "package_weights_kg", issues, allow_zero=False)
        if weight is not None and weight > MAX_PACKAGE_WEIGHT_KG:
            issues.append(
                RowIssue(
                    "package_weights_kg",
                    "implausible_weight",
                    f"A package of {raw} kg is heavier than {MAX_PACKAGE_WEIGHT_KG} kg. "
                    "Check the unit: weights are in kilograms.",
                )
            )
        packages.append({"weight_value": str(weight) if weight else None, "weight_unit": "kg"})

    dims_raw = [part.strip() for part in (values.get("package_dimensions_cm") or "").split(";")]
    dims_raw = [part for part in dims_raw if part]
    if dims_raw:
        if len(dims_raw) != len(packages):
            issues.append(
                RowIssue(
                    "package_dimensions_cm",
                    "dimension_count_mismatch",
                    f"{len(dims_raw)} dimension(s) for {len(packages)} package(s). Give one "
                    "LxWxH per package, or leave the column empty.",
                )
            )
        else:
            for package, raw in zip(packages, dims_raw, strict=True):
                sides = [side.strip() for side in raw.lower().replace("×", "x").split("x")]
                numbers = [
                    _decimal(side, "package_dimensions_cm", issues, allow_zero=False)
                    for side in sides
                ]
                if len(sides) != 3 or any(number is None for number in numbers):
                    issues.append(
                        RowIssue(
                            "package_dimensions_cm",
                            "invalid_dimensions",
                            f"'{raw}' is not LxWxH in centimetres, such as 40x30x20.",
                        )
                    )
                    continue
                package.update(
                    {
                        "length_value": str(numbers[0]),
                        "width_value": str(numbers[1]),
                        "height_value": str(numbers[2]),
                        "dimension_unit": "cm",
                    }
                )
    return packages


def _items(values: dict[str, str], currency: str | None, issues: list[RowIssue]) -> list[dict]:
    raw = values.get("items") or ""
    items: list[dict[str, Any]] = []
    for index, chunk in enumerate((part.strip() for part in raw.split(";")), start=1):
        if not chunk:
            continue
        parts = [part.strip() for part in chunk.split("|")]
        description = collapse_whitespace(parts[0]) if parts else None
        if not description or len(parts) > 4:
            issues.append(
                RowIssue(
                    "items",
                    "invalid_item",
                    f"Item {index} is not 'description|quantity|unit|declared value'.",
                )
            )
            continue
        quantity = _decimal(parts[1] if len(parts) > 1 else "", "items", issues, allow_zero=False)
        unit = (parts[2] if len(parts) > 2 else "").lower() or "piece"
        if unit not in shipment_item_service.ALLOWED_UNITS:
            issues.append(
                RowIssue(
                    "items",
                    "unknown_unit",
                    f"Item {index}: unit '{unit}' is not one of "
                    f"{', '.join(shipment_item_service.ALLOWED_UNITS)}.",
                )
            )
            continue
        value = _decimal(parts[3] if len(parts) > 3 else "", "items", issues, allow_zero=True)
        items.append(
            {
                "description": description[:300],
                "quantity": str(quantity) if quantity else "1",
                "unit": unit,
                "declared_value": str(value) if value is not None else None,
                "declared_value_currency": currency if value is not None else None,
            }
        )
    return items


def build_plan(db: Session, row: csv_safety.ParsedRow) -> ShipmentPlan:
    """Validate one row into a creation plan. **Writes nothing.**"""
    values = row.values
    issues: list[RowIssue] = []
    reference = common.reference_value(
        values.get("external_reference"), "external_reference", issues
    )
    plan = ShipmentPlan(row_number=row.row_number, reference=reference, issues=issues)

    customer_ref = common.reference_value(values.get("customer_ref"), "customer_ref", issues)
    customer = common.customer_for_row(db, customer_ref, issues)
    if customer is not None:
        plan.customer_id = customer.id
        plan.customer_public_id = customer.public_id

    mode = collapse_whitespace(values.get("transport_mode", "")) or TransportMode.AIR
    if mode.casefold() != TransportMode.AIR:
        issues.append(
            RowIssue(
                "transport_mode",
                "air_only",
                f"'{mode}' cannot be imported. Only air shipments are imported in this release.",
            )
        )

    service = (collapse_whitespace(values.get("service_type", "")) or "").lower() or (
        ServiceType.STANDARD_PARCEL
    )
    if service not in set(ServiceType):
        issues.append(
            RowIssue(
                "service_type",
                "unknown_value",
                f"'{service}' is not a service type. Use one of: {', '.join(ServiceType)}.",
            )
        )

    state = (collapse_whitespace(values.get("booking_state", "")) or "").lower() or (
        BookingState.DRAFT
    )
    if state not in IMPORTABLE_BOOKING_STATES:
        issues.append(
            RowIssue(
                "booking_state",
                "unknown_value",
                f"'{state}' cannot be imported. Use draft or confirmed.",
            )
        )
    plan.booking_state = state

    booking_day = common.date_value(values.get("booking_date"), "booking_date", issues)
    if booking_day is not None:
        if booking_day > utcnow().date():
            issues.append(
                RowIssue("booking_date", "future_date", "The booking date is in the future.")
            )
        plan.booking_date = datetime.combine(booking_day, datetime.min.time())

    route_group = _route_group(values.get("route_group", ""), issues)
    direction = collapse_whitespace(values.get("direction", "")) or None

    texts = {name: _text(values, name, issues) for name in MAX_LENGTHS}

    origin_country = destination_country = None
    try:
        origin_country = normalize_country_code(values.get("sender_country_code"))
    except ValueError as exc:
        issues.append(RowIssue("sender_country_code", "unknown_country", str(exc)))
    try:
        destination_country = normalize_country_code(values.get("recipient_country_code"))
    except ValueError as exc:
        issues.append(RowIssue("recipient_country_code", "unknown_country", str(exc)))
    if not collapse_whitespace(values.get("recipient_country_code", "")):
        issues.append(
            RowIssue(
                "recipient_country_code", "missing_value", "recipient_country_code is required."
            )
        )

    if route_group:
        try:
            direction = booking_service.validate_route(
                route_group,
                direction,
                origin_country=origin_country,
                destination_country=destination_country,
            )
        except ValidationError as exc:
            issues.append(RowIssue(exc.field or "route_group", "invalid_route", exc.message))
            direction = None
    if route_group and direction and not origin_country:
        # The sender's country follows from the direction when the file leaves it out.
        origin_country = DIRECTION_COUNTRIES[direction][0]

    email = collapse_whitespace(values.get("recipient_email", ""))
    if email:
        try:
            normalize_email(email)
        except ValueError:
            issues.append(
                RowIssue("recipient_email", "invalid_email", f"'{email}' is not a valid email.")
            )

    for name in ("recipient_name", "recipient_city", "contents_description"):
        if not texts.get(name) and not any(issue.field_name == name for issue in issues):
            issues.append(RowIssue(name, "missing_value", f"{name} is required."))

    currency = collapse_whitespace(values.get("declared_value_currency", "")) or None
    # The booking screen's list, checked per row so the preview names the row rather than
    # the commit failing on it (RC-UAT-25 item 3).
    if currency and currency.upper() not in booking_service.DECLARED_VALUE_CURRENCIES:
        issues.append(
            RowIssue(
                "declared_value_currency",
                "invalid_currency",
                booking_service.DECLARED_VALUE_CURRENCY_MESSAGE,
            )
        )
        currency = None
    currency = currency.upper() if currency else None
    declared_value = _decimal(
        values.get("declared_value", ""), "declared_value", issues, allow_zero=True
    )

    packages = _packages(values, issues)
    plan.items = _items(values, currency or "CAD", issues)

    if plan.is_valid and customer is not None:
        plan.draft = {
            "customer_id": customer.id,
            "route_group": route_group,
            "direction": direction,
            "service_type": service,
            "transport_mode": TransportMode.AIR,
            "booking_reference": texts.get("booking_reference"),
            "contents_description": texts.get("contents_description"),
            "declared_value": str(declared_value) if declared_value is not None else None,
            "declared_value_currency": currency,
            "internal_notes": collapse_whitespace(values.get("internal_notes", "")) or None,
            "sender": {
                "name": texts.get("sender_name") or customer.full_name,
                "phone_entered": collapse_whitespace(values.get("sender_phone", "")) or None,
                "address_line1": texts.get("sender_address_line1"),
                "city": texts.get("sender_city"),
                "province_state": texts.get("sender_province_state"),
                "postal_code": texts.get("sender_postal_code"),
                "country_code": origin_country,
            },
            "recipient": {
                "name": texts.get("recipient_name"),
                "company": texts.get("recipient_company"),
                "phone_entered": collapse_whitespace(values.get("recipient_phone", "")) or None,
                "email": email or None,
                "address_line1": texts.get("recipient_address_line1"),
                "address_line2": texts.get("recipient_address_line2"),
                "city": texts.get("recipient_city"),
                "province_state": texts.get("recipient_province_state"),
                "postal_code": texts.get("recipient_postal_code"),
                "country_code": destination_country,
                "delivery_note": texts.get("recipient_delivery_note"),
            },
            "packages": packages,
        }
    return plan


def _summary(plan: ShipmentPlan) -> dict[str, Any]:
    draft = plan.draft
    if not draft:
        return {}
    return {
        "route_group": draft["route_group"],
        "direction": draft["direction"],
        "transport_mode": draft["transport_mode"],
        "booking_state": plan.booking_state,
        "recipient_name": draft["recipient"]["name"],
        "recipient_city": draft["recipient"]["city"],
        "package_count": len(draft["packages"]),
        "item_count": len(plan.items),
    }


def _already_imported(db: Session, reference: str) -> ShipmentImportLink | None:
    return db.scalar(
        select(ShipmentImportLink).where(
            ShipmentImportLink.source_system == SHIPMENT_IMPORT_SOURCE,
            ShipmentImportLink.external_reference == reference,
        )
    )


def _parse(content: bytes) -> csv_safety.ParsedFile:
    return csv_safety.parse(content, known_fields=KNOWN_HEADERS, required_headers=REQUIRED_FIELDS)


# --- Dry run ----------------------------------------------------------------------------


DUPLICATE = "duplicate"


def dry_run(db: Session, content: bytes, *, file_name: str | None = None) -> common.DryRun:
    """Parse and validate every row and say what a commit would do. **Writes nothing.**"""
    parsed = _parse(content)
    counts = {common.READY: 0, DUPLICATE: 0, common.REJECTED: 0}
    rows: list[common.DryRunRow] = []
    seen: dict[str, int] = {}
    for parsed_row in parsed.rows:
        plan = build_plan(db, parsed_row)
        out = common.DryRunRow(
            row_number=plan.row_number,
            classification=common.REJECTED,
            reference=plan.reference,
            customer_public_id=plan.customer_public_id,
            summary=_summary(plan),
            issues=list(plan.issues),
        )
        if plan.reference and plan.reference in seen:
            out.classification = DUPLICATE
            out.issues.append(
                RowIssue(
                    "external_reference",
                    "duplicate_within_file",
                    f"This reference repeats row {seen[plan.reference]}; it will not be imported "
                    "twice.",
                )
            )
        elif plan.reference and _already_imported(db, plan.reference) is not None:
            out.classification = DUPLICATE
            out.issues.append(
                RowIssue(
                    "external_reference",
                    "already_imported",
                    "A shipment with this external reference was already imported. Duplicates "
                    "are refused.",
                )
            )
        elif plan.is_valid:
            out.classification = common.READY
        if plan.reference and plan.reference not in seen:
            seen[plan.reference] = plan.row_number
        counts[out.classification] += 1
        rows.append(out)

    notes = [
        (
            "dry_run_only_shipments",
            "Dry run only: no shipment, package, item or import batch has been created.",
        ),
        (
            "no_side_effects",
            "An import never creates a quote, an invoice, an email or a milestone notification.",
        ),
        (
            "air_only_existing_customers",
            "Only air shipments are imported. A customer is never created: every row must "
            "name an existing customer.",
        ),
    ]
    if parsed.unmapped_headers:
        notes.append(
            (
                "unmapped_columns",
                "These columns were not recognized and are ignored: "
                + ", ".join(parsed.unmapped_headers)
                + ".",
            )
        )
    return common.DryRun(
        kind=KIND,
        content_sha256=common.content_digest(content),
        options={},
        file_name=common.clean_file_name(file_name),
        row_count=len(parsed.rows),
        headers=parsed.headers,
        unmapped_headers=parsed.unmapped_headers,
        rows=rows,
        counts=counts,
        notes=[text for _code, text in notes],
        note_codes=[code for code, _text in notes],
    )


# --- Commit ------------------------------------------------------------------------------


def commit(
    db: Session,
    content: bytes,
    *,
    expected_sha256: str,
    actor: User,
    file_name: str | None = None,
    ip_address: str | None = None,
) -> common.CommitResult:
    """Create the valid, non-duplicate rows inside the caller's transaction.

    Each row is created inside its own savepoint, so a row that a service refuses at write
    time (a rule the dry run could not see) is rolled back alone and reported as rejected.
    """
    digest = common.check_digest(content, expected_sha256)
    dry_run_event_id = common.require_matching_dry_run(
        db, kind=KIND, content_sha256=digest, options={}, actor=actor
    )
    parsed = _parse(content)

    now = utcnow()
    batch = ImportBatch(
        public_id=common.next_batch_public_id(db),
        kind=KIND,
        file_name=common.clean_file_name(file_name),
        content_sha256=digest,
        source_system=SHIPMENT_IMPORT_SOURCE,
        conflict_policy="refuse_duplicates",
        row_count=len(parsed.rows),
        committed_at=now,
        committed_by_user_id=actor.id,
    )
    db.add(batch)
    db.flush()

    counts = {common.CREATED: 0, common.MATCHED: 0, common.SKIPPED: 0, common.REJECTED: 0}
    result_rows: list[dict] = []
    seen: set[str] = set()
    for parsed_row in parsed.rows:
        plan = build_plan(db, parsed_row)
        try:
            outcome, reason, shipment = _apply(db, batch, plan, seen=seen, actor=actor, now=now)
        except OperationalError as exc:
            # A locked or unavailable database mid-commit. Nothing of this batch may land:
            # roll the whole transaction back (batch, earlier rows and all) and say so.
            db.rollback()
            raise ConflictError(
                "The database was busy and the import was stopped. Nothing has been "
                "imported. Run the dry run again and retry.",
                detail={"reason": "database_busy"},
            ) from exc
        counts[outcome] += 1
        db.add(
            ImportBatchRow(
                batch_id=batch.id,
                row_number=plan.row_number,
                outcome=outcome,
                reason_code=reason,
                customer_id=plan.customer_id,
                source_record_id=plan.reference,
            )
        )
        result_rows.append(
            {
                "row_number": plan.row_number,
                "outcome": outcome,
                "reason_code": reason,
                "reference": plan.reference,
                "record_id": shipment.id if shipment is not None else None,
                "record_label": (shipment.public_id or "draft") if shipment is not None else None,
            }
        )

    batch.created_count = counts[common.CREATED]
    batch.matched_count = counts[common.MATCHED]
    batch.skipped_count = counts[common.SKIPPED]
    batch.rejected_count = counts[common.REJECTED]
    db.flush()

    audit_service.record_audit(
        db,
        action="shipment.import_commit",
        entity_type="import_batch",
        entity_id=batch.public_id,
        summary=(
            f"Imported {counts[common.CREATED]} shipment(s) from CSV; "
            f"{counts[common.SKIPPED]} duplicate(s) refused, {counts[common.REJECTED]} rejected"
        ),
        actor=actor,
        ip_address=ip_address,
        detail={
            "batch_public_id": batch.public_id,
            "row_count": batch.row_count,
            "created": counts[common.CREATED],
            "skipped": counts[common.SKIPPED],
            "rejected": counts[common.REJECTED],
            "content_sha256": digest,
            # Consumes the dry run: a second commit needs a new one (bulk_import_common).
            "dry_run_event_id": dry_run_event_id,
        },
    )
    return common.CommitResult(
        kind=KIND,
        batch_public_id=batch.public_id,
        created=counts[common.CREATED],
        matched=counts[common.MATCHED],
        skipped=counts[common.SKIPPED],
        rejected=counts[common.REJECTED],
        row_count=batch.row_count,
        rows=result_rows,
    )


def _apply(db: Session, batch: ImportBatch, plan: ShipmentPlan, *, seen: set[str], actor, now):
    if not plan.is_valid:
        codes = sorted({issue.code for issue in plan.issues})
        return common.REJECTED, ",".join(codes)[:60], None
    assert plan.reference is not None
    if plan.reference in seen:
        return common.SKIPPED, "duplicate_within_file", None
    seen.add(plan.reference)
    if _already_imported(db, plan.reference) is not None:
        return common.SKIPPED, "duplicate_external_reference", None

    savepoint = db.begin_nested()
    try:
        shipment = booking_service.create_draft(db, dict(plan.draft), actor=actor)
        shipment.source_system = SHIPMENT_IMPORT_SOURCE
        shipment.source_record_id = plan.reference
        if plan.booking_date is not None:
            shipment.booking_date = plan.booking_date
        for item in plan.items:
            shipment_item_service.add_item(db, shipment, item, actor=actor)
        if plan.booking_state == BookingState.CONFIRMED:
            # The single, non-retrying confirmation. ``confirm_booking`` retries a locked
            # database by rolling the *session* back, which inside this loop would undo the
            # batch and every earlier row while the loop carried on. Here a lock raises
            # ``OperationalError`` and ``commit`` aborts the whole import instead.
            booking_service._confirm_once(
                db,
                shipment_id=shipment.id,
                key=f"import:{batch.public_id}:{plan.row_number}",
                actor=actor,
                ip_address=None,
            )
        db.add(
            ShipmentImportLink(
                batch_id=batch.id,
                row_number=plan.row_number,
                shipment_id=shipment.id,
                source_system=SHIPMENT_IMPORT_SOURCE,
                external_reference=plan.reference,
                created_at=now,
            )
        )
        db.flush()
    except DomainError as exc:
        savepoint.rollback()
        return common.REJECTED, f"refused:{exc.code}"[:60], None
    except IntegrityError as exc:
        # Another commit imported the same external reference between our check and this
        # insert. The unique link constraint caught it: a refused duplicate, not a 500.
        savepoint.rollback()
        if "external_reference" not in str(exc.orig):
            raise
        return common.SKIPPED, "duplicate_external_reference", None
    savepoint.commit()
    return common.CREATED, "created_from_import", shipment
