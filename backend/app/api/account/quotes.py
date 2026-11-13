"""Customer Account: quotes sent by Solaris Express, and the customer's answer (Phase 13G).

``GET  /api/v1/account/quotes``
``GET  /api/v1/account/quotes/{offer_id}``
``POST /api/v1/account/quotes/{offer_id}/accept``
``POST /api/v1/account/quotes/{offer_id}/decline``  (``{"reason": "..."}`` optional)

OD-77 (D-08): staff send the quote; the customer accepts or declines it here. Authorized
exactly like the shipment, profile and notification routes: privacy headers, the account
session (CSRF on the two POSTs, enforced by the session dependency), the rate limit, then the
identity's one active link to a customer (``_authorized_customer``), re-evaluated on every
request. Ownership is in the lookup: an offer of another customer, an unknown one and a
malformed id all give the same 404.

What a customer reads is the offer's frozen **customer view** only -- the Solaris service
name, billable kilograms, the rate per kilogram, the base charge, the surcharges they pay,
the total and the currency. Never a cost, exchange rate, markup, margin, tariff or vendor
code, vendor name, the staff reason for a withdrawal, or the email outcome.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response

from app.api.account.deps import AccountClientKey, AccountDb, CurrentAccountSession
from app.api.account.profile import PROFILE_WRITE_ATTEMPTS, PROFILE_WRITE_WINDOW_SECONDS
from app.api.account.routes import _read_json
from app.api.account.shipments import (
    RATE_LIMIT_MESSAGE,
    _apply_headers,
    _authorized_customer,
    _limit_or_refuse,
)
from app.core.db import run_unit_with_retry
from app.core.security import rate_limiter
from app.models import QuoteOffer
from app.schemas.quote_offers import (
    AccountQuoteDetail,
    AccountQuoteList,
    AccountQuoteSummary,
    AccountQuoteSurcharge,
    QuoteTaxOut,
)
from app.services import quote_offer_service
from app.services.customer_labels import customer_safe_label, vendor_names
from app.services.errors import RateLimitedError, ValidationError

router = APIRouter(tags=["customer-account"])


def _limit_answer(identity_public_id: str) -> None:
    """Accept and decline have their own bucket (the profile's limits, not its allowance),
    so answering a quote never spends the allowance for editing the profile."""
    allowed, retry_after = rate_limiter.check(
        f"account:quote_answer:{identity_public_id}",
        PROFILE_WRITE_ATTEMPTS,
        PROFILE_WRITE_WINDOW_SECONDS,
    )
    if not allowed:
        raise RateLimitedError(RATE_LIMIT_MESSAGE, retry_after=retry_after)


def _customer_language(db, offer: QuoteOffer) -> str:
    from app.models import Customer  # noqa: PLC0415
    from app.services import notification_service  # noqa: PLC0415

    return notification_service.language_for(db, db.get(Customer, offer.customer_id))


def _summary(offer: QuoteOffer, db=None) -> AccountQuoteSummary:
    view = quote_offer_service.customer_view(offer)
    return AccountQuoteSummary(
        id=offer.id,
        shipment_reference=view.get("shipment_reference"),
        version=view.get("version"),
        service=view.get("service"),
        status=offer.status,
        sent_at=offer.sent_at,
        total_cad=view.get("total_cad"),
        currency=view.get("currency") or "CAD",
        # RC-UAT-21 (DEC-0232, P-9 stand-in): the invoice's GST/HST rule, read from the
        # shipment's route when the quote is read.
        tax=_tax(db, offer),
    )


def _tax(db, offer: QuoteOffer) -> QuoteTaxOut | None:
    if db is None:
        return None
    from app.models import Shipment  # noqa: PLC0415
    from app.services import quote_tax_wording  # noqa: PLC0415

    tax = quote_tax_wording.quote_tax(db, db.get(Shipment, offer.shipment_id))
    return QuoteTaxOut(**tax) if tax is not None else None


def _detail(db, offer: QuoteOffer) -> AccountQuoteDetail:
    view = quote_offer_service.customer_view(offer)
    summary = _summary(offer, db)
    closed = quote_offer_service.closed_reason(db, offer)
    # The view is frozen at send time; an offer frozen before the vendor-name rule (owner,
    # 2026-10-21, DEC-0222) is made safe again on the way out.
    names = vendor_names(db)
    language = _customer_language(db, offer)
    return AccountQuoteDetail(
        **summary.model_dump(),
        billable_weight_kg=view.get("billable_weight_kg"),
        rate_per_kg_cad=view.get("rate_per_kg_cad"),
        base_charge_cad=view.get("base_charge_cad"),
        surcharges=[
            AccountQuoteSurcharge(
                name=customer_safe_label(str(s.get("name", "")), names, language=language),
                amount_cad=str(s.get("amount_cad")),
            )
            for s in view.get("surcharges") or []
        ],
        tax_included=bool(view.get("tax_included", False)),
        responded_at=offer.responded_at,
        decline_reason=offer.decline_reason,
        can_answer=closed is None,
        closed_reason=closed,
    )


@router.get("/quotes", response_model=AccountQuoteList, summary="Your quotes")
def list_quotes(
    request: Request,
    response: Response,
    db: AccountDb,
    session: CurrentAccountSession,
    client_key: AccountClientKey,
) -> AccountQuoteList:
    _apply_headers(response)
    identity, _ = session
    _limit_or_refuse(identity.public_id, "quotes")
    customer = _authorized_customer(db, request, identity, "quotes")
    items = [_summary(o, db) for o in quote_offer_service.list_for_customer(db, customer.id)]
    return AccountQuoteList(items=items)


@router.get("/quotes/{offer_id}", response_model=AccountQuoteDetail, summary="One of your quotes")
def quote_detail(
    request: Request,
    response: Response,
    db: AccountDb,
    session: CurrentAccountSession,
    client_key: AccountClientKey,
    offer_id: str,
) -> AccountQuoteDetail:
    _apply_headers(response)
    identity, _ = session
    _limit_or_refuse(identity.public_id, "quote")
    customer = _authorized_customer(db, request, identity, "quote")
    offer = quote_offer_service.owned_offer(db, offer_id, customer.id)
    detail = _detail(db, offer)
    return detail


def _answer(
    db, request: Request, identity, offer_id: str, *, accept: bool, reason: str | None = None
):
    customer = _authorized_customer(db, request, identity, "quote")
    customer_id = customer.id
    identity_id = identity.id
    # End the read transaction: the answer is its own unit, re-run whole on a lock (DEC-0204).
    db.rollback()

    def work():
        from app.models import CustomerIdentity  # noqa: PLC0415

        offer = quote_offer_service.owned_offer(db, offer_id, customer_id)
        who = db.get(CustomerIdentity, identity_id)
        if accept:
            quote_offer_service.accept(db, offer, who)
        else:
            quote_offer_service.decline(db, offer, who, reason=reason)
        return offer.id

    answered = run_unit_with_retry(db, work)
    return _detail(db, quote_offer_service.get(db, answered))


@router.post(
    "/quotes/{offer_id}/accept", response_model=AccountQuoteDetail, summary="Accept a quote"
)
def accept_quote(
    request: Request,
    response: Response,
    db: AccountDb,
    session: CurrentAccountSession,
    client_key: AccountClientKey,
    offer_id: str,
) -> AccountQuoteDetail:
    _apply_headers(response)
    identity, _ = session
    _limit_answer(identity.public_id)
    return _answer(db, request, identity, offer_id, accept=True)


@router.post(
    "/quotes/{offer_id}/decline", response_model=AccountQuoteDetail, summary="Decline a quote"
)
async def decline_quote(
    request: Request,
    response: Response,
    db: AccountDb,
    session: CurrentAccountSession,
    client_key: AccountClientKey,
    offer_id: str,
) -> AccountQuoteDetail:
    _apply_headers(response)
    identity, _ = session
    _limit_answer(identity.public_id)
    payload: dict[str, Any] = {}
    if await request.body():
        payload = await _read_json(request)
    if set(payload) - {"reason"}:
        raise ValidationError("That request could not be read.")
    reason = payload.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ValidationError("That request could not be read.", field="reason")
    return _answer(db, request, identity, offer_id, accept=False, reason=reason or None)
