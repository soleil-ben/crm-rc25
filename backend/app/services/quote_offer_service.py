"""Quote offers: staff send a finalised quote, the customer accepts or declines it (Phase 13G).

OD-77 (D-08): staff **send** the quote; the customer answers it in the Customer Account.

* **Sending** needs the shipment's latest quote version to be ``finalized`` (an open draft
  after it means staff are re-pricing: finalise it first) and the shipment to have a
  customer. One offer per version, ever. An older offer still waiting for an answer is
  withdrawn ("superseded by vN"). The offer freezes a **customer-safe** view of the version
  (``customer_view``): service label, billable kilograms, selling rate per kilogram, base
  charge, each surcharge line the customer pays (name and amount), total, currency. Nothing
  cost-derived is read into it.
* **Email.** After the offer is committed, one quote-sent email goes through the account
  email seam (null or capture transports only: nothing reaches a customer), in the
  customer's language, carrying the reference and the account link only -- no amount. A
  suppressed address or a customer without one is not emailed. The outcome is recorded on
  the offer in its own unit; the send itself is never inside a retried unit, so a lock can
  never send it twice. A failure is recorded, never raised: the offer stands.
* **Answering.** Only an offer that is ``sent``, only by an active identity linked to that
  customer (the route resolves it), and only while the offer's version is still the latest
  finalised one. The status change is a conditional update (``WHERE status = 'sent'``), so a
  second answer -- or two at once -- gets a conflict, never a second answer.
* **Re-pricing.** Finalising a newer version withdraws the sent offer
  (``pricing_service.finalize`` calls ``withdraw_open_for_shipment``), and acceptance
  re-checks the version anyway.
* **Resending** (Phase 15): staff send the email again for an unanswered offer whose email
  ``failed`` or found no address (once one is added): ``prepare_resend`` claims it and audits
  ``quote.email_resent``; the route commits and calls ``send_email`` as for the first send.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.enums import SOLARIS_SERVICE_LABELS, ConsentChannel
from app.core.time_utils import utcnow
from app.models import (
    Customer,
    CustomerIdentity,
    QuoteOffer,
    QuoteVersion,
    Shipment,
    User,
)
from app.services import (
    account_email_service,
    audit_service,
    consent_service,
    customer_identity_service,
    notification_service,
)
from app.services.errors import ConflictError, NotFoundError, ValidationError

logger = logging.getLogger("solaris.quote_offers")

#: The Customer Account page the quote-sent email links to.
ACCOUNT_QUOTES_PATH = "quotes"
REASON_MAX = 400


def template_key(language: str) -> str:
    return f"quote.sent.{'en' if language == 'en' else 'vi'}"


# --- Reading -------------------------------------------------------------------------------------


def get(db: Session, offer_id: int) -> QuoteOffer:
    offer = db.get(QuoteOffer, offer_id)
    if offer is None:
        raise NotFoundError("That quote offer does not exist.")
    return offer


def list_for_shipment(db: Session, shipment_id: int) -> list[QuoteOffer]:
    return list(
        db.scalars(
            select(QuoteOffer)
            .where(QuoteOffer.shipment_id == shipment_id)
            .order_by(QuoteOffer.sent_at.desc(), QuoteOffer.id.desc())
        )
    )


def list_for_customer(db: Session, customer_id: int, *, limit: int = 100) -> list[QuoteOffer]:
    return list(
        db.scalars(
            select(QuoteOffer)
            .where(
                QuoteOffer.customer_id == customer_id,
                # RC-UAT-21 Phase D (DEC-0233): a soft-deleted version's offer is not shown.
                QuoteOffer.quote_version_id.not_in(_deleted_versions()),
            )
            .order_by(QuoteOffer.sent_at.desc(), QuoteOffer.id.desc())
            .limit(limit)
        )
    )


def owned_offer(db: Session, offer_id: Any, customer_id: int) -> QuoteOffer:
    """The customer's own offer, or one 404 for every other case (unknown, malformed,
    another customer's)."""
    try:
        number = int(str(offer_id))
    except (TypeError, ValueError) as error:
        raise NotFoundError("That quote does not exist.") from error
    offer = db.get(QuoteOffer, number) if 0 < number < 2**31 else None
    if offer is None or offer.customer_id != customer_id:
        raise NotFoundError("That quote does not exist.")
    from app.services import quote_deletion_service  # noqa: PLC0415

    if quote_deletion_service.is_deleted(db, offer.quote_version_id):
        raise NotFoundError("That quote does not exist.")
    return offer


