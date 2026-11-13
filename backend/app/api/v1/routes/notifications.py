"""Staff routes for milestone notifications (Phase 13F).

Reading the outbox needs ``shipment:read`` and ``customer:read`` (it names a shipment and a
customer); retrying one and changing a customer's choices on their behalf need
``tracking:write`` (the permission that records milestones). The outbox holds no address and
no body, so nothing here can reveal a message's content.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import DbSession, require
from app.core.db import run_unit_with_retry
from app.core.permissions import Permission
from app.models import Customer, NotificationOutbox, Shipment, User
from app.schemas.notifications import (
    NotificationListOut,
    NotificationOut,
    PreferencesIn,
    PreferencesOut,
)
from app.services import customer_service, notification_service

router = APIRouter(tags=["notifications"])
P = Permission
Reader = Annotated[User, Depends(require(P.SHIPMENT_READ, P.CUSTOMER_READ))]
Writer = Annotated[User, Depends(require(P.SHIPMENT_READ, P.CUSTOMER_READ, P.TRACKING_WRITE))]


def _out(db, row: NotificationOutbox) -> NotificationOut:
    shipment = db.get(Shipment, row.shipment_id)
    customer = db.get(Customer, row.customer_id) if row.customer_id else None
    return NotificationOut(
        id=row.id,
        shipment_id=row.shipment_id,
        shipment_reference=shipment.public_id if shipment else None,
        customer_id=row.customer_id,
        customer_reference=customer.public_id if customer else None,
        customer_name=customer.full_name if customer else None,
        milestone=row.milestone,
        channel=row.channel,
        language=row.language,
        template_key=row.template_key,
        status=row.status,
        skip_reason=row.skip_reason,
        transport=row.transport,
        attempts=row.attempts,
        last_error=row.last_error,
        created_at=row.created_at,
        processed_at=row.processed_at,
    )


@router.get("/notifications", response_model=NotificationListOut)
def list_notifications(
    db: DbSession,
    _user: Reader,
    status: str | None = Query(default=None, max_length=10),
    shipment_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> NotificationListOut:
    conditions = []
    if status:
        conditions.append(NotificationOutbox.status == status)
    if shipment_id:
        conditions.append(NotificationOutbox.shipment_id == shipment_id)
    total = db.scalar(select(func.count()).select_from(NotificationOutbox).where(*conditions)) or 0
    rows = db.scalars(
        select(NotificationOutbox)
        .where(*conditions)
        .order_by(NotificationOutbox.created_at.desc(), NotificationOutbox.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return NotificationListOut(items=[_out(db, r) for r in rows], total=total)


@router.post("/notifications/{outbox_id}/retry", response_model=NotificationOut)
def retry_notification(outbox_id: int, db: DbSession, user: Writer) -> NotificationOut:
    def work():
        return notification_service.retry(db, notification_service.get(db, outbox_id), actor=user)

    run_unit_with_retry(db, work)
    notification_service.dispatch_after_commit(db)
    return _out(db, notification_service.get(db, outbox_id))


@router.get("/customers/{customer_id}/notification-preferences", response_model=PreferencesOut)
def customer_preferences(customer_id: int, db: DbSession, _user: Reader) -> PreferencesOut:
    customer = customer_service.get_customer(db, customer_id)
    return PreferencesOut(preferences=notification_service.preferences_for(db, customer.id))


@router.patch("/customers/{customer_id}/notification-preferences", response_model=PreferencesOut)
def set_customer_preferences(
    customer_id: int, payload: PreferencesIn, db: DbSession, user: Writer
) -> PreferencesOut:
    def work():
        customer = customer_service.get_customer(db, customer_id)
        return notification_service.set_preferences(
            db, customer, payload.preferences, via="staff", actor=user
        )

    return PreferencesOut(preferences=run_unit_with_retry(db, work))
