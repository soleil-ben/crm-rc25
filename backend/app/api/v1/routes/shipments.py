"""Shipment routes: bookings, packages, transport legs, manual events, and labels.

Handlers stay thin on purpose — parse, authorize, delegate, commit. Every business rule
(route validation, idempotent confirmation, measurement conversion, status derivation,
label layout) lives in a service module, so the API, the seed command, and the tests all
apply the same rule.

Authorization is declared per route from the permission matrix and enforced by
``require(...)``. Hiding a control in React is never the boundary; ``tests/
test_shipment_permissions.py`` calls these endpoints directly to prove it.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select

from app.api import shipment_presenters as sp
from app.api.deps import DbSession, OrgSettings, client_ip, require
from app.core.db import commit_with_retry
from app.core.enums import (
    ROUTE_DIRECTIONS,
    BookingState,
    LegType,
    OperationalState,
    RouteGroup,
    ServiceType,
    ShipmentEventType,
    TransportMode,
    value_label,
)
from app.core.permissions import Permission
from app.models import LegTrackingReference, Shipment, User
from app.schemas.common import OkResponse, Page
from app.schemas.shipment import (
    CancelRequest,
    ConfirmBookingRequest,
    ConfirmBookingResponse,
    EventEditIn,
    EventIn,
    EventOut,
    EventRevisionOut,
    LabelJobOut,
    LabelPreviewOut,
    LegIn,
    LegOut,
    LegUpdate,
    PackageIn,
    PackageOut,
    PackageUpdate,
    RebookRequest,
    ReferenceLookupOut,
    ShipmentDetail,
    ShipmentDraftCreate,
    ShipmentFinancialsUpdate,
    ShipmentListItem,
    ShipmentUpdate,
    TrackingReferenceIn,
    TrackingReferenceOut,
)
from app.services import (
    booking_service,
    event_service,
    label_service,
    leg_service,
    notification_service,
    package_service,
    shipment_service,
)
from app.services.errors import NotFoundError, ValidationError

router = APIRouter(tags=["shipments"])

ShipmentReader = Annotated[User, Depends(require(Permission.SHIPMENT_READ))]
ShipmentWriter = Annotated[User, Depends(require(Permission.SHIPMENT_WRITE))]
ShipmentCanceller = Annotated[User, Depends(require(Permission.SHIPMENT_CANCEL))]
TrackingWriter = Annotated[User, Depends(require(Permission.TRACKING_WRITE))]
LabelGenerator = Annotated[User, Depends(require(Permission.LABEL_GENERATE))]
FinancialWriter = Annotated[User, Depends(require(Permission.FINANCIAL_WRITE))]


def _load(db, shipment_id: int) -> Shipment:
    return booking_service.get_shipment(db, shipment_id)


# --- Reference lookup and metadata ---------------------------------------


@router.get("/shipments/lookup", response_model=ReferenceLookupOut)
def lookup(
    db: DbSession,
    _user: ShipmentReader,
    reference: str = Query(min_length=3, max_length=60),
) -> ReferenceLookupOut:
    """Exact Solaris ID or package reference lookup, for the internal barcode search.

    Both resolve to the same shipment; a package scan additionally says which package was
    scanned (CRM.md section 6).
    """
    match = shipment_service.lookup_reference(db, reference)
    if match is None:
        raise NotFoundError("No shipment or package matches that reference.")
    return ReferenceLookupOut(
        kind=match.kind,
        matched_value=match.matched_value,
        shipment_id=match.shipment.id,
        shipment_public_id=match.shipment.public_id,
        package_id=match.package.id if match.package else None,
        package_reference=match.package.package_reference if match.package else None,
        customer_id=match.shipment.customer_id,
    )


@router.get("/search/shipments", response_model=Page[ShipmentListItem])
def search_shipments(
    db: DbSession,
    _user: ShipmentReader,
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=8, ge=1, le=25),
) -> Page[ShipmentListItem]:
    """Shipment half of the global search (Design.md section 4).

    Customers stay on ``/search`` so the two groups render separately. A scanner types an
    identifier and presses Enter, so an exact match is listed first.
    """
    rows = shipment_service.search_shipments(db, q, limit=limit)
    items = sp.shipment_list_items(db, rows)
    return Page[ShipmentListItem](items=items, total=len(items), limit=limit, offset=0)


@router.get("/shipments/meta")
def shipment_meta(_user: ShipmentReader) -> dict:
    """Vocabularies the booking screens need, with their server-side constraints."""
    return {
        "route_groups": [
            {
                "value": route,
                "label": value_label(route),
                "directions": [
                    {"value": direction, "label": value_label(direction)}
                    for direction in ROUTE_DIRECTIONS[route]
                ],
            }
            for route in RouteGroup
        ],
        "service_types": [{"value": item, "label": value_label(item)} for item in ServiceType],
        "transport_modes": [{"value": item, "label": value_label(item)} for item in TransportMode],
        # The booking screen's currency list (RC-UAT-25 item 3); the server refuses others.
        "declared_value_currencies": list(booking_service.DECLARED_VALUE_CURRENCIES),
        "operational_states": [
            {"value": item, "label": value_label(item)} for item in OperationalState
        ],
        "booking_states": [{"value": item, "label": value_label(item)} for item in BookingState],
        "leg_types": [{"value": item, "label": value_label(item)} for item in LegType],
        "event_types": [{"value": item, "label": value_label(item)} for item in ShipmentEventType],
        "carriers": list(leg_service.KNOWN_CARRIERS),
        # The leg editor's provider picker, per leg type: the vendor on every leg (RC-20).
        "leg_providers": {
            leg_type: list(providers) for leg_type, providers in leg_service.LEG_PROVIDERS.items()
        },
        "carrier_note": (
            "Carrier names are labels only. No provider account is connected, so nothing "
            "is synchronized automatically."
        ),
    }


# --- Shipment list and detail ---------------------------------------------


@router.get("/shipments", response_model=Page[ShipmentListItem])
def list_shipments(
    db: DbSession,
    _user: ShipmentReader,
    search: str | None = None,
    route_group: list[str] | None = Query(default=None),
    booking_state: list[str] | None = Query(default=None),
    operational_state: list[str] | None = Query(default=None),
    customer_id: int | None = None,
    owner_user_id: int | None = None,
    exceptions_only: bool = False,
    booked_from: date | None = None,
    booked_to: date | None = None,
    sort: str = Query(default="booking_date"),
    direction: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Page[ShipmentListItem]:
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
    stmt = (
        shipment_service.apply_sort(select(Shipment).where(*conditions), sort, direction)
        .limit(limit)
        .offset(offset)
    )
    rows = list(db.scalars(stmt).all())
    return Page[ShipmentListItem](
        items=sp.shipment_list_items(db, rows), total=total, limit=limit, offset=offset
    )


@router.post("/shipments", response_model=ShipmentDetail, status_code=201)
def create_draft(
    payload: ShipmentDraftCreate,
    request: Request,
    db: DbSession,
    user: ShipmentWriter,
) -> ShipmentDetail:
    """Create a draft booking. A draft never receives a customer-facing Solaris ID."""
    data = payload.model_dump(exclude_none=True)
    data["sender"] = payload.sender.model_dump(exclude_none=True) if payload.sender else None
    data["recipient"] = (
        payload.recipient.model_dump(exclude_none=True) if payload.recipient else None
    )
    data["packages"] = [package.model_dump() for package in payload.packages]
    shipment = booking_service.create_draft(db, data, actor=user, ip_address=client_ip(request))
    commit_with_retry(db)
    db.refresh(shipment)
    return sp.shipment_detail(db, shipment, viewer=user)


@router.get("/shipments/{shipment_id}", response_model=ShipmentDetail)
def read_shipment(db: DbSession, user: ShipmentReader, shipment_id: int) -> ShipmentDetail:
    return sp.shipment_detail(db, _load(db, shipment_id), viewer=user)


@router.patch("/shipments/{shipment_id}", response_model=ShipmentDetail)
def update_shipment(
    shipment_id: int,
    payload: ShipmentUpdate,
    request: Request,
    db: DbSession,
    user: ShipmentWriter,
) -> ShipmentDetail:
    shipment = _load(db, shipment_id)
    data = payload.model_dump(exclude_unset=True)
    if payload.sender is not None:
        data["sender"] = payload.sender.model_dump(exclude_none=True)
    if payload.recipient is not None:
        data["recipient"] = payload.recipient.model_dump(exclude_none=True)
    booking_service.update_shipment(db, shipment, data, actor=user, ip_address=client_ip(request))
    commit_with_retry(db)
    db.refresh(shipment)
    return sp.shipment_detail(db, shipment, viewer=user)


@router.patch("/shipments/{shipment_id}/financials", response_model=ShipmentDetail)
def update_financials(
    shipment_id: int,
    payload: ShipmentFinancialsUpdate,
    request: Request,
    db: DbSession,
    user: FinancialWriter,
) -> ShipmentDetail:
    """Record amounts manually. No rate calculation happens anywhere in this release."""
    from app.services import audit_service

    shipment = _load(db, shipment_id)
    data = payload.model_dump(exclude_unset=True)
    if "currency" in data:
        # RC-UAT-25 item 7 (Ben 2026-10-25): a code such as "CA" or "$" was stored as typed
        # and every amount on the Financials tab then failed to format, blanking the page.
        from app.services.shipment_finance_summary_service import (  # noqa: PLC0415
            recorded_currency,
        )

        data["currency"] = recorded_currency(data["currency"])
    for field, value in data.items():
        setattr(shipment, field, value)
    audit_service.record_audit(
        db,
        action="shipment.financials_update",
        entity_type="shipment",
        entity_id=shipment.id,
        summary=f"Updated recorded amounts on {shipment.public_id or 'draft booking'}",
        actor=user,
        ip_address=client_ip(request),
        detail={"fields": sorted(data.keys())},
    )
    commit_with_retry(db)
    db.refresh(shipment)
    return sp.shipment_detail(db, shipment, viewer=user)


@router.post("/shipments/{shipment_id}/confirm", response_model=ConfirmBookingResponse)
def confirm_booking(
    shipment_id: int,
    payload: ConfirmBookingRequest,
    request: Request,
    db: DbSession,
    user: ShipmentWriter,
) -> ConfirmBookingResponse:
    """Confirm a draft and issue its permanent Solaris Shipment ID.

    Retrying with the same idempotency key returns the original booking rather than
    creating a second one; reusing the key for materially different data is a 409.
    """
    result = booking_service.confirm_booking(
        db,
        shipment_id=shipment_id,
        idempotency_key=payload.idempotency_key,
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    db.refresh(result.shipment)
    return ConfirmBookingResponse(
        shipment=sp.shipment_detail(db, result.shipment, viewer=user),
        created=result.created,
        id_generation_attempts=result.id_generation_attempts,
    )


@router.post("/shipments/{shipment_id}/cancel", response_model=ShipmentDetail)
def cancel_shipment(
    shipment_id: int,
    payload: CancelRequest,
    request: Request,
    db: DbSession,
    user: ShipmentCanceller,
) -> ShipmentDetail:
    """Cancel a booking. The Solaris ID retires with the record and is never reused."""
    shipment = _load(db, shipment_id)
    booking_service.cancel_shipment(
        db, shipment, reason=payload.reason, actor=user, ip_address=client_ip(request)
    )
    commit_with_retry(db)
    db.refresh(shipment)
    return sp.shipment_detail(db, shipment, viewer=user)


@router.post("/shipments/{shipment_id}/rebook", response_model=ShipmentDetail, status_code=201)
def rebook_shipment(
    shipment_id: int,
    payload: RebookRequest,
    request: Request,
    db: DbSession,
    user: ShipmentCanceller,
) -> ShipmentDetail:
    """Cancel a booking and open a linked replacement draft.

    Confirming the replacement issues a *new* Solaris ID. The original keeps its original
    meaning, and both records link to each other.
    """
    original = _load(db, shipment_id)
    changes = payload.model_dump(exclude_unset=True, exclude={"reason"})
    if payload.sender is not None:
        changes["sender"] = payload.sender.model_dump(exclude_none=True)
    if payload.recipient is not None:
        changes["recipient"] = payload.recipient.model_dump(exclude_none=True)
    replacement = booking_service.rebook_shipment(
        db,
        original,
        reason=payload.reason,
        changes=changes,
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    db.refresh(replacement)
    return sp.shipment_detail(db, replacement, viewer=user)


# --- Packages -------------------------------------------------------------


@router.get("/shipments/{shipment_id}/packages", response_model=list[PackageOut])
def list_packages(db: DbSession, _user: ShipmentReader, shipment_id: int) -> list[PackageOut]:
    _load(db, shipment_id)
    return sp.packages_out(db, shipment_id)


@router.post("/shipments/{shipment_id}/packages", response_model=PackageOut, status_code=201)
def add_package(
    shipment_id: int,
    payload: PackageIn,
    request: Request,
    db: DbSession,
    user: ShipmentWriter,
) -> PackageOut:
    shipment = _load(db, shipment_id)
    package = package_service.add_package(
        db, shipment, payload.model_dump(), actor=user, ip_address=client_ip(request)
    )
    commit_with_retry(db)
    return sp.package_out(package, package_service.active_packages(db, shipment_id))


@router.patch("/packages/{package_id}", response_model=PackageOut)
def update_package(
    package_id: int,
    payload: PackageUpdate,
    request: Request,
    db: DbSession,
    user: ShipmentWriter,
) -> PackageOut:
    package = package_service.get_package(db, package_id)
    package_service.update_package(
        db,
        package,
        payload.model_dump(exclude_unset=True),
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return sp.package_out(package, package_service.active_packages(db, package.shipment_id))


@router.post("/packages/{package_id}/duplicate", response_model=PackageOut, status_code=201)
def duplicate_package(
    package_id: int, request: Request, db: DbSession, user: ShipmentWriter
) -> PackageOut:
    package = package_service.get_package(db, package_id)
    copy = package_service.duplicate_package(db, package, actor=user, ip_address=client_ip(request))
    commit_with_retry(db)
    return sp.package_out(copy, package_service.active_packages(db, copy.shipment_id))


@router.post("/packages/{package_id}/cancel", response_model=PackageOut)
def cancel_package(
    package_id: int,
    payload: CancelRequest,
    request: Request,
    db: DbSession,
    user: ShipmentWriter,
) -> PackageOut:
    """Cancel a package. Its reference is retained and never reused."""
    package = package_service.get_package(db, package_id)
    package_service.cancel_package(
        db, package, reason=payload.reason, actor=user, ip_address=client_ip(request)
    )
    shipment = _load(db, package.shipment_id)
    event_service.recompute_status(db, shipment)
    commit_with_retry(db)
    return sp.package_out(package, package_service.active_packages(db, package.shipment_id))


@router.delete("/packages/{package_id}", response_model=OkResponse)
def remove_draft_package(package_id: int, db: DbSession, user: ShipmentWriter) -> OkResponse:
    """Delete a package from an unconfirmed draft only."""
    package = package_service.get_package(db, package_id)
    package_service.remove_draft_package(db, package, actor=user)
    commit_with_retry(db)
    return OkResponse(message="Package removed from the draft.")


# --- Transport legs -------------------------------------------------------


@router.get("/shipments/{shipment_id}/legs", response_model=list[LegOut])
def list_legs(db: DbSession, _user: ShipmentReader, shipment_id: int) -> list[LegOut]:
    _load(db, shipment_id)
    return sp.legs_out(db, shipment_id)


@router.post("/shipments/{shipment_id}/legs", response_model=LegOut, status_code=201)
def create_leg(
    shipment_id: int,
    payload: LegIn,
    request: Request,
    db: DbSession,
    user: TrackingWriter,
) -> LegOut:
    shipment = _load(db, shipment_id)
    leg = leg_service.create_leg(
        db, shipment, payload.model_dump(), actor=user, ip_address=client_ip(request)
    )
    commit_with_retry(db)
    return next(item for item in sp.legs_out(db, shipment_id) if item.id == leg.id)


@router.patch("/legs/{leg_id}", response_model=LegOut)
def update_leg(
    leg_id: int,
    payload: LegUpdate,
    request: Request,
    db: DbSession,
    user: TrackingWriter,
) -> LegOut:
    leg = leg_service.get_leg(db, leg_id)
    leg_service.update_leg(
        db,
        leg,
        payload.model_dump(exclude_unset=True),
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return next(item for item in sp.legs_out(db, leg.shipment_id) if item.id == leg_id)


@router.delete("/legs/{leg_id}", response_model=OkResponse)
def delete_leg(leg_id: int, request: Request, db: DbSession, user: TrackingWriter) -> OkResponse:
    leg = leg_service.get_leg(db, leg_id)
    leg_service.delete_leg(db, leg, actor=user, ip_address=client_ip(request))
    commit_with_retry(db)
    return OkResponse(message="Transport leg removed.")


@router.post(
    "/legs/{leg_id}/tracking-references", response_model=TrackingReferenceOut, status_code=201
)
def add_tracking_reference(
    leg_id: int,
    payload: TrackingReferenceIn,
    request: Request,
    db: DbSession,
    user: TrackingWriter,
) -> TrackingReferenceOut:
    """Record a carrier reference. Nothing is fetched from a provider in this phase."""
    leg = leg_service.get_leg(db, leg_id)
    reference = leg_service.add_tracking_reference(
        db, leg, payload.model_dump(), actor=user, ip_address=client_ip(request)
    )
    commit_with_retry(db)
    references = {
        package.id: package.package_reference
        for package in package_service.all_packages(db, leg.shipment_id)
    }
    return sp.tracking_reference_out(reference, references)


@router.post("/tracking-references/{reference_id}/retire", response_model=TrackingReferenceOut)
def retire_tracking_reference(
    reference_id: int,
    payload: CancelRequest,
    request: Request,
    db: DbSession,
    user: TrackingWriter,
) -> TrackingReferenceOut:
    """Retire a superseded carrier reference. The row is preserved, never overwritten."""
    reference = leg_service.get_tracking_reference(db, reference_id)
    leg_service.retire_tracking_reference(
        db, reference, reason=payload.reason, actor=user, ip_address=client_ip(request)
    )
    commit_with_retry(db)
    shipment_id = db.get(LegTrackingReference, reference_id).leg.shipment_id
    references = {
        package.id: package.package_reference
        for package in package_service.all_packages(db, shipment_id)
    }
    return sp.tracking_reference_out(reference, references)


# --- Manual operational events --------------------------------------------


@router.get("/shipments/{shipment_id}/events", response_model=list[EventOut])
def list_events(
    db: DbSession,
    _user: ShipmentReader,
    shipment_id: int,
    include_voided: bool = False,
) -> list[EventOut]:
    _load(db, shipment_id)
    return sp.events_out(db, event_service.timeline(db, shipment_id, include_voided=include_voided))


@router.post("/shipments/{shipment_id}/events", response_model=list[EventOut], status_code=201)
def record_event(
    shipment_id: int,
    payload: EventIn,
    request: Request,
    db: DbSession,
    user: TrackingWriter,
) -> list[EventOut]:
    """Record a manual operational event and recompute the derived status."""
    shipment = _load(db, shipment_id)
    created = event_service.record_event(
        db, shipment, payload.model_dump(), actor=user, ip_address=client_ip(request)
    )
    commit_with_retry(db)
    # Phase 13F: notify on the milestone just committed (test capture only, OD-72).
    notification_service.dispatch_after_commit(db)
    return sp.events_out(db, created)


@router.post("/events/{event_id}/void", response_model=OkResponse)
def void_event(
    event_id: int,
    payload: CancelRequest,
    request: Request,
    db: DbSession,
    user: TrackingWriter,
) -> OkResponse:
    """Void an event as a correction. History is preserved, never deleted."""
    from app.models import ShipmentEvent

    event = db.get(ShipmentEvent, event_id)
    if event is None:
        raise NotFoundError("That event does not exist.")
    event_service.void_event(
        db, event, reason=payload.reason, actor=user, ip_address=client_ip(request)
    )
    commit_with_retry(db)
    return OkResponse(message="Event voided. The correction is recorded in the audit log.")


# RC-UAT-25 item 6 (Ben, 2026-10-25): correct a recorded event, published or not. The same
# permission that records and voids (Admin and Operations). Audited with before and after;
# a published event's wording changes only to a standard update; no milestone email is sent.


@router.post("/shipments/{shipment_id}/events/edit", response_model=list[EventOut])
def edit_event(
    shipment_id: int,
    payload: EventEditIn,
    request: Request,
    db: DbSession,
    user: TrackingWriter,
) -> list[EventOut]:
    """Correct one recorded event (all of its package rows) and recompute the status."""
    shipment = _load(db, shipment_id)
    result = event_service.edit_event(
        db, shipment, payload.model_dump(), actor=user, ip_address=client_ip(request)
    )
    commit_with_retry(db)
    return sp.events_out(db, result.events)


@router.get("/shipments/{shipment_id}/event-revisions", response_model=list[EventRevisionOut])
def list_event_revisions(
    db: DbSession, _user: ShipmentReader, shipment_id: int
) -> list[EventRevisionOut]:
    """Every edit of this shipment's timeline events, newest first."""
    _load(db, shipment_id)
    rows = event_service.revisions(db, shipment_id)
    editors = {row.edited_by_user_id for row in rows if row.edited_by_user_id}
    users = (
        {u.id: u for u in db.scalars(select(User).where(User.id.in_(editors))).all()}
        if editors
        else {}
    )
    return [
        EventRevisionOut(
            id=row.id,
            shipment_id=row.shipment_id,
            event_ids_before=json.loads(row.event_ids_before),
            event_ids_after=json.loads(row.event_ids_after),
            before=json.loads(row.before_json),
            after=json.loads(row.after_json),
            reason=row.reason,
            was_published=row.was_published,
            public_wording_changed=row.public_wording_changed,
            edited_at=row.edited_at,
            edited_by=sp._staff(users.get(row.edited_by_user_id)),
        )
        for row in rows
    ]