def _deleted_versions():
    """Soft-deleted quote versions (RC-UAT-21 Phase D), for ``NOT IN`` filters."""
    from app.services import quote_deletion_service  # noqa: PLC0415

    return quote_deletion_service.open_deletions_subquery()


def customer_view(offer: QuoteOffer) -> dict[str, Any]:
    return json.loads(offer.customer_view_json or "{}")


def version_number(offer: QuoteOffer) -> int | None:
    return customer_view(offer).get("version")


def is_current(db: Session, offer: QuoteOffer) -> bool:
    """Whether the offer's version is still the shipment's latest finalised one."""
    version = db.get(QuoteVersion, offer.quote_version_id)
    if version is None or version.status != "finalized":
        return False
    newer = db.scalar(
        select(QuoteVersion.id).where(
            QuoteVersion.shipment_id == offer.shipment_id,
            QuoteVersion.status == "finalized",
            QuoteVersion.version > version.version,
            # RC-UAT-21 Phase D: a soft-deleted version is not a newer quote.
            QuoteVersion.id.not_in(_deleted_versions()),
        )
    )
    return newer is None


# --- The customer-safe view ----------------------------------------------------------------------


def _money(value: Decimal | None) -> str:
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


def build_customer_view(shipment: Shipment, version: QuoteVersion) -> dict[str, Any]:
    """The frozen customer content of a finalised version.

    Reads **only** the customer side: the service label, billable weight, selling rate, and
    each line's ``revenue_cad`` and customer-facing ``description``. Never ``cost_*``,
    ``markup_*``, ``fx_snapshot_id``, ``tariff_version_id``, the snapshot or the margin.
    Surcharge lines the customer pays nothing for (a cost share only) are left out, as on
    the invoice. A surcharge name that names a vendor is replaced by a neutral label in the
    customer's language (owner, 2026-10-21, DEC-0222; ``customer_labels``).
    """
    from sqlalchemy.orm import object_session  # noqa: PLC0415

    from app.services.customer_labels import customer_safe_label, vendor_names  # noqa: PLC0415

    db = object_session(version) or object_session(shipment)
    names = vendor_names(db)
    language = "vi"
    if db is not None and shipment.customer_id is not None:
        language = notification_service.language_for(db, db.get(Customer, shipment.customer_id))
    base = next((line for line in version.lines if line.kind == "base_freight"), None)
    surcharges = [
        {
            "name": customer_safe_label(line.description, names, language=language),
            "amount_cad": _money(line.revenue_cad),
        }
        for line in version.lines
        if line.kind == "surcharge" and line.revenue_cad and line.revenue_cad > 0
    ]
    return {
        "shipment_reference": shipment.public_id,
        "version": version.version,
        "service": SOLARIS_SERVICE_LABELS.get(version.solaris_service, version.solaris_service),
        "billable_weight_kg": str(Decimal(version.billable_weight_kg).quantize(Decimal("0.001")))
        if version.billable_weight_kg is not None
        else None,
        "rate_per_kg_cad": _money(version.selling_rate_cad),
        "base_charge_cad": _money(base.revenue_cad if base else version.base_revenue_cad),
        "surcharges": surcharges,
        "total_cad": _money(version.total_revenue_cad),
        "currency": "CAD",
        # GST/HST is chosen per invoice (OD-64), so the quote is before tax.
        "tax_included": False,
    }


# --- Staff: send and withdraw --------------------------------------------------------------------


def _latest_version(db: Session, shipment_id: int) -> QuoteVersion | None:
    return db.scalar(
        select(QuoteVersion)
        .where(QuoteVersion.shipment_id == shipment_id)
        .order_by(QuoteVersion.version.desc())
        .limit(1)
    )


