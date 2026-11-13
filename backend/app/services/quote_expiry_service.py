"""Quotes expire when a new tariff version becomes active (owner decision 9, 2026-10-21).

The rule, exactly as the owner gave it: a quote expires **only** when the customer's goods
have not yet been received **and** a new tariff version becomes active. On activation every
finalised quote version priced against an older version of the same vendor's tariff --
with or without an offer, sent or accepted -- expires, unless:

* the shipment **has been received**: it has a published, unvoided milestone of
  ``received_at_solaris`` or later, or its operational state is ``received_at_solaris`` or
  later. Quotes for received shipments never expire;
* the shipment has an **issued invoice** (any live, unvoided one). An issued invoice is never
  touched, so its quote does not expire either (stand-in, listed in the fix-pack notes);
* the master the shipment **currently** rides in (``master_lock_service.master_for_shipment``)
  is **booked or completed**: a booked master is priced at the tariff it was booked under
  (``pricing_service.estimate_for``), so the new tariff cannot re-price it (stand-in, listed);
* the shipment is cancelled.

Expiring records a ``quote_expiries`` row (version, the tariff version that caused it, the
reason), turns a ``sent`` or ``accepted`` offer into ``expired`` (the Customer Account shows
it neutrally and it can no longer be answered), discards the draft invoice prepared from it
(audited ``invoice.draft_discarded``) and audits ``quote.expired``. The quote version keeps
its status; staff re-price, which opens the next version on the new tariff. No customer is
notified (owner: no).

Idempotent: activation calls this from the tariff routes, the approver's approval and
``tariff_import_service.activate_version``; a version already expired is skipped.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.enums import (
    BookingState,
    OperationalState,
    ShipmentEventType,
    TariffVersionStatus,
)
from app.core.time_utils import utcnow
from app.models import (
    CustomerInvoice,
    InvoiceDraft,
    QuoteExpiry,
    QuoteOffer,
    QuoteVersion,
    Shipment,
    ShipmentEvent,
    TariffVersion,
    User,
)
from app.services import audit_service

#: Milestones that mean the goods are in Solaris's hands (or beyond).
RECEIVED_EVENT_TYPES = frozenset(
    {
        ShipmentEventType.RECEIVED_AT_SOLARIS,
        ShipmentEventType.PROCESSING,
        ShipmentEventType.DEPARTED_ORIGIN,
        ShipmentEventType.IN_TRANSIT,
        ShipmentEventType.CUSTOMS_PROCESSING,
        ShipmentEventType.ARRIVED_DESTINATION,
        ShipmentEventType.OUT_FOR_DELIVERY,
        ShipmentEventType.DELIVERED_TO_RECIPIENT,
        ShipmentEventType.DELIVERED_TO_COLLECTION_POINT,
        ShipmentEventType.DELIVERY_ATTEMPTED,
        ShipmentEventType.RETURN_IN_PROGRESS,
        ShipmentEventType.RETURNED,
    }
)
#: Operational states at or after receipt. ``exception`` is not here: an exception can be
#: raised before the parcel arrives (stand-in, listed).
RECEIVED_OPERATIONAL_STATES = frozenset(
    {
        OperationalState.RECEIVED_AT_SOLARIS,
        OperationalState.PROCESSING,
        OperationalState.DEPARTED_ORIGIN,
        OperationalState.IN_TRANSIT,
        OperationalState.CUSTOMS_PROCESSING,
        OperationalState.ARRIVED_DESTINATION,
        OperationalState.OUT_FOR_DELIVERY,
        OperationalState.PARTIALLY_DELIVERED,
        OperationalState.DELIVERED,
        OperationalState.DELIVERY_ATTEMPTED,
        OperationalState.RETURN_IN_PROGRESS,
        OperationalState.RETURNED,
    }
)
#: Offer statuses that expire with their version (still open, or accepted and not invoiced).
EXPIRING_OFFER_STATUSES = ("sent", "accepted")


def expiry_for(db: Session, quote_version_id: int) -> QuoteExpiry | None:
    return db.scalar(select(QuoteExpiry).where(QuoteExpiry.quote_version_id == quote_version_id))


def is_expired(db: Session, quote_version_id: int | None) -> bool:
    return quote_version_id is not None and expiry_for(db, quote_version_id) is not None


def expiries_for_shipment(db: Session, shipment_id: int) -> dict[int, QuoteExpiry]:
    return {
        row.quote_version_id: row
        for row in db.scalars(select(QuoteExpiry).where(QuoteExpiry.shipment_id == shipment_id))
    }


def expiry_view(db: Session, row: QuoteExpiry | None) -> dict[str, Any] | None:
    if row is None:
        return None
    tariff = db.get(TariffVersion, row.tariff_version_id) if row.tariff_version_id else None
    return {
        "expired_at": row.expired_at,
        "reason": row.reason,
        "tariff_version_public_id": tariff.public_id if tariff else None,
        "previous_offer_status": row.previous_offer_status,
    }


def is_received(db: Session, shipment: Shipment) -> bool:
    """Whether the goods are in Solaris's hands (or beyond): see the module docstring."""
    if shipment.operational_state in RECEIVED_OPERATIONAL_STATES:
        return True
    return (
        db.scalar(
            select(ShipmentEvent.id)
            .where(
                ShipmentEvent.shipment_id == shipment.id,
                ShipmentEvent.event_type.in_(sorted(RECEIVED_EVENT_TYPES)),
                ShipmentEvent.is_public_update.is_(True),
                ShipmentEvent.is_voided.is_(False),
            )
            .limit(1)
        )
        is not None
    )


