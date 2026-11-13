"""CSV export routes (CRM.md section 13).

Each route does four things and nothing else: check the export permission (which is
separate from the permission to read the records), build the same filter predicates the
corresponding list screen uses, audit the fact of the export, and stream.

Two properties worth stating because they are easy to lose:

* **The audit entry records the export, never the exported data.** Type, filters, row
  count, and actor. No customer value reaches the audit log (CRM.md section 11).
* **The response streams and nothing is written to disk.** No export file containing
  customer data is persisted, so there is nothing to find later.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import DbSession, OrgSettings, Thresholds, client_ip, require
from app.core.db import commit_with_retry
from app.core.enums import ConsentChannel
from app.core.permissions import Permission
from app.models import Customer, Shipment, ShipmentPackage, User
from app.services import (
    audit_service,
    customer_service,
    export_service,
    report_service,
    segment_service,
    shipment_service,
)
from app.services.errors import NotFoundError, ValidationError

router = APIRouter(prefix="/exports", tags=["exports"])

#: A caller must be able to read the records *and* be allowed to export. Two permissions,
#: two dependencies, both enforced (CRM.md section 13, AC-2).
CustomerExporter = Annotated[
    User, Depends(require(Permission.CUSTOMER_READ, Permission.EXPORT_CUSTOMERS))
]
ShipmentExporter = Annotated[
    User, Depends(require(Permission.SHIPMENT_READ, Permission.EXPORT_SHIPMENTS))
]
SegmentExporter = Annotated[
    User, Depends(require(Permission.SEGMENT_READ, Permission.EXPORT_MARKETING_SEGMENT))
]
ReportExporter = Annotated[
    User, Depends(require(Permission.REPORT_READ, Permission.EXPORT_REPORTS))
]


def _csv_response(definition_key: str, filename: str, chunks: Iterator[str]) -> StreamingResponse:
    return StreamingResponse(
        chunks,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # An export is a snapshot of live personal data. It must not sit in a shared
            # cache, and it must not be stored by an intermediary.
            "Cache-Control": "no-store",
            "X-Export-Type": definition_key,
        },
    )


def _audit_export(
    db,
    *,
    user: User,
    request: Request,
    definition: export_service.ExportDefinition,
    row_count: int,
    filters: dict,
) -> None:
    """Record that an export happened. Never record what was in it."""
    audit_service.record_audit(
        db,
        action=f"export.{definition.key}",
        entity_type="export",
        entity_id=definition.key,
        summary=f"Exported {row_count} {definition.key} row(s) to CSV",
        actor=user,
        ip_address=client_ip(request),
        detail={
            "export_type": definition.key,
            "row_count": row_count,
            # Filter *values* are query parameters the operator chose, not customer
            # records. A free-text search term could contain a customer's name, so it is
            # recorded as present or absent rather than verbatim.
            "filters": {
                key: ("[provided]" if key == "search" else value)
                for key, value in sorted(filters.items())
                if value not in (None, [], "", False)
            },
            "columns": definition.headers_for(user.role),
        },
    )
    commit_with_retry(db)


@router.get("/definitions")
def export_definitions(user: Annotated[User, Depends(require(Permission.CUSTOMER_READ))]) -> dict:
    """Which exports this caller may run, and exactly which columns each produces.

    Documented through the API so the column contract is discoverable rather than only
    written down in ``docs/``.
    """
    from app.core.permissions import permissions_for

    granted = permissions_for(user.role)
    return {
        "exports": [
            {
                "key": definition.key,
                "permission": definition.permission,
                "allowed": definition.permission in granted,
                "filename": definition.filename,
                "description": definition.description,
                "columns": definition.headers_for(user.role),
            }
            for definition in export_service.EXPORTS.values()
        ],
        "reports": {
            "permission": export_service.REPORT_EXPORT_PERMISSION,
            "allowed": export_service.REPORT_EXPORT_PERMISSION in granted,
            "available": list(report_service.available_report_keys(user.role)),
        },
        "protections": [
            "Cells beginning with =, +, -, @, tab, carriage return or newline are prefixed "
            "so a spreadsheet treats them as text.",
            "Files are UTF-8 with a byte-order mark so Vietnamese text opens correctly.",
            "Exports stream and are never written to disk.",
            "Every export is audited; no exported value reaches the audit log.",
        ],
    }


@router.get("/customers.csv")
def export_customers(
    request: Request,
    db: DbSession,
    thresholds: Thresholds,
    org: OrgSettings,
    user: CustomerExporter,
    search: str | None = None,
    q: str | None = Query(default=None, max_length=120),
    category: list[str] | None = Query(default=None),
    lifecycle_status: list[str] | None = Query(default=None),
    preferred_language: list[str] | None = Query(default=None),
    primary_route: list[str] | None = Query(default=None),
    observed_route: str | None = None,
    owner_user_id: int | None = None,
    tag_id: list[int] | None = Query(default=None),
    has_overdue_task: bool | None = None,
    has_service_issue: bool | None = None,
    last_shipment_within_days: int | None = Query(default=None, ge=0),
    last_shipment_before_days: int | None = Query(default=None, ge=0),
    created_from: date | None = None,
    created_to: date | None = None,
    include_archived: bool = False,
) -> StreamingResponse:
    """Customers matching the same filters the list screen applies."""
    # The list accepts `q` as an alias for `search`; the export must apply the same
    # predicate for the same URL or the file would quietly be everybody.
    search = search or q
    definition = export_service.CUSTOMER_EXPORT
    filters = {
        "search": search,
        "category": category,
        "lifecycle_status": lifecycle_status,
        "preferred_language": preferred_language,
        "primary_route": primary_route,
        "observed_route": observed_route,
        "owner_user_id": owner_user_id,
        "tag_id": tag_id,
        "has_overdue_task": has_overdue_task,
        "has_service_issue": has_service_issue,
        "last_shipment_within_days": last_shipment_within_days,
        "last_shipment_before_days": last_shipment_before_days,
        "created_from": created_from.isoformat() if created_from else None,
        "created_to": created_to.isoformat() if created_to else None,
        "include_archived": include_archived,
    }

    conditions = customer_service.build_list_conditions(
        db,
        thresholds,
        search=search,
        category=category,
        lifecycle_status=lifecycle_status,
        preferred_language=preferred_language,
        primary_route=primary_route,
        observed_route=observed_route,
        owner_user_id=owner_user_id,
        tag_id=tag_id,
        has_overdue_task=has_overdue_task,
        has_service_issue=has_service_issue,
        last_shipment_within_days=last_shipment_within_days,
        last_shipment_before_days=last_shipment_before_days,
        created_from=created_from,
        created_to=created_to,
        include_archived=include_archived,
    )
    total = int(db.scalar(select(func.count(Customer.id)).where(*conditions)) or 0)
    # Audited before the stream begins: a client that disconnects mid-download has still
    # caused the data to be read, and the record of that must not depend on the download
    # finishing.
    _audit_export(
        db, user=user, request=request, definition=definition, row_count=total, filters=filters
    )

    statement = (
        select(Customer).where(*conditions).order_by(Customer.public_id.asc(), Customer.id.asc())
    )
    rows = export_service.customer_rows(db, statement, user.role, thresholds)
    return _csv_response(
        definition.key,
        definition.filename,
        export_service.stream_csv(
            definition.headers_for(user.role), rows, tz_name=org.office_timezone
        ),
    )


@router.get("/shipments.csv")
def export_shipments(
    request: Request,
    db: DbSession,
    org: OrgSettings,
    user: ShipmentExporter,
    search: str | None = None,
    route_group: list[str] | None = Query(default=None),
    booking_state: list[str] | None = Query(default=None),
    operational_state: list[str] | None = Query(default=None),
    customer_id: int | None = None,
    owner_user_id: int | None = None,
    exceptions_only: bool = False,
    booked_from: date | None = None,
    booked_to: date | None = None,
) -> StreamingResponse:
    definition = export_service.SHIPMENT_EXPORT
    filters = {
        "search": search,
        "route_group": route_group,
        "booking_state": booking_state,
        "operational_state": operational_state,
        "customer_id": customer_id,
        "owner_user_id": owner_user_id,
        "exceptions_only": exceptions_only,
        "booked_from": booked_from.isoformat() if booked_from else None,
        "booked_to": booked_to.isoformat() if booked_to else None,
    }
    conditions = shipment_service.build_list_query(
        search=search,
        route_group=route_group,
        booking_state=booking_state,
        operational_state=operational_state,
        customer_id=customer_id,
        owner_user_id=owner_user_id,
        exceptions_only=exceptions_only,
        booked_from=booked_from,
        booked_to=booked_to,
    )
    total = int(db.scalar(select(func.count(Shipment.id)).where(*conditions)) or 0)
    _audit_export(
        db, user=user, request=request, definition=definition, row_count=total, filters=filters
    )

    statement = select(Shipment).where(*conditions).order_by(Shipment.id.asc())
    rows = export_service.shipment_rows(db, statement, user.role)
    return _csv_response(
        definition.key,
        definition.filename,
        export_service.stream_csv(
            definition.headers_for(user.role), rows, tz_name=org.office_timezone
        ),
    )


@router.get("/packages.csv")
def export_packages(
    request: Request,
    db: DbSession,
    org: OrgSettings,
    user: ShipmentExporter,
    search: str | None = None,
    route_group: list[str] | None = Query(default=None),
    booking_state: list[str] | None = Query(default=None),
    operational_state: list[str] | None = Query(default=None),
    customer_id: int | None = None,
    owner_user_id: int | None = None,
    exceptions_only: bool = False,
    booked_from: date | None = None,
    booked_to: date | None = None,
    include_cancelled_packages: bool = True,
) -> StreamingResponse:
    """Packages belonging to the shipments the same filters select.

    One row per package. This file is the only place a package is a row; every shipment
    metric still counts the parent shipment once (AC-14).
    """
    definition = export_service.PACKAGE_EXPORT
    filters = {
        "search": search,
        "route_group": route_group,
        "booking_state": booking_state,
        "operational_state": operational_state,
        "customer_id": customer_id,
        "owner_user_id": owner_user_id,
        "exceptions_only": exceptions_only,
        "booked_from": booked_from.isoformat() if booked_from else None,
        "booked_to": booked_to.isoformat() if booked_to else None,
        "include_cancelled_packages": include_cancelled_packages,
    }
    shipment_conditions = shipment_service.build_list_query(
        search=search,
        route_group=route_group,
        booking_state=booking_state,
        operational_state=operational_state,
        customer_id=customer_id,
        owner_user_id=owner_user_id,
        exceptions_only=exceptions_only,
        booked_from=booked_from,
        booked_to=booked_to,
    )
    package_conditions = [
        ShipmentPackage.shipment_id.in_(select(Shipment.id).where(*shipment_conditions))
    ]
    if not include_cancelled_packages:
        package_conditions.append(ShipmentPackage.is_active.is_(True))

    total = int(db.scalar(select(func.count(ShipmentPackage.id)).where(*package_conditions)) or 0)
    _audit_export(
        db, user=user, request=request, definition=definition, row_count=total, filters=filters
    )

    statement = (
        select(ShipmentPackage)
        .where(*package_conditions)
        .order_by(ShipmentPackage.shipment_id.asc(), ShipmentPackage.sequence.asc())
    )
    rows = export_service.package_rows(db, statement, user.role)
    return _csv_response(
        definition.key,
        definition.filename,
        export_service.stream_csv(
            definition.headers_for(user.role), rows, tz_name=org.office_timezone
        ),
    )


@router.get("/segments/{segment_id}/audience.csv")
def export_segment_audience(
    segment_id: int,
    request: Request,
    db: DbSession,
    thresholds: Thresholds,
    org: OrgSettings,
    user: SegmentExporter,
    channel: str = Query(default=ConsentChannel.EMAIL),
) -> StreamingResponse:
    """A marketing audience: segment members who are actually contactable.

    The segment count and the audience count are deliberately different numbers. A segment
    is a view of customers; an audience is who may lawfully be contacted. Suppressed,
    withdrawn, unknown-consent, do-not-contact and archived records are **omitted from the
    file**, not flagged inside it (CRM.md section 11, Design.md section 8).
    """
    from app.models import SavedSegment

    if channel not in {item.value for item in ConsentChannel}:
        raise ValidationError(f"Unknown consent channel: {channel}", field="channel")

    segment = db.get(SavedSegment, segment_id)
    if segment is None:
        raise NotFoundError("Segment not found.")

    definition = export_service.MARKETING_SEGMENT_EXPORT
    parsed = segment_service.load_definition(segment.definition_json)
    members = db.scalars(segment_service.build_query(parsed, thresholds)).unique().all()
    eligible = list(export_service.marketing_segment_rows(db, iter(members), channel))

    _audit_export(
        db,
        user=user,
        request=request,
        definition=definition,
        row_count=len(eligible),
        filters={
            "segment_id": segment_id,
            "segment_name": segment.name,
            "channel": channel,
            "segment_members": len(members),
        },
    )
    return _csv_response(
        definition.key,
        definition.filename,
        export_service.stream_csv(
            list(definition.headers_for(user.role)),
            iter(eligible),
            tz_name=org.office_timezone,
        ),
    )


@router.get("/reports/{report_key}.csv")
def export_report(
    report_key: str,
    request: Request,
    db: DbSession,
    org: OrgSettings,
    thresholds: Thresholds,
    user: ReportExporter,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    route_group: list[str] | None = Query(default=None),
) -> StreamingResponse:
    """Export one report's results, using the report's own declared columns.

    The column allowlist is the report definition, so an exported report cannot contain a
    field the screen did not show — including a financial column this role caused to be
    omitted.
    """
    period = report_service.resolve_period(from_date=from_date, to_date=to_date, org=org)
    table = report_service.build_report(
        db,
        report_key,
        period=period,
        thresholds=thresholds,
        route_groups=route_group,
        role=user.role,
    )

    audit_service.record_audit(
        db,
        action="export.report",
        entity_type="export",
        entity_id=report_key,
        summary=f"Exported report '{report_key}' ({len(table.rows)} row(s)) to CSV",
        actor=user,
        ip_address=client_ip(request),
        detail={
            "export_type": "report",
            "report": report_key,
            "row_count": len(table.rows),
            "columns": [column.key for column in table.columns],
            "filters": {
                "from": period.from_date.isoformat(),
                "to": period.to_date.isoformat(),
                "timezone": period.timezone_name,
                "route_group": route_group or [],
            },
        },
    )
    commit_with_retry(db)

    filename = f"solaris-report-{report_key.replace('_', '-')}-{period.from_date}.csv"
    return _csv_response(
        "report",
        filename,
        export_service.stream_csv(
            [column.header for column in _report_headers(table)],
            export_service.report_rows(table),
            tz_name=org.office_timezone,
        ),
    )


def _report_headers(table) -> list[export_service.ExportColumn]:
    return [
        export_service.ExportColumn(key=column.key, header=column.label) for column in table.columns
    ]
