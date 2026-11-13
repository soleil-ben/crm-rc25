"""Finance schemas (Phase 13E).

Two kinds, kept apart on purpose:

* **Staff** schemas (``*Out``) -- returned only by staff routes behind the financial
  permissions; the vendor-bill and profitability ones also need ``tariff:read`` because they
  carry vendor cost.
* **Customer documents** (``InvoiceDocumentOut``, ``ReceiptDocumentOut``) -- the invoice and
  the receipt as a customer sees them: revenue only, an explicit allowlist, ``extra="forbid"``
  so a cost field cannot be added by accident. No cost, margin, exchange rate, vendor name,
  master reference or sibling shipment.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FinanceModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class FinanceSettingsOut(FinanceModel):
    invoice_due_days: int
    tax_status: str
    updated_at: datetime


class FinanceSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_due_days: int | None = Field(default=None, ge=0, le=365)


class InvoiceLineOut(FinanceModel):
    sequence: int
    description: str
    quantity: Decimal | None
    unit: str | None
    #: Before tax on an invoice issued with the Solaris Invoicing layout (DEC-0235); as entered
    #: on an older one.
    amount_cad: Decimal
    #: DEC-0235 (``tax_layout: invoicing_v1`` only, else None): the Rate column (net / qty, 4
    #: decimals), the line's tax, its all-in amount and its TAX column ("HST ON", "GST", ...).
    unit_price_cad: Decimal | None = None
    tax_cad: Decimal | None = None
    gross_cad: Decimal | None = None
    tax_code: str | None = None


class TaxRowOut(FinanceModel):
    """A summary tax row of the Solaris Invoicing layout: "HST ON @ 13%", "GST @ 0%"."""

    label: str
    tax_cad: Decimal


class PaymentOut(FinanceModel):
    id: int
    kind: str
    receipt_public_id: str | None
    refund_of_payment_id: int | None
    amount_cad: Decimal
    currency: str
    method: str
    reference: str | None
    note: str | None
    received_at: datetime
    recorded_at: datetime


class InvoiceOut(FinanceModel):
    id: int
    public_id: str
    shipment_id: int
    shipment_reference: str | None
    customer_id: int
    customer_name: str | None
    customer_reference: str | None
    quote_version_id: int
    consolidation_id: int | None
    status: str
    currency: str
    subtotal_cad: Decimal
    tax_cad: Decimal | None
    tax_status: str
    total_cad: Decimal
    paid_cad: Decimal
    balance_cad: Decimal
    period_month: str
    is_adjustment: bool
    issued_at: datetime
    due_at: datetime
    voided_at: datetime | None
    void_reason: str | None


class InvoiceDetailOut(InvoiceOut):
    lines: list[InvoiceLineOut]
    payments: list[PaymentOut]
    #: ``invoicing_v1`` for an invoice issued with per-line GST/HST (DEC-0235), else None.
    tax_layout: str | None = None
    tax_rows: list[TaxRowOut] | None = None


class InvoiceListOut(FinanceModel):
    items: list[InvoiceOut]
    total: int


class IssueInvoiceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: GST/HST, chosen by staff per invoice (OD-64): 0, 5 or 13.
    tax_rate_percent: int = Field(default=0)


class PaymentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: CAD payments give this; VND payments give ``amount_vnd`` instead (OD-66).
    amount_cad: Decimal | None = Field(default=None, gt=0)
    amount_vnd: Decimal | None = Field(default=None, gt=0)
    currency: str = Field(default="CAD", max_length=3)
    method: str = Field(max_length=20)
    reference: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=400)
    received_at: datetime | None = None


class RefundIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_cad: Decimal = Field(gt=0)
    reason: str = Field(min_length=1, max_length=400)
    method: str | None = Field(default=None, max_length=20)
    reference: str | None = Field(default=None, max_length=120)


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=400)


# --- Customer documents (allowlisted, revenue only) ----------------------------------------


class InvoiceDocumentLineOut(FinanceModel):
    description: str
    quantity: Decimal | None
    unit: str | None
    amount_cad: Decimal
    #: The Solaris Invoicing layout only (DEC-0235): Rate, the line's tax, all-in, TAX column.
    unit_price_cad: Decimal | None = None
    tax_cad: Decimal | None = None
    gross_cad: Decimal | None = None
    tax_code: str | None = None


class InvoiceDocumentOut(FinanceModel):
    company_name: str
    company_trade_name: str
    company_business_number: str
    company_address: str
    company_email: str | None = None
    invoice_number: str
    status: str
    issued_at: datetime
    due_at: datetime
    customer_name: str | None
    customer_reference: str | None
    shipment_reference: str | None
    service: str | None
    currency: str
    #: Owner decision 9a: printed from the draft the invoice was sent from, when there was one.
    bill_to_name: str | None = None
    bill_to_address: str | None = None
    purchase_order_reference: str | None = None
    invoice_notes: str | None = None
    lines: list[InvoiceDocumentLineOut]
    subtotal_cad: Decimal
    tax_cad: Decimal | None
    tax_status: str
    #: Owner, 2026-10-22: ``included`` when the line amounts include the GST/HST (the total is
    #: their sum, the tax backed out), else ``added``; and the sentence printed when included.
    tax_mode: str = "added"
    tax_included_note: str | None = None
    #: Review, 2026-10-24: "HST" / "GST" from the province table, else "GST/HST"; and the tax
    #: row as printed ("HST 13 %", "Zero-rated (0 %)").
    tax_label: str = "GST/HST"
    tax_line_label: str | None = None
    total_cad: Decimal
    paid_cad: Decimal
    balance_cad: Decimal
    #: DEC-0235: ``invoicing_v1`` (per-line GST/HST) or None (an older invoice); the summary
    #: rows; "Due on receipt" / "Net N days"; how to pay.
    tax_layout: str | None = None
    tax_rows: list[TaxRowOut] | None = None
    payment_terms: str | None = None
    payment_etransfer: str | None = None
    payment_wire: str | None = None


class ReceiptDocumentOut(FinanceModel):
    company_name: str
    company_trade_name: str
    company_business_number: str
    company_address: str
    company_email: str | None = None
    amount_received_vnd: Decimal | None
    conversion_vnd_per_cad: Decimal | None
    receipt_number: str
    invoice_number: str
    received_at: datetime
    amount_cad: Decimal
    method: str
    reference: str | None
    customer_name: str | None
    customer_reference: str | None
    shipment_reference: str | None
    invoice_total_cad: Decimal
    balance_cad: Decimal


# --- Reports -------------------------------------------------------------------------------


class ReportOut(FinanceModel):
    """A report payload as the service built it (internal staff report)."""

    report: dict[str, Any]


class PeriodOut(FinanceModel):
    month: str
    state: str
    lock_date: datetime
    closed_at: datetime | None
    version: int | None
    reopened_at: datetime | None
    reopen_reason: str | None


class AcceptedNotInvoicedOut(FinanceModel):
    """Phase 15: a quote the customer accepted whose shipment has no live invoice yet. Staff
    issue the invoice through the existing flow (nothing is issued automatically). Revenue
    only: the accepted total is what the customer agreed to pay."""

    offer_id: int
    shipment_id: int
    shipment_reference: str | None
    customer_name: str | None
    version: int | None
    accepted_at: datetime | None
    total_cad: str | None
    consolidation_id: int | None
    superseded_by_version: int | None
    #: Owner decision 9a: the draft invoice prepared on acceptance, when there is one.
    invoice_draft_id: int | None = None
    invoice_draft_revision: int | None = None


class AcceptedNotInvoicedListOut(FinanceModel):
    items: list[AcceptedNotInvoicedOut]
    total: int


# --- The shipment page's money summary (RC-UAT-25 item 8, Ben 2026-10-25) ----------------


class SummaryMasterOut(BaseModel):
    id: int
    public_id: str
    state: str
    #: Booked or completed with no open unlock: items and fee lines cannot change.
    locked: bool


class SummaryQuoteOut(BaseModel):
    id: int
    version: int
    status: str
    finalized_at: datetime | None
    total_revenue_cad: Decimal | None
    #: ``None`` for a role without ``tariff:read`` (vendor cost), whatever is recorded.
    allocated_cost_cad: Decimal | None
    gross_profit_cad: Decimal | None
    expired: bool


class SummaryInvoiceOut(BaseModel):
    id: int
    public_id: str
    status: str
    total_cad: Decimal
    paid_cad: Decimal
    balance_cad: Decimal
    issued_at: datetime | None


class SummaryDraftOut(BaseModel):
    id: int
    status: str
    revision: int


class ShipmentFinancialSummaryOut(BaseModel):
    shipment_id: int
    master: SummaryMasterOut | None
    #: The newest quote version still listed (draft, finalised or superseded).
    quote: SummaryQuoteOut | None
    #: The newest finalised version (the one Issue invoice bills), when there is one.
    finalised_quote: SummaryQuoteOut | None
    invoice: SummaryInvoiceOut | None
    draft_invoice: SummaryDraftOut | None
    #: add_to_master | price | finalise_quote | requote | issue_invoice | review_draft |
    #: open_invoice
    next_step: str
    #: What Issue invoice would answer right now, word for word, when it would refuse.
    invoice_blocked_reason: str | None
    invoice_blocked_code: str | None
    cost_visible: bool
    can_issue_invoice: bool
    can_price: bool
