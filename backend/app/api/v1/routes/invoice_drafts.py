"""Staff routes for draft invoices and invoice PDFs (owner decision 9a, 2026-10-21).

Permissions are the invoice's own: reading a draft or downloading a PDF is
``financial:read``; editing and sending a draft is ``financial:write`` (the same as issuing
an invoice today). Nothing here is mounted on the public or Customer Account routers.

``GET   /invoice-drafts``                    drafts (``?status=draft`` by default)
``GET   /invoice-drafts/{id}``               one draft
``GET   /shipments/{id}/invoice-draft``      the shipment's latest draft, or null
``PATCH /invoice-drafts/{id}``               save edits; ``expected_revision`` and
                                             ``tax_confirmed: true`` required (else 422
                                             ``tax_unconfirmed``; owner, 2026-10-22)
``POST  /invoice-drafts/{id}/send``          issue the invoice; ``expected_revision`` required;
                                             the saved revision's GST/HST confirmed (else 422
                                             ``tax_unconfirmed``);
                                             ``acknowledge_superseded`` when a newer version exists
``POST  /invoice-drafts/{id}/withdraw``      discard the draft with a reason (financial write)
``GET   /invoice-drafts/{id}/pdf?revision=`` the draft as a PDF, watermarked DRAFT; refused
                                             like Send (422 ``tax_unconfirmed``) until the
                                             saved revision's GST/HST is confirmed (owner,
                                             2026-10-23; DEC-0229)
``GET   /invoices/{id}/pdf``                 an issued invoice as a PDF
``GET   /finance/tax-rates``                 the GST/HST rate per province (``financial:read``)
``PATCH /finance/tax-rates/{code}``          Admin edits one (``settings:manage``; audited
                                             ``tax_rate.update``; DEC-0227)
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.deps import DbSession, require
from app.core.db import run_unit_with_retry
from app.core.permissions import Permission
from app.models import CustomerInvoice, InvoiceDraft, User
from app.services import (
    booking_service,
    finance_service,
    invoice_draft_service,
    invoice_pdf_service,
    tax_rate_service,
)

router = APIRouter(tags=["invoice-drafts"])

P = Permission
Reader = Annotated[User, Depends(require(P.FINANCIAL_READ))]
Writer = Annotated[User, Depends(require(P.FINANCIAL_READ, P.FINANCIAL_WRITE))]
SettingsManager = Annotated[User, Depends(require(P.FINANCIAL_READ, P.SETTINGS_MANAGE))]


class DraftLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(max_length=300)
    amount_cad: str = Field(max_length=20)


class DraftUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int
    bill_to_name: str | None = Field(default=None, max_length=200)
    bill_to_address: str | None = Field(default=None, max_length=1000)
    customer_reference: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    tax_rate_percent: int | None = None
    #: Owner, 2026-10-22: GST/HST included in the line amounts, or added on top.
    tax_mode: Literal["included", "added"] | None = None
    #: The box "I have checked the GST/HST on this invoice"; a save without it is refused.
    tax_confirmed: bool | None = None
    #: What the screen showed beside the ticked box; required when the save changes the lines,
    #: the rate or the mode, and must equal the server's figures (review, 2026-10-22).
    confirmed_total_cad: str | None = Field(default=None, max_length=20)
    confirmed_tax_mode: Literal["included", "added"] | None = None
    confirmed_tax_rate_percent: int | None = None
    lines: list[DraftLineIn] | None = Field(default=None, max_length=50)
    total_change_reason: str | None = Field(default=None, max_length=400)


class DraftSendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int
    #: Send at the accepted price although a newer quote version was finalised (M1).
    acknowledge_superseded: bool = False


class DraftWithdrawIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(max_length=300)


class DraftLineOut(BaseModel):
    description: str
    amount_cad: str


class DraftTaxLineOut(BaseModel):
    """One line as the issued invoice will show it (DEC-0235): Qty (1 on a draft line), Rate
    (net / qty, 4 decimals), the net, the tax, the all-in amount and the TAX column."""

    description: str
    quantity: str
    unit_price_cad: str
    net_cad: str
    tax_cad: str
    gross_cad: str
    tax_code: str


class DraftTaxRowOut(BaseModel):
    """A summary tax row as the issued invoice will show it: "HST ON @ 13%", "GST @ 0%"."""

    label: str
    tax_cad: str


class DraftTaxRouteOut(BaseModel):
    """What the draft's GST/HST was auto-filled from (owner, 2026-10-23; DEC-0227)."""

    route_band: str
    origin_country_code: str | None
    destination_country_code: str | None
    destination_province: str | None
    suggested_rate_percent: int | None
    suggested_mode: str


