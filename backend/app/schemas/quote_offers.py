"""Quote offer schemas (Phase 13G).

The staff shape carries the offer's state and its customer view. The Customer Account
shapes are an **allowlist** (``extra="forbid"``): the frozen customer view and the answer,
never a cost, rate source, markup, margin, staff reason for a withdrawal, or email outcome.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QuoteOfferOut(BaseModel):
    """Staff: one offer and what became of it."""

    id: int
    shipment_id: int
    quote_version_id: int
    version: int | None
    status: str
    #: False once a newer version is finalised (the offer can no longer be accepted).
    is_current: bool
    customer_view: dict[str, Any]
    sent_at: datetime
    sent_by_user_id: int | None
    responded_at: datetime | None
    #: The account reference of the identity that answered.
    responded_by: str | None
    decline_reason: str | None
    withdrawn_reason: str | None
    withdrawn_at: datetime | None
    #: staff | superseded | customer_merged | customer_changed
    withdrawn_code: str | None
    #: Set when a newer version was finalised after the customer accepted this one.
    superseded_by_version: int | None
    superseded_at: datetime | None
    email_status: str | None


class WithdrawOfferIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=400)


class AccountQuoteSurcharge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    amount_cad: str


class QuoteTaxOut(BaseModel):
    """What the quote says about GST/HST (RC-UAT-21, P-9 stand-in; DEC-0232): the invoice rule.

    ``band`` ``domestic`` -- prices include GST/HST at ``rate_percent`` (``label`` HST or GST;
    ``rate_percent`` null when the destination province is unknown); ``international`` --
    zero-rated (0 %). The screens compose the sentence in the reader's language.
    """

    model_config = ConfigDict(extra="forbid")

    band: str
    label: str | None
    rate_percent: int | None


class AccountQuoteSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    shipment_reference: str | None
    version: int | None
    service: str | None
    #: sent | accepted | declined | withdrawn
    status: str
    sent_at: datetime
    total_cad: str | None
    currency: str
    #: RC-UAT-21 (DEC-0232): the GST/HST wording under the total.
    tax: QuoteTaxOut | None = None


class AccountQuoteDetail(AccountQuoteSummary):
    model_config = ConfigDict(extra="forbid")

    billable_weight_kg: str | None
    rate_per_kg_cad: str | None
    base_charge_cad: str | None
    surcharges: list[AccountQuoteSurcharge]
    tax_included: bool
    responded_at: datetime | None
    decline_reason: str | None
    #: True while the customer may accept or decline.
    can_answer: bool
    #: Why not, when not: accepted | declined | withdrawn | replaced | updating.
    closed_reason: str | None


class AccountQuoteList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AccountQuoteSummary]


class QuoteDocumentOut(BaseModel):
    """Staff: the printable customer quote for one finalised version (Phase 14).

    An **allowlist** (``extra="forbid"``), like the invoice document: the company's details
    (OD-64), the customer, the Solaris service and the customer's charges before tax. Never a
    vendor cost, exchange rate, markup, margin, vendor name, product code or tariff version.
    """

    model_config = ConfigDict(extra="forbid")

    company_name: str
    company_trade_name: str
    company_business_number: str
    company_address: str
    company_email: str | None = None
    customer_name: str | None
    customer_reference: str | None
    shipment_reference: str | None
    version: int
    finalized_at: datetime | None
    service: str | None
    billable_weight_kg: str | None
    rate_per_kg_cad: str | None
    base_charge_cad: str | None
    surcharges: list[AccountQuoteSurcharge]
    total_cad: str | None
    currency: str
    tax_included: bool
    #: ``finalized`` or ``superseded`` (a later version was finalised; the page says so).
    status: str
    #: The version finalised after this one, when this one is superseded.
    superseded_by_version: int | None = None
    #: RC-UAT-21 (DEC-0232): the GST/HST wording under the total, as on the account's quote.
    tax: QuoteTaxOut | None = None
