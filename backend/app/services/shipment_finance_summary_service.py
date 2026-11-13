"""The shipment page's money summary and next step (RC-UAT-25 item 8, Ben 2026-10-25).

Straight after booking, staff want to see what the shipment is quoted at (and what it costs,
when their role may see vendor cost) and to invoice the client without hunting for the
master's workspace. This module reads -- it never writes -- and answers:

* the master the shipment rides in (pricing needs one), and whether its edits are locked;
* the newest quote version still listed (an Admin's soft-deleted ones are not), with its
  revenue; its vendor cost and margin only for a role with ``tariff:read``, the same rule
  as the quote and vendor-bill screens (Marketing has no ``financial:read`` and never gets
  here; the read-only manager sees revenue only);
* the live issued invoice, else the live draft invoice prepared when the customer accepted;
* the single next step, and -- when Issue invoice would be refused -- the refusal Issue
  invoice itself returns (``finance_service.invoiceable_version``).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.permissions import Permission, permissions_for
from app.models import Consolidation, QuoteVersion, Shipment
from app.services import (
    consolidation_service,
    finance_service,
    invoice_draft_service,
    master_lock_service,
    pricing_service,
    quote_deletion_service,
    quote_expiry_service,
)
from app.services.errors import ConflictError, ValidationError

P = Permission


def recorded_currency(value: str | None) -> str | None:
    """The recorded-amounts currency (RC-UAT-25 item 7, Ben 2026-10-25): three ASCII letters,
    upper-cased; blank is None (Unknown). Before this, any 1-3 characters were stored as
    typed ("CA", "$"), which no currency formatter accepts, and the Financials tab failed."""
    cleaned = " ".join((value or "").split())
    if not cleaned:
        return None
    if len(cleaned) != 3 or not (cleaned.isascii() and cleaned.isalpha()):
        raise ValidationError("Use a three-letter currency code such as CAD.", field="currency")
    return cleaned.upper()


def _quote(db: Session, version: QuoteVersion, *, cost_visible: bool) -> dict[str, Any]:
    return {
        "id": version.id,
        "version": version.version,
        "status": version.status,
        "finalized_at": version.finalized_at,
        "total_revenue_cad": version.total_revenue_cad,
        "allocated_cost_cad": version.allocated_cost_cad if cost_visible else None,
        "gross_profit_cad": version.gross_profit_cad if cost_visible else None,
        "expired": quote_expiry_service.is_expired(db, version.id),
    }


def summary(db: Session, shipment: Shipment, *, role: str) -> dict[str, Any]:
    granted = permissions_for(role)
    cost_visible = P.TARIFF_READ in granted
    can_issue = P.FINANCIAL_WRITE in granted
    can_price = {P.TARIFF_READ, P.FINANCIAL_WRITE} <= granted

    membership = consolidation_service.active_membership_for_shipment(db, shipment.id)
    master = db.get(Consolidation, membership.consolidation_id) if membership else None
    master_out = None
    if master is not None:
        master_out = {
            "id": master.id,
            "public_id": master.public_id,
            "state": master.state,
            "locked": master_lock_service.lock_view(db, master)["locked"],
        }

    deleted = quote_deletion_service.deleted_version_ids(db, shipment.id)
    versions = [v for v in pricing_service.list_versions(db, shipment.id) if v.id not in deleted]
    latest = versions[-1] if versions else None
    finalised = next((v for v in reversed(versions) if v.status == "finalized"), None)

    invoice = finance_service.live_invoice(db, shipment.id)
    draft = invoice_draft_service.live_for_shipment(db, shipment.id)

    blocked_reason: str | None = None
    blocked_code: str | None = None
    if invoice is None and draft is None:
        try:
            finance_service.invoiceable_version(db, shipment)
        except ConflictError as refusal:
            blocked_reason = refusal.message
            blocked_code = refusal.detail.get("code")

    if invoice is not None:
        next_step = "open_invoice"
    elif draft is not None:
        next_step = "review_draft"
    elif blocked_reason is None:
        next_step = "issue_invoice"
    elif blocked_code in {"quote_expired", "quote_deleted"}:
        next_step = "requote"
    elif latest is not None and latest.status == "draft":
        next_step = "finalise_quote"
    elif master is None:
        next_step = "add_to_master"
    else:
        next_step = "price"

    return {
        "shipment_id": shipment.id,
        "master": master_out,
        "quote": _quote(db, latest, cost_visible=cost_visible) if latest else None,
        "finalised_quote": (
            _quote(db, finalised, cost_visible=cost_visible) if finalised else None
        ),
        "invoice": (
            {
                "id": invoice.id,
                "public_id": invoice.public_id,
                "status": invoice.status,
                "total_cad": invoice.total_cad,
                "paid_cad": invoice.paid_cad,
                "balance_cad": finance_service.balance(invoice),
                "issued_at": invoice.issued_at,
            }
            if invoice
            else None
        ),
        "draft_invoice": (
            {"id": draft.id, "status": draft.status, "revision": draft.revision} if draft else None
        ),
        "next_step": next_step,
        "invoice_blocked_reason": blocked_reason,
        "invoice_blocked_code": blocked_code,
        "cost_visible": cost_visible,
        "can_issue_invoice": can_issue,
        "can_price": can_price,
    }