def _has_issued_invoice(db: Session, shipment_id: int) -> bool:
    return (
        db.scalar(
            select(CustomerInvoice.id).where(
                CustomerInvoice.shipment_id == shipment_id, CustomerInvoice.status != "void"
            )
        )
        is not None
    )


def keep_reason(db: Session, version: QuoteVersion, shipment: Shipment | None) -> str | None:
    """Why this finalised version does not expire, or None when it does."""
    from app.services import master_lock_service  # noqa: PLC0415

    if shipment is None or shipment.booking_state == BookingState.CANCELLED:
        return "cancelled"
    if is_received(db, shipment):
        return "received"
    if _has_issued_invoice(db, shipment.id):
        return "invoice_issued"
    # The master the shipment rides in NOW, not the one the version was priced in: a shipment
    # moved out of a booked master is re-priceable, one moved into a booked master is not.
    master = master_lock_service.master_for_shipment(db, shipment.id)
    if master_lock_service.is_locked_state(master):
        return "master_booked"
    return None


def _expire_offer(db: Session, offer: QuoteOffer, *, now: datetime) -> str | None:
    """Expire a sent or accepted offer with a conditional UPDATE; return its true previous
    status (None when it was neither).

    The status is read from the database, not the session, and the UPDATE only applies
    while the row still holds the status just read and is still sent or accepted -- so a
    customer's acceptance that commits in between is seen (the previous status recorded is
    ``accepted``) rather than overwritten or misreported (independent review M5).
    """
    previous = None
    for _attempt in range(3):
        current = db.scalar(
            select(QuoteOffer.status)
            .where(QuoteOffer.id == offer.id)
            .execution_options(populate_existing=True)
        )
        if current not in EXPIRING_OFFER_STATUSES:
            break
        changed = db.execute(
            update(QuoteOffer)
            .where(
                QuoteOffer.id == offer.id,
                QuoteOffer.status.in_(EXPIRING_OFFER_STATUSES),
                QuoteOffer.status == current,
            )
            .values(status="expired", updated_at=now)
            .execution_options(synchronize_session=False)
        ).rowcount
        if changed == 1:
            previous = current
            break
    db.refresh(offer)
    return previous


def expire_for_new_tariff(
    db: Session,
    version: TariffVersion,
    *,
    actor: User | None,
    now: datetime | None = None,
) -> list[QuoteExpiry]:
    """Expire the quotes the activation of ``version`` makes stale. Returns the new rows."""
    from app.services import invoice_draft_service  # noqa: PLC0415 - avoids an import cycle

    if version is None or version.status != TariffVersionStatus.ACTIVE:
        return []
    now = now or utcnow()
    older = select(TariffVersion.id).where(
        TariffVersion.vendor_id == version.vendor_id, TariffVersion.id != version.id
    )
    candidates = list(
        db.scalars(
            select(QuoteVersion)
            .where(
                QuoteVersion.status == "finalized",
                QuoteVersion.tariff_version_id.in_(older),
                ~select(QuoteExpiry.id)
                .where(QuoteExpiry.quote_version_id == QuoteVersion.id)
                .exists(),
            )
            .order_by(QuoteVersion.id)
        )
    )
    created: list[QuoteExpiry] = []
    for quote in candidates:
        shipment = db.get(Shipment, quote.shipment_id)
        if keep_reason(db, quote, shipment) is not None:
            continue
        reason = f"tariff {version.public_id} became active before the goods were received"
        offer = db.scalar(select(QuoteOffer).where(QuoteOffer.quote_version_id == quote.id))
        previous = _expire_offer(db, offer, now=now) if offer is not None else None
        # Re-read after the offer changed: an acceptance that committed a moment ago has
        # created its draft by now, and that draft is withdrawn with the quote.
        draft = db.scalar(
            select(InvoiceDraft)
            .where(
                InvoiceDraft.shipment_id == shipment.id,
                InvoiceDraft.quote_version_id == quote.id,
                InvoiceDraft.status == "draft",
            )
            .execution_options(populate_existing=True)
        )
        if draft is not None:
            invoice_draft_service.discard(
                db, draft, reason=f"quote v{quote.version} expired: {reason}", actor=actor, now=now
            )
        row = QuoteExpiry(
            quote_version_id=quote.id,
            shipment_id=shipment.id,
            tariff_version_id=version.id,
            offer_id=offer.id if offer else None,
            previous_offer_status=previous,
            invoice_draft_id=draft.id if draft else None,
            reason=reason[:400],
            expired_at=now,
        )
        db.add(row)
        db.flush()
        audit_service.record_audit(
            db,
            action="quote.expired",
            entity_type="shipment",
            entity_id=shipment.id,
            summary=(
                f"Quote v{quote.version} for {shipment.public_id} expired: tariff "
                f"{version.public_id} became active before the goods were received"
            )[:400],
            actor=actor,
            detail={
                "quote_version_id": quote.id,
                "version": quote.version,
                "tariff_version": version.public_id,
                "offer_id": offer.id if offer else None,
                "previous_offer_status": previous,
                "invoice_draft_id": draft.id if draft else None,
            },
        )
        created.append(row)
    return created
