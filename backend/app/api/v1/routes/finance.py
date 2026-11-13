"""Staff finance routes (Phase 13E): invoices, payments, receipts, vendor bills, reports.

Permissions:

* Customer invoices, payments, receipts and AR aging (revenue) need ``financial:read``;
  issuing and recording payments ``financial:write``. Refunds, voids and reopening a closed
  month are **Admin's** (``financial:adjust``).
* Vendor bills, AP, profitability and closing a month carry vendor cost, so they also need
  ``tariff:read`` (Operations and Admin, OD-45).
* The CSV exports need ``export:reports`` as well, and are audited without their contents.

Nothing here is on the public or Customer Account routers. The two customer documents are
served to staff (to print or send by hand) through their own allowlisted schemas.
"""

from __future__ import annotations

import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import StreamingResponse

from app.api.deps import DbSession, require
from app.core.db import commit_with_retry, run_unit_with_retry
from app.core.permissions import Permission
from app.models import (
    Customer,
    CustomerInvoice,
    CustomerPayment,
    Shipment,
    User,
    VendorInvoice,
)
from app.schemas.finance import (
    AcceptedNotInvoicedListOut,
    AcceptedNotInvoicedOut,
    FinanceSettingsOut,
    FinanceSettingsUpdate,
    InvoiceDetailOut,
    InvoiceDocumentOut,
    InvoiceLineOut,
    InvoiceListOut,
    InvoiceOut,
    IssueInvoiceIn,
    PaymentIn,
    PaymentOut,
    PeriodOut,
    ReasonIn,
    ReceiptDocumentOut,
    RefundIn,
    ReportOut,
    ShipmentFinancialSummaryOut,
)
from app.schemas.vendor_bills import (
    VendorApproveIn,
    VendorInvoiceIn,
    VendorInvoiceOut,
    VendorLineOut,
    VendorPaidIn,
)
from app.services import (
    audit_service,
    booking_service,
    consolidation_service,
    export_service,
    finance_service,
    invoice_tax_math,
    quote_offer_service,
    shipment_finance_summary_service,
)
from app.services.errors import NotFoundError

router = APIRouter(tags=["finance"])

P = Permission
Reader = Annotated[User, Depends(require(P.FINANCIAL_READ))]
Writer = Annotated[User, Depends(require(P.FINANCIAL_READ, P.FINANCIAL_WRITE))]
Adjuster = Annotated[
    User, Depends(require(P.FINANCIAL_READ, P.FINANCIAL_WRITE, P.FINANCIAL_ADJUST))
]
CostReader = Annotated[User, Depends(require(P.FINANCIAL_READ, P.TARIFF_READ))]
CostWriter = Annotated[User, Depends(require(P.FINANCIAL_READ, P.FINANCIAL_WRITE, P.TARIFF_READ))]
SettingsManager = Annotated[User, Depends(require(P.FINANCIAL_READ, P.SETTINGS_MANAGE))]
ArExporter = Annotated[User, Depends(require(P.FINANCIAL_READ, P.EXPORT_REPORTS))]
CostExporter = Annotated[User, Depends(require(P.FINANCIAL_READ, P.TARIFF_READ, P.EXPORT_REPORTS))]


def invoice_out(db, invoice: CustomerInvoice) -> InvoiceOut:
    customer = db.get(Customer, invoice.customer_id)
    shipment = db.get(Shipment, invoice.shipment_id)
    return InvoiceOut(
        id=invoice.id,
        public_id=invoice.public_id,
        shipment_id=invoice.shipment_id,
        shipment_reference=shipment.public_id if shipment else None,
        customer_id=invoice.customer_id,
        customer_name=customer.full_name if customer else None,
        customer_reference=customer.public_id if customer else None,
        quote_version_id=invoice.quote_version_id,
        consolidation_id=invoice.consolidation_id,
        status=invoice.status,
        currency=invoice.currency,
        subtotal_cad=invoice.subtotal_cad,
        tax_cad=invoice.tax_cad,
        tax_status=invoice.tax_status,
        total_cad=invoice.total_cad,
        paid_cad=invoice.paid_cad,
        balance_cad=finance_service.balance(invoice),
        period_month=invoice.period_month,
        is_adjustment=invoice.is_adjustment,
        issued_at=invoice.issued_at,
        due_at=invoice.due_at,
        voided_at=invoice.voided_at,
        void_reason=invoice.void_reason,
    )


