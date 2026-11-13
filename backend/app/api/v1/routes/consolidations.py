"""Staff consolidation and commodity-item routes (Phase 13B).

All on the staff router. Reading a consolidation is ``shipment:read``; creating, editing,
filling and booking one is ``shipment:write``; a master milestone is ``tracking:write``,
the same permission as a milestone on a single shipment, because that is what it becomes
for every member. Nothing here is mounted on the public or Customer Account routers.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from app.api.deps import DbSession, client_ip, require
from app.core.db import commit_with_retry, run_unit_with_retry
from app.core.enums import STAFF_SERVICE_LABELS
from app.core.permissions import Permission
from app.models import (
    Consolidation,
    ConsolidationMembership,
    Customer,
    Shipment,
    ShipmentItem,
    TariffProduct,
    TariffVersion,
    User,
    Vendor,
)
from app.schemas.consolidation import (
    ConsolidationCreate,
    ConsolidationDetailOut,
    ConsolidationListOut,
    ConsolidationOut,
    ConsolidationUpdate,
    MasterEventIn,
    MasterEventResultOut,
    MemberAddIn,
    MemberShipmentOut,
    ReasonIn,
    RelockIn,
    ShipmentItemIn,
    ShipmentItemOut,
    ShipmentItemUpdate,
    UnlockIn,
)
from app.schemas.pricing import WorkspaceCustomerIn, WorkspaceCustomerUpdate
from app.services import (
    booking_service,
    consolidation_service,
    master_lock_service,
    notification_service,
    shipment_item_service,
    workspace_service,
)
from app.services.errors import NotFoundError

router = APIRouter(tags=["consolidations"])

# A consolidation carries the vendor's reference, product and the weight the vendor bills:
# vendor cost data by another name. Reading one therefore needs ``tariff:read`` (Operations
# and Admin, DEC-0172 / OD-45) on top of ``shipment:read``; Marketing and the read-only
# manager, who read shipments, do not read consolidations. Writing needs ``shipment:write``
# as well.
Reader = Annotated[User, Depends(require(Permission.SHIPMENT_READ, Permission.TARIFF_READ))]
Writer = Annotated[
    User,
    Depends(require(Permission.SHIPMENT_READ, Permission.TARIFF_READ, Permission.SHIPMENT_WRITE)),
]
ItemReader = Annotated[User, Depends(require(Permission.SHIPMENT_READ))]
ItemWriter = Annotated[User, Depends(require(Permission.SHIPMENT_WRITE))]
#: Owner decision 8 (stand-in): unlocking a booked master for edits is Admin's alone.
Unlocker = Annotated[
    User,
    Depends(
        require(
            Permission.SHIPMENT_READ,
            Permission.TARIFF_READ,
            Permission.SHIPMENT_WRITE,
            Permission.MASTER_UNLOCK,
        )
    ),
]
TrackingWriter = Annotated[
    User, Depends(require(Permission.TRACKING_WRITE, Permission.TARIFF_READ))
]


def _member_count(db, consolidation_id: int) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(ConsolidationMembership)
            .where(
                ConsolidationMembership.consolidation_id == consolidation_id,
                ConsolidationMembership.removed_at.is_(None),
            )
        )
        or 0
    )


def consolidation_out(db, row: Consolidation) -> ConsolidationOut:
    vendor = db.get(Vendor, row.vendor_id)
    version = db.get(TariffVersion, row.tariff_version_id) if row.tariff_version_id else None
    product = db.get(TariffProduct, row.tariff_product_id) if row.tariff_product_id else None
    return ConsolidationOut(
        id=row.id,
        public_id=row.public_id,
        vendor_key=vendor.key if vendor else "",
        solaris_service=row.solaris_service,
        solaris_service_label=STAFF_SERVICE_LABELS.get(row.solaris_service, row.solaris_service),
        origin=row.origin,
        state=row.state,
        vendor_reference=row.vendor_reference,
        tariff_version_public_id=version.public_id if version else None,
        vendor_product_code=product.code if product else None,
        actual_weight_kg=row.actual_weight_kg,
        length_cm=row.length_cm,
        width_cm=row.width_cm,
        height_cm=row.height_cm,
        carton_count=row.carton_count,
        dim_divisor=row.dim_divisor,
        volumetric_weight_kg=row.volumetric_weight_kg,
        chargeable_weight_kg=row.chargeable_weight_kg,
        handed_over_at=row.handed_over_at,
        cutoff_at=row.cutoff_at,
        booked_at=row.booked_at,
        completed_at=row.completed_at,
        cancelled_at=row.cancelled_at,
        cancellation_reason=row.cancellation_reason,
        internal_notes=row.internal_notes,
        member_count=_member_count(db, row.id),
        created_at=row.created_at,
        updated_at=row.updated_at,
        edit_lock=master_lock_service.lock_view(db, row),
    )


def _members_out(db, row: Consolidation) -> list[MemberShipmentOut]:
    out: list[MemberShipmentOut] = []
    for membership in consolidation_service.active_memberships(db, row.id):
        shipment = db.get(Shipment, membership.shipment_id)
        if shipment is None:
            continue
        customer = db.get(Customer, shipment.customer_id)
        out.append(
            MemberShipmentOut(
                shipment_id=shipment.id,
                public_id=shipment.public_id,
                customer_public_id=customer.public_id if customer else None,
                customer_name=customer.full_name if customer else None,
                booking_state=shipment.booking_state,
                operational_state=shipment.operational_state,
                package_count=shipment.package_count,
                added_at=membership.added_at,
            )
        )
    return out


def detail_out(db, row: Consolidation) -> ConsolidationDetailOut:
    base = consolidation_out(db, row)
    return ConsolidationDetailOut(**base.model_dump(), members=_members_out(db, row))


# --- Consolidations -------------------------------------------------------------------------


@router.get("/consolidations", response_model=ConsolidationListOut)
def list_consolidations(
    db: DbSession,
    _user: Reader,
    state: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ConsolidationListOut:
    conditions = []
    if state:
        conditions.append(Consolidation.state == state)
    total = db.scalar(select(func.count()).select_from(Consolidation).where(*conditions)) or 0
    rows = db.scalars(
        select(Consolidation)
        .where(*conditions)
        .order_by(Consolidation.created_at.desc(), Consolidation.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return ConsolidationListOut(items=[consolidation_out(db, r) for r in rows], total=total)


@router.post("/consolidations", response_model=ConsolidationDetailOut, status_code=201)
def create_consolidation(
    payload: ConsolidationCreate, request: Request, db: DbSession, user: Writer
) -> ConsolidationDetailOut:
    row = consolidation_service.create_consolidation(
        db, payload.model_dump(), actor=user, ip_address=client_ip(request)
    )
    commit_with_retry(db)
    db.refresh(row)
    return detail_out(db, row)


@router.get("/consolidations/{consolidation_id}", response_model=ConsolidationDetailOut)
def read_consolidation(
    consolidation_id: int, db: DbSession, _user: Reader
) -> ConsolidationDetailOut:
    return detail_out(db, consolidation_service.get_consolidation(db, consolidation_id))


@router.patch("/consolidations/{consolidation_id}", response_model=ConsolidationDetailOut)
def update_consolidation(
    consolidation_id: int,
    payload: ConsolidationUpdate,
    request: Request,
    db: DbSession,
    user: Writer,
) -> ConsolidationDetailOut:
    row = consolidation_service.get_consolidation(db, consolidation_id)
    consolidation_service.update_consolidation(
        db, row, payload.model_dump(exclude_unset=True), actor=user, ip_address=client_ip(request)
    )
    commit_with_retry(db)
    db.refresh(row)
    return detail_out(db, row)


@router.post("/consolidations/{consolidation_id}/members", response_model=ConsolidationDetailOut)
def add_member(
    consolidation_id: int, payload: MemberAddIn, request: Request, db: DbSession, user: Writer
) -> ConsolidationDetailOut:
    row = consolidation_service.get_consolidation(db, consolidation_id)
    shipment = booking_service.get_shipment(db, payload.shipment_id)
    consolidation_service.add_member(db, row, shipment, actor=user, ip_address=client_ip(request))
    commit_with_retry(db)
    db.refresh(row)
    return detail_out(db, row)


@router.post(
    "/consolidations/{consolidation_id}/customers",
    response_model=ConsolidationDetailOut,
    status_code=201,
)
def add_customer(
    consolidation_id: int,
    payload: WorkspaceCustomerIn,
    request: Request,
    db: DbSession,
    user: Writer,
) -> ConsolidationDetailOut:
    """Workspace (DEC-0272): book a customer's shipment and put it in a piece of this master,
    in one step. Every booking rule applies; if any step is refused nothing is kept."""

    def work():
        row = consolidation_service.get_consolidation(db, consolidation_id)
        data = payload.model_dump(exclude_none=True)
        for party in ("sender", "recipient"):
            value = getattr(payload, party)
            data[party] = value.model_dump(exclude_none=True) if value else None
        workspace_service.add_customer(db, row, data, actor=user, ip_address=client_ip(request))
        return row

    try:
        row = run_unit_with_retry(db, work)
    except Exception:
        db.rollback()
        raise
    db.refresh(row)
    return detail_out(db, row)


@router.patch(
    "/consolidations/{consolidation_id}/customers/{shipment_id}",
    response_model=ConsolidationDetailOut,
)
def update_customer(
    consolidation_id: int,
    shipment_id: int,
    payload: WorkspaceCustomerUpdate,
    request: Request,
    db: DbSession,
    user: Writer,
) -> ConsolidationDetailOut:
    """Workspace (DEC-0273): edit a customer's reference, weights and piece. Only the fields
    sent change; weights and the piece follow the master lock."""

    def work():
        row = consolidation_service.get_consolidation(db, consolidation_id)
        shipment = booking_service.get_shipment(db, shipment_id)
        workspace_service.update_customer(
            db,
            row,
            shipment,
            payload.model_dump(exclude_unset=True),
            actor=user,
            ip_address=client_ip(request),
        )
        return row

    try:
        row = run_unit_with_retry(db, work)
    except Exception:
        db.rollback()
        raise
    db.refresh(row)
    return detail_out(db, row)


@router.post(
    "/consolidations/{consolidation_id}/members/{shipment_id}/remove",
    response_model=ConsolidationDetailOut,
)
def remove_member(
    consolidation_id: int,
    shipment_id: int,
    payload: ReasonIn,
    request: Request,
    db: DbSession,
    user: Writer,
) -> ConsolidationDetailOut:
    row = consolidation_service.get_consolidation(db, consolidation_id)
    shipment = booking_service.get_shipment(db, shipment_id)
    consolidation_service.remove_member(
        db, row, shipment, reason=payload.reason, actor=user, ip_address=client_ip(request)
    )
    commit_with_retry(db)
    db.refresh(row)
    return detail_out(db, row)


@router.post("/consolidations/{consolidation_id}/book", response_model=ConsolidationDetailOut)
def book_consolidation(
    consolidation_id: int, request: Request, db: DbSession, user: Writer
) -> ConsolidationDetailOut:
    row = consolidation_service.get_consolidation(db, consolidation_id)
    consolidation_service.book_consolidation(db, row, actor=user, ip_address=client_ip(request))
    commit_with_retry(db)
    db.refresh(row)
    return detail_out(db, row)


@router.post("/consolidations/{consolidation_id}/complete", response_model=ConsolidationDetailOut)
def complete_consolidation(
    consolidation_id: int, request: Request, db: DbSession, user: Writer
) -> ConsolidationDetailOut:
    row = consolidation_service.get_consolidation(db, consolidation_id)
    consolidation_service.complete_consolidation(db, row, actor=user, ip_address=client_ip(request))
    commit_with_retry(db)
    db.refresh(row)
    return detail_out(db, row)


@router.post("/consolidations/{consolidation_id}/cancel", response_model=ConsolidationDetailOut)
def cancel_consolidation(
    consolidation_id: int, payload: ReasonIn, request: Request, db: DbSession, user: Writer
) -> ConsolidationDetailOut:
    row = consolidation_service.get_consolidation(db, consolidation_id)
    consolidation_service.cancel_consolidation(
        db, row, reason=payload.reason, actor=user, ip_address=client_ip(request)
    )
    commit_with_retry(db)
    db.refresh(row)
    return detail_out(db, row)


@router.post("/consolidations/{consolidation_id}/unlock", response_model=ConsolidationDetailOut)
def unlock_for_edits(
    consolidation_id: int, payload: UnlockIn, db: DbSession, user: Unlocker
) -> ConsolidationDetailOut:
    """Owner decision 8: Admin opens a temporary, audited unlock of a booked master's items
    and fee lines (reason required)."""
    row = consolidation_service.get_consolidation(db, consolidation_id)
    master_lock_service.unlock(db, row, reason=payload.reason, actor=user)
    commit_with_retry(db)
    db.refresh(row)
    return detail_out(db, row)


@router.post("/consolidations/{consolidation_id}/relock", response_model=ConsolidationDetailOut)
def relock(
    consolidation_id: int, payload: RelockIn, db: DbSession, user: Writer
) -> ConsolidationDetailOut:
    """Lock the master's items and fees again (Admin or Operations)."""
    row = consolidation_service.get_consolidation(db, consolidation_id)
    master_lock_service.relock(db, row, actor=user, reason=payload.reason)
    commit_with_retry(db)
    db.refresh(row)
    return detail_out(db, row)


