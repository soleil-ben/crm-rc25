"""Staff quote-offer routes: send a finalised quote to the customer, read the answer (13G).

OD-77 (D-08): staff send; the customer accepts or declines in the Customer Account. Sending
and withdrawing need what finalising a quote needs (Operations and Admin); reading needs what
reading a quote needs. Marketing and the read-only manager can do neither.

The send commits the offer first, then emails the customer through the account email seam
outside any retried unit (null or capture transports only), so a lock never sends twice and
an email fault never undoes the offer. A failed (or address-less) email can be sent again
(Phase 15, ``/resend-email``) through the same seam.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.api.v1.routes.pricing import QuoteReader, QuoteWriter
from app.core.db import run_unit_with_retry
from app.models import Customer, CustomerIdentity, QuoteOffer, QuoteVersion
from app.schemas.quote_offers import QuoteDocumentOut, QuoteOfferOut, WithdrawOfferIn
from app.services import (
    booking_service,
    finance_service,
    quote_deletion_service,
    quote_offer_service,
    quote_tax_wording,
)
from app.services.errors import ConflictError, NotFoundError

router = APIRouter(tags=["quote-offers"])


def offer_out(db, offer: QuoteOffer) -> QuoteOfferOut:
    identity = (
        db.get(CustomerIdentity, offer.responded_identity_id)
        if offer.responded_identity_id
        else None
    )
    return QuoteOfferOut(
        id=offer.id,
        shipment_id=offer.shipment_id,
        quote_version_id=offer.quote_version_id,
        version=quote_offer_service.version_number(offer),
        status=offer.status,
        is_current=quote_offer_service.is_current(db, offer),
        customer_view=quote_offer_service.customer_view(offer),
        sent_at=offer.sent_at,
        sent_by_user_id=offer.sent_by_user_id,
        responded_at=offer.responded_at,
        responded_by=identity.public_id if identity else None,
        decline_reason=offer.decline_reason,
        withdrawn_reason=offer.withdrawn_reason,
        withdrawn_at=offer.withdrawn_at,
        withdrawn_code=offer.withdrawn_code,
        superseded_by_version=offer.superseded_by_version,
        superseded_at=offer.superseded_at,
        email_status=offer.email_status,
    )


@router.get("/shipments/{shipment_id}/quote-offers", response_model=list[QuoteOfferOut])
def list_offers(shipment_id: int, db: DbSession, _user: QuoteReader) -> list[QuoteOfferOut]:
    shipment = booking_service.get_shipment(db, shipment_id)
    # RC-UAT-21 Phase D (DEC-0233): the offer of a soft-deleted version is not listed.
    deleted = quote_deletion_service.deleted_version_ids(db, shipment.id)
    return [
        offer_out(db, o)
        for o in quote_offer_service.list_for_shipment(db, shipment.id)
        if o.quote_version_id not in deleted
    ]


@router.post("/shipments/{shipment_id}/quotes/send", response_model=QuoteOfferOut, status_code=201)
def send_quote(shipment_id: int, db: DbSession, user: QuoteWriter) -> QuoteOfferOut:
    def work():
        shipment = booking_service.get_shipment(db, shipment_id)
        offer = quote_offer_service.send_quote(db, shipment, actor=user)
        return offer.id

    offer_id = run_unit_with_retry(db, work)
    quote_offer_service.send_email(db, offer_id)
    return offer_out(db, quote_offer_service.get(db, offer_id))


@router.post("/quote-offers/{offer_id}/withdraw", response_model=QuoteOfferOut)
def withdraw_offer(
    offer_id: int, payload: WithdrawOfferIn, db: DbSession, user: QuoteWriter
) -> QuoteOfferOut:
    def work():
        offer = quote_offer_service.get(db, offer_id)
        quote_offer_service.withdraw(db, offer, reason=payload.reason, actor=user)
        return offer.id

    run_unit_with_retry(db, work)
    return offer_out(db, quote_offer_service.get(db, offer_id))


@router.post("/quote-offers/{offer_id}/resend-email", response_model=QuoteOfferOut)
def resend_offer_email(offer_id: int, db: DbSession, user: QuoteWriter) -> QuoteOfferOut:
    """Send the quote-sent email again (Phase 15): an unanswered offer whose email failed, or
    found no address and the customer now has one. Same permission as sending. The claim and
    the audit (``quote.email_resent``) commit first; the email goes out after, outside any
    retried unit, and its outcome is recorded on the offer as for the first send."""

    def work():
        offer = quote_offer_service.get(db, offer_id)
        quote_offer_service.prepare_resend(db, offer, actor=user)
        return offer.id

    run_unit_with_retry(db, work)
    quote_offer_service.send_email(db, offer_id)
    return offer_out(db, quote_offer_service.get(db, offer_id))


@router.get("/shipments/{shipment_id}/quotes/{version}/document", response_model=QuoteDocumentOut)
def quote_document(
    shipment_id: int, version: int, db: DbSession, _user: QuoteReader
) -> QuoteDocumentOut:
    """The printable customer quote for one finalised version (Phase 14).

    Built from the same customer-side reader as the offer the customer sees
    (``build_customer_view``) and the company details on every invoice (OD-64): revenue
    only. A draft has no document (409): its figures are not final. A superseded version is
    still printable (it is what the customer was quoted then) and says which version replaced
    it (Phase 14 review).
    """
    shipment = booking_service.get_shipment(db, shipment_id)
    row = db.scalar(
        select(QuoteVersion).where(
            QuoteVersion.shipment_id == shipment.id, QuoteVersion.version == version
        )
    )
    if row is None or quote_deletion_service.is_deleted(db, row.id):
        raise NotFoundError("That quote version does not exist.")
    if row.status not in {"finalized", "superseded"}:
        raise ConflictError("Only a finalised quote has a printable document.")
    superseded_by = (
        db.scalar(
            select(func.min(QuoteVersion.version)).where(
                QuoteVersion.shipment_id == shipment.id,
                QuoteVersion.version > row.version,
                QuoteVersion.status.in_(("finalized", "superseded")),
            )
        )
        if row.status == "superseded"
        else None
    )
    view = quote_offer_service.build_customer_view(shipment, row)
    customer = db.get(Customer, shipment.customer_id)
    return QuoteDocumentOut(
        **finance_service.COMPANY,
        customer_name=customer.full_name if customer else None,
        customer_reference=customer.public_id if customer else None,
        shipment_reference=view["shipment_reference"],
        version=row.version,
        finalized_at=row.finalized_at,
        service=view["service"],
        billable_weight_kg=view["billable_weight_kg"],
        rate_per_kg_cad=view["rate_per_kg_cad"],
        base_charge_cad=view["base_charge_cad"],
        surcharges=view["surcharges"],
        total_cad=view["total_cad"],
        currency=view["currency"],
        tax_included=view["tax_included"],
        status=row.status,
        superseded_by_version=superseded_by,
        # RC-UAT-21 (DEC-0232, P-9 stand-in): the account quote's GST/HST wording.
        tax=quote_tax_wording.quote_tax(db, shipment),
    )