#: Why an offer was withdrawn, as a code the Customer Account may word (never the text).
WITHDRAWN_CODES = ("staff", "superseded", "customer_merged", "customer_changed")


def _withdraw(offer: QuoteOffer, reason: str, now: datetime, code: str) -> None:
    offer.status = "withdrawn"
    offer.withdrawn_reason = reason[:REASON_MAX]
    offer.withdrawn_code = code
    offer.withdrawn_at = now
    offer.updated_at = now


def closed_reason(db: Session, offer: QuoteOffer) -> str | None:
    """Why the customer cannot answer this offer, as a customer-safe code, or None.

    ``accepted`` | ``declined`` (already answered); ``withdrawn`` (staff withdrew it, or the
    customer record changed); ``replaced`` (a newer version was finalised, or the version
    otherwise stopped being the latest finalised one); ``updating`` (staff have a newer draft
    open). Internal words such as "superseded" never reach the customer.
    """
    if offer.status in ("accepted", "declined"):
        return offer.status
    if offer.status == "expired":
        # Owner decision 9: a new tariff became active before the goods were received.
        return "expired"
    if offer.status == "withdrawn":
        return "replaced" if offer.withdrawn_code == "superseded" else "withdrawn"
    shipment = db.get(Shipment, offer.shipment_id)
    if shipment is None or shipment.customer_id != offer.customer_id:
        return "withdrawn"
    latest = _latest_version(db, offer.shipment_id)
    if latest is not None and latest.id != offer.quote_version_id:
        return "updating" if latest.status == "draft" else "replaced"
    if not is_current(db, offer):
        return "replaced"
    return None


def withdraw_open_for_shipment(
    db: Session,
    shipment_id: int,
    *,
    reason: str,
    actor: User | None,
    now: datetime | None = None,
    code: str = "superseded",
) -> list[QuoteOffer]:
    """Withdraw any offer of this shipment still waiting for an answer."""
    now = now or utcnow()
    withdrawn = list(
        db.scalars(
            select(QuoteOffer).where(
                QuoteOffer.shipment_id == shipment_id, QuoteOffer.status == "sent"
            )
        )
    )
    for offer in withdrawn:
        _withdraw(offer, reason, now, code)
    if withdrawn:
        db.flush()
        for offer in withdrawn:
            audit_service.record_audit(
                db,
                action="quote.withdrawn",
                entity_type="quote_offer",
                entity_id=offer.id,
                summary=f"Withdrew quote offer {offer.id}: {reason}"[:400],
                actor=actor,
                detail={
                    "shipment_id": shipment_id,
                    "reason": reason[:REASON_MAX],
                    "code": code,
                },
            )
    return withdrawn


def on_version_finalized(
    db: Session,
    shipment_id: int,
    version: int,
    *,
    actor: User | None,
    now: datetime | None = None,
) -> None:
    """A newer version was finalised (called by ``pricing_service.finalize``).

    An unanswered offer is withdrawn ("superseded by vN"). An offer the customer already
    **accepted** is not silently left behind: it is flagged (``superseded_by_version``) and
    audited (``quote.accepted_superseded``) so staff see that the customer accepted an
    earlier price.
    """
    now = now or utcnow()
    withdraw_open_for_shipment(
        db, shipment_id, reason=f"superseded by v{version}", actor=actor, now=now
    )
    accepted = list(
        db.scalars(
            select(QuoteOffer).where(
                QuoteOffer.shipment_id == shipment_id,
                QuoteOffer.status == "accepted",
                QuoteOffer.superseded_by_version.is_(None),
            )
        )
    )
    for offer in accepted:
        offer.superseded_by_version = version
        offer.superseded_at = now
        offer.updated_at = now
    if accepted:
        db.flush()
    for offer in accepted:
        audit_service.record_audit(
            db,
            action="quote.accepted_superseded",
            entity_type="quote_offer",
            entity_id=offer.id,
            summary=(
                f"Quote v{version} finalised after the customer accepted "
                f"v{version_number(offer)} (offer {offer.id})"
            ),
            actor=actor,
            detail={
                "shipment_id": shipment_id,
                "accepted_version": version_number(offer),
                "new_version": version,
            },
        )


