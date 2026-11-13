"""Milestone notifications (Phase 13F, OD-72).

A published milestone on a shipment queues **one** email to its customer per milestone:

====================  =====================================================================
milestone             reached when
====================  =====================================================================
``received``          a published "received at warehouse" event
``in_transit``        a published "departed origin" or "in transit" event
``out_for_delivery``  a published "out for delivery" event
``delivered``         a published "delivered to recipient" event **and** the shipment as a
                      whole is delivered -- one parcel of three is not "delivered" (AC-7)
====================  =====================================================================

A collection-point handover is not a delivery (CRM.md section 10) and notifies nothing. Only
a **published** event counts (``is_public_update``), checked when the event is recorded: a
customer is never told about a step the tracking page does not show, and an unpublished event
notifies nothing. A milestone behind the **furthest milestone the shipment already reached**
notifies nothing (a late or backdated event): the furthest point is the highest milestone among
the shipment's other published, unvoided events, or its current state when that state is on the
milestone ladder -- so an exception, an on-hold or a return in progress (states off the ladder,
rank 0; a delivery attempt is on it, at out for delivery) never lets an earlier step through
(Phase 15). A shipment whose state is returned or cancelled notifies nothing further; a row
queued before that is skipped as ``closed`` and its key freed, so a shipment sent out again (or
a return voided as a mistake) notifies normally. The dedup key
``{shipment}:{milestone}:{version}`` makes a repeat, a correction, a milestone recorded on
several packages, or a master milestone fanned out to members notify once. **Voiding** the
event that queued a row that has not gone out moves the row to another standing event for the
same milestone (another package's) if there is one; otherwise it withdraws the row and frees
the key, so the real milestone still notifies.

Dispatch is **claim, send, record** (never send inside a retried database unit, which could
send twice): rows are claimed (``queued`` -> ``sending``) and committed, each is then decided
on its own -- no address (``no_email``), the customer turned that milestone off
(``opted_out``; no saved choice means on), the address is suppressed (``suppressed``, the
owner's 2026-10-20 instruction), the event was voided (``voided``) -- and sent through the
account email seam, whose only transports are ``null`` and ``capture``, so **nothing reaches
a customer** (test capture only); the outcome is recorded in its own unit. A fault on one row
is recorded on that row and never blocks the rest. A transport error leaves the row
``failed`` for up to ``MAX_ATTEMPTS`` tries; a claim older than ``CLAIM_TIMEOUT`` (a process
that died mid-send) is picked up again.

Language: the language the customer chose in their account, else English for a customer
recorded as English, else Vietnamese (Vietnamese first, OD-71).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import BookingState, ConsentChannel, OperationalState, ShipmentEventType
from app.core.time_utils import utcnow
from app.models import (
    Customer,
    CustomerIdentity,
    CustomerIdentityLink,
    NotificationOutbox,
    NotificationPreference,
    Shipment,
    ShipmentEvent,
    User,
)
from app.services import account_email_service, audit_service, consent_service, package_service
from app.services.errors import ConflictError, NotFoundError, ValidationError

logger = logging.getLogger("solaris.notifications")

TEMPLATE_VERSION = "v1"
MAX_ATTEMPTS = 3
CLAIM_TIMEOUT = timedelta(minutes=10)
MILESTONES = ("received", "in_transit", "out_for_delivery", "delivered")
EVENT_MILESTONE = {
    ShipmentEventType.RECEIVED_AT_SOLARIS: "received",
    ShipmentEventType.DEPARTED_ORIGIN: "in_transit",
    ShipmentEventType.IN_TRANSIT: "in_transit",
    ShipmentEventType.OUT_FOR_DELIVERY: "out_for_delivery",
    ShipmentEventType.DELIVERED_TO_RECIPIENT: "delivered",
}
#: How far along a shipment is, by milestone order. A milestone below this is not notified.
_STATE_RANK = {
    OperationalState.RECEIVED_AT_SOLARIS: 1,
    OperationalState.PROCESSING: 1,
    OperationalState.DEPARTED_ORIGIN: 2,
    OperationalState.IN_TRANSIT: 2,
    OperationalState.CUSTOMS_PROCESSING: 2,
    OperationalState.ARRIVED_DESTINATION: 2,
    OperationalState.OUT_FOR_DELIVERY: 3,
    OperationalState.DELIVERY_ATTEMPTED: 3,
    OperationalState.PARTIALLY_DELIVERED: 3,
    OperationalState.DELIVERED: 4,
}
_MILESTONE_RANK = {"received": 1, "in_transit": 2, "out_for_delivery": 3, "delivered": 4}
#: Phase 15: a shipment in one of these states notifies nothing further.
_FINISHED_STATES = (OperationalState.RETURNED, OperationalState.CANCELLED)
#: OD-72: customers opt out per milestone; a milestone with no saved choice is on.
DEFAULT_ENABLED = True


def template_key(milestone: str, language: str) -> str:
    return f"notify.{milestone}.{language}"


def language_for(db: Session, customer: Customer | None) -> str:
    """The customer's language (Vietnamese or English, which the account's profile setting
    writes), else the account's, else Vietnamese (OD-71)."""
    if customer is None:
        return "vi"
    if customer.preferred_language in ("en", "vi"):
        return customer.preferred_language
    identity = db.scalar(
        select(CustomerIdentity)
        .join(CustomerIdentityLink, CustomerIdentityLink.identity_id == CustomerIdentity.id)
        .where(
            CustomerIdentityLink.customer_id == customer.id,
            CustomerIdentityLink.status == "active",
        )
        .limit(1)
    )
    if identity is not None and identity.preferred_language in ("en", "vi"):
        return identity.preferred_language
    return "vi"


