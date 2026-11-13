"""Finance: customer invoices, payments, vendor bills, actual cost, month close (Phase 13E).

New tables only; no existing table is altered (DEC-0181).

* ``finance_settings`` -- one row: invoice due days and the invoice tax status shown while
  D-11 is open. Customer payments are CAD only until the owner decides how a VND payment
  is converted.
* ``customer_invoices`` / ``customer_invoice_lines`` -- what a customer owes, issued from a
  **finalised** quote version and numbered ``INV-000001`` at issue. Revenue only: the lines
  are the quote's customer lines, never its cost. Immutable once issued; a mistake is a void
  (with a reason) and a new invoice.
* ``customer_payments`` -- money received (``payment``, receipt ``RCT-000001``) or returned
  (``refund``, against a payment). CAD only by default. No credit: a payment may not exceed
  the balance, and nothing is kept on account.
* ``vendor_invoices`` / ``vendor_invoice_lines`` -- the vendor's actual bill for a master
  (``VB-000001``), in VND or CAD, beside the cost the engine expected when it was entered;
  the variance needs a reason before approval.
* ``cost_allocations`` -- the approved bill split onto the master's shipments: base freight
  and the piece fee by chargeable-weight share, each surcharge line by the engine's own split
  for that fee, anything else by weight share.
* ``period_closes`` -- a reporting month closed at M+7 with its figures frozen, and any
  audited reopening.

**Internal**, except an invoice's and a receipt's customer document, which is served through
its own allowlisted schema (``schemas/finance.py``: ``InvoiceDocumentOut``) and carries no
cost, margin, exchange rate or vendor name.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class FinanceSettings(Base):
    __tablename__ = "finance_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: Days from issue to due date. 0 = due on issue (D-10 open: no payment gate either way).
    invoice_due_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Printed on every invoice while D-11 (tax on invoices) is open.
    tax_status: Mapped[str] = mapped_column(String(30), nullable=False, default="review_pending")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class CustomerInvoice(Base):
    __tablename__ = "customer_invoices"
    __table_args__ = (
        # One live invoice per shipment: a second needs the first voided.
        Index(
            "uq_customer_invoices_live_shipment",
            "shipment_id",
            unique=True,
            sqlite_where=text("status != 'void'"),
            postgresql_where=text("status != 'void'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
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
    consolidation_id: Mapped[int | None] = mapped_column(
        ForeignKey("consolidations.id", ondelete="SET NULL"), nullable=True
    )
    #: issued | partially_paid | paid | void
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="issued")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CAD")
    subtotal_cad: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    #: None while the tax decision is open (D-11); no tax is computed.
    tax_cad: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    tax_status: Mapped[str] = mapped_column(String(30), nullable=False)
    total_cad: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    paid_cad: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    #: Management revenue month (hand-in in Vietnam), ``YYYY-MM``; see ``period_month_for``.
    period_month: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    #: True when the hand-in month was already closed, so the invoice was booked in the
    #: first open month instead (a next-month adjustment, never a silent edit).
    is_adjustment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: The customer's name, reference and the service as printed, frozen at issue.
    document_json: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    issued_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    due_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    void_reason: Mapped[str | None] = mapped_column(String(400), nullable=True)

    lines: Mapped[list[CustomerInvoiceLine]] = relationship(
        order_by="CustomerInvoiceLine.sequence", cascade="all, delete-orphan"
    )


class CustomerInvoiceLine(Base):
    __tablename__ = "customer_invoice_lines"
    __table_args__ = (
        UniqueConstraint("invoice_id", "sequence", name="uq_customer_invoice_lines_sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("customer_invoices.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    amount_cad: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


class CustomerPayment(Base):
    __tablename__ = "customer_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("customer_invoices.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    #: payment | refund
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    #: ``RCT-000001`` for a payment; a refund carries none.
    receipt_public_id: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True)
    #: The payment a refund returns money against.
    refund_of_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_payments.id", ondelete="RESTRICT"), nullable=True
    )
    amount_cad: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CAD")
    #: cash | bank_transfer | e_transfer | card | other
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(String(400), nullable=True)
    #: The day the money moved; cash reporting uses it (handoff section 9).
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    recorded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class PaymentConversion(Base):
    """How a VND payment was put into CAD (OD-66): Vietcombank's selling rate on the invoice
    date. One row per VND payment; the payment's ``amount_cad`` is the converted figure."""

    __tablename__ = "payment_conversions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_id: Mapped[int] = mapped_column(
        ForeignKey("customer_payments.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    amount_vnd: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    #: VND per CAD: the selling rate (Vietcombank's third column) on the invoice date.
    vnd_per_cad: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    fx_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("fx_rate_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    rate_day: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VendorInvoice(Base):
    __tablename__ = "vendor_invoices"
    __table_args__ = (
        Index(
            "uq_vendor_invoices_live_consolidation",
            "consolidation_id",
            unique=True,
            sqlite_where=text("status != 'void'"),
            postgresql_where=text("status != 'void'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    consolidation_id: Mapped[int] = mapped_column(
        ForeignKey("consolidations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    vendor_bill_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    billed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    #: VND | CAD. A CAD bill is taken as CAD and never converted twice.
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    #: entered | approved | paid | void
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="entered")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    #: VND per CAD used to put a VND bill into CAD, frozen at entry: Vietcombank's middle
    #: (transfer, second column) rate on the bill date (OD-67). Named for its first use.
    fx_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("fx_rate_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    fx_cash_buy_vnd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    total_cad: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    #: What the engine expected for the whole master when the bill was entered.
    expected_vnd: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    expected_cad: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    expected_json: Mapped[str] = mapped_column(Text, nullable=False)
    variance_cad: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    variance_reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    period_month: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    is_adjustment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    entered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    entered_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paid_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(400), nullable=True)

    lines: Mapped[list[VendorInvoiceLine]] = relationship(
        order_by="VendorInvoiceLine.sequence", cascade="all, delete-orphan"
    )


class VendorInvoiceLine(Base):
    __tablename__ = "vendor_invoice_lines"
    __table_args__ = (
        UniqueConstraint("vendor_invoice_id", "sequence", name="uq_vendor_invoice_lines_sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_invoice_id: Mapped[int] = mapped_column(
        ForeignKey("vendor_invoices.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    #: base | piece_fee | surcharge | other
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    #: The engine's fee instance key for a surcharge line, so it splits like the estimate.
    fee_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)


class CostAllocation(Base):
    __tablename__ = "cost_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_invoice_id: Mapped[int] = mapped_column(
        ForeignKey("vendor_invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vendor_invoice_line_id: Mapped[int] = mapped_column(
        ForeignKey("vendor_invoice_lines.id", ondelete="CASCADE"), nullable=False
    )
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount_cad: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


class PeriodClose(Base):
    __tablename__ = "period_closes"
    __table_args__ = (UniqueConstraint("month", "version", name="uq_period_closes_month_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    closed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    closed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: The month's profitability figures as they stood at close.
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reopened_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reopen_reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