def withdraw_for_customer_change(
    db: Session,
    shipment_id: int,
    *,
    new_customer_id: int | None,
    reason: str = "customer changed",
    code: str = "customer_changed",
    actor: User | None,
    now: datetime | None = None,
) -> None:
    """The shipment's customer changed: an unanswered offer is withdrawn (the new customer
    was never offered it, the old one may no longer answer); answered offers follow the
    shipment to the new customer so its history stays with it."""
    withdraw_open_for_shipment(db, shipment_id, reason=reason, actor=actor, now=now, code=code)
    for offer in db.scalars(select(QuoteOffer).where(QuoteOffer.shipment_id == shipment_id)):
        if offer.customer_id != new_customer_id:
            offer.customer_id = new_customer_id
    db.flush()


def move_for_merge(db: Session, *, source_id: int, target_id: int, actor: User | None) -> int:
    """A customer merge: every offer of the source's shipments is handled as a customer
    change (reason "customer merged"). Returns how many offers were touched."""
    offers = list(db.scalars(select(QuoteOffer).where(QuoteOffer.customer_id == source_id)))
    for shipment_id in sorted({o.shipment_id for o in offers}):
        withdraw_for_customer_change(
            db,
            shipment_id,
            new_customer_id=target_id,
            reason="customer merged",
            code="customer_merged",
            actor=actor,
        )
    return len(offers)


def send_quote(
    db: Session, shipment: Shipment, *, actor: User | None, now: datetime | None = None
) -> QuoteOffer:
    """Offer the shipment's finalised quote to its customer. The caller commits, then calls
    ``send_email`` (never inside a retried unit)."""
    now = now or utcnow()
    if shipment.customer_id is None:
        raise ConflictError("This shipment has no customer to send the quote to.")
    latest = _latest_version(db, shipment.id)
    if latest is None or latest.status != "finalized":
        raise ConflictError(
            "Only a finalised quote is sent, and it must be the latest version: finalise "
            "the quote first."
        )
    if db.scalar(select(QuoteOffer.id).where(QuoteOffer.quote_version_id == latest.id)):
        raise ConflictError(f"Quote v{latest.version} has already been sent.")
    from app.services import quote_expiry_service  # noqa: PLC0415

    if quote_expiry_service.is_expired(db, latest.id):
        raise ConflictError(
            f"Quote v{latest.version} expired when a new tariff became active: re-quote on "
            "the new rate, then send the new version.",
            detail={"code": "quote_expired"},
        )
    from app.services import quote_deletion_service  # noqa: PLC0415

    quote_deletion_service.refuse_if_deleted(db, latest, doing="sending it")
    withdraw_open_for_shipment(
        db, shipment.id, reason=f"superseded by v{latest.version}", actor=actor, now=now
    )
    offer = QuoteOffer(
        quote_version_id=latest.id,
        shipment_id=shipment.id,
        customer_id=shipment.customer_id,
        status="sent",
        customer_view_json=json.dumps(build_customer_view(shipment, latest), ensure_ascii=False),
        sent_at=now,
        sent_by_user_id=actor.id if actor else None,
        created_at=now,
        updated_at=now,
    )
    db.add(offer)
    db.flush()
    audit_service.record_audit(
        db,
        action="quote.sent",
        entity_type="quote_offer",
        entity_id=offer.id,
        summary=f"Sent quote v{latest.version} for {shipment.public_id} to the customer",
        actor=actor,
        detail={
            "shipment_id": shipment.id,
            "quote_version_id": latest.id,
            "version": latest.version,
            "customer_id": shipment.customer_id,
        },
    )
    return offer