# --- Queueing ------------------------------------------------------------------------------------


def enqueue_for_events(
    db: Session, shipment: Shipment, events: list[ShipmentEvent], *, now: datetime | None = None
) -> list[NotificationOutbox]:
    """Queue one notification per milestone these events newly reach. Idempotent; call after
    the shipment's status has been recomputed."""
    now = now or utcnow()
    if _finished(db, shipment):
        return []  # returned or cancelled: nothing further (Phase 15)
    current = furthest_reached(db, shipment, exclude_ids={e.id for e in events})
    queued: list[NotificationOutbox] = []
    seen: set[str] = set()
    customer = db.get(Customer, shipment.customer_id)
    for event in events:
        milestone = EVENT_MILESTONE.get(event.event_type)
        if milestone is None or not event.is_public_update or milestone in seen:
            continue
        if milestone == "delivered" and shipment.operational_state != OperationalState.DELIVERED:
            continue  # one parcel of several is not the shipment delivered
        if _MILESTONE_RANK[milestone] < current:
            continue  # a late or backdated step behind the furthest milestone reached
        seen.add(milestone)
        key = f"{shipment.id}:{milestone}:{TEMPLATE_VERSION}"
        if db.scalar(select(NotificationOutbox.id).where(NotificationOutbox.dedup_key == key)):
            continue
        language = language_for(db, customer)
        row = NotificationOutbox(
            dedup_key=key,
            shipment_id=shipment.id,
            customer_id=customer.id if customer else None,
            event_id=event.id,
            milestone=milestone,
            channel="email",
            language=language,
            template_key=template_key(milestone, language),
            template_version=TEMPLATE_VERSION,
            status="queued",
            attempts=0,
            created_at=now,
        )
        db.add(row)
        queued.append(row)
    if queued:
        db.flush()
    return queued


def _finished(db: Session, shipment: Shipment) -> bool:
    """Returned or cancelled, read from the **shipment's state** only (review 2026-10-21): the
    booking is cancelled, the state is returned or cancelled, or every active package is
    returned. One parcel of several returned does not close the shipment, and a shipment sent
    out again (its state back on the milestone ladder) notifies normally."""
    if (
        shipment.operational_state in _FINISHED_STATES
        or shipment.booking_state == BookingState.CANCELLED
    ):
        return True
    active = package_service.active_packages(db, shipment.id)
    return bool(active) and all(
        package.operational_state == OperationalState.RETURNED for package in active
    )


