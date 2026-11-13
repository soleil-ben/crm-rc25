"""Vendor-bill schemas (Phase 13E). **Staff only: vendor cost.**

Kept apart from ``schemas/finance.py`` so the general finance module -- which holds the
customer's invoice and receipt documents -- stays under the guard that no general or
customer-facing schema carries a vendor or exchange-rate field
(``tests/test_tariff_import.py``). Returned only by routes behind ``tariff:read``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.finance import FinanceModel


class VendorLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(max_length=12)
    fee_key: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    amount: Decimal = Field(gt=0)


class VendorInvoiceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor_bill_number: str | None = Field(default=None, max_length=60)
    billed_at: datetime | None = None
    currency: str = Field(max_length=3)
    lines: list[VendorLineIn] = Field(min_length=1, max_length=200)


class VendorApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variance_reason: str | None = Field(default=None, max_length=400)


class VendorPaidIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: str | None = Field(default=None, max_length=120)
    paid_at: datetime | None = None


class VendorLineOut(FinanceModel):
    sequence: int
    kind: str
    fee_key: str | None
    description: str
    amount: Decimal


class VendorInvoiceOut(FinanceModel):
    id: int
    public_id: str
    consolidation_id: int
    vendor_bill_number: str | None
    billed_at: datetime
    currency: str
    status: str
    total_amount: Decimal
    #: VND per CAD used for a VND bill (Vietcombank middle rate on the bill date, OD-67).
    fx_rate_vnd: Decimal | None
    total_cad: Decimal
    expected_vnd: Decimal | None
    expected_cad: Decimal | None
    variance_cad: Decimal | None
    variance_reason: str | None
    period_month: str
    is_adjustment: bool
    entered_at: datetime
    approved_at: datetime | None
    paid_at: datetime | None
    paid_reference: str | None
    voided_at: datetime | None
    void_reason: str | None
    lines: list[VendorLineOut]
    #: shipment id -> actual cost (CAD) once approved.
    allocations: dict[str, Decimal]
