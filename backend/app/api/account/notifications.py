"""Customer Account: milestone notification choices and history (Phase 13F, OD-72).

Two routes on the Customer Account router, authorized exactly like the shipment and profile
routes (the identity's one active link to a customer). The history shows only this
customer's notifications: milestone, shipment reference, when, and whether it went out --
never a skip reason that names another system, never an address, never a body.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.api.account.deps import AccountClientKey, AccountDb, CurrentAccountSession
from app.api.account.profile import _limit_write
from app.api.account.routes import _read_json
from app.api.account.shipments import _apply_headers, _authorized_customer, _limit_or_refuse
from app.core.db import commit_with_retry
from app.models import Shipment
from app.schemas.account_notifications import (
    AccountNotificationItem,
    AccountNotificationsResponse,
)
from app.services import notification_service
from app.services.errors import ValidationError

router = APIRouter(tags=["customer-account"])

#: What the customer is told about each outcome. ``off`` covers both their own opt-out and
#: an address that cannot receive mail; the difference is not theirs to need.
_CUSTOMER_STATE = {
    "queued": "pending",
    "sending": "pending",
    "sent": "sent",
    # The null transport noted the message and produced nothing: it was not sent.
    "recorded": "not_sent",
    "skipped": "not_sent",
}


def _state(row) -> str:
    if row.status == "failed":
        return "not_sent" if row.attempts >= notification_service.MAX_ATTEMPTS else "pending"
    return _CUSTOMER_STATE.get(row.status, "pending")


def _response(db, customer_id: int) -> AccountNotificationsResponse:
    items = []
    for row in notification_service.history_for_customer(db, customer_id):
        shipment = db.get(Shipment, row.shipment_id)
        items.append(
            AccountNotificationItem(
                milestone=row.milestone,
                shipment_reference=shipment.public_id if shipment else None,
                created_at=row.created_at,
                state=_state(row),
            )
        )
    return AccountNotificationsResponse(
        channel="email",
        preferences=notification_service.preferences_for(db, customer_id),
        history=items,
    )


@router.get(
    "/notifications",
    response_model=AccountNotificationsResponse,
    summary="Your milestone notifications",
)
def read_notifications(
    request: Request,
    response: Response,
    db: AccountDb,
    session: CurrentAccountSession,
    client_key: AccountClientKey,
) -> AccountNotificationsResponse:
    _apply_headers(response)
    identity, _ = session
    _limit_or_refuse(identity.public_id, "notifications")
    customer = _authorized_customer(db, request, identity, "notifications")
    result = _response(db, customer.id)
    commit_with_retry(db)
    return result


@router.post(
    "/notifications/preferences",
    response_model=AccountNotificationsResponse,
    summary="Turn milestone notifications on or off",
)
async def update_preferences(
    request: Request,
    response: Response,
    db: AccountDb,
    session: CurrentAccountSession,
    client_key: AccountClientKey,
) -> AccountNotificationsResponse:
    _apply_headers(response)
    identity, _ = session
    _limit_write(identity.public_id)
    customer = _authorized_customer(db, request, identity, "notifications")
    payload = await _read_json(request)
    choices = payload.get("preferences") if isinstance(payload, dict) else None
    if not isinstance(choices, dict) or set(payload) - {"preferences"}:
        raise ValidationError("That request could not be read.")
    notification_service.set_preferences(
        db, customer, choices, via="account", identity_reference=identity.public_id
    )
    commit_with_retry(db)
    return _response(db, customer.id)