@router.post(
    "/consolidations/{consolidation_id}/events",
    response_model=MasterEventResultOut,
    status_code=201,
)
def record_master_event(
    consolidation_id: int,
    payload: MasterEventIn,
    request: Request,
    db: DbSession,
    user: TrackingWriter,
) -> MasterEventResultOut:
    row = consolidation_service.get_consolidation(db, consolidation_id)
    result = consolidation_service.record_master_event(
        db, row, payload.model_dump(exclude_none=True), actor=user, ip_address=client_ip(request)
    )
    commit_with_retry(db)
    # Phase 13F: notify on the milestone just committed (test capture only, OD-72).
    notification_service.dispatch_after_commit(db)
    return MasterEventResultOut(**result)


# --- Commodity items --------------------------------------------------------------------------


@router.get("/shipments/{shipment_id}/items", response_model=list[ShipmentItemOut])
def list_items(shipment_id: int, db: DbSession, _user: ItemReader) -> list[ShipmentItemOut]:
    shipment = booking_service.get_shipment(db, shipment_id)
    return [
        ShipmentItemOut.model_validate(i) for i in shipment_item_service.list_items(db, shipment.id)
    ]


@router.post("/shipments/{shipment_id}/items", response_model=ShipmentItemOut, status_code=201)
def add_item(
    shipment_id: int, payload: ShipmentItemIn, request: Request, db: DbSession, user: ItemWriter
) -> ShipmentItemOut:
    shipment = booking_service.get_shipment(db, shipment_id)
    item = shipment_item_service.add_item(
        db, shipment, payload.model_dump(), actor=user, ip_address=client_ip(request)
    )
    commit_with_retry(db)
    db.refresh(item)
    return ShipmentItemOut.model_validate(item)


