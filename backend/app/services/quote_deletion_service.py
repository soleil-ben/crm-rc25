"""Admin soft delete of old quote records, and restore (RC-UAT-21 Phase D, DEC-0233).

OD-95 and OD-98 keep quotes with an issued invoice or on a booked master "with minimal
storage" and ask for "an Admin manual delete later"; OD-107 says build it. Nothing in this
system has ever been hard-deleted, so the delete is **soft**: a row in
``quote_version_deletions`` (reason required, audited ``quote.soft_delete``). The quote,
its lines, its offer and its expiry stay for audit. A soft-deleted version disappears from:

* the staff quote list and offer list of the shipment (``/shipments/{id}/quotes``,
  ``/shipments/{id}/quote-offers``) unless an Admin asks for deleted ones;
* the printable quote document (404);
* the Customer Account quote list and detail (404, as for an unknown quote);
* the accepted-not-invoiced list.

**Refused** (stand-in D-1): a draft (the working copy); a version referenced by an issued,
unvoided invoice; a version with a live draft invoice; a version whose offer is still open
(``sent``); a version whose offer was accepted while the shipment has no live invoice; a
version younger than the configured minimum age (``data_retention_settings.
quote_delete_min_age_days``, default 0, stand-in D-3). **Allowed**: superseded, expired,
withdrawn or declined versions, and finalised versions never sent.

Restoring (Admin, reason required, audited ``quote.restore``) closes the row; the history of
both stays. A deleted version cannot be sent or invoiced until it is restored.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time_utils import utcnow
from app.models import (
    CustomerInvoice,
    InvoiceDraft,
    QuoteExpiry,
    QuoteOffer,
    QuoteVersion,
    QuoteVersionDeletion,
    Shipment,
    User,
)
from app.services import audit_service
from app.services.errors import ConflictError, NotFoundError, ValidationError

REASON_MAX = 400

#: Why a version cannot be soft-deleted, by code (the UI words each one).
REFUSALS: dict[str, str] = {
    "already_deleted": "This quote version is already deleted.",
    "draft": "A draft quote is the working copy: finalise or re-price it instead.",
    "issued_invoice": "An issued invoice uses this quote version: void the invoice first.",
    "live_draft_invoice": (
        "A draft invoice is being prepared from this quote version: withdraw the draft first."
    ),
    "open_offer": "This quote is waiting for the customer's answer: withdraw the offer first.",
    "accepted_not_invoiced": (
        "The customer accepted this quote and the shipment is not invoiced yet."
    ),
    "too_recent": "This quote version is newer than the minimum age for deleting quotes.",
}


# --- Reading -------------------------------------------------------------------------------------


def open_deletions_subquery():
    """The ids of every soft-deleted (not restored) version, for ``NOT IN`` filters."""
    return select(QuoteVersionDeletion.quote_version_id).where(
        QuoteVersionDeletion.restored_at.is_(None),
        QuoteVersionDeletion.quote_version_id.is_not(None),
    )


def open_deletion(db: Session, version_id: int) -> QuoteVersionDeletion | None:
    return db.scalar(
        select(QuoteVersionDeletion).where(
            QuoteVersionDeletion.quote_version_id == version_id,
            QuoteVersionDeletion.restored_at.is_(None),
        )
    )


def is_deleted(db: Session, version_id: int | None) -> bool:
    return version_id is not None and open_deletion(db, version_id) is not None


def deleted_version_ids(db: Session, shipment_id: int) -> set[int]:
    return set(
        db.scalars(
            select(QuoteVersionDeletion.quote_version_id).where(
                QuoteVersionDeletion.shipment_id == shipment_id,
                QuoteVersionDeletion.restored_at.is_(None),
                QuoteVersionDeletion.quote_version_id.is_not(None),
            )
        )
    )


def min_age_days(db: Session) -> int:
    from app.services import data_retention_service  # noqa: PLC0415

    return data_retention_service.read_settings(db).quote_delete_min_age_days


def _reference_time(version: QuoteVersion) -> datetime:
    return version.superseded_at or version.finalized_at or version.created_at


def refusal(db: Session, version: QuoteVersion, *, now: datetime | None = None) -> str | None:
    """Why ``version`` cannot be soft-deleted now, as a ``REFUSALS`` code, or None."""
    now = now or utcnow()
    if is_deleted(db, version.id):
        return "already_deleted"
    if version.status == "draft":
        return "draft"
    if db.scalar(
        select(CustomerInvoice.id).where(
            CustomerInvoice.quote_version_id == version.id, CustomerInvoice.status != "void"
        )
    ):
        return "issued_invoice"
    if db.scalar(
        select(InvoiceDraft.id).where(
            InvoiceDraft.quote_version_id == version.id, InvoiceDraft.status == "draft"
        )
    ):
        return "live_draft_invoice"
    offer = db.scalar(select(QuoteOffer).where(QuoteOffer.quote_version_id == version.id))
    if offer is not None and offer.status == "sent":
        return "open_offer"
    if offer is not None and offer.status == "accepted":
        invoiced = db.scalar(
            select(CustomerInvoice.id).where(
                CustomerInvoice.shipment_id == version.shipment_id,
                CustomerInvoice.status != "void",
            )
        )
        if not invoiced:
            return "accepted_not_invoiced"
    age = min_age_days(db)
    if age > 0 and _reference_time(version) > now - timedelta(days=age):
        return "too_recent"
    return None


def history(db: Session, shipment: Shipment, *, include_deleted: bool) -> list[dict[str, Any]]:
    """Every version of the shipment, newest first, with its offer, deletion and whether an
    Admin may delete it (the refusal code otherwise). Deleted versions only on request."""
    now = utcnow()
    versions = list(
        db.scalars(
            select(QuoteVersion)
            .where(QuoteVersion.shipment_id == shipment.id)
            .order_by(QuoteVersion.version.desc())
        )
    )
    offers = {
        o.quote_version_id: o
        for o in db.scalars(select(QuoteOffer).where(QuoteOffer.shipment_id == shipment.id))
    }
    expired = set(
        db.scalars(
            select(QuoteExpiry.quote_version_id).where(QuoteExpiry.shipment_id == shipment.id)
        )
    )
    deletions = {
        d.quote_version_id: d
        for d in db.scalars(
            select(QuoteVersionDeletion).where(
                QuoteVersionDeletion.shipment_id == shipment.id,
                QuoteVersionDeletion.restored_at.is_(None),
            )
        )
    }
    rows = []
    for version in versions:
        deletion = deletions.get(version.id)
        if deletion is not None and not include_deleted:
            continue
        offer = offers.get(version.id)
        code = None if deletion is not None else refusal(db, version, now=now)
        deleted_by = (
            db.get(User, deletion.deleted_by_user_id)
            if deletion and deletion.deleted_by_user_id
            else None
        )
        rows.append(
            {
                "quote_version_id": version.id,
                "version": version.version,
                "status": version.status,
                "created_at": version.created_at,
                "finalized_at": version.finalized_at,
                "total_revenue_cad": version.total_revenue_cad,
                "offer_status": offer.status if offer else None,
                "expired": version.id in expired,
                "deletable": deletion is None and code is None,
                "refusal": code,
                "refusal_message": REFUSALS.get(code) if code else None,
                "deleted": (
                    {
                        "deleted_at": deletion.deleted_at,
                        "deleted_by": deleted_by.email if deleted_by else None,
                        "reason": deletion.reason,
                    }
                    if deletion
                    else None
                ),
            }
        )
    return rows


# --- Writing -------------------------------------------------------------------------------------


def _reason(reason: str | None) -> str:
    text = (reason or "").strip()
    if not text:
        raise ValidationError("A reason is required.", field="reason")
    if len(text) > REASON_MAX:
        raise ValidationError(f"Keep the reason under {REASON_MAX} characters.", field="reason")
    return text


def get_version(db: Session, version_id: int) -> QuoteVersion:
    version = db.get(QuoteVersion, version_id) if 0 < version_id < 2**31 else None
    if version is None:
        raise NotFoundError("That quote version does not exist.")
    return version


def soft_delete(
    db: Session,
    version: QuoteVersion,
    *,
    reason: str | None,
    actor: User | None,
    now: datetime | None = None,
) -> QuoteVersionDeletion:
    """Soft-delete ``version`` (Admin; the route checks ``quote:delete``). The caller commits."""
    now = now or utcnow()
    text = _reason(reason)
    code = refusal(db, version, now=now)
    if code is not None:
        raise ConflictError(REFUSALS[code], detail={"code": code})
    row = QuoteVersionDeletion(
        quote_version_id=version.id,
        shipment_id=version.shipment_id,
        version=version.version,
        reason=text,
        deleted_at=now,
        deleted_by_user_id=actor.id if actor else None,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as error:  # a concurrent delete of the same version won
        raise ConflictError(REFUSALS["already_deleted"], detail={"code": "already_deleted"}) from (
            error
        )
    shipment = db.get(Shipment, version.shipment_id)
    audit_service.record_audit(
        db,
        action="quote.soft_delete",
        entity_type="quote_version",
        entity_id=version.id,
        summary=(
            f"Quote v{version.version} of {shipment.public_id if shipment else '?'} deleted "
            "(soft delete; the record is kept)"
        ),
        actor=actor,
        detail={
            "shipment_id": version.shipment_id,
            "version": version.version,
            "status": version.status,
            "reason": text,
            "deletion_id": row.id,
        },
    )
    return row


def restore(
    db: Session,
    version: QuoteVersion,
    *,
    reason: str | None,
    actor: User | None,
    now: datetime | None = None,
) -> QuoteVersionDeletion:
    """Restore a soft-deleted version (Admin). The caller commits."""
    now = now or utcnow()
    text = _reason(reason)
    row = open_deletion(db, version.id)
    if row is None:
        raise ConflictError("This quote version is not deleted.", detail={"code": "not_deleted"})
    row.restored_at = now
    row.restored_by_user_id = actor.id if actor else None
    row.restore_reason = text
    shipment = db.get(Shipment, version.shipment_id)
    audit_service.record_audit(
        db,
        action="quote.restore",
        entity_type="quote_version",
        entity_id=version.id,
        summary=f"Quote v{version.version} of {shipment.public_id if shipment else '?'} restored",
        actor=actor,
        detail={
            "shipment_id": version.shipment_id,
            "version": version.version,
            "reason": text,
            "deletion_id": row.id,
        },
    )
    return row


def refuse_if_latest_finalised_deleted(db: Session, shipment_id: int, *, doing: str) -> None:
    """Raise when the shipment's newest finalised version (deleted ones included) is
    soft-deleted: callers that skip deleted versions would otherwise find none and say only
    "finalise first"."""
    newest = db.scalar(
        select(QuoteVersion)
        .where(QuoteVersion.shipment_id == shipment_id, QuoteVersion.status == "finalized")
        .order_by(QuoteVersion.version.desc())
        .limit(1)
    )
    if newest is not None:
        refuse_if_deleted(db, newest, doing=doing)


def refuse_if_deleted(db: Session, version: QuoteVersion, *, doing: str) -> None:
    """Raise when ``version`` is soft-deleted: it cannot be sent or invoiced until restored."""
    if is_deleted(db, version.id):
        raise ConflictError(
            f"Quote v{version.version} was deleted by an Admin: restore it, or re-quote, "
            f"before {doing}.",
            detail={"code": "quote_deleted"},
        )
