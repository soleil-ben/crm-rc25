"""GST/HST by route and the costume-jewellery customer price (owner, 2026-10-23; RC-UAT-20).

Three new tables; nothing existing is altered (DEC-0181). Revision ``f7c2d9e3a1b5``.

* ``tax_rates`` -- the GST/HST rate of each Canadian province or territory, by its two-letter
  code (DEC-0227). A **domestic** shipment's draft invoice auto-fills the rate of its
  destination province, included in the price; an international one is zero-rated (0 %, no
  row needed). Seeded by the migration (ON 13 HST; NS 14 HST; NB, NL, PE 15 HST; AB, BC, MB,
  QC, SK, NT, NU, YT 5 GST); Admin edits them on Settings (audited ``tax_rate.update``).
  The code also holds the same defaults, used for a province with no row (a test database
  built with ``create_all`` has no seeded rows; reading never writes).
* ``invoice_draft_tax_route`` -- what a draft invoice's GST/HST was auto-filled from: the
  route band (``international`` / ``domestic`` / ``unknown``), the countries and the
  destination province read from the shipment, and the rate and mode suggested. When the
  route is domestic but the province is unknown, ``rate_required`` is true and the draft has
  **no usable rate** until staff choose one (``rate_chosen_at``); ``invoice_drafts`` keeps
  its non-null ``tax_rate_percent`` (0 as a placeholder that is never shown or sent).
* ``fee_line_manual_prices`` -- the customer price in CAD staff enter for a ``manual_amount``
  fee line (costume jewellery, HCM air row 27; DEC-0228), next to the vendor's VND cost kept in
  ``shipment_fee_lines.manual_unit_price_vnd``. One row per fee line.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TaxRate(Base):
    """The GST/HST rate of one Canadian province or territory (DEC-0227)."""

    __tablename__ = "tax_rates"

    #: Two-letter province or territory code: ON, NS, NB, NL, PE, AB, BC, MB, QC, SK, NT, NU, YT.
    province_code: Mapped[str] = mapped_column(String(2), primary_key=True)
    #: Whole percent (``invoice_drafts.tax_rate_percent`` is an integer).
    rate_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    #: ``HST`` or ``GST``.
    tax_label: Mapped[str] = mapped_column(String(10), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class InvoiceDraftTaxRoute(Base):
    """Where a draft invoice's GST/HST auto-fill came from (DEC-0227). One row per draft."""

    __tablename__ = "invoice_draft_tax_route"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_drafts.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    #: international | domestic | unknown
    route_band: Mapped[str] = mapped_column(String(16), nullable=False)
    origin_country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    destination_country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    #: The destination province code read from the delivery address, or None (unknown).
    destination_province: Mapped[str | None] = mapped_column(String(2), nullable=True)
    #: The rate suggested; None when staff must choose (domestic, province unknown).
    suggested_rate_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suggested_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    #: True when no rate could be suggested: Save needs a rate and Send/Download need a save.
    rate_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rate_chosen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rate_chosen_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FeeLineManualPrice(Base):
    """The customer price (CAD) of a ``manual_amount`` fee line (DEC-0228). One per line."""

    __tablename__ = "fee_line_manual_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fee_line_id: Mapped[int] = mapped_column(
        ForeignKey("shipment_fee_lines.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    customer_price_cad: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