def _item(db, shipment: Shipment, item_id: int) -> ShipmentItem:
    item = db.get(ShipmentItem, item_id)
    if item is None or item.shipment_id != shipment.id:
        raise NotFoundError("That item does not belong to this shipment.")
    return item


@router.patch("/shipments/{shipment_id}/items/{item_id}", response_model=ShipmentItemOut)
def update_item(
    shipment_id: int,
    item_id: int,
    payload: ShipmentItemUpdate,
    request: Request,
    db: DbSession,
    user: ItemWriter,
) -> ShipmentItemOut:
    shipment = booking_service.get_shipment(db, shipment_id)
    item = _item(db, shipment, item_id)
    shipment_item_service.update_item(
        db,
        shipment,
        item,
        payload.model_dump(exclude_unset=True),
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    db.refresh(item)
    return ShipmentItemOut.model_validate(item)


@router.post("/shipments/{shipment_id}/items/{item_id}/remove", response_model=ShipmentItemOut)
def remove_item(
    shipment_id: int, item_id: int, request: Request, db: DbSession, user: ItemWriter
) -> ShipmentItemOut:
    shipment = booking_service.get_shipment(db, shipment_id)
    item = _item(db, shipment, item_id)
    shipment_item_service.remove_item(db, shipment, item, actor=user, ip_address=client_ip(request))
    commit_with_retry(db)
    db.refresh(item)
    return ShipmentItemOut.model_validate(item)
