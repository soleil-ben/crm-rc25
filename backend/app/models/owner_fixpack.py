"""Master edit lock, quote expiry and draft invoices (owner answers 8, 9 and 9a, 2026-10-21).

Three new tables; nothing existing is altered (DEC-0181). Revision ``d4f7a2c9e1b8``.

* ``master_edit_unlocks`` -- after a master is booked its members' items and fee lines are
  locked (owner decision 8). Admin may open a temporary unlock with a reason; the row is
  closed (``relocked_at``) by hand (Admin or Operations) or automatically when a quote for a
  member shipment is finalised after the unlock. At most one open unlock per master.
* ``quote_expiries`` -- a finalised quote version that expired because a new tariff version
  became active while the shipment's goods had not yet been received (owner decision 9).
  One row per expired version. The version itself keeps its status; an offer that was
  ``sent`` or ``accepted`` becomes ``expired`` (``quote_offers.status`` is a string).
* ``invoice_drafts`` -- the invoice prepared automatically, as a draft, when the customer
  accepts a quote (owner decision 9a). Staff edit the bill-to details, reference, notes,
  GST/HST and the lines; ``revision`` guards against two people saving over each other.
  **Send** issues the real numbered invoice (``customer_invoices``) from the saved draft;
  no ``INV-`` number exists until then. At most one live draft per shipment.

Internal. The customer sees a draft only as the PDF staff send, and an invoice only by its
document; nothing here is read by the public or Customer Account routers except the
offer's ``expired`` status, which the account words neutrally.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

INVOICE_DRAFT_STATUSES = ("draft", "issued", "discarded")


class MasterEditUnlock(Base):
    """A temporary, audited unlock of a booked master's items and fee lines (Admin)."""

    __tablename__ = "master_edit_unlocks"
    __table_args__ = (
        # One open unlock per master: unlocking twice is refused, relocking closes it.
        Index(
            "uq_master_edit_unlocks_open_consolidation",
            "consolidation_id",
            unique=True,
            sqlite_where=text("relocked_at IS NULL"),
            postgresql_where=text("relocked_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    consolidation_id: Mapped[int] = mapped_column(
        ForeignKey("consolidations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unlocked_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Required, at most 400 characters.
    reason: Mapped[str] = mapped_column(String(400), nullable=False)
    unlocked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    relocked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    relocked_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Staff text when locked again by hand; ``quote finalised (vN, SHIPMENT)`` when the
    #: lock came back automatically.
    relock_reason: Mapped[str | None] = mapped_column(String(400), nullable=True)

    @property
    def is_open(self) -> bool:
        return self.relocked_at is None


class QuoteExpiry(Base):
    """A finalised quote version that expired on a new tariff version (owner decision 9)."""

    __tablename__ = "quote_expiries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: One expiry per version, ever.
    quote_version_id: Mapped[int] = mapped_column(
        ForeignKey("quote_versions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The tariff version whose activation expired the quote.
    tariff_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("tariff_versions.id", ondelete="SET NULL"), nullable=True
    )
    #: The offer of this version, when one was sent, and what its status was before.
    offer_id: Mapped[int | None] = mapped_column(
        ForeignKey("quote_offers.id", ondelete="SET NULL"), nullable=True
    )
    previous_offer_status: Mapped[str | None] = mapped_column(String(12), nullable=True)
    #: The draft invoice withdrawn because of the expiry, when there was one.
    invoice_draft_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoice_drafts.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str] = mapped_column(String(400), nullable=False)
    expired_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class InvoiceDraft(Base):
    """The invoice prepared when a quote is accepted, editable until staff send it."""

    __tablename__ = "invoice_drafts"
    __table_args__ = (
        # One live draft per shipment: a new acceptance discards the older draft first.
        Index(
            "uq_invoice_drafts_live_shipment",
            "shipment_id",
            unique=True,
            sqlite_where=text("status = 'draft'"),
            postgresql_where=text("status = 'draft'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    #: Who pays: the shipment's payer when one is recorded, else its customer.
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quote_version_id: Mapped[int] = mapped_column(
        ForeignKey("quote_versions.id", ondelete="RESTRICT"), nullable=False
    )
    offer_id: Mapped[int | None] = mapped_column(
        ForeignKey("quote_offers.id", ondelete="SET NULL"), nullable=True
    )
    #: draft | issued | discarded
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="draft")
    bill_to_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bill_to_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The customer's own reference or purchase-order number, printed on the invoice.
    customer_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: GST/HST chosen by staff: 0, 5 or 13 (OD-64).
    tax_rate_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: ``[{"description": str, "amount_cad": "0.00"}]``: revenue lines only.
    lines_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    #: The accepted quote's total before tax, frozen at creation, to tell an edited total.
    quote_total_cad: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    #: Why the lines' total differs from the accepted quote; required when it does.
    total_change_reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    #: Optimistic concurrency: every save and the send name the revision they read.
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: The Customer Account identity whose acceptance created the draft.
    created_by_identity_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_identities.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    issued_invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_invoices.id", ondelete="SET NULL"), nullable=True
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    discarded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    discard_reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    #: What became of the invoice email after Send: sent | recorded | no_email | failed.
    email_status: Mapped[str | None] = mapped_column(String(20), nullable=True)


#: How a draft's GST/HST relates to its line amounts (owner, 2026-10-22).
INVOICE_TAX_MODES = ("included", "added")


class InvoiceDraftTax(Base):
    """A draft invoice's GST/HST mode and staff confirmation (owner answer, 2026-10-22).

    Revision ``e6b1c4a8d2f3``; one row per draft, created with the draft from now on. Rates
    are usually all-in: in mode ``included`` the tax is backed out of the lines' total
    (``tax = round_half_up(total * rate / (100 + rate))``, ``subtotal = total - tax``); in mode
    ``added`` it is charged on top (the RC-UAT-18 behaviour). ``rate_percent`` mirrors
    ``invoice_drafts.tax_rate_percent`` (the source of truth), written in the same unit.

    **Confirmation** holds for one saved revision: ``confirmed_revision`` equal to the draft's
    ``revision`` means staff ticked "I have checked the GST/HST on this invoice" for exactly
    what is saved. Any save that changes the draft bumps its revision, so a confirmation never
    outlives a change. A draft with no row reads as mode ``added`` at its rate, unconfirmed.
    """

    __tablename__ = "invoice_draft_tax"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_drafts.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    #: included | added
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    rate_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmed_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