def invoice_detail(db, invoice: CustomerInvoice) -> InvoiceDetailOut:
    # DEC-0235: the per-line Rate / Tax of an invoice issued with the Solaris Invoicing layout.
    layout = finance_service.tax_layout_of(invoice)
    return InvoiceDetailOut(
        **invoice_out(db, invoice).model_dump(),
        lines=[
            InvoiceLineOut(
                sequence=line.sequence,
                description=line.description,
                quantity=line.quantity,
                unit=line.unit,
                amount_cad=line.amount_cad,
                **finance_service.invoice_line_facts(layout, line),
            )
            for line in invoice.lines
        ],
        payments=[
            PaymentOut.model_validate(p) for p in finance_service.payments_for(db, invoice.id)
        ],
        tax_layout=invoice_tax_math.LAYOUT if layout is not None else None,
        tax_rows=layout["rows"] if layout is not None else None,
    )


def vendor_invoice_out(db, invoice: VendorInvoice) -> VendorInvoiceOut:
    return VendorInvoiceOut(
        id=invoice.id,
        public_id=invoice.public_id,
        consolidation_id=invoice.consolidation_id,
        vendor_bill_number=invoice.vendor_bill_number,
        billed_at=invoice.billed_at,
        currency=invoice.currency,
        status=invoice.status,
        total_amount=invoice.total_amount,
        fx_rate_vnd=invoice.fx_cash_buy_vnd,
        total_cad=invoice.total_cad,
        expected_vnd=invoice.expected_vnd,
        expected_cad=invoice.expected_cad,
        variance_cad=invoice.variance_cad,
        variance_reason=invoice.variance_reason,
        period_month=invoice.period_month,
        is_adjustment=invoice.is_adjustment,
        entered_at=invoice.entered_at,
        approved_at=invoice.approved_at,
        paid_at=invoice.paid_at,
        paid_reference=invoice.paid_reference,
        voided_at=invoice.voided_at,
        void_reason=invoice.void_reason,
        lines=[VendorLineOut.model_validate(line) for line in invoice.lines],
        allocations={str(k): v for k, v in finance_service.allocations_for(db, invoice.id).items()},
    )


def _payment(db, payment_id: int) -> CustomerPayment:
    row = db.get(CustomerPayment, payment_id)
    if row is None:
        raise NotFoundError("Payment not found.")
    return row


# --- Settings ----------------------------------------------------------------------------------


@router.get("/finance/settings", response_model=FinanceSettingsOut)
def read_settings(db: DbSession, _user: Reader) -> FinanceSettingsOut:
    row = finance_service.get_settings(db)
    commit_with_retry(db)
    return FinanceSettingsOut.model_validate(row)


@router.patch("/finance/settings", response_model=FinanceSettingsOut)
def update_settings(
    payload: FinanceSettingsUpdate, db: DbSession, user: SettingsManager
) -> FinanceSettingsOut:
    def work():
        row = finance_service.update_settings(
            db, payload.model_dump(exclude_unset=True), actor=user
        )
        return row

    row = run_unit_with_retry(db, work)
    return FinanceSettingsOut.model_validate(row)


# --- Customer invoices -------------------------------------------------------------------------


