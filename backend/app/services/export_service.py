"""CSV exports (CRM.md section 13).

Four rules, each of which has failed somewhere in some product before:

1. **Every export declares an allowlist of columns.** Not an exclusion list. An exclusion
   list is wrong the moment somebody adds a column, and the person adding a column is not
   the person thinking about exports — Phase 2 added address snapshots to ``shipments``
   and Phase 4A added a payload column to a new table, and under an exclusion list both
   would have appeared in an export by default. The allowlist fails the safe way
   (DEC-0080).

2. **Every cell is escaped against spreadsheet formula injection.** A customer whose name
   or note begins with ``=``, ``+``, ``-``, ``@``, tab, carriage return or newline must
   not become a formula when the file is opened (DEC-0081).

3. **Exports stream.** The generator holds one bounded page at a time, so exporting the
   whole customer book does not depend on the book being small.

4. **Nothing is written to disk.** The response is generated and sent. No export file
   containing customer data is ever persisted, so there is nothing to leak later.

What is deliberately *not* in any allowlist here: internal notes, interaction bodies,
audit payloads, session or credential material, integration secrets, raw provider
payloads, and anything from the Phase 4A integration tables. A test asserts the column
sets directly, and a second test asserts that no allowlist names a forbidden field.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.enums import ConsentChannel, value_label
from app.core.normalization import escape_csv_value
from app.core.permissions import Permission, permissions_for
from app.core.time_utils import to_timezone
from app.models import Customer, Shipment, ShipmentPackage
from app.services.errors import PermissionDeniedError

#: Rows fetched per database round trip while streaming. Small enough that memory stays
#: flat on a large export, large enough that a big export is not thousands of queries.
BATCH_SIZE = 500

#: Excel needs a UTF-8 byte-order mark to open a UTF-8 CSV as UTF-8 rather than as the
#: system codepage. Without it, Vietnamese diacritics arrive as mojibake even though the
#: file is perfectly valid (CRM.md section 13).
UTF8_BOM = "﻿"

#: Fields no export may ever carry, checked by a test against every allowlist. This is a
#: belt-and-braces guard *on top of* the allowlists, not a substitute for them.
FORBIDDEN_COLUMN_FRAGMENTS: tuple[str, ...] = (
    "password",
    "secret",
    "token",
    "credential",
    "api_key",
    "session",
    "signature",
    "payload",
    "internal_note",
    "internal_notes",
    "internal_detail",
    "audit",
    "csrf",
    "authorization",
    "cookie",
)


@dataclass(frozen=True)
class ExportColumn:
    """One allowlisted column.

    ``permission`` gates the column itself: a caller without it does not receive the
    column at all — not blank, not null, not zero. The header is absent too, because a
    header named "shipping_cost" over an empty column still tells the reader that a cost
    exists and they are not allowed to see it.
    """

    key: str
    header: str
    permission: str | None = None


@dataclass(frozen=True)
class ExportDefinition:
    key: str
    #: Permission required to run this export at all, independent of record access.
    permission: str
    filename: str
    columns: tuple[ExportColumn, ...]
    description: str

    def headers_for(self, role: str) -> list[str]:
        granted = permissions_for(role)
        return [
            column.header
            for column in self.columns
            if column.permission is None or column.permission in granted
        ]

    def columns_for(self, role: str) -> list[ExportColumn]:
        granted = permissions_for(role)
        return [
            column
            for column in self.columns
            if column.permission is None or column.permission in granted
        ]


# --- Allowlists ---------------------------------------------------------------
#
# Read these as the privacy contract. A field that is not written here does not leave the
# system through an export.

CUSTOMER_EXPORT = ExportDefinition(
    key="customers",
    permission=Permission.EXPORT_CUSTOMERS,
    filename="solaris-customers.csv",
    description=(
        "Customer records matching the active filters and the caller's record scope. "
        "Private notes are deliberately excluded."
    ),
    columns=(
        ExportColumn("customer_id", "customer_id"),
        ExportColumn("full_name", "full_name"),
        ExportColumn("phone", "phone"),
        ExportColumn("email", "email"),
        ExportColumn("city", "city"),
        ExportColumn("province_state", "province_state"),
        ExportColumn("country_code", "country_code"),
        ExportColumn("preferred_language", "preferred_language"),
        ExportColumn("category", "category"),
        ExportColumn("business_name", "business_name"),
        ExportColumn("primary_route_group", "declared_primary_route"),
        ExportColumn("observed_primary_route_group", "observed_primary_route"),
        ExportColumn("lifecycle_status", "lifecycle_status"),
        ExportColumn("total_qualifying_shipments", "qualifying_shipments"),
        ExportColumn("total_bookings", "bookings"),
        ExportColumn("first_shipment_at", "first_shipment_at"),
        ExportColumn("last_shipment_at", "last_shipment_at"),
        ExportColumn("is_repeat_customer", "repeat_customer"),
        ExportColumn("do_not_contact", "do_not_contact"),
        ExportColumn("email_marketing_eligible", "email_marketing_eligible"),
        ExportColumn("sms_marketing_eligible", "sms_marketing_eligible"),
        ExportColumn("is_archived", "archived"),
        ExportColumn("created_at", "date_added"),
        ExportColumn("source_system", "source_system"),
        ExportColumn("source_record_id", "source_record_id"),
    ),
)

MARKETING_SEGMENT_EXPORT = ExportDefinition(
    key="marketing_segment",
    permission=Permission.EXPORT_MARKETING_SEGMENT,
    filename="solaris-segment-audience.csv",
    description=(
        "Segment members who are actually eligible to receive marketing on the selected "
        "channel. Suppressed, withdrawn, unknown-consent, do-not-contact and archived "
        "records are excluded from the file, not merely flagged in it."
    ),
    columns=(
        ExportColumn("customer_id", "customer_id"),
        ExportColumn("full_name", "full_name"),
        ExportColumn("channel", "channel"),
        ExportColumn("address", "address"),
        ExportColumn("preferred_language", "preferred_language"),
        ExportColumn("city", "city"),
        ExportColumn("country_code", "country_code"),
        ExportColumn("consent_status", "consent_status"),
        ExportColumn("consent_basis", "consent_basis"),
        ExportColumn("consent_obtained_at", "consent_obtained_at"),
    ),
)

SHIPMENT_EXPORT = ExportDefinition(
    key="shipments",
    permission=Permission.EXPORT_SHIPMENTS,
    filename="solaris-shipments.csv",
    description=(
        "Shipment records matching the active filters. Recipient and sender street "
        "addresses, phone numbers, emails, internal notes and carrier costs are excluded "
        "or permission-gated."
    ),
    columns=(
        ExportColumn("public_id", "solaris_shipment_id"),
        ExportColumn("customer_public_id", "customer_id"),
        ExportColumn("customer_name", "customer_name"),
        ExportColumn("route_group", "route_group"),
        ExportColumn("direction", "direction"),
        ExportColumn("service_type", "service_type"),
        ExportColumn("transport_mode", "transport_mode"),
        ExportColumn("booking_state", "booking_state"),
        ExportColumn("operational_state", "operational_state"),
        ExportColumn("payment_state", "payment_state"),
        ExportColumn("is_return", "is_return"),
        ExportColumn("package_count", "package_count"),
        ExportColumn("packages_active", "packages_active"),
        ExportColumn("packages_delivered", "packages_delivered"),
        # Coarse geography only. Street lines, postal codes, recipient phone and
        # recipient email are not exportable: a shipment export is an operations report,
        # not a copy of somebody's address book.
        ExportColumn("origin_city", "origin_city"),
        ExportColumn("origin_country_code", "origin_country"),
        ExportColumn("destination_city", "destination_city"),
        ExportColumn("destination_country_code", "destination_country"),
        ExportColumn("booking_date", "booking_date"),
        ExportColumn("first_handoff_at", "first_handoff_at"),
        ExportColumn("estimated_delivery_at", "estimated_delivery_at"),
        ExportColumn("delivered_at", "delivered_at"),
        ExportColumn("cancelled_at", "cancelled_at"),
        ExportColumn("currency", "currency", Permission.FINANCIAL_READ),
        ExportColumn("selling_amount", "selling_amount", Permission.FINANCIAL_READ),
        ExportColumn("discount_amount", "discount_amount", Permission.FINANCIAL_READ),
        ExportColumn("refund_amount", "refund_amount", Permission.FINANCIAL_READ),
        ExportColumn("shipping_cost", "shipping_cost", Permission.FINANCIAL_COST_READ),
        ExportColumn("surcharges_amount", "surcharges_amount", Permission.FINANCIAL_COST_READ),
    ),
)

PACKAGE_EXPORT = ExportDefinition(
    key="packages",
    permission=Permission.EXPORT_SHIPMENTS,
    filename="solaris-packages.csv",
    description=(
        "Package records for the shipments matching the active filters. A package is "
        "never a shipment: this file has one row per package and the shipment reports "
        "count each shipment once."
    ),
    columns=(
        ExportColumn("package_reference", "package_reference"),
        ExportColumn("shipment_public_id", "solaris_shipment_id"),
        ExportColumn("customer_public_id", "customer_id"),
        ExportColumn("sequence", "sequence"),
        ExportColumn("route_group", "route_group"),
        ExportColumn("is_active", "active"),
        ExportColumn("operational_state", "operational_state"),
        ExportColumn("length_cm", "length_cm"),
        ExportColumn("width_cm", "width_cm"),
        ExportColumn("height_cm", "height_cm"),
        ExportColumn("weight_kg", "weight_kg"),
        ExportColumn("dimension_unit", "entered_dimension_unit"),
        ExportColumn("weight_unit", "entered_weight_unit"),
        ExportColumn("contents_summary", "contents_summary"),
        ExportColumn("warehouse_location", "warehouse_location"),
        ExportColumn("delivered_to_recipient_at", "delivered_to_recipient_at"),
        ExportColumn("cancelled_at", "cancelled_at"),
    ),
)

#: Report results are exported from the report's own declared columns, so the allowlist
#: is the report definition itself and cannot drift from what the screen showed.
REPORT_EXPORT_PERMISSION = Permission.EXPORT_REPORTS

EXPORTS: dict[str, ExportDefinition] = {
    definition.key: definition
    for definition in (
        CUSTOMER_EXPORT,
        MARKETING_SEGMENT_EXPORT,
        SHIPMENT_EXPORT,
        PACKAGE_EXPORT,
    )
}


def require_export_permission(role: str, definition: ExportDefinition) -> None:
    """Export permission is checked independently of record access (CRM.md section 13).

    Being allowed to read a customer is not being allowed to extract every customer.
    """
    if definition.permission not in permissions_for(role):
        raise PermissionDeniedError(
            "Your role does not allow this export.",
            detail={"required": [definition.permission], "role": role},
        )


# --- Serialization ------------------------------------------------------------


def format_cell(value: Any, tz_name: str | None = None) -> str:
    """Render one value as CSV text, then escape it against formula injection."""
    if value is None:
        # Empty, not "None" and not 0. An unknown value must read as unknown.
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, datetime):
        local = to_timezone(value, tz_name)
        return escape_csv_value(local.isoformat(timespec="seconds") if local else "")
    if isinstance(value, Decimal):
        return escape_csv_value(format(value, "f"))
    if isinstance(value, float | int):
        return escape_csv_value(str(value))
    return escape_csv_value(str(value))


def write_row(buffer: io.StringIO, writer: csv.writer, values: list[str]) -> str:
    writer.writerow(values)
    chunk = buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    return chunk


def stream_csv(
    headers: list[str], rows: Iterator[list[Any]], *, tz_name: str | None = None
) -> Iterator[str]:
    """Yield a CSV a chunk at a time.

    ``csv.writer`` handles quoting, embedded commas, embedded quotes and newlines
    correctly; ``format_cell`` handles the formula-injection prefix. Doing quoting by hand
    is how CSV exports produce files that will not parse.
    """
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    yield UTF8_BOM + write_row(buffer, writer, headers)
    for row in rows:
        yield write_row(buffer, writer, [format_cell(value, tz_name) for value in row])


def paged(db: Session, statement: Select, batch_size: int = BATCH_SIZE) -> Iterator[Any]:
    """Walk a query in bounded pages.

    Deliberately offset-paged with a stable ``ORDER BY`` supplied by the caller rather
    than materialized in one list: the point is that memory does not grow with the size of
    the export.
    """
    offset = 0
    while True:
        page = list(db.scalars(statement.limit(batch_size).offset(offset)).unique().all())
        if not page:
            return
        yield from page
        if len(page) < batch_size:
            return
        offset += batch_size


# --- Row builders -------------------------------------------------------------


def customer_rows(
    db: Session,
    statement: Select,
    role: str,
    thresholds,
) -> Iterator[list[Any]]:
    """One row per customer, with derived activity computed per record."""
    from app.services import consent_service
    from app.services.activity_service import compute_customer_activity

    columns = CUSTOMER_EXPORT.columns_for(role)
    for customer in paged(db, statement):
        activity = compute_customer_activity(db, customer, thresholds)
        values = {
            "customer_id": customer.public_id,
            "full_name": customer.full_name,
            "phone": customer.phone_entered,
            "email": customer.email_entered,
            "city": customer.city,
            "province_state": customer.province_state,
            "country_code": customer.country_code,
            "preferred_language": value_label(customer.preferred_language),
            "category": value_label(customer.category),
            "business_name": customer.business_name,
            "primary_route_group": customer.primary_route_group,
            "observed_primary_route_group": activity.observed_primary_route_group,
            "lifecycle_status": activity.lifecycle_status,
            "total_qualifying_shipments": activity.total_qualifying_shipments,
            "total_bookings": activity.total_bookings,
            "first_shipment_at": activity.first_shipment_at,
            "last_shipment_at": activity.last_shipment_at,
            "is_repeat_customer": activity.is_repeat_customer,
            "do_not_contact": customer.do_not_contact,
            "email_marketing_eligible": consent_service.marketing_eligible(
                db, customer, ConsentChannel.EMAIL
            ),
            "sms_marketing_eligible": consent_service.marketing_eligible(
                db, customer, ConsentChannel.SMS
            ),
            "is_archived": customer.is_archived,
            "created_at": customer.created_at,
            "source_system": customer.source_system,
            "source_record_id": customer.source_record_id,
        }
        yield [values[column.key] for column in columns]


def marketing_segment_rows(
    db: Session, customers: Iterator[Customer], channel: str
) -> Iterator[list[Any]]:
    """Only the members who may actually be contacted on this channel.

    Ineligible records are **omitted from the file**, not flagged in it. A flagged row in
    a spreadsheet is one careless sort away from being mailed (CRM.md section 13).
    """
    from app.services import consent_service

    columns = MARKETING_SEGMENT_EXPORT.columns
    for customer in customers:
        if not consent_service.marketing_eligible(db, customer, channel):
            continue
        address = consent_service.normalized_address_for(customer, channel)
        if not address:
            continue
        state = consent_service.current_state(db, customer, channel)
        values = {
            "customer_id": customer.public_id,
            "full_name": customer.full_name,
            "channel": channel,
            "address": address,
            "preferred_language": value_label(customer.preferred_language),
            "city": customer.city,
            "country_code": customer.country_code,
            "consent_status": state.status,
            "consent_basis": state.basis,
            "consent_obtained_at": state.obtained_at,
        }
        yield [values[column.key] for column in columns]


def shipment_rows(db: Session, statement: Select, role: str) -> Iterator[list[Any]]:
    from sqlalchemy import func

    columns = SHIPMENT_EXPORT.columns_for(role)
    for shipment in paged(db, statement):
        customer = db.get(Customer, shipment.customer_id)
        package_stats = db.execute(
            select(
                func.count(ShipmentPackage.id),
                func.sum(
                    _one_when(ShipmentPackage.is_active.is_(True)),
                ),
                func.sum(
                    _one_when(ShipmentPackage.delivered_to_recipient_at.is_not(None)),
                ),
            ).where(ShipmentPackage.shipment_id == shipment.id)
        ).one()
        values = {
            "public_id": shipment.public_id,
            "customer_public_id": customer.public_id if customer else None,
            "customer_name": customer.full_name if customer else None,
            "route_group": shipment.route_group,
            "direction": shipment.direction,
            "service_type": shipment.service_type,
            "transport_mode": shipment.transport_mode,
            "booking_state": shipment.booking_state,
            "operational_state": shipment.operational_state,
            "payment_state": shipment.payment_state,
            "is_return": shipment.is_return,
            "package_count": shipment.package_count,
            "packages_active": int(package_stats[1] or 0),
            "packages_delivered": int(package_stats[2] or 0),
            "origin_city": shipment.sender_city,
            "origin_country_code": shipment.sender_country_code,
            "destination_city": shipment.recipient_city,
            "destination_country_code": shipment.recipient_country_code,
            "booking_date": shipment.booking_date,
            "first_handoff_at": shipment.first_handoff_at,
            "estimated_delivery_at": shipment.estimated_delivery_at,
            "delivered_at": shipment.delivered_at,
            "cancelled_at": shipment.cancelled_at,
            "currency": shipment.currency,
            "selling_amount": shipment.selling_amount,
            "discount_amount": shipment.discount_amount,
            "refund_amount": shipment.refund_amount,
            "shipping_cost": shipment.shipping_cost,
            "surcharges_amount": shipment.surcharges_amount,
        }
        yield [values[column.key] for column in columns]


def _one_when(condition):
    from sqlalchemy import case

    return case((condition, 1), else_=0)


def package_rows(db: Session, statement: Select, role: str) -> Iterator[list[Any]]:
    columns = PACKAGE_EXPORT.columns_for(role)
    for package in paged(db, statement):
        shipment = db.get(Shipment, package.shipment_id)
        customer = db.get(Customer, shipment.customer_id) if shipment else None
        values = {
            "package_reference": package.package_reference,
            "shipment_public_id": shipment.public_id if shipment else None,
            "customer_public_id": customer.public_id if customer else None,
            "sequence": package.sequence,
            "route_group": shipment.route_group if shipment else None,
            "is_active": package.is_active,
            "operational_state": package.operational_state,
            "length_cm": package.length_cm,
            "width_cm": package.width_cm,
            "height_cm": package.height_cm,
            "weight_kg": package.weight_kg,
            "dimension_unit": package.dimension_unit,
            "weight_unit": package.weight_unit,
            "contents_summary": package.contents_summary,
            "warehouse_location": package.warehouse_location,
            "delivered_to_recipient_at": package.delivered_to_recipient_at,
            "cancelled_at": package.cancelled_at,
        }
        yield [values[column.key] for column in columns]


def report_rows(table) -> Iterator[list[Any]]:
    """Report results, from the report's own declared columns.

    The allowlist here *is* the report definition, so an exported report cannot contain a
    field the screen did not show — including a financial column the caller's role caused
    to be omitted.
    """
    for row in table.rows:
        yield [row.get(column.key) for column in table.columns]
