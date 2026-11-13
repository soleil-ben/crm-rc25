"""Quote offers: a finalised quote sent to the customer, and their answer (Phase 13G).

One new table; nothing existing is altered (DEC-0181).

``quote_offers`` -- one row per finalised quote version that staff sent to the customer
(OD-77, D-08). ``customer_view_json`` is the frozen, **customer-safe** content of the offer:
the Solaris service label, the billable kilograms, the selling rate per kilogram, the base
charge, each customer surcharge line (name and amount), the total and the currency. Nothing
cost-derived is ever written to it: no vendor cost, exchange rate, markup, margin, tariff or
vendor product code, or vendor name. The Customer Account reads only this column.

Status: ``sent`` (open for an answer), ``accepted``, ``declined``, or ``withdrawn`` (by staff,
or because a newer version was finalised). At most one ``sent`` offer per shipment.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

#: ``expired`` since the owner answers of 2026-10-21 (decision 9): a new tariff version became
#: active before the goods were received. A new string value, not a schema change.
OFFER_STATUSES = ("sent", "accepted", "declined", "withdrawn", "expired")


class QuoteOffer(Base):
    """A finalised quote version offered to the customer."""

    __tablename__ = "quote_offers"
    __table_args__ = (
        # One open offer per shipment: a newer one withdraws the older first.
        Index(
            "uq_quote_offers_open_shipment",
            "shipment_id",
            unique=True,
            sqlite_where=text("status = 'sent'"),
            postgresql_where=text("status = 'sent'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: The frozen version offered. One offer per version, ever.
    quote_version_id: Mapped[int] = mapped_column(
        ForeignKey("quote_versions.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: sent | accepted | declined | withdrawn | expired
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="sent")
    #: The customer-safe content, frozen when sent. Never anything cost-derived.
    customer_view_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    sent_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    responded_identity_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_identities.id", ondelete="SET NULL"), nullable=True
    )
    decline_reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    withdrawn_reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: Why it was withdrawn, as a code the Customer Account may word: staff | superseded |
    #: customer_merged | customer_changed. The free-text reason stays staff-only.
    withdrawn_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: Set when a newer version was finalised after the customer accepted this one: the
    #: customer accepted an earlier price, and staff must see it (13G review).
    superseded_by_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: What became of the quote-sent email, recorded after the send: sent (the capture
    #: transport took it), recorded (the null transport noted it), no_email, suppressed,
    #: failed; resending (Phase 15: claimed for a staff resend, replaced by the outcome; a
    #: claim older than 10 minutes may be taken over); skipped (the offer was answered or
    #: withdrawn before the email went, so nothing was sent).
    #: Null until decided. No address and no body are stored.
    email_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