class TaxRateOut(BaseModel):
    province_code: str
    province_name: str
    rate_percent: int
    tax_label: str
    updated_at: Any = None
    updated_by: str | None = None


class TaxRateListOut(BaseModel):
    items: list[TaxRateOut]
    allowed_rates: list[int]


class TaxRateUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rate_percent: int | None = Field(default=None, ge=0, le=30)
    tax_label: Literal["GST", "HST"] | None = None


class InvoiceDraftOut(BaseModel):
    """Revenue only: no cost, margin, exchange rate or vendor name."""

    id: int
    shipment_id: int
    shipment_reference: str | None
    consolidation_id: int | None
    customer_id: int
    customer_name: str | None
    customer_email: str | None = None
    quote_version_id: int
    quote_version: int | None
    offer_id: int | None
    status: str
    bill_to_name: str | None
    bill_to_address: str | None
    customer_reference: str | None
    notes: str | None
    #: None while a domestic draft's province is unknown and staff must choose (DEC-0227).
    tax_rate_percent: int | None
    tax_mode: str
    tax_rate_required: bool = False
    #: "HST" / "GST" from the province table, else "GST/HST" (review, 2026-10-24).
    tax_label: str = "GST/HST"
    allowed_tax_rates: list[int] = []
    tax_route: DraftTaxRouteOut | None = None
    tax_confirmed: bool
    tax_confirmed_at: Any = None
    tax_confirmed_by: str | None = None
    lines: list[DraftLineOut]
    #: DEC-0235: the per-line breakdown and the summary rows of the invoice Send will issue
    #: (None while no rate is chosen).
    tax_layout: str | None = None
    tax_lines: list[DraftTaxLineOut] | None = None
    tax_rows: list[DraftTaxRowOut] | None = None
    lines_total_cad: str
    subtotal_cad: str | None
    tax_cad: str | None
    total_cad: str | None
    quote_total_cad: str
    total_change_reason: str | None
    revision: int
    created_at: Any
    updated_at: Any
    issued_invoice_id: int | None
    issued_invoice_public_id: str | None
    issued_at: Any
    discarded_at: Any
    discard_reason: str | None
    email_status: str | None
    quote_expired: bool
    superseded_by_version: int | None = None
    language: str


class InvoiceDraftListOut(BaseModel):
    items: list[InvoiceDraftOut]
    total: int


class DraftSendOut(BaseModel):
    draft: InvoiceDraftOut
    invoice_id: int
    invoice_public_id: str
    email_status: str | None


def _out(db, draft: InvoiceDraft) -> InvoiceDraftOut:
    return InvoiceDraftOut(**invoice_draft_service.view(db, draft))


@router.get("/invoice-drafts", response_model=InvoiceDraftListOut)
def list_drafts(
    db: DbSession,
    _user: Reader,
    status: str = Query(default="draft", max_length=12),
    limit: int = Query(default=100, ge=1, le=500),
) -> InvoiceDraftListOut:
    conditions = [InvoiceDraft.status == status] if status != "all" else []
    total = db.scalar(select(func.count()).select_from(InvoiceDraft).where(*conditions)) or 0
    rows = db.scalars(
        select(InvoiceDraft)
        .where(*conditions)
        .order_by(InvoiceDraft.updated_at.desc(), InvoiceDraft.id.desc())
        .limit(limit)
    ).all()
    return InvoiceDraftListOut(items=[_out(db, row) for row in rows], total=total)


@router.get("/invoice-drafts/{draft_id}", response_model=InvoiceDraftOut)
def read_draft(draft_id: int, db: DbSession, _user: Reader) -> InvoiceDraftOut:
    return _out(db, invoice_draft_service.get(db, draft_id))


@router.get("/shipments/{shipment_id}/invoice-draft", response_model=InvoiceDraftOut | None)
def shipment_draft(shipment_id: int, db: DbSession, _user: Reader) -> InvoiceDraftOut | None:
    shipment = booking_service.get_shipment(db, shipment_id)
    draft = invoice_draft_service.live_for_shipment(
        db, shipment.id
    ) or invoice_draft_service.latest_for_shipment(db, shipment.id)
    return _out(db, draft) if draft else None


@router.patch("/invoice-drafts/{draft_id}", response_model=InvoiceDraftOut)
def update_draft(
    draft_id: int, payload: DraftUpdateIn, db: DbSession, user: Writer
) -> InvoiceDraftOut:
    changes = payload.model_dump(exclude_unset=True)
    expected = changes.pop("expected_revision")

    def work():
        draft = invoice_draft_service.get(db, draft_id)
        invoice_draft_service.update_draft(
            db, draft, changes, expected_revision=expected, actor=user
        )
        return draft

    draft = run_unit_with_retry(db, work)
    db.refresh(draft)
    return _out(db, draft)