def furthest_reached(
    db: Session, shipment: Shipment, *, exclude_ids: set[int] | None = None
) -> int:
    """The furthest milestone (1-4) the shipment has already reached, or 0.

    The highest of: its current state, when that state is on the milestone ladder (an
    exception or a return state is not and counts nothing; a delivery attempt counts as out
    for delivery); and every published,
    unvoided milestone event on the shipment other than ``exclude_ids`` (the events being
    queued now). A recipient delivery counts as delivered only when the whole shipment is;
    otherwise as out for delivery (one parcel of several delivered, AC-7)."""
    furthest = _STATE_RANK.get(shipment.operational_state, 0)
    query = select(ShipmentEvent.event_type).where(
        ShipmentEvent.shipment_id == shipment.id,
        ShipmentEvent.event_type.in_(list(EVENT_MILESTONE)),
        ShipmentEvent.is_voided.is_(False),
        ShipmentEvent.is_public_update.is_(True),
    )
    if exclude_ids:
        query = query.where(ShipmentEvent.id.notin_(exclude_ids))
    whole_delivered = shipment.operational_state == OperationalState.DELIVERED
    for event_type in set(db.scalars(query)):
        rank = _MILESTONE_RANK[EVENT_MILESTONE[event_type]]
        if rank == _MILESTONE_RANK["delivered"] and not whole_delivered:
            rank = _MILESTONE_RANK["out_for_delivery"]
        furthest = max(furthest, rank)
    return furthest


def withdraw_for_voided_event(
    db: Session, event: ShipmentEvent, *, now: datetime | None = None
) -> int:
    """A voided event's notification that has not gone out is withdrawn and its key freed, so
    the corrected milestone notifies when it is recorded. One already sent stays as history."""
    now = now or utcnow()
    count = 0
    for row in db.scalars(
        select(NotificationOutbox).where(
            NotificationOutbox.event_id == event.id,
            NotificationOutbox.status.in_(("queued", "failed")),
        )
    ):
        standing = _standing_event(db, row)
        if standing is not None:
            row.event_id = standing.id  # another package's event still reaches the milestone
            continue
        _withdraw(row, now)
        count += 1
    db.flush()
    return count


def _standing_event(db: Session, row: NotificationOutbox) -> ShipmentEvent | None:
    """Another published, unvoided event on the shipment that still reaches the row's
    milestone, or None."""
    if row.milestone == "delivered":
        shipment = db.get(Shipment, row.shipment_id)
        if shipment is None or shipment.operational_state != OperationalState.DELIVERED:
            return None
    types = [t for t, m in EVENT_MILESTONE.items() if m == row.milestone]
    return db.scalar(
        select(ShipmentEvent)
        .where(
            ShipmentEvent.shipment_id == row.shipment_id,
            ShipmentEvent.event_type.in_(types),
            ShipmentEvent.is_voided.is_(False),
            ShipmentEvent.is_public_update.is_(True),
            ShipmentEvent.id != row.event_id,
        )
        .order_by(ShipmentEvent.id)
        .limit(1)
    )


def _withdraw(row: NotificationOutbox, now: datetime) -> None:
    row.status = "skipped"
    row.skip_reason = "voided"
    row.processed_at = now
    row.last_error = None
    row.dedup_key = f"{row.dedup_key}:withdrawn:{row.id}"[:80]


# --- Preferences ---------------------------------------------------------------------------------


def preferences_for(db: Session, customer_id: int) -> dict[str, bool]:
    saved = {
        row.milestone: row.enabled
        for row in db.scalars(
            select(NotificationPreference).where(NotificationPreference.customer_id == customer_id)
        )
    }
    return {m: saved.get(m, DEFAULT_ENABLED) for m in MILESTONES}