def withdraw(
    db: Session,
    offer: QuoteOffer,
    *,
    reason: str | None,
    actor: User | None,
    now: datetime | None = None,
) -> QuoteOffer:
    reason = " ".join((reason or "").split())
    if not reason:
        raise ValidationError("Give a reason to withdraw the quote.", field="reason")
    if len(reason) > REASON_MAX:
        raise ValidationError(f"At most {REASON_MAX} characters.", field="reason")
    if offer.status != "sent":
        raise ConflictError(f"This quote is {offer.status}; only a sent quote is withdrawn.")
    _withdraw(offer, reason, now or utcnow(), "staff")
    db.flush()
    audit_service.record_audit(
        db,
        action="quote.withdrawn",
        entity_type="quote_offer",
        entity_id=offer.id,
        summary=f"Withdrew quote offer {offer.id}: {reason}"[:400],
        actor=actor,
        detail={"shipment_id": offer.shipment_id, "reason": reason},
    )
    return offer


# --- The quote-sent email: decide, send outside any unit, record --------------------------------


def _decide_email(db: Session, offer: QuoteOffer) -> tuple[str | None, Any]:
    if offer.status != "sent":
        # Answered or withdrawn between the claim and the send (Phase 15 review): nothing is
        # sent, and the outcome is recorded so the claim does not stand.
        return "skipped", None
    customer = db.get(Customer, offer.customer_id) if offer.customer_id else None
    address = (
        consent_service.normalized_address_for(customer, ConsentChannel.EMAIL) if customer else None
    )
    if not address:
        return "no_email", None
    # A quote is operational email: a suppression blocks marketing only (DEC-0143), so it is
    # not read here. Milestone notifications are the one named exception (OD-72).
    language = notification_service.language_for(db, customer)
    shipment = db.get(Shipment, offer.shipment_id)
    message = account_email_service.OutboundEmail(
        to_email=customer.email_entered or address,
        template_key=template_key(language),
        language=language,
        parameters={
            "shipment_reference": shipment.public_id or "",
            "account_url": customer_identity_service.account_page_url(ACCOUNT_QUOTES_PATH),
        },
    )
    return None, message


def _record_email(db: Session, offer_id: int, status: str) -> None:
    from app.core.db import run_unit_with_retry  # noqa: PLC0415

    def work() -> None:
        offer = db.get(QuoteOffer, offer_id)
        offer.email_status = status
        db.flush()

    run_unit_with_retry(db, work)


def send_email(db: Session, offer_id: int) -> str:
    """Email the customer that a quote is waiting. Call after the offer is committed.

    Returns the recorded outcome. Never raises: a fault is logged and recorded as
    ``failed`` (or left unrecorded if even that cannot be written), and the offer stands.
    """
    try:
        offer = db.get(QuoteOffer, offer_id)
        reason, message = _decide_email(db, offer)
    except Exception:  # noqa: BLE001 - the offer stands whatever the email does
        db.rollback()
        logger.warning("quote_email_undecided offer=%s", offer_id, exc_info=True)
        status = "failed"
    else:
        db.rollback()  # end the read transaction before the side effect; nothing is pending
        if reason is not None:
            status = reason
        else:
            try:
                result = account_email_service.send(message)
                status = "sent" if result.delivered else "recorded"
            except Exception:  # noqa: BLE001 - a transport fault is recorded, never raised
                logger.warning("quote_email_failed offer=%s", offer_id, exc_info=True)
                status = "failed"
    try:
        _record_email(db, offer_id, status)
    except Exception:  # noqa: BLE001 - recorded in the log instead
        db.rollback()
        logger.warning("quote_email_unrecorded offer=%s", offer_id, exc_info=True)
    return status


#: Phase 15 review: a ``resending`` claim older than this was abandoned (the process died
#: mid-send) and may be taken over by a new resend; a younger one is in flight (409).
RESEND_CLAIM_TIMEOUT = timedelta(minutes=10)

#: Phase 15: an offer's email may be sent again from these outcomes (``no_email`` once an
#: address has been added to the customer).
RESENDABLE_EMAIL = ("failed", "no_email")