@router.post("/invoice-drafts/{draft_id}/send", response_model=DraftSendOut)
def send_draft(draft_id: int, payload: DraftSendIn, db: DbSession, user: Writer) -> DraftSendOut:
    """Issue the invoice from the saved draft, commit, then email the customer (outside the
    unit, so a retry can never send twice)."""

    def work():
        draft = invoice_draft_service.get(db, draft_id)
        invoice = invoice_draft_service.send(
            db,
            draft,
            expected_revision=payload.expected_revision,
            acknowledge_superseded=payload.acknowledge_superseded,
            actor=user,
        )
        return draft.id, invoice.id, invoice.public_id

    sent_id, invoice_id, public_id = run_unit_with_retry(db, work)
    status = invoice_draft_service.send_email(db, sent_id)
    draft = invoice_draft_service.get(db, sent_id)
    return DraftSendOut(
        draft=_out(db, draft),
        invoice_id=invoice_id,
        invoice_public_id=public_id,
        email_status=status,
    )


@router.post("/invoice-drafts/{draft_id}/withdraw", response_model=InvoiceDraftOut)
def withdraw_draft(
    draft_id: int, payload: DraftWithdrawIn, db: DbSession, user: Writer
) -> InvoiceDraftOut:
    """Discard a draft with a reason (audited ``invoice.draft_discarded``), so the shipment can
    be invoiced from its latest quote version the normal way."""

    def work():
        draft = invoice_draft_service.get(db, draft_id)
        invoice_draft_service.withdraw(db, draft, reason=payload.reason, actor=user)
        return draft

    draft = run_unit_with_retry(db, work)
    db.refresh(draft)
    return _out(db, draft)


def _pdf(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/invoice-drafts/{draft_id}/pdf")
def draft_pdf(
    draft_id: int,
    db: DbSession,
    _user: Reader,
    revision: int = Query(..., ge=1),
) -> Response:
    """The saved draft, watermarked DRAFT. ``revision`` must be the saved one, so a page with
    unsaved or stale edits never prints something other than what it shows."""
    draft = invoice_draft_service.get(db, draft_id)
    invoice_draft_service.require_draft(draft)
    invoice_draft_service.check_revision(draft, revision)
    # Owner, 2026-10-23 (DEC-0229): the same rule and error as Send.
    if not invoice_draft_service.tax_confirmed(db, draft):
        raise invoice_draft_service.tax_unconfirmed_error("download it")
    content = invoice_pdf_service.draft_pdf(db, draft)
    reference = invoice_draft_service.view(db, draft)["shipment_reference"] or draft.id
    return _pdf(content, f"draft-invoice-{reference}.pdf")


@router.get("/invoices/{invoice_id}/pdf")
def invoice_pdf(invoice_id: int, db: DbSession, _user: Reader) -> Response:
    invoice: CustomerInvoice = finance_service.get_invoice(db, invoice_id)
    content = invoice_pdf_service.invoice_pdf(db, invoice)
    return _pdf(content, f"{invoice.public_id}.pdf")


# --- GST/HST by province (owner, 2026-10-23; DEC-0227) ---------------------------------------


def _rates_out(db) -> TaxRateListOut:
    return TaxRateListOut(
        items=[
            TaxRateOut(
                province_code=rate.province_code,
                province_name=tax_rate_service.PROVINCE_NAMES[rate.province_code],
                rate_percent=rate.rate_percent,
                tax_label=rate.tax_label,
                updated_at=rate.updated_at,
                updated_by=rate.updated_by,
            )
            for rate in tax_rate_service.rate_table(db).values()
        ],
        allowed_rates=list(tax_rate_service.allowed_rates(db)),
    )


@router.get("/finance/tax-rates", response_model=TaxRateListOut)
def list_tax_rates(db: DbSession, _user: Reader) -> TaxRateListOut:
    return _rates_out(db)


@router.patch("/finance/tax-rates/{province_code}", response_model=TaxRateListOut)
def update_tax_rate(
    payload: TaxRateUpdateIn,
    db: DbSession,
    user: SettingsManager,
    province_code: str = Path(..., min_length=2, max_length=2),
) -> TaxRateListOut:
    """Admin edits one province's rate or label; the next draft auto-fills from it."""

    def work():
        tax_rate_service.update_rate(
            db, province_code, payload.model_dump(exclude_unset=True), actor=user
        )

    run_unit_with_retry(db, work)
    return _rates_out(db)