# --- Labels ---------------------------------------------------------------


@router.get("/shipments/{shipment_id}/label-preview", response_model=LabelPreviewOut)
def label_preview(
    db: DbSession, org: OrgSettings, _user: LabelGenerator, shipment_id: int
) -> LabelPreviewOut:
    """Metadata for the exact-ratio 4 × 6 on-screen preview."""
    shipment = _load(db, shipment_id)
    return LabelPreviewOut(**label_service.preview_payload(db, shipment, org=org))


@router.get("/shipments/{shipment_id}/labels.pdf")
def generate_labels(
    request: Request,
    db: DbSession,
    org: OrgSettings,
    user: LabelGenerator,
    shipment_id: int,
    package_id: list[int] | None = Query(default=None),
) -> Response:
    """One 4 × 6 inch portrait page per selected active package.

    Generation is recorded — including whether it was a reprint — but nothing here claims
    a physical printer produced a label.
    """
    shipment = _load(db, shipment_id)
    document, packages, kind = label_service.build_label_document(
        db, shipment, org=org, package_ids=package_id
    )
    label_service.record_generation(
        db,
        shipment,
        packages,
        document,
        kind=kind,
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    filename = label_service.label_filename(shipment, document.page_count)
    return Response(
        content=document.pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Solaris-Label-Pages": str(document.page_count),
        },
    )


@router.get("/shipments/{shipment_id}/label-jobs", response_model=list[LabelJobOut])
def label_history(db: DbSession, _user: ShipmentReader, shipment_id: int) -> list[LabelJobOut]:
    """Reprint history: what was generated, when, by whom, and for which references."""
    _load(db, shipment_id)
    return sp.label_jobs_out(db, label_service.print_history(db, shipment_id))


@router.get("/shipments/{shipment_id}/label-fonts")
def label_font_note(_user: LabelGenerator) -> dict:
    """Provenance of the embedded label font, surfaced for operational review."""
    return {
        "family": "Roboto",
        "version": "2.138 (2017)",
        "license": "Apache License 2.0",
        "source": "https://github.com/google/roboto",
        "reason": (
            "Embedded so Vietnamese diacritics render in generated PDFs. The fonts "
            "bundled with the PDF library do not cover the required codepoints."
        ),
    }


def _validate_route_group(value: str) -> None:  # pragma: no cover - defensive
    if value not in set(RouteGroup):
        raise ValidationError(f"Unknown route group '{value}'.", field="route_group")