def prepare_resend(
    db: Session, offer: QuoteOffer, *, actor: User | None, now: datetime | None = None
) -> QuoteOffer:
    """Claim an offer's quote-sent email for one more send (Phase 15). The caller commits, then
    calls ``send_email`` -- the same decide / send / record seam, never inside a retried unit.

    Only an offer still waiting for an answer (``sent`` and answerable), whose email
    ``failed`` or found no address (and the customer now has one). The claim is a conditional
    update to ``resending``, so two staff pressing Resend at once send once: the second gets a
    conflict. Audited ``quote.email_resent``.
    """
    now = now or utcnow()
    if offer.status != "sent" or closed_reason(db, offer) is not None:
        raise ConflictError("Only a quote still waiting for the customer's answer is re-emailed.")
    previous = offer.email_status
    stale_claim = previous == "resending" and (
        offer.updated_at is None or offer.updated_at < now - RESEND_CLAIM_TIMEOUT
    )
    if previous == "resending" and not stale_claim:
        raise ConflictError("This quote email is already being sent again.")
    if previous not in RESENDABLE_EMAIL and not stale_claim:
        raise ConflictError("Only a quote email that failed or had no address is sent again.")
    if previous == "no_email":
        customer = db.get(Customer, offer.customer_id) if offer.customer_id else None
        address = (
            consent_service.normalized_address_for(customer, ConsentChannel.EMAIL)
            if customer
            else None
        )
        if not address:
            raise ConflictError(
                "The customer still has no email address. Add one to the customer first."
            )
    condition = [QuoteOffer.id == offer.id, QuoteOffer.email_status == previous]
    if stale_claim:
        # Taking over a claim abandoned mid-send (a process that died): only if nobody else
        # took it over first, which the unchanged timestamp proves.
        condition.append(QuoteOffer.updated_at == offer.updated_at)
    changed = db.execute(
        update(QuoteOffer)
        .where(*condition)
        .values(email_status="resending", updated_at=now)
        .execution_options(synchronize_session=False)
    ).rowcount
    if changed != 1:
        raise ConflictError("This quote email is already being sent again.")
    db.refresh(offer)
    audit_service.record_audit(
        db,
        action="quote.email_resent",
        entity_type="quote_offer",
        entity_id=offer.id,
        summary=f"Sent the quote v{version_number(offer)} email again (was {previous})",
        actor=actor,
        detail={"shipment_id": offer.shipment_id, "previous_email_status": previous},
    )
    return offer


# --- Accepted, not invoiced (Phase 15) -----------------------------------------------------------


def accepted_not_invoiced(db: Session, *, limit: int = 200) -> tuple[list[tuple], int]:
    """Each shipment's latest accepted offer, when the shipment has no live (unvoided)
    customer invoice and is not cancelled: ``(rows, total)``, newest first. Each row is
    ``(offer, shipment public id, customer name, master id)``, read in one joined query with
    the limit in SQL; ``total`` is the true count. Read-only: staff are prompted to issue the
    invoice through the existing flow; nothing here issues one (stand-in: acceptance records
    only)."""
    from sqlalchemy import and_, func, or_  # noqa: PLC0415
    from sqlalchemy.orm import aliased  # noqa: PLC0415

    from app.core.enums import BookingState  # noqa: PLC0415
    from app.models import CustomerInvoice  # noqa: PLC0415

    newer = aliased(QuoteOffer)
    live_invoice = (
        select(CustomerInvoice.id)
        .where(
            CustomerInvoice.shipment_id == QuoteOffer.shipment_id,
            CustomerInvoice.status != "void",
        )
        .exists()
    )
    newer_accepted = (
        select(newer.id)
        .where(
            newer.shipment_id == QuoteOffer.shipment_id,
            newer.status == "accepted",
            or_(
                newer.responded_at > QuoteOffer.responded_at,
                and_(newer.responded_at == QuoteOffer.responded_at, newer.id > QuoteOffer.id),
            ),
        )
        .exists()
    )
    conditions = (
        QuoteOffer.status == "accepted",
        Shipment.booking_state != BookingState.CANCELLED,
        ~live_invoice,
        ~newer_accepted,
        QuoteOffer.quote_version_id.not_in(_deleted_versions()),
    )
    base = select(QuoteOffer.id).join(Shipment, Shipment.id == QuoteOffer.shipment_id)
    total = db.scalar(select(func.count()).select_from(base.where(*conditions).subquery())) or 0
    rows = db.execute(
        select(QuoteOffer, Shipment.public_id, Customer.full_name, QuoteVersion.consolidation_id)
        .join(Shipment, Shipment.id == QuoteOffer.shipment_id)
        .outerjoin(Customer, Customer.id == Shipment.customer_id)
        .outerjoin(QuoteVersion, QuoteVersion.id == QuoteOffer.quote_version_id)
        .where(*conditions)
        .order_by(QuoteOffer.responded_at.desc(), QuoteOffer.id.desc())
        .limit(limit)
    ).all()
    return [tuple(row) for row in rows], int(total)