@router.get("/invoices", response_model=InvoiceListOut)
def list_invoices(
    db: DbSession,
    _user: Reader,
    status: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> InvoiceListOut:
    rows, total = finance_service.list_invoices(db, status=status, limit=limit, offset=offset)
    return InvoiceListOut(items=[invoice_out(db, r) for r in rows], total=total)


@router.get("/finance/accepted-not-invoiced", response_model=AcceptedNotInvoicedListOut)
def accepted_not_invoiced(
    db: DbSession,
    _user: Reader,
    limit: int = Query(default=100, ge=1, le=500),
) -> AcceptedNotInvoicedListOut:
    """Phase 15: quotes the customer accepted whose shipment has no live invoice, newest
    first. Read-only; staff issue the invoice from the workspace (no automatic invoice).
    ``total`` is the true count; ``items`` at most ``limit``."""
    from app.services import invoice_draft_service  # noqa: PLC0415

    rows, total = quote_offer_service.accepted_not_invoiced(db, limit=limit)
    items = []
    for offer, reference, customer_name, consolidation_id in rows:
        view = quote_offer_service.customer_view(offer)
        # Owner decision 9a: the draft prepared on acceptance, when there is one.
        draft = invoice_draft_service.live_for_shipment(db, offer.shipment_id)
        items.append(
            AcceptedNotInvoicedOut(
                offer_id=offer.id,
                shipment_id=offer.shipment_id,
                shipment_reference=reference,
                customer_name=customer_name,
                version=view.get("version"),
                accepted_at=offer.responded_at,
                total_cad=view.get("total_cad"),
                consolidation_id=consolidation_id,
                superseded_by_version=offer.superseded_by_version,
                invoice_draft_id=draft.id if draft else None,
                invoice_draft_revision=draft.revision if draft else None,
            )
        )
    return AcceptedNotInvoicedListOut(items=items, total=total)


@router.get("/shipments/{shipment_id}/invoice", response_model=InvoiceDetailOut | None)
def shipment_invoice(shipment_id: int, db: DbSession, _user: Reader) -> InvoiceDetailOut | None:
    shipment = booking_service.get_shipment(db, shipment_id)
    invoice = finance_service.live_invoice(db, shipment.id)
    return invoice_detail(db, invoice) if invoice else None


@router.get(
    "/shipments/{shipment_id}/financial-summary", response_model=ShipmentFinancialSummaryOut
)
def shipment_financial_summary(
    shipment_id: int, db: DbSession, user: Reader
) -> ShipmentFinancialSummaryOut:
    """The shipment page's quoted / cost summary and next step (RC-UAT-25 item 8, Ben
    2026-10-25). Read-only; vendor cost only with ``tariff:read``."""
    shipment = booking_service.get_shipment(db, shipment_id)
    return ShipmentFinancialSummaryOut(
        **shipment_finance_summary_service.summary(db, shipment, role=user.role)
    )


@router.post("/shipments/{shipment_id}/invoice", response_model=InvoiceDetailOut, status_code=201)
def issue_invoice(
    shipment_id: int, db: DbSession, user: Writer, payload: IssueInvoiceIn | None = None
) -> InvoiceDetailOut:
    """Issue at the GST/HST rate staff chose (0, 5 or 13 %, OD-64); 0 when not given."""
    rate = payload.tax_rate_percent if payload else 0

    def work():
        shipment = booking_service.get_shipment(db, shipment_id)
        invoice = finance_service.issue_invoice(db, shipment, actor=user, tax_rate_percent=rate)
        return shipment, invoice

    shipment, invoice = run_unit_with_retry(db, work)
    db.refresh(invoice)
    return invoice_detail(db, invoice)


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetailOut)
def read_invoice(invoice_id: int, db: DbSession, _user: Reader) -> InvoiceDetailOut:
    return invoice_detail(db, finance_service.get_invoice(db, invoice_id))


@router.get("/invoices/{invoice_id}/document", response_model=InvoiceDocumentOut)
def invoice_document(invoice_id: int, db: DbSession, _user: Reader) -> InvoiceDocumentOut:
    invoice = finance_service.get_invoice(db, invoice_id)
    return InvoiceDocumentOut(**finance_service.invoice_document(db, invoice))


@router.post("/invoices/{invoice_id}/payments", response_model=InvoiceDetailOut, status_code=201)
def record_payment(
    invoice_id: int, payload: PaymentIn, db: DbSession, user: Writer
) -> InvoiceDetailOut:
    def work():
        invoice = finance_service.get_invoice(db, invoice_id)
        finance_service.record_payment(db, invoice, payload.model_dump(), actor=user)
        return invoice

    invoice = run_unit_with_retry(db, work)
    db.refresh(invoice)
    return invoice_detail(db, invoice)


@router.post("/invoices/{invoice_id}/void", response_model=InvoiceDetailOut)
def void_invoice(
    invoice_id: int, payload: ReasonIn, db: DbSession, user: Adjuster
) -> InvoiceDetailOut:
    def work():
        invoice = finance_service.get_invoice(db, invoice_id)
        finance_service.void_invoice(db, invoice, payload.reason, actor=user)
        return invoice

    invoice = run_unit_with_retry(db, work)
    db.refresh(invoice)
    return invoice_detail(db, invoice)


@router.post("/payments/{payment_id}/refund", response_model=InvoiceDetailOut, status_code=201)
def refund_payment(
    payment_id: int, payload: RefundIn, db: DbSession, user: Adjuster
) -> InvoiceDetailOut:
    def work():
        payment = _payment(db, payment_id)
        finance_service.refund_payment(db, payment, payload.model_dump(), actor=user)
        return payment

    payment = run_unit_with_retry(db, work)
    invoice = finance_service.get_invoice(db, payment.invoice_id)
    db.refresh(invoice)
    return invoice_detail(db, invoice)