def set_preferences(
    db: Session,
    customer: Customer,
    choices: dict[str, Any],
    *,
    via: str,
    actor: User | None = None,
    identity_reference: str | None = None,
    now: datetime | None = None,
) -> dict[str, bool]:
    now = now or utcnow()
    unknown = set(choices) - set(MILESTONES)
    if unknown or not choices:
        raise ValidationError("Choose among: received, in transit, out for delivery, delivered.")
    for milestone, enabled in choices.items():
        if not isinstance(enabled, bool):
            raise ValidationError("Each choice is on or off.", field=milestone)
        row = db.scalar(
            select(NotificationPreference).where(
                NotificationPreference.customer_id == customer.id,
                NotificationPreference.milestone == milestone,
            )
        )
        if row is None:
            row = NotificationPreference(customer_id=customer.id, milestone=milestone)
            db.add(row)
        row.enabled = enabled
        row.updated_via = via
        row.updated_at = now
    db.flush()
    audit_service.record_audit(
        db,
        action="notification.preferences_update",
        entity_type="customer",
        entity_id=customer.id,
        summary=f"Milestone notification choices changed ({via})",
        actor=actor,
        detail={
            "via": via,
            "account": identity_reference,
            "choices": {k: bool(v) for k, v in sorted(choices.items())},
        },
    )
    return preferences_for(db, customer.id)


# --- Dispatch: claim, send, record ---------------------------------------------------------------


def _tracking_url(db: Session, shipment: Shipment) -> str:
    base = settings.tracking_base_url.rstrip("/")
    packages = package_service.active_packages(db, shipment.id)
    reference = packages[0].package_reference if packages else shipment.public_id
    return f"{base}/{reference}"


def _claim(db: Session, limit: int, now: datetime) -> list[int]:
    stale = now - CLAIM_TIMEOUT
    rows = list(
        db.scalars(
            select(NotificationOutbox)
            .where(
                (NotificationOutbox.status == "queued")
                | (
                    (NotificationOutbox.status == "failed")
                    & (NotificationOutbox.attempts < MAX_ATTEMPTS)
                )
                | (
                    (NotificationOutbox.status == "sending")
                    & (NotificationOutbox.processed_at < stale)
                )
            )
            .order_by(NotificationOutbox.created_at, NotificationOutbox.id)
            .limit(limit)
        )
    )
    for row in rows:
        row.status = "sending"
        row.processed_at = now
    db.flush()
    return [row.id for row in rows]


def _decide(db: Session, row: NotificationOutbox) -> tuple[str | None, Any]:
    """``(skip_reason, message)``: a reason to skip, or the message to send. Reads only."""
    event = db.get(ShipmentEvent, row.event_id) if row.event_id else None
    if (
        event is not None
        and (event.is_voided or not event.is_public_update)
        and _standing_event(db, row) is None
    ):
        return "voided", None
    shipment = db.get(Shipment, row.shipment_id)
    if shipment is None or _finished(db, shipment):
        return "closed", None  # returned or cancelled before it went out (Phase 15)
    customer = db.get(Customer, row.customer_id) if row.customer_id else None
    address = (
        consent_service.normalized_address_for(customer, ConsentChannel.EMAIL) if customer else None
    )
    if not address:
        return "no_email", None
    if not preferences_for(db, customer.id)[row.milestone]:
        return "opted_out", None
    if consent_service.is_suppressed(db, ConsentChannel.EMAIL, address):
        return "suppressed", None
    message = account_email_service.OutboundEmail(
        to_email=customer.email_entered or address,
        template_key=row.template_key,
        language=row.language,
        parameters={
            "shipment_reference": shipment.public_id or "",
            "tracking_url": _tracking_url(db, shipment),
        },
    )
    return None, message


def _record(db: Session, outbox_id: int, now: datetime, **fields: Any) -> None:
    from app.core.db import run_unit_with_retry  # noqa: PLC0415

    def work() -> None:
        row = db.get(NotificationOutbox, outbox_id)
        for name, value in fields.items():
            setattr(row, name, value)
        row.processed_at = now
        if fields.get("skip_reason") == "voided":
            row.dedup_key = f"{row.dedup_key}:withdrawn:{row.id}"[:80]
        elif fields.get("skip_reason") == "closed":
            # Freed like a withdrawn row: if the return proves a mistake (voided) or the
            # shipment is sent out again, the real milestone still notifies once.
            row.dedup_key = f"{row.dedup_key}:closed:{row.id}"[:80]
        db.flush()

    run_unit_with_retry(db, work)