def latest_accepted(db: Session, shipment_id: int) -> QuoteOffer | None:
    return db.scalar(
        select(QuoteOffer)
        .where(QuoteOffer.shipment_id == shipment_id, QuoteOffer.status == "accepted")
        .order_by(QuoteOffer.responded_at.desc(), QuoteOffer.id.desc())
        .limit(1)
    )


# --- The customer's answer -----------------------------------------------------------------------


#: What the customer is told when an answer is refused. Customer-safe: no staff reason.
CLOSED_MESSAGES = {
    "accepted": "This quote has already been answered.",
    "declined": "This quote has already been answered.",
    "withdrawn": "Solaris Express withdrew this quote.",
    "replaced": "This quote has been replaced by a newer one.",
    "updating": (
        "Solaris Express is updating this quote. You can answer once the new quote is sent."
    ),
    "expired": (
        "This quote has expired because the rates changed. Solaris Express will send you a "
        "new quote."
    ),
}


def _answer(
    db: Session,
    offer: QuoteOffer,
    identity: CustomerIdentity,
    *,
    status: str,
    decline_reason: str | None,
    now: datetime,
) -> QuoteOffer:
    reason = closed_reason(db, offer)
    if reason is not None:
        raise ConflictError(CLOSED_MESSAGES[reason], detail={"status": reason})
    shipment = db.get(Shipment, offer.shipment_id)
    changed = db.execute(
        update(QuoteOffer)
        .where(QuoteOffer.id == offer.id, QuoteOffer.status == "sent")
        .values(
            status=status,
            responded_at=now,
            responded_identity_id=identity.id,
            decline_reason=decline_reason,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    ).rowcount
    if changed != 1:
        raise ConflictError("This quote is no longer open for an answer.")
    db.refresh(offer)
    action = "quote.accepted" if status == "accepted" else "quote.declined"
    audit_service.record_audit(
        db,
        action=action,
        entity_type="quote_offer",
        entity_id=offer.id,
        summary=(
            f"The customer {'accepted' if status == 'accepted' else 'declined'} quote "
            f"v{version_number(offer)} for {shipment.public_id}"
        ),
        actor_label=f"customer_account:{identity.public_id}",
        detail={
            "shipment_id": offer.shipment_id,
            "quote_version_id": offer.quote_version_id,
            "account": identity.public_id,
            "decline_reason": decline_reason,
        },
    )
    return offer


def accept(
    db: Session, offer: QuoteOffer, identity: CustomerIdentity, *, now: datetime | None = None
) -> QuoteOffer:
    """Accept the offer and, in the same unit, prepare its invoice as a draft (owner
    decision 9a, 2026-10-21; ``invoice_draft_service.create_for_acceptance``)."""
    from app.services import invoice_draft_service  # noqa: PLC0415

    now = now or utcnow()
    answered = _answer(db, offer, identity, status="accepted", decline_reason=None, now=now)
    invoice_draft_service.create_for_acceptance(db, answered, identity, now=now)
    return answered


def decline(
    db: Session,
    offer: QuoteOffer,
    identity: CustomerIdentity,
    *,
    reason: str | None,
    now: datetime | None = None,
) -> QuoteOffer:
    if reason is not None and not isinstance(reason, str):
        raise ValidationError("That request could not be read.", field="reason")
    reason = " ".join((reason or "").split()) or None
    if reason is not None and len(reason) > REASON_MAX:
        raise ValidationError(f"At most {REASON_MAX} characters.", field="reason")
    return _answer(
        db, offer, identity, status="declined", decline_reason=reason, now=now or utcnow()
    )