@router.get("/payments/{payment_id}/receipt", response_model=ReceiptDocumentOut)
def receipt(payment_id: int, db: DbSession, _user: Reader) -> ReceiptDocumentOut:
    return ReceiptDocumentOut(**finance_service.receipt_document(db, _payment(db, payment_id)))


# --- Vendor bills ------------------------------------------------------------------------------


@router.get(
    "/consolidations/{consolidation_id}/vendor-invoices", response_model=list[VendorInvoiceOut]
)
def list_vendor_invoices(
    consolidation_id: int, db: DbSession, _user: CostReader
) -> list[VendorInvoiceOut]:
    consolidation = consolidation_service.get_consolidation(db, consolidation_id)
    return [
        vendor_invoice_out(db, v) for v in finance_service.vendor_invoices_for(db, consolidation.id)
    ]


@router.post(
    "/consolidations/{consolidation_id}/vendor-invoices",
    response_model=VendorInvoiceOut,
    status_code=201,
)
def enter_vendor_invoice(
    consolidation_id: int, payload: VendorInvoiceIn, db: DbSession, user: CostWriter
) -> VendorInvoiceOut:
    def work():
        consolidation = consolidation_service.get_consolidation(db, consolidation_id)
        row = finance_service.enter_vendor_invoice(
            db, consolidation, payload.model_dump(), actor=user
        )
        return consolidation, row

    consolidation, row = run_unit_with_retry(db, work)
    db.refresh(row)
    return vendor_invoice_out(db, row)


def _vendor(db, vendor_invoice_id: int) -> VendorInvoice:
    return finance_service.get_vendor_invoice(db, vendor_invoice_id)


@router.post("/vendor-invoices/{vendor_invoice_id}/approve", response_model=VendorInvoiceOut)
def approve_vendor_invoice(
    vendor_invoice_id: int, payload: VendorApproveIn, db: DbSession, user: CostWriter
) -> VendorInvoiceOut:
    def work():
        row = _vendor(db, vendor_invoice_id)
        finance_service.approve_vendor_invoice(db, row, payload.model_dump(), actor=user)
        return row

    row = run_unit_with_retry(db, work)
    db.refresh(row)
    return vendor_invoice_out(db, row)


@router.post("/vendor-invoices/{vendor_invoice_id}/paid", response_model=VendorInvoiceOut)
def vendor_invoice_paid(
    vendor_invoice_id: int, payload: VendorPaidIn, db: DbSession, user: CostWriter
) -> VendorInvoiceOut:
    def work():
        row = _vendor(db, vendor_invoice_id)
        finance_service.mark_vendor_invoice_paid(db, row, payload.model_dump(), actor=user)
        return row

    row = run_unit_with_retry(db, work)
    db.refresh(row)
    return vendor_invoice_out(db, row)


@router.post("/vendor-invoices/{vendor_invoice_id}/void", response_model=VendorInvoiceOut)
def void_vendor_invoice(
    vendor_invoice_id: int, payload: ReasonIn, db: DbSession, user: Adjuster
) -> VendorInvoiceOut:
    def work():
        row = _vendor(db, vendor_invoice_id)
        finance_service.void_vendor_invoice(db, row, payload.reason, actor=user)
        return row

    row = run_unit_with_retry(db, work)
    db.refresh(row)
    return vendor_invoice_out(db, row)


# --- Reports and periods -----------------------------------------------------------------------


@router.get("/finance/ar-aging", response_model=ReportOut)
def ar_aging(db: DbSession, _user: Reader) -> ReportOut:
    return ReportOut(report=finance_service._jsonable(finance_service.ar_aging(db)))


@router.get("/finance/ap", response_model=ReportOut)
def accounts_payable(db: DbSession, _user: CostReader) -> ReportOut:
    return ReportOut(report=finance_service._jsonable(finance_service.accounts_payable(db)))


@router.get("/finance/profitability", response_model=ReportOut)
def profitability(
    db: DbSession,
    _user: CostReader,
    month: str = Query(pattern=r"^\d{4}-\d{2}$"),
) -> ReportOut:
    """A closed month answers from its frozen snapshot; any other month is live."""
    snapshot = finance_service.closed_snapshot(db, month)
    if snapshot is not None:
        return ReportOut(report={**snapshot, "state": "closed", "from_snapshot": True})
    live = finance_service._jsonable(finance_service.profitability(db, month))
    return ReportOut(report={**live, "from_snapshot": False})