def _deliver(db: Session, outbox_id: int, now: datetime) -> None:
    row = db.get(NotificationOutbox, outbox_id)
    try:
        reason, message = _decide(db, row)
    except Exception as error:  # noqa: BLE001 - one row's fault never blocks the others
        db.rollback()
        _record(
            db,
            outbox_id,
            now,
            status="failed",
            attempts=row.attempts + 1,
            last_error=type(error).__name__[:200],
        )
        return
    if reason is not None:
        _record(db, outbox_id, now, status="skipped", skip_reason=reason, last_error=None)
        return
    attempts = row.attempts + 1
    db.rollback()  # end the read transaction before the side effect; nothing is pending
    try:
        result = account_email_service.send(message)
    except Exception as error:  # noqa: BLE001 - a transport fault is recorded, never raised
        _record(
            db,
            outbox_id,
            now,
            status="failed",
            attempts=attempts,
            last_error=type(error).__name__[:200],
        )
        return
    _record(
        db,
        outbox_id,
        now,
        status="sent" if result.delivered else "recorded",
        transport=result.transport,
        attempts=attempts,
        skip_reason=None,
        last_error=None,
    )


def dispatch_pending(db: Session, *, limit: int = 100, now: datetime | None = None) -> int:
    """Claim, send and record queued (and retryable) notifications. Commits as it goes."""
    from app.core.db import run_unit_with_retry  # noqa: PLC0415

    now = now or utcnow()
    ids = run_unit_with_retry(db, lambda: _claim(db, limit, now))
    for outbox_id in ids:
        try:
            _deliver(db, outbox_id, now)
        except Exception:  # noqa: BLE001 - one row's fault never blocks the others
            # The outcome could not be written; the claim lapses after CLAIM_TIMEOUT and the
            # row is decided again then.
            db.rollback()
            logger.warning("notification_outcome_unrecorded id=%s", outbox_id, exc_info=True)
    return len(ids)


def dispatch_after_commit(db: Session) -> None:
    """Hand queued notifications to the transport once the milestone itself is committed.

    A failure here never undoes or fails the milestone the request recorded: it is logged and
    the rows stay for the worker (``python -m app.workers.notification_worker``).
    """
    try:
        dispatch_pending(db)
    except Exception:  # noqa: BLE001 - recorded, left for the worker, never raised
        db.rollback()
        logger.warning("notification_dispatch_deferred", exc_info=True)


def retry(db: Session, row: NotificationOutbox, *, actor: User | None) -> NotificationOutbox:
    if row.status != "failed":
        raise ConflictError("Only a failed notification is retried.")
    row.status = "queued"
    row.attempts = 0
    db.flush()
    audit_service.record_audit(
        db,
        action="notification.retry",
        entity_type="notification",
        entity_id=row.id,
        summary=f"Queued notification {row.id} again",
        actor=actor,
        detail={"milestone": row.milestone},
    )
    return row


def get(db: Session, outbox_id: int) -> NotificationOutbox:
    row = db.get(NotificationOutbox, outbox_id)
    if row is None:
        raise NotFoundError("Notification not found.")
    return row


def history_for_customer(
    db: Session, customer_id: int, *, limit: int = 100
) -> list[NotificationOutbox]:
    """The customer's own history. A withdrawn row (its event was voided) is left out: it would
    reveal a step the tracking page no longer shows."""
    return list(
        db.scalars(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.customer_id == customer_id,
                NotificationOutbox.skip_reason.is_distinct_from("voided"),
            )
            .order_by(NotificationOutbox.created_at.desc(), NotificationOutbox.id.desc())
            .limit(limit)
        )
    )