@router.get("/finance/periods", response_model=list[PeriodOut])
def list_periods(db: DbSession, _user: Reader) -> list[PeriodOut]:
    return [PeriodOut(**row) for row in finance_service.periods(db)]


@router.post("/finance/periods/{month}/close", response_model=PeriodOut)
def close_period(
    month: Annotated[str, Path(pattern=r"^\d{4}-\d{2}$")], db: DbSession, user: CostWriter
) -> PeriodOut:
    def work():
        finance_service.close_month(db, month, actor=user)

    run_unit_with_retry(db, work)
    return PeriodOut(**finance_service.period_row(db, month))


@router.post("/finance/periods/{month}/reopen", response_model=PeriodOut)
def reopen_period(
    month: Annotated[str, Path(pattern=r"^\d{4}-\d{2}$")],
    payload: ReasonIn,
    db: DbSession,
    user: Adjuster,
) -> PeriodOut:
    def work():
        finance_service.reopen_month(db, month, payload.reason, actor=user)

    run_unit_with_retry(db, work)
    return PeriodOut(**finance_service.period_row(db, month))


# --- CSV exports (audited; contents never logged) ----------------------------------------------


def _csv(filename: str, header: list[str], rows: list[list]) -> StreamingResponse:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    # Every cell escaped against spreadsheet formula injection (DEC-0081).
    writer.writerows([[export_service.format_cell(cell) for cell in row] for row in rows])
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


def _audit_export(db, user: User, key: str, count: int, detail: dict) -> None:
    """Record the export (never its contents). Its own unit, re-run on a SQLite lock: the
    report was read first, so a plain commit could meet a stale snapshot (DEC-0204)."""

    def work():
        audit_service.record_audit(
            db,
            action=f"export.{key}",
            entity_type="export",
            entity_id=key,
            summary=f"Exported {count} {key} row(s) to CSV",
            actor=user,
            detail={"export_type": key, "row_count": count, **detail},
        )

    run_unit_with_retry(db, work)


@router.get("/finance/ar-aging.csv")
def ar_aging_csv(db: DbSession, user: ArExporter) -> StreamingResponse:
    report = finance_service.ar_aging(db)
    rows = [
        [
            r["invoice_number"],
            r["customer_reference"],
            r["customer_name"],
            r["issued_at"].date().isoformat(),
            r["due_at"].date().isoformat(),
            r["total_cad"],
            r["paid_cad"],
            r["balance_cad"],
            r["days_overdue"],
            r["bucket"],
        ]
        for r in report["rows"]
    ]
    _audit_export(db, user, "ar_aging", len(rows), {})
    return _csv(
        "ar_aging.csv",
        [
            "invoice",
            "customer_reference",
            "customer_name",
            "issued",
            "due",
            "total_cad",
            "paid_cad",
            "balance_cad",
            "days_overdue",
            "bucket",
        ],
        rows,
    )


@router.get("/finance/profitability.csv")
def profitability_csv(
    db: DbSession, user: CostExporter, month: str = Query(pattern=r"^\d{4}-\d{2}$")
) -> StreamingResponse:
    report = finance_service.closed_snapshot(db, month) or finance_service._jsonable(
        finance_service.profitability(db, month)
    )
    rows = [
        [
            month,
            r["consolidation_reference"],
            r["service"],
            r["origin"],
            r["shipments"],
            r["customers"],
            r["billable_kg"],
            r["revenue_cad"],
            r["estimated_cost_cad"],
            r["actual_cost_cad"],
            r["unmatched_cost_cad"],
            r["cost_basis"],
            r["profit_cad"],
            r["margin_percent"],
        ]
        for r in report["masters"]
    ]
    _audit_export(db, user, "profitability", len(rows), {"month": month})
    return _csv(
        f"profitability_{month}.csv",
        [
            "month",
            "master",
            "service",
            "origin",
            "shipments",
            "customers",
            "billable_kg",
            "revenue_cad",
            "estimated_cost_cad",
            "actual_cost_cad",
            "unmatched_cost_cad",
            "cost_basis",
            "profit_cad",
            "margin_percent",
        ],
        rows,
    )
