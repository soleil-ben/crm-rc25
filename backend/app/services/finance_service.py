"""Finance (Phase 13E): invoices, payments, receipts, vendor bills, actual cost, month close.

The rules, in the order a master moves through them:

* **Invoice** -- issued from the shipment's **finalised** quote version (an unpaid quote is
  never an invoice), numbered ``INV-`` at issue, revenue lines only, payer = the shipment's
  recorded payer or else its customer. Staff choose GST/HST of 0, 5 or 13 % per invoice
  (OD-64). One live invoice per shipment; a void needs a reason and leaves the number used.
  **Per line** (owner Ben, 2026-10-24; DEC-0235, the Solaris Invoicing desk rules): an invoice
  issued from now on works its GST/HST out line by line (``invoice_tax_math``), stores each
  line's **net** (before tax) as ``customer_invoice_lines.amount_cad`` and the per-line facts
  in ``document_json`` (``tax_layout: invoicing_v1``); subtotal = the nets, tax = the line
  taxes, total = what the customer pays. An invoice issued before (no ``tax_layout``) keeps
  its stored figures and reads exactly as it did.
* **Payment** -- CAD, or VND converted at Vietcombank's sell rate of the invoice date
  (OD-73, OD-75), never more than the balance (no credit is kept on account, OD-68), dated
  the day the money moved; each payment gets a receipt ``RCT-``. A **refund** returns money
  against one payment, never more than it brought in. Refunds and voids are Admin's or
  Operations' (``financial:adjust``, OD-69).
* **Vendor bill** -- the vendor's actual charge for a booked master, in VND or CAD, entered
  beside the cost the engine expects for it now; a VND bill is put into CAD at the cash-
  buying rate of the bill date, frozen on the bill (OD-73). The variance needs a reason
  before **approval**, and approval splits the bill onto the master's shipments: base
  freight, the piece fee and anything unkeyed by chargeable-weight share, each surcharge
  line by the engine's own split for that fee.
* **Periods** -- a revenue month (the Vietnam hand-in month of the master) locks seven days
  after it ends (M+7). An invoice or bill whose month is locked is booked in the first open
  month as an adjustment, never written into the locked month; a payment dated in a locked
  month, a void or a bill void inside one, is refused. A locked month can be **closed**
  (figures frozen) and **reopened** by Admin or Operations (OD-69) with a reason; every step
  is audited.

Everything here is internal except ``invoice_document`` and ``receipt_document``, which
build the customer's view from an allowlist: no cost, margin, rate or vendor name.
"""

from __future__ import annotations

import dataclasses
import json
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import SOLARIS_SERVICE_LABELS, PaymentState
from app.core.time_utils import is_known_timezone, utcnow
from app.models import (
    Consolidation,
    CostAllocation,
    Customer,
    CustomerInvoice,
    CustomerInvoiceLine,
    CustomerPayment,
    FinanceSettings,
    FxRateSnapshot,
    PaymentConversion,
    PeriodClose,
    QuoteOffer,
    QuoteVersion,
    Shipment,
    User,
    VendorInvoice,
    VendorInvoiceLine,
)
from app.pricing import engine as pe
from app.services import (
    audit_service,
    booking_service,
    fx_service,
    identifier_service,
    pricing_service,
)
from app.services import invoice_tax_math as tax_math
from app.services.errors import ConflictError, NotFoundError, ValidationError

CENT = Decimal("0.01")
#: The company on every invoice, receipt and printable quote (OD-64, owner, 2026-10-20; the
#: Solaris Invoicing desk's values, owner Ben, 2026-10-24, DEC-0235).
COMPANY = {
    "company_name": "Solaris Express Inc.",
    "company_trade_name": "Solaris Express",
    "company_business_number": "795093756RT0001",
    "company_address": "2446 Cawthra Rd Building 1 Unit 8, Mississauga ON L5A 3K6",
    "company_email": "solarisexpressinc@gmail.com",
}
#: How an invoice is paid (DEC-0235): printed on the invoice and its PDF.
PAYMENT = {
    "payment_etransfer": "info@solarisexpress.ca",
    "payment_wire": (
        "Bank of Montreal, 2825 Eglinton Avenue West, Mississauga ON L5M 6J3 · SWIFT BOFMCAM2 · "
        "Account 1969380"
    ),
}
#: The invoice PDF's footer, exactly (DEC-0235).
INVOICE_FOOTER = (
    "Thank you for your business! We accept payment via E-transfer to info@solarisexpress.ca"
)


def payment_terms(days: int) -> str:
    """ "Due on receipt" when the due date is the issue date (``invoice_due_days`` 0, the
    default), else "Net N days" (DEC-0235)."""
    if days <= 0:
        return "Due on receipt"
    return f"Net {days} day" if days == 1 else f"Net {days} days"


def invoice_terms(invoice: CustomerInvoice) -> str:
    return payment_terms((invoice.due_at.date() - invoice.issued_at.date()).days)


#: GST/HST rates staff choose from per invoice (OD-64). GST/HST applies only to domestic
#: moves, so a Vietnam -> Canada shipment is invoiced at 0%; staff choose, never the code.
TAX_RATES = (0, 5, 13)

PAYMENT_METHODS = ("cash", "bank_transfer", "e_transfer", "card", "other")
VENDOR_LINE_KINDS = ("base", "piece_fee", "surcharge", "other")
LOCK_AFTER_DAYS = 7


def _cents(value: Decimal) -> Decimal:
    return pe.to_cents(value)


def _amount(value: Any, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except Exception as error:  # noqa: BLE001
        raise ValidationError(f"{field} must be a number.", field=field) from error
    if not number.is_finite() or number <= 0:
        raise ValidationError(f"{field} must be greater than zero.", field=field)
    if number != number.quantize(CENT):
        raise ValidationError(f"{field} has more than two decimals.", field=field)
    return number


def _moment(value: Any, field: str, now: datetime) -> datetime:
    """A date or datetime from a payload as naive UTC (how every time here is stored), never
    in the future."""
    if value is None or value == "":
        return now
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValidationError("Not a valid date.", field=field) from error
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day)
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    if value > now:
        raise ValidationError("A date cannot be in the future.", field=field)
    return value


def _today_for(now: datetime, actor: User | None) -> date:
    """The latest calendar date it is "today" for this entry: in the business's own zone, or
    in the actor's own zone when that is ahead (a Vietnam office entering today's date)."""
    today = _local_date(now)
    zone_name = getattr(actor, "timezone", None)
    if zone_name and is_known_timezone(zone_name):
        from zoneinfo import ZoneInfo  # noqa: PLC0415

        today = max(today, now.replace(tzinfo=UTC).astimezone(ZoneInfo(zone_name)).date())
    return today


def _received_on(value: Any, field: str, now: datetime, actor: User | None = None) -> datetime:
    """A payment's received date (RC-20): a plain calendar date, stored as naive midnight of
    that date in the DateTime column, never converted between time zones.

    Staff enter a date ("money arrived on 20 September"), not an instant. Converting it to
    UTC or to Toronto moved it a day: midnight 20 September read as UTC is 19 September
    20:00 in Toronto. So the date part is taken **as written**: ``2026-09-20``,
    ``2026-09-20T00:00:00`` and ``2026-09-20T00:00:00-04:00`` are all 20 September, and any
    offset is ignored. With no value, today in the business's time zone. "Not in the future"
    compares dates, against today in the business zone (or the actor's own zone when ahead),
    so today's date entered on a Toronto evening is accepted.
    """
    if value is None or value == "":
        day = _local_date(now)
    else:
        if isinstance(value, str):
            text = value.strip()
            try:
                value = (
                    date.fromisoformat(text) if len(text) == 10 else datetime.fromisoformat(text)
                )
            except ValueError as error:
                raise ValidationError("Not a valid date.", field=field) from error
        if isinstance(value, datetime):
            day = value.date()  # the wall date as written, whatever its offset
        elif isinstance(value, date):
            day = value
        else:
            raise ValidationError("Not a valid date.", field=field)
        if day > _today_for(now, actor):
            raise ValidationError("A date cannot be in the future.", field=field)
    return datetime(day.year, day.month, day.day)


def _reason(value: Any, field: str = "reason") -> str:
    text = " ".join(str(value or "").split())
    if not text:
        raise ValidationError("A reason is required.", field=field)
    return text[:400]


# --- Settings -----------------------------------------------------------------------------------


def get_settings(db: Session) -> FinanceSettings:
    """The settings row, or unsaved defaults: reading never writes (DEC-0204)."""
    row = db.scalar(select(FinanceSettings).limit(1))
    if row is None:
        row = FinanceSettings(invoice_due_days=0, tax_status="review_pending", updated_at=utcnow())
    return row


def update_settings(db: Session, payload: dict[str, Any], *, actor: User | None) -> FinanceSettings:
    row = get_settings(db)
    changed = False
    if "invoice_due_days" in payload and payload["invoice_due_days"] is not None:
        days = int(payload["invoice_due_days"])
        if not 0 <= days <= 365:
            raise ValidationError("Due days must be between 0 and 365.", field="invoice_due_days")
        changed = days != row.invoice_due_days
        row.invoice_due_days = days
    if not changed:
        # Nothing actually changed (Phase 14 review): no write, no audit entry; the current
        # settings are returned as they are.
        return row
    if row.id is None:
        db.add(row)
    row.updated_at = utcnow()
    row.updated_by_user_id = actor.id if actor else None
    db.flush()
    audit_service.record_audit(
        db,
        action="finance.settings_update",
        entity_type="finance_settings",
        entity_id=row.id,
        summary="Updated the finance settings",
        actor=actor,
        detail={"invoice_due_days": row.invoice_due_days},
    )
    return row


# --- Periods (M+7) ------------------------------------------------------------------------------


def month_of(moment: datetime | date) -> str:
    return f"{moment.year:04d}-{moment.month:02d}"


def _parse_month(month: str) -> date:
    try:
        year, number = (int(part) for part in month.split("-"))
        return date(year, number, 1)
    except (ValueError, AttributeError) as error:
        raise ValidationError("A month is written YYYY-MM.", field="month") from error


def _next_month(month: str) -> str:
    first = _parse_month(month)
    return month_of(date(first.year + (first.month == 12), first.month % 12 + 1, 1))


def lock_date(month: str) -> datetime:
    """The moment a month locks: seven days after it ends (M+7), at 00:00 UTC."""
    following = _parse_month(_next_month(month))
    return datetime(following.year, following.month, following.day) + timedelta(
        days=LOCK_AFTER_DAYS
    )


def latest_close(db: Session, month: str) -> PeriodClose | None:
    return db.scalar(
        select(PeriodClose)
        .where(PeriodClose.month == month)
        .order_by(PeriodClose.version.desc())
        .limit(1)
    )


def period_state(db: Session, month: str, *, now: datetime | None = None) -> str:
    """``open``, ``locked`` (past M+7, figures still live), ``closed`` or ``reopened``."""
    close = latest_close(db, month)
    if close is not None:
        return "reopened" if close.reopened_at is not None else "closed"
    return "locked" if (now or utcnow()) >= lock_date(month) else "open"


def is_locked(db: Session, month: str, *, now: datetime | None = None) -> bool:
    return period_state(db, month, now=now) in {"locked", "closed"}


def booking_month(db: Session, month: str, *, now: datetime | None = None) -> tuple[str, bool]:
    """Where a figure for ``month`` is booked: the month itself, or the first open month
    after it when it is locked (a next-month adjustment)."""
    if not is_locked(db, month, now=now):
        return month, False
    candidate = _next_month(month)
    while is_locked(db, candidate, now=now):
        candidate = _next_month(candidate)
    return candidate, True


def master_month(db: Session, consolidation: Consolidation | None, fallback: datetime) -> str:
    """The one revenue month a master's invoices and bill share.

    Whatever was booked first for the master fixes it (its earliest non-adjustment invoice or
    bill), so revenue and its cost never land in different months because the hand-in date
    was recorded between the invoice and the bill. Otherwise ``revenue_month``.
    """
    if consolidation is not None:
        months = [
            row.period_month
            for model in (CustomerInvoice, VendorInvoice)
            for row in db.scalars(
                select(model).where(
                    model.consolidation_id == consolidation.id,
                    model.status != "void",
                    model.is_adjustment.is_(False),
                )
            )
        ]
        if months:
            return min(months)
    return revenue_month(consolidation, fallback)


def revenue_month(consolidation: Consolidation | None, fallback: datetime) -> str:
    """The management revenue month: the master's hand-in date in Vietnam (handoff owner
    decision 12), then its booking date, then the fallback."""
    if consolidation is not None:
        for moment in (consolidation.handed_over_at, consolidation.booked_at):
            if moment is not None:
                return month_of(moment)
    return month_of(fallback)


# --- Customer invoices --------------------------------------------------------------------------


def get_invoice(db: Session, invoice_id: int) -> CustomerInvoice:
    row = db.get(CustomerInvoice, invoice_id)
    if row is None:
        raise NotFoundError("Invoice not found.")
    return row


def live_invoice(db: Session, shipment_id: int) -> CustomerInvoice | None:
    return db.scalar(
        select(CustomerInvoice).where(
            CustomerInvoice.shipment_id == shipment_id, CustomerInvoice.status != "void"
        )
    )


def list_invoices(
    db: Session, *, status: str | None = None, limit: int = 50, offset: int = 0
) -> tuple[list[CustomerInvoice], int]:
    conditions = [CustomerInvoice.status == status] if status else []
    total = db.scalar(select(func.count()).select_from(CustomerInvoice).where(*conditions)) or 0
    rows = db.scalars(
        select(CustomerInvoice)
        .where(*conditions)
        .order_by(CustomerInvoice.issued_at.desc(), CustomerInvoice.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(rows), total


def _latest_finalized(db: Session, shipment_id: int) -> QuoteVersion | None:
    """The latest finalised version, ignoring one an Admin soft-deleted (RC-UAT-21 D)."""
    from app.services import quote_deletion_service  # noqa: PLC0415

    return db.scalar(
        select(QuoteVersion)
        .where(
            QuoteVersion.shipment_id == shipment_id,
            QuoteVersion.status == "finalized",
            QuoteVersion.id.not_in(quote_deletion_service.open_deletions_subquery()),
        )
        .order_by(QuoteVersion.version.desc())
        .limit(1)
    )


def _sync_payment_state(
    shipment: Shipment, invoice: CustomerInvoice | None, *, refunded: bool = False
) -> None:
    """Keep the shipment's existing payment field in step with its invoice."""
    if invoice is None or invoice.status == "void":
        shipment.payment_state = PaymentState.UNRECORDED
    elif invoice.status == "paid":
        shipment.payment_state = PaymentState.PAID
    elif invoice.status == "partially_paid":
        shipment.payment_state = PaymentState.PARTIALLY_PAID
    elif invoice.paid_cad == 0 and refunded:
        shipment.payment_state = PaymentState.REFUNDED
    else:
        shipment.payment_state = PaymentState.UNPAID


def invoiceable_version(db: Session, shipment: Shipment) -> QuoteVersion:
    """The quote version the manual Issue invoice path would bill, or the refusal it gives.

    Shared by ``issue_invoice`` and the shipment's Financials tab (RC-UAT-25 item 8, Ben
    2026-10-25), so the tab explains a blocked invoice with the very message Issue invoice
    would return. Read-only: raises ``ConflictError``, writes nothing.
    """
    from app.services import (  # noqa: PLC0415
        invoice_draft_service,
        quote_deletion_service,
        quote_expiry_service,
    )

    if live_invoice(db, shipment.id) is not None:
        raise ConflictError("This shipment already has an invoice; void it to issue another.")
    draft = invoice_draft_service.live_for_shipment(db, shipment.id)
    if draft is not None:
        raise ConflictError(
            "This shipment has a draft invoice from the accepted quote; review it and send "
            "it from the draft.",
            detail={"code": "invoice_draft_exists", "invoice_draft_id": draft.id},
        )
    # RC-UAT-21 Phase D: a soft-deleted latest finalised version is refused by name.
    quote_deletion_service.refuse_if_latest_finalised_deleted(db, shipment.id, doing="invoicing")
    version = _latest_finalized(db, shipment.id)
    if version is None:
        raise ConflictError("Finalise the shipment's quote before issuing an invoice.")
    if quote_expiry_service.is_expired(db, version.id):
        raise ConflictError(
            f"Quote v{version.version} expired when a new tariff became active: re-quote on "
            "the new rate before invoicing.",
            detail={"code": "quote_expired"},
        )
    return version


def issue_invoice(
    db: Session,
    shipment: Shipment,
    *,
    actor: User | None,
    now: datetime | None = None,
    tax_rate_percent: int = 0,
) -> CustomerInvoice:
    """Issue the invoice of the shipment's latest finalised quote (the manual path).

    Owner decision 9a: when a customer accepts a quote its invoice is prepared as a draft,
    and staff send it from there -- so a shipment with a live draft is refused here and
    pointed to it. An expired quote (owner decision 9) is never invoiced: re-price it.
    """
    now = now or utcnow()
    version = invoiceable_version(db, shipment)
    lines = [
        (line.description, line.quantity, line.unit, line.revenue_cad)
        for line in version.lines
        if line.revenue_cad and line.revenue_cad > 0
    ]
    payer_id = booking_service.payer_customer_id(db, shipment.id) or shipment.customer_id
    return _new_invoice(
        db,
        shipment,
        version,
        payer_id=payer_id,
        lines=lines,
        tax_rate_percent=tax_rate_percent,
        extra_document={},
        actor=actor,
        now=now,
    )


def issue_invoice_from_draft(
    db: Session,
    shipment: Shipment,
    *,
    version: QuoteVersion,
    payer_id: int,
    lines: list[tuple[str, Decimal]],
    tax_rate_percent: int,
    extra_document: dict[str, Any],
    actor: User | None,
    now: datetime | None = None,
    tax_mode: str = "added",
    allowed_rates: tuple[int, ...] | None = None,
) -> CustomerInvoice:
    """Issue the real invoice from a saved draft (owner decision 9a): the same numbering,
    revenue month and GST/HST as ``issue_invoice``, with the draft's lines and bill-to.

    ``tax_mode`` (owner, 2026-10-22): ``included`` -- the lines are all-in, the total is their
    sum and the tax is backed out of each line (DEC-0235); ``added`` -- the tax is charged on
    top of each line (the manual path's only behaviour).

    ``allowed_rates`` (owner, 2026-10-23; DEC-0227): a draft may carry 0, 5, 13, 14, 15 or any
    rate in ``tax_rates``; the manual path keeps ``TAX_RATES``."""
    now = now or utcnow()
    if live_invoice(db, shipment.id) is not None:
        raise ConflictError("This shipment already has an invoice; void it to issue another.")
    return _new_invoice(
        db,
        shipment,
        version,
        payer_id=payer_id,
        lines=[(description, None, None, amount) for description, amount in lines],
        tax_rate_percent=tax_rate_percent,
        extra_document=extra_document,
        actor=actor,
        now=now,
        tax_mode=tax_mode,
        allowed_rates=allowed_rates,
    )


def _new_invoice(
    db: Session,
    shipment: Shipment,
    version: QuoteVersion,
    *,
    payer_id: int,
    lines: list[tuple[str, Decimal | None, str | None, Decimal]],
    tax_rate_percent: int,
    extra_document: dict[str, Any],
    actor: User | None,
    now: datetime,
    tax_mode: str = "added",
    allowed_rates: tuple[int, ...] | None = None,
) -> CustomerInvoice:
    customer = db.get(Customer, payer_id)
    consolidation = (
        db.get(Consolidation, version.consolidation_id) if version.consolidation_id else None
    )
    month, adjustment = booking_month(db, master_month(db, consolidation, now), now=now)
    if allowed_rates is None and tax_rate_percent not in TAX_RATES:
        # The manual path (no draft) is unchanged (owner, 2026-10-23).
        raise ValidationError("GST/HST must be 0%, 5% or 13%.", field="tax_rate_percent")
    if allowed_rates is not None and tax_rate_percent not in allowed_rates:
        words = ", ".join(f"{rate}%" for rate in allowed_rates)
        raise ValidationError(f"GST/HST must be one of {words}.", field="tax_rate_percent")
    settings = get_settings(db)
    if tax_mode not in ("included", "added"):
        raise ValidationError("GST/HST is included or added.", field="tax_mode")
    # DEC-0235: line by line. A line's amount is its gross (qty x quoted rate): all-in when
    # included, before tax when added. Revenue (profitability) stays the subtotal, before tax.
    figures = tax_math.breakdown(
        [(amount, quantity) for _description, quantity, _unit, amount in lines],
        tax_rate_percent,
        tax_mode,
        label=extra_document.get("tax_label"),
    )
    subtotal, tax, total = figures.totals
    invoice = CustomerInvoice(
        public_id=identifier_service.next_invoice_public_id(db),
        shipment_id=shipment.id,
        customer_id=payer_id,
        quote_version_id=version.id,
        consolidation_id=version.consolidation_id,
        status="issued",
        currency="CAD",
        subtotal_cad=subtotal,
        tax_cad=tax,
        tax_status=f"gst_hst_{tax_rate_percent}",
        total_cad=total,
        paid_cad=Decimal(0),
        period_month=month,
        is_adjustment=adjustment,
        document_json=json.dumps(
            {
                "customer_name": customer.full_name if customer else None,
                "customer_reference": customer.public_id if customer else None,
                "shipment_reference": shipment.public_id,
                "service": SOLARIS_SERVICE_LABELS.get(
                    version.solaris_service, version.solaris_service
                ),
                "billable_weight_kg": str(version.billable_weight_kg)
                if version.billable_weight_kg is not None
                else None,
                "selling_rate_cad": str(version.selling_rate_cad)
                if version.selling_rate_cad is not None
                else None,
                "tax_mode": tax_mode,
                **extra_document,
                # DEC-0235: the per-line facts the invoice prints (the lines store the nets).
                "tax_layout": tax_math.LAYOUT,
                "tax_lines": [
                    {"sequence": sequence, **figure.as_dict()}
                    for sequence, figure in enumerate(figures.lines, start=1)
                ],
                "tax_rows": figures.rows_as_dicts(),
            },
            ensure_ascii=False,
        ),
        issued_at=now,
        issued_by_user_id=actor.id if actor else None,
        due_at=now + timedelta(days=settings.invoice_due_days),
    )
    for sequence, ((description, quantity, unit, _gross), figure) in enumerate(
        zip(lines, figures.lines, strict=True), start=1
    ):
        invoice.lines.append(
            CustomerInvoiceLine(
                sequence=sequence,
                description=description,
                quantity=quantity,
                unit=unit,
                amount_cad=figure.net_cad,
            )
        )
    db.add(invoice)
    db.flush()
    _sync_payment_state(shipment, invoice)
    offer_state = closed_offer_state(db, version.id)
    audit_service.record_audit(
        db,
        action="invoice.issue",
        entity_type="customer_invoice",
        entity_id=invoice.public_id,
        summary=f"Issued {invoice.public_id} for {shipment.public_id}: CAD {invoice.total_cad}"
        + (
            f" (quote v{version.version} was {offer_state} by the customer or staff)"
            if offer_state
            else ""
        ),
        actor=actor,
        detail={
            "shipment_id": shipment.id,
            "quote_version_id": version.id,
            "period_month": month,
            "is_adjustment": adjustment,
            "offer_state": offer_state,
            "from_draft": bool(extra_document),
        },
    )
    return invoice


#: Offer states that do not stop an invoice (stand-in, Phase 17) but are noted when one is
#: issued: staff withdrew the quote, or the customer declined it.
CLOSED_OFFER_STATES = ("withdrawn", "declined")


def closed_offer_state(db: Session, quote_version_id: int) -> str | None:
    """``withdrawn`` or ``declined`` when the newest offer of this quote version is, else None.

    Issuing is still allowed (the owner has not ruled on it); the workspace warns before the
    Issue invoice button and the issue audit records the state.
    """
    status = db.scalar(
        select(QuoteOffer.status)
        .where(QuoteOffer.quote_version_id == quote_version_id)
        .order_by(QuoteOffer.id.desc())
        .limit(1)
    )
    return status if status in CLOSED_OFFER_STATES else None


def payments_for(db: Session, invoice_id: int) -> list[CustomerPayment]:
    return list(
        db.scalars(
            select(CustomerPayment)
            .where(CustomerPayment.invoice_id == invoice_id)
            .order_by(CustomerPayment.received_at, CustomerPayment.id)
        )
    )


def _recompute(db: Session, invoice: CustomerInvoice) -> bool:
    """Re-derive paid amount and status from the payments. Returns whether any refund exists."""
    rows = payments_for(db, invoice.id)
    paid = sum((p.amount_cad for p in rows if p.kind == "payment"), Decimal(0))
    refunded = sum((p.amount_cad for p in rows if p.kind == "refund"), Decimal(0))
    invoice.paid_cad = paid - refunded
    if invoice.status == "void":
        return refunded > 0
    if invoice.paid_cad >= invoice.total_cad:
        invoice.status = "paid"
    elif invoice.paid_cad > 0:
        invoice.status = "partially_paid"
    else:
        invoice.status = "issued"
    return refunded > 0


#: A VND rate older than this before the invoice date is refused rather than used silently.
VND_RATE_MAX_AGE = timedelta(days=4)


def _invoice_vnd_rate(
    db: Session, invoice: CustomerInvoice
) -> tuple[Decimal, int | None, datetime]:
    """The selling rate a VND payment on this invoice uses (OD-66), frozen per invoice.

    The first VND payment fixes it: the reading in force at the end of the invoice date in the
    business's own time zone. Later VND payments on the same invoice reuse it, so a fetch later
    that day cannot change the rate between two payments. A reading older than
    ``VND_RATE_MAX_AGE`` before that date is refused.
    """
    earlier = db.scalar(
        select(PaymentConversion)
        .join(CustomerPayment, CustomerPayment.id == PaymentConversion.payment_id)
        .where(CustomerPayment.invoice_id == invoice.id)
        .order_by(PaymentConversion.id)
        .limit(1)
    )
    if earlier is not None:
        return earlier.vnd_per_cad, earlier.fx_snapshot_id, earlier.rate_day
    day = _local_date(invoice.issued_at)
    snapshot = _snapshot_for_local_day(db, day)
    if snapshot is None:
        raise ConflictError(
            "No recent Vietcombank rate is recorded for the invoice date, so a VND payment "
            "cannot be converted. Record the day's rate first."
        )
    # A CAD invoice paid in VND is CAD -> VND: the selling rate (OD-73).
    return snapshot.sell_vnd, snapshot.id, datetime(day.year, day.month, day.day)


def _snapshot_for_local_day(db: Session, day: date) -> FxRateSnapshot | None:
    """The reading in force at the end of ``day`` in the business's own time zone, or None
    when it is older than ``VND_RATE_MAX_AGE`` before that day began."""
    from zoneinfo import ZoneInfo  # noqa: PLC0415

    zone = ZoneInfo(settings_timezone())

    def utc(d: date) -> datetime:
        return datetime(d.year, d.month, d.day, tzinfo=zone).astimezone(UTC).replace(tzinfo=None)

    snapshot = fx_service.snapshot_on(db, day, end=utc(day + timedelta(days=1)))
    if snapshot is None or snapshot.retrieved_at < utc(day) - VND_RATE_MAX_AGE:
        return None
    return snapshot


def _local_date(moment: datetime) -> date:
    """The calendar date of a stored (UTC) moment in the business's own time zone."""
    from zoneinfo import ZoneInfo  # noqa: PLC0415

    zone = ZoneInfo(settings_timezone())
    return moment.replace(tzinfo=UTC).astimezone(zone).date()


def settings_timezone() -> str:
    from app.core.config import settings  # noqa: PLC0415

    return settings.default_timezone or "America/Toronto"


def balance(invoice: CustomerInvoice) -> Decimal:
    return invoice.total_cad - invoice.paid_cad


def record_payment(
    db: Session,
    invoice: CustomerInvoice,
    payload: dict[str, Any],
    *,
    actor: User | None,
    now: datetime | None = None,
) -> CustomerPayment:
    now = now or utcnow()
    if invoice.status == "void":
        raise ConflictError("This invoice is void.")
    currency = str(payload.get("currency") or "CAD").upper()
    conversion: PaymentConversion | None = None
    if currency == "CAD":
        amount = _amount(payload.get("amount_cad"), "amount_cad")
    elif currency == "VND":
        # OD-66: Vietcombank's selling rate (third column) on the invoice date.
        amount_vnd = _amount(payload.get("amount_vnd"), "amount_vnd")
        rate, snapshot_id, rate_day = _invoice_vnd_rate(db, invoice)
        amount = _cents(amount_vnd / rate)
        # A VND amount that covers the balance converts to it, not to balance + 1 cent: the
        # customer paid in full, and nothing is kept as credit either way.
        if amount > balance(invoice) and amount - balance(invoice) <= CENT:
            amount = balance(invoice)
        conversion = PaymentConversion(
            amount_vnd=amount_vnd,
            vnd_per_cad=rate,
            fx_snapshot_id=snapshot_id,
            rate_day=rate_day,
        )
    else:
        raise ValidationError("Currency must be CAD or VND.", field="currency")
    if amount > balance(invoice):
        raise ValidationError(
            f"The balance is CAD {balance(invoice)}. A payment cannot exceed it; nothing is "
            "kept on account as credit.",
            field="amount_cad",
        )
    method = str(payload.get("method") or "")
    if method not in PAYMENT_METHODS:
        raise ValidationError(
            f"Method must be one of {', '.join(PAYMENT_METHODS)}.", field="method"
        )
    # A plain date, stored as its own midnight (RC-20): the period month is that date's month.
    received = _received_on(payload.get("received_at"), "received_at", now, actor)
    if is_locked(db, month_of(received), now=now):
        raise ConflictError(
            f"{month_of(received)} is closed (M+7). Admin or Operations must reopen it to record "
            "a payment received in it; do not re-date the payment."
        )
    payment = CustomerPayment(
        invoice_id=invoice.id,
        kind="payment",
        receipt_public_id=identifier_service.next_receipt_public_id(db),
        amount_cad=amount,
        currency=currency,
        method=method,
        reference=(payload.get("reference") or None) and str(payload["reference"])[:120],
        note=(payload.get("note") or None) and str(payload["note"])[:400],
        received_at=received,
        recorded_at=now,
        recorded_by_user_id=actor.id if actor else None,
    )
    db.add(payment)
    db.flush()
    if conversion is not None:
        conversion.payment_id = payment.id
        db.add(conversion)
        db.flush()
    refunded = _recompute(db, invoice)
    _sync_payment_state(db.get(Shipment, invoice.shipment_id), invoice, refunded=refunded)
    db.flush()
    audit_service.record_audit(
        db,
        action="invoice.payment",
        entity_type="customer_invoice",
        entity_id=invoice.public_id,
        summary=f"Recorded CAD {amount} on {invoice.public_id} ({payment.receipt_public_id})",
        actor=actor,
        detail={
            "payment_id": payment.id,
            "method": method,
            "amount_cad": str(amount),
            "currency": currency,
            "amount_vnd": str(conversion.amount_vnd) if conversion else None,
            "vnd_per_cad": str(conversion.vnd_per_cad) if conversion else None,
        },
    )
    return payment


def refund_payment(
    db: Session,
    payment: CustomerPayment,
    payload: dict[str, Any],
    *,
    actor: User | None,
    now: datetime | None = None,
) -> CustomerPayment:
    now = now or utcnow()
    if payment.kind != "payment":
        raise ConflictError("Only a payment can be refunded.")
    invoice = db.get(CustomerInvoice, payment.invoice_id)
    amount = _amount(payload.get("amount_cad"), "amount_cad")
    already = sum(
        (
            r.amount_cad
            for r in payments_for(db, invoice.id)
            if r.kind == "refund" and r.refund_of_payment_id == payment.id
        ),
        Decimal(0),
    )
    if amount > payment.amount_cad - already:
        raise ValidationError(
            f"At most CAD {payment.amount_cad - already} of this payment can be refunded.",
            field="amount_cad",
        )
    reason = _reason(payload.get("reason"))
    method = str(payload.get("method") or payment.method)
    if method not in PAYMENT_METHODS:
        raise ValidationError(
            f"Method must be one of {', '.join(PAYMENT_METHODS)}.", field="method"
        )
    refund = CustomerPayment(
        invoice_id=invoice.id,
        kind="refund",
        refund_of_payment_id=payment.id,
        amount_cad=amount,
        currency="CAD",
        method=method,
        reference=(payload.get("reference") or None) and str(payload["reference"])[:120],
        note=reason,
        # The same plain-date convention as a payment (RC-20): today in the business zone.
        # ``recorded_at`` keeps the exact moment.
        received_at=_received_on(None, "received_at", now),
        recorded_at=now,
        recorded_by_user_id=actor.id if actor else None,
    )
    db.add(refund)
    db.flush()
    refunded = _recompute(db, invoice)
    _sync_payment_state(db.get(Shipment, invoice.shipment_id), invoice, refunded=refunded)
    db.flush()
    audit_service.record_audit(
        db,
        action="invoice.refund",
        entity_type="customer_invoice",
        entity_id=invoice.public_id,
        summary=f"Refunded CAD {amount} of {payment.receipt_public_id} on {invoice.public_id}",
        actor=actor,
        detail={"payment_id": payment.id, "refund_id": refund.id, "reason": reason},
    )
    return refund


def void_invoice(
    db: Session,
    invoice: CustomerInvoice,
    reason: Any,
    *,
    actor: User | None,
    now: datetime | None = None,
) -> CustomerInvoice:
    now = now or utcnow()
    if invoice.status == "void":
        raise ConflictError("This invoice is already void.")
    _recompute(db, invoice)
    if invoice.paid_cad != 0:
        raise ConflictError("Refund the payments on this invoice before voiding it.")
    if is_locked(db, invoice.period_month, now=now):
        raise ConflictError(
            f"{invoice.period_month} is closed (M+7); Admin or Operations must reopen it before "
            "this invoice can be voided."
        )
    invoice.status = "void"
    invoice.voided_at = now
    invoice.voided_by_user_id = actor.id if actor else None
    invoice.void_reason = _reason(reason)
    _sync_payment_state(db.get(Shipment, invoice.shipment_id), invoice)
    db.flush()
    audit_service.record_audit(
        db,
        action="invoice.void",
        entity_type="customer_invoice",
        entity_id=invoice.public_id,
        summary=f"Voided {invoice.public_id}",
        actor=actor,
        detail={"reason": invoice.void_reason},
    )
    return invoice


# --- Customer documents (allowlisted) -----------------------------------------------------------


def tax_layout_of(invoice: CustomerInvoice) -> dict[str, Any] | None:
    """The per-line facts of an invoice issued with the Solaris Invoicing layout (DEC-0235):
    ``{"lines": {sequence: facts}, "rows": [{"label", "tax_cad"}]}``; None for an invoice issued
    before (its lines hold the amounts as entered and it reads as it always did)."""
    document = json.loads(invoice.document_json or "{}")
    if document.get("tax_layout") != tax_math.LAYOUT:
        return None
    return {
        "lines": {row["sequence"]: row for row in document.get("tax_lines") or []},
        "rows": document.get("tax_rows") or [],
    }


def invoice_line_facts(layout: dict[str, Any] | None, line: CustomerInvoiceLine) -> dict[str, Any]:
    """A line's Rate / Tax figures from ``tax_layout_of`` (all None on an older invoice)."""
    facts = (layout or {"lines": {}})["lines"].get(line.sequence)
    if not facts:
        return {"unit_price_cad": None, "tax_cad": None, "gross_cad": None, "tax_code": None}
    return {
        "unit_price_cad": Decimal(facts["unit_price_cad"]),
        "tax_cad": Decimal(facts["tax_cad"]),
        "gross_cad": Decimal(facts["gross_cad"]),
        "tax_code": facts["tax_code"],
    }


def invoice_document(db: Session, invoice: CustomerInvoice) -> dict[str, Any]:
    """The customer's invoice: revenue only, from an allowlist. Never cost, margin, exchange
    rate, vendor name or master siblings. A line that names a vendor reads as a neutral label
    (owner, 2026-10-21, DEC-0222).

    An invoice issued with the Solaris Invoicing layout (DEC-0235) is in English, carries the
    per-line Qty / Rate / Tax and the summary rows, the terms and how to pay, and no "Prices
    include" sentence. An older invoice reads exactly as it did."""
    from app.models import Customer  # noqa: PLC0415
    from app.services import notification_service  # noqa: PLC0415
    from app.services.customer_labels import (  # noqa: PLC0415
        customer_safe_label,
        customer_safe_text,
        vendor_names,
    )

    document = json.loads(invoice.document_json)
    names = vendor_names(db)
    layout = tax_layout_of(invoice)
    language = (
        "en"
        if layout is not None
        else notification_service.language_for(db, db.get(Customer, invoice.customer_id))
    )

    def text(field: str) -> Any:
        # Free text staff typed: only the words naming a vendor are replaced (DEC-0222).
        return customer_safe_text(document.get(field), names, language=language)

    def line_out(line: CustomerInvoiceLine) -> dict[str, Any]:
        out = {
            "description": customer_safe_label(line.description, names, language=language),
            "quantity": line.quantity,
            "unit": line.unit,
            "amount_cad": line.amount_cad,
        }
        if layout is not None:
            out.update(invoice_line_facts(layout, line))
            # Qty blank reads as 1 (DEC-0235).
            out["quantity"] = line.quantity if line.quantity is not None else Decimal(1)
        return out

    if layout is not None:
        rows = layout["rows"]
        tax_note = None
        line_label = rows[0]["label"] if rows else None
    else:
        rows = None
        tax_note = tax_included_note(
            document.get("tax_mode"), invoice.tax_status, language, document.get("tax_label")
        )
        line_label = tax_line_label(invoice.tax_status, language, document.get("tax_label"))
    return {
        **COMPANY,
        "invoice_number": invoice.public_id,
        "status": invoice.status,
        "issued_at": invoice.issued_at,
        "due_at": invoice.due_at,
        "customer_name": text("customer_name"),
        "customer_reference": text("customer_reference"),
        "shipment_reference": document.get("shipment_reference"),
        "service": document.get("service"),
        "currency": invoice.currency,
        # Owner decision 9a: the bill-to details of the draft the invoice was sent from.
        "bill_to_name": text("bill_to_name") or text("customer_name"),
        "bill_to_address": text("bill_to_address"),
        "purchase_order_reference": text("purchase_order_reference"),
        "invoice_notes": text("invoice_notes"),
        "lines": [line_out(line) for line in invoice.lines],
        "subtotal_cad": invoice.subtotal_cad,
        "tax_cad": invoice.tax_cad,
        "tax_status": invoice.tax_status,
        # Owner, 2026-10-22: whether the line amounts include the GST/HST, and the sentence
        # the documents print when they do ("Prices include GST/HST 13 %").
        "tax_mode": document.get("tax_mode") or "added",
        # Not on the Solaris Invoicing layout (DEC-0235): its lines are before tax.
        "tax_included_note": tax_note,
        # Review, 2026-10-24: "HST" / "GST" when the rate came from the province table, else
        # "GST/HST"; and the tax row as printed ("HST 13 %", "Zero-rated (0 %)"; on the new
        # layout the first summary row, "HST ON @ 13%", "GST @ 0%").
        "tax_label": document.get("tax_label") or GENERIC_TAX_LABEL,
        "tax_line_label": line_label,
        "total_cad": invoice.total_cad,
        "paid_cad": invoice.paid_cad,
        "balance_cad": balance(invoice),
        # DEC-0235: the layout, the summary rows, the terms and how to pay.
        "tax_layout": tax_math.LAYOUT if layout is not None else None,
        "tax_rows": rows,
        "payment_terms": invoice_terms(invoice),
        **PAYMENT,
    }


#: The sentence an invoice prints when its prices include the GST/HST (owner, 2026-10-22).
#: The Vietnamese wording is proposed, for review.
TAX_INCLUDED_NOTE = {
    "en": "Prices include {label} {rate} %",
    "vi": "Giá đã bao gồm {label} {rate} %",
}
#: The tax row of a 0 % invoice (review, 2026-10-24; Vietnamese proposed, for review).
ZERO_RATED_LABEL = {"en": "Zero-rated (0 %)", "vi": "Thuế suất 0 (0 %)"}
GENERIC_TAX_LABEL = "GST/HST"
TAX_LABELS = ("GST", "HST", GENERIC_TAX_LABEL)


def _label(label: str | None) -> str:
    return label if label in TAX_LABELS else GENERIC_TAX_LABEL


def tax_line_label(tax_status: str | None, language: str, label: str | None = None) -> str | None:
    """The tax row's label: "HST 13 %", "GST/HST 5 %", "Zero-rated (0 %)"; None when the
    rate is not a GST/HST rate (``review_pending``)."""
    rate = tax_rate_of(tax_status)
    if rate is None:
        return None
    if rate == 0:
        return ZERO_RATED_LABEL["en" if language == "en" else "vi"]
    return f"{_label(label)} {rate} %"


def tax_rate_of(tax_status: str | None) -> int | None:
    """``gst_hst_13`` -> 13; anything else (``review_pending``) -> None."""
    text = str(tax_status or "")
    if not text.startswith("gst_hst_"):
        return None
    try:
        return int(text.rsplit("_", 1)[-1])
    except ValueError:
        return None


def tax_included_note(
    mode: str | None, tax_status: str | None, language: str, label: str | None = None
) -> str | None:
    rate = tax_rate_of(tax_status)
    # At 0 % nothing is included: no "Prices include GST/HST 0 %" (review, 2026-10-22).
    if mode != "included" or not rate:
        return None
    words = TAX_INCLUDED_NOTE["en" if language == "en" else "vi"]
    return words.format(rate=rate, label=_label(label))


def receipt_document(db: Session, payment: CustomerPayment) -> dict[str, Any]:
    from app.models import Customer  # noqa: PLC0415
    from app.services import notification_service  # noqa: PLC0415
    from app.services.customer_labels import customer_safe_text, vendor_names  # noqa: PLC0415

    if payment.kind != "payment" or not payment.receipt_public_id:
        raise NotFoundError("Only a recorded payment has a receipt.")
    invoice = db.get(CustomerInvoice, payment.invoice_id)
    document = json.loads(invoice.document_json)
    names = vendor_names(db)
    language = notification_service.language_for(db, db.get(Customer, invoice.customer_id))

    def text(value: Any) -> Any:
        return customer_safe_text(value, names, language=language)

    conversion = db.scalar(
        select(PaymentConversion).where(PaymentConversion.payment_id == payment.id)
    )
    return {
        **COMPANY,
        "amount_received_vnd": conversion.amount_vnd if conversion else None,
        "conversion_vnd_per_cad": conversion.vnd_per_cad if conversion else None,
        "receipt_number": payment.receipt_public_id,
        "invoice_number": invoice.public_id,
        "received_at": payment.received_at,
        "amount_cad": payment.amount_cad,
        "method": payment.method,
        "reference": text(payment.reference),
        "customer_name": text(document.get("customer_name")),
        "customer_reference": text(document.get("customer_reference")),
        "shipment_reference": document.get("shipment_reference"),
        "invoice_total_cad": invoice.total_cad,
        "balance_cad": balance(invoice),
    }


# --- Vendor bills and actual cost ---------------------------------------------------------------


def get_vendor_invoice(db: Session, vendor_invoice_id: int) -> VendorInvoice:
    row = db.get(VendorInvoice, vendor_invoice_id)
    if row is None:
        raise NotFoundError("Vendor bill not found.")
    return row


def vendor_invoices_for(db: Session, consolidation_id: int) -> list[VendorInvoice]:
    return list(
        db.scalars(
            select(VendorInvoice)
            .where(VendorInvoice.consolidation_id == consolidation_id)
            .order_by(VendorInvoice.entered_at.desc(), VendorInvoice.id.desc())
        )
    )


def _expected(est: pe.Estimate) -> tuple[Decimal | None, Decimal | None]:
    cad: Decimal | None = Decimal(0)
    for member in est.members.values():
        if member.base_cost_cad is None or member.surcharge_cost_cad is None:
            cad = None
            break
        cad += member.base_cost_cad + member.surcharge_cost_cad
    return est.total_cost_vnd, cad


def enter_vendor_invoice(
    db: Session,
    consolidation: Consolidation,
    payload: dict[str, Any],
    *,
    actor: User | None,
    now: datetime | None = None,
) -> VendorInvoice:
    now = now or utcnow()
    if consolidation.state not in {"booked", "completed"}:
        raise ConflictError("A vendor bill is entered for a booked master.")
    if db.scalar(
        select(VendorInvoice).where(
            VendorInvoice.consolidation_id == consolidation.id, VendorInvoice.status != "void"
        )
    ):
        raise ConflictError("This master already has a vendor bill; void it to enter another.")
    currency = str(payload.get("currency") or "").upper()
    if currency not in {"VND", "CAD"}:
        raise ValidationError("Currency must be VND or CAD.", field="currency")
    raw_lines = payload.get("lines") or []
    if not raw_lines:
        raise ValidationError("A vendor bill needs at least one line.", field="lines")
    est, _version = pricing_service.estimate_for(db, consolidation, now=now)
    fee_keys = {fee.key for fee in est.fees}
    billed_at = _moment(payload.get("billed_at"), "billed_at", now)
    # OD-73 (owner, 2026-10-20, superseding OD-67): VND -> CAD at Vietcombank's buy rate
    # (first column) on the bill date.
    snapshot = _snapshot_for_local_day(db, _local_date(billed_at)) if currency == "VND" else None
    if currency == "VND" and snapshot is None:
        raise ConflictError(
            "No recent Vietcombank rate is recorded for the bill date; a VND bill cannot be "
            "put into CAD. Record the day's rate first."
        )
    rate = snapshot.cash_buy_vnd if snapshot else None

    lines: list[VendorInvoiceLine] = []
    total = Decimal(0)
    total_cad = Decimal(0)
    for sequence, raw in enumerate(raw_lines, start=1):
        kind = str(raw.get("kind") or "")
        if kind not in VENDOR_LINE_KINDS:
            raise ValidationError(
                f"Line {sequence}: kind must be one of {', '.join(VENDOR_LINE_KINDS)}.",
                field="lines",
            )
        fee_key = raw.get("fee_key") or None
        if fee_key is not None and (kind != "surcharge" or fee_key not in fee_keys):
            raise ValidationError(
                f"Line {sequence}: that surcharge is not on this master's estimate.",
                field="lines",
            )
        amount = _amount(raw.get("amount"), f"lines[{sequence}].amount")
        description = " ".join(str(raw.get("description") or kind).split())[:300]
        lines.append(
            VendorInvoiceLine(
                sequence=sequence,
                kind=kind,
                fee_key=fee_key,
                description=description,
                amount=amount,
            )
        )
        total += amount
        total_cad += _cents(amount / rate) if rate else amount
    expected_vnd, expected_cad = _expected(est)
    month, adjustment = booking_month(db, master_month(db, consolidation, now), now=now)
    invoice = VendorInvoice(
        public_id=identifier_service.next_vendor_invoice_public_id(db),
        consolidation_id=consolidation.id,
        vendor_bill_number=(payload.get("vendor_bill_number") or None)
        and str(payload["vendor_bill_number"])[:60],
        billed_at=billed_at,
        currency=currency,
        status="entered",
        total_amount=total,
        fx_snapshot_id=snapshot.id if snapshot else None,
        fx_cash_buy_vnd=rate,
        total_cad=total_cad,
        expected_vnd=expected_vnd,
        expected_cad=expected_cad,
        expected_json=json.dumps(pricing_service.estimate_dict(est), ensure_ascii=False),
        variance_cad=(total_cad - expected_cad) if expected_cad is not None else None,
        period_month=month,
        is_adjustment=adjustment,
        entered_at=now,
        entered_by_user_id=actor.id if actor else None,
    )
    invoice.lines.extend(lines)
    db.add(invoice)
    db.flush()
    audit_service.record_audit(
        db,
        action="vendor_invoice.enter",
        entity_type="vendor_invoice",
        entity_id=invoice.public_id,
        summary=(
            f"Entered vendor bill {invoice.public_id} for {consolidation.public_id}: "
            f"{currency} {total}"
        ),
        actor=actor,
        detail={"consolidation_id": consolidation.id, "variance_cad": str(invoice.variance_cad)},
    )
    return invoice


def _allocate_actual(db: Session, invoice: VendorInvoice, est: pe.Estimate) -> list[CostAllocation]:
    """Split each bill line onto shipments, in cents, by the rule the estimate uses.

    Base freight, the piece fee and unkeyed lines go by chargeable-weight share. A surcharge
    line keyed to an estimate fee goes the way the engine splits that fee: a direct fee to its
    own shipment, a master-wide fee by the trigger share (OD-48) -- worked out afresh on the
    billed amount, so it holds even where the estimate could not price the fee. A line that
    cannot be placed is refused, never spread across customers who did not cause it.
    """
    members = sorted(est.members.values(), key=lambda m: m.shipment_id)
    if not members:
        raise ConflictError("The master has no shipments to carry its cost.")
    if any(m.billable_kg is None for m in members):
        raise ConflictError("Every shipment on the master needs a chargeable weight first.")
    ids = [m.shipment_id for m in members]
    weight_of = {m.shipment_id: Fraction(str(m.billable_kg)) for m in members}
    if sum(weight_of.values()) <= 0:
        raise ConflictError("The shipments on the master have no chargeable weight to share by.")
    settings = pricing_service.get_settings(db)
    trigger_share = Fraction(settings.trigger_share_numerator, settings.trigger_share_denominator)
    fees = {fee.key: fee for fee in est.fees}
    rate = invoice.fx_cash_buy_vnd
    rows: list[CostAllocation] = []
    for line in invoice.lines:
        amount_cad = _cents(line.amount / rate) if rate else line.amount
        if line.fee_key:
            fee = fees.get(line.fee_key)
            if fee is None:
                raise ConflictError(
                    f"Line {line.sequence} follows a surcharge that is no longer on the master's "
                    "estimate; void the bill and enter it again."
                )
            split = pe._cost_split(
                dataclasses.replace(fee, vendor_fee_vnd=amount_cad), ids, weight_of, trigger_share
            )
            if not split:
                raise ConflictError(
                    f"Line {line.sequence}: no shipment on the master carries that surcharge."
                )
        else:
            split = pe.allocate(amount_cad, ids, [weight_of[i] for i in ids])
        for shipment_id, part in split.items():
            rows.append(
                CostAllocation(
                    vendor_invoice_id=invoice.id,
                    vendor_invoice_line_id=line.id,
                    shipment_id=shipment_id,
                    amount_cad=part,
                )
            )
    return rows


def approve_vendor_invoice(
    db: Session,
    invoice: VendorInvoice,
    payload: dict[str, Any],
    *,
    actor: User | None,
    now: datetime | None = None,
) -> VendorInvoice:
    now = now or utcnow()
    if invoice.status != "entered":
        raise ConflictError(f"This bill is {invoice.status}; only an entered bill is approved.")
    reason = " ".join(str(payload.get("variance_reason") or "").split()) or None
    if (invoice.variance_cad is None or invoice.variance_cad != 0) and not reason:
        raise ValidationError(
            "The bill differs from the expected cost (or none could be computed); say why "
            "before approving.",
            field="variance_reason",
        )
    consolidation = db.get(Consolidation, invoice.consolidation_id)
    est, _ = pricing_service.estimate_for(db, consolidation, now=now)
    if is_locked(db, invoice.period_month, now=now):
        invoice.period_month, _ = booking_month(db, invoice.period_month, now=now)
        invoice.is_adjustment = True
    db.add_all(_allocate_actual(db, invoice, est))
    invoice.status = "approved"
    invoice.variance_reason = reason[:400] if reason else None
    invoice.approved_at = now
    invoice.approved_by_user_id = actor.id if actor else None
    db.flush()
    audit_service.record_audit(
        db,
        action="vendor_invoice.approve",
        entity_type="vendor_invoice",
        entity_id=invoice.public_id,
        summary=f"Approved vendor bill {invoice.public_id}; actual cost allocated",
        actor=actor,
        detail={"variance_cad": str(invoice.variance_cad), "variance_reason": reason},
    )
    return invoice


def mark_vendor_invoice_paid(
    db: Session,
    invoice: VendorInvoice,
    payload: dict[str, Any],
    *,
    actor: User | None,
    now: datetime | None = None,
) -> VendorInvoice:
    now = now or utcnow()
    if invoice.status != "approved":
        raise ConflictError("Only an approved bill is marked paid.")
    invoice.status = "paid"
    invoice.paid_at = _moment(payload.get("paid_at"), "paid_at", now)
    invoice.paid_reference = (payload.get("reference") or None) and str(payload["reference"])[:120]
    db.flush()
    audit_service.record_audit(
        db,
        action="vendor_invoice.paid",
        entity_type="vendor_invoice",
        entity_id=invoice.public_id,
        summary=f"Marked vendor bill {invoice.public_id} paid",
        actor=actor,
        detail={"reference": invoice.paid_reference},
    )
    return invoice


def void_vendor_invoice(
    db: Session,
    invoice: VendorInvoice,
    reason: Any,
    *,
    actor: User | None,
    now: datetime | None = None,
) -> VendorInvoice:
    now = now or utcnow()
    if invoice.status == "void":
        raise ConflictError("This bill is already void.")
    if invoice.status in {"approved", "paid"} and is_locked(db, invoice.period_month, now=now):
        raise ConflictError(
            f"{invoice.period_month} is closed (M+7); Admin or Operations must reopen it first."
        )
    for row in db.scalars(
        select(CostAllocation).where(CostAllocation.vendor_invoice_id == invoice.id)
    ):
        db.delete(row)
    invoice.status = "void"
    invoice.voided_at = now
    invoice.void_reason = _reason(reason)
    db.flush()
    audit_service.record_audit(
        db,
        action="vendor_invoice.void",
        entity_type="vendor_invoice",
        entity_id=invoice.public_id,
        summary=f"Voided vendor bill {invoice.public_id}",
        actor=actor,
        detail={"reason": invoice.void_reason},
    )
    return invoice


def allocations_for(db: Session, vendor_invoice_id: int) -> dict[int, Decimal]:
    totals: dict[int, Decimal] = {}
    for row in db.scalars(
        select(CostAllocation).where(CostAllocation.vendor_invoice_id == vendor_invoice_id)
    ):
        totals[row.shipment_id] = totals.get(row.shipment_id, Decimal(0)) + row.amount_cad
    return totals


# --- Reports ------------------------------------------------------------------------------------

AGING_BUCKETS = (("current", 0), ("1_30", 30), ("31_60", 60), ("61_90", 90), ("over_90", None))


def _bucket(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "current"
    for name, limit in AGING_BUCKETS[1:]:
        if limit is None or days_overdue <= limit:
            return name
    return "over_90"


def ar_aging(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    rows = []
    totals = {name: Decimal(0) for name, _ in AGING_BUCKETS}
    for invoice in db.scalars(
        select(CustomerInvoice)
        .where(CustomerInvoice.status.in_(("issued", "partially_paid")))
        .order_by(CustomerInvoice.due_at)
    ):
        customer = db.get(Customer, invoice.customer_id)
        overdue = (now.date() - invoice.due_at.date()).days
        bucket = _bucket(overdue)
        owed = balance(invoice)
        totals[bucket] += owed
        rows.append(
            {
                "invoice_id": invoice.id,
                "invoice_number": invoice.public_id,
                "customer_name": customer.full_name if customer else None,
                "customer_reference": customer.public_id if customer else None,
                "issued_at": invoice.issued_at,
                "due_at": invoice.due_at,
                "total_cad": invoice.total_cad,
                "paid_cad": invoice.paid_cad,
                "balance_cad": owed,
                "days_overdue": max(overdue, 0),
                "bucket": bucket,
            }
        )
    return {
        "as_of": now,
        "rows": rows,
        "totals": totals,
        "total_cad": sum(totals.values(), Decimal(0)),
    }


def accounts_payable(db: Session) -> dict[str, Any]:
    rows = []
    owed = Decimal(0)
    for invoice in db.scalars(
        select(VendorInvoice)
        .where(VendorInvoice.status.in_(("entered", "approved")))
        .order_by(VendorInvoice.billed_at)
    ):
        consolidation = db.get(Consolidation, invoice.consolidation_id)
        rows.append(
            {
                "vendor_invoice_id": invoice.id,
                "public_id": invoice.public_id,
                "consolidation_id": invoice.consolidation_id,
                "consolidation_reference": consolidation.public_id if consolidation else None,
                "vendor_bill_number": invoice.vendor_bill_number,
                "status": invoice.status,
                "billed_at": invoice.billed_at,
                "currency": invoice.currency,
                "total_amount": invoice.total_amount,
                "total_cad": invoice.total_cad,
            }
        )
        owed += invoice.total_cad
    return {"rows": rows, "total_cad": owed}


def _margin(profit: Decimal | None, revenue: Decimal) -> Decimal | None:
    if profit is None or revenue <= 0:
        return None
    return (profit / revenue * 100).quantize(Decimal("0.1"))


def profitability(db: Session, month: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Management profitability for one revenue month (hand-in month), CAD.

    * **Revenue**: invoices booked in the month (late adjustments included).
    * **Matched cost** for each invoiced shipment: its share of an approved vendor bill booked
      in the month when there is one (``actual``), else its finalised quote's cost
      (``estimated``). Profit and margin are revenue minus matched cost, so a margin never
      sets one customer's revenue against three customers' bill.
    * **Unmatched cost**: bill shares booked in the month for shipments with no invoice in
      the month (not yet invoiced, or invoiced in a later month as an adjustment). Shown
      beside the figures, never silently netted against someone else's revenue.

    An internal management convention, not an accounting statement (handoff section 9).
    """
    _parse_month(month)
    invoices = list(
        db.scalars(
            select(CustomerInvoice).where(
                CustomerInvoice.period_month == month, CustomerInvoice.status != "void"
            )
        )
    )
    bills = list(
        db.scalars(
            select(VendorInvoice).where(
                VendorInvoice.period_month == month,
                VendorInvoice.status.in_(("approved", "paid")),
            )
        )
    )
    # shipment -> (master, actual share) from this month's approved bills.
    actual: dict[int, Decimal] = {}
    bill_master: dict[int, int] = {}
    for bill in bills:
        for shipment_id, amount in allocations_for(db, bill.id).items():
            actual[shipment_id] = actual.get(shipment_id, Decimal(0)) + amount
            bill_master[shipment_id] = bill.consolidation_id

    def blank(key: int | None) -> dict[str, Any]:
        consolidation = db.get(Consolidation, key) if key else None
        return {
            "consolidation_id": key,
            "consolidation_reference": consolidation.public_id if consolidation else None,
            "service": consolidation.solaris_service if consolidation else None,
            "origin": consolidation.origin if consolidation else None,
            "shipments": 0,
            "customers": set(),
            "billable_kg": Decimal(0),
            "revenue_cad": Decimal(0),
            "estimated_cost_cad": Decimal(0),
            "actual_cost_cad": None,
            "matched_cost_cad": Decimal(0),
            "unmatched_cost_cad": Decimal(0),
            "actual_shipments": 0,
            "adjustments": 0,
        }

    masters: dict[int | None, dict[str, Any]] = {}
    invoiced: set[int] = set()
    for invoice in invoices:
        version = db.get(QuoteVersion, invoice.quote_version_id)
        row = masters.setdefault(invoice.consolidation_id, blank(invoice.consolidation_id))
        estimated = version.allocated_cost_cad or Decimal(0)
        share = actual.get(invoice.shipment_id)
        row["shipments"] += 1
        row["customers"].add(invoice.customer_id)
        row["billable_kg"] += version.billable_weight_kg or Decimal(0)
        # Revenue is before GST/HST: the tax is owed to the government, not earned (OD-64).
        row["revenue_cad"] += invoice.subtotal_cad
        row["estimated_cost_cad"] += estimated
        if share is not None:
            row["actual_cost_cad"] = (row["actual_cost_cad"] or Decimal(0)) + share
            row["actual_shipments"] += 1
        row["matched_cost_cad"] += share if share is not None else estimated
        row["adjustments"] += int(invoice.is_adjustment)
        invoiced.add(invoice.shipment_id)
    for shipment_id, amount in actual.items():
        if shipment_id not in invoiced:
            row = masters.setdefault(bill_master[shipment_id], blank(bill_master[shipment_id]))
            row["unmatched_cost_cad"] += amount

    rows_out = []
    summary = {
        "masters": 0,
        "shipments": 0,
        "customers": set(),
        "billable_kg": Decimal(0),
        "revenue_cad": Decimal(0),
        "estimated_cost_cad": Decimal(0),
        "actual_cost_cad": Decimal(0),
        "matched_cost_cad": Decimal(0),
        "unmatched_cost_cad": Decimal(0),
    }
    splits: dict[tuple[str, str], dict[str, Decimal]] = {}
    for row in masters.values():
        profit = row["revenue_cad"] - row["matched_cost_cad"]
        if row["shipments"] == 0:
            basis = "none"
        elif row["actual_shipments"] == row["shipments"]:
            basis = "actual"
        elif row["actual_shipments"] == 0:
            basis = "estimated"
        else:
            basis = "mixed"
        rows_out.append(
            {
                **{k: v for k, v in row.items() if k not in {"customers", "actual_shipments"}},
                "customers": len(row["customers"]),
                "cost_basis": basis,
                "profit_cad": profit,
                "margin_percent": _margin(profit, row["revenue_cad"]),
            }
        )
        summary["masters"] += 1
        summary["shipments"] += row["shipments"]
        summary["customers"] |= row["customers"]
        for key in (
            "billable_kg",
            "revenue_cad",
            "estimated_cost_cad",
            "matched_cost_cad",
            "unmatched_cost_cad",
        ):
            summary[key] += row[key]
        summary["actual_cost_cad"] += row["actual_cost_cad"] or Decimal(0)
        split = splits.setdefault(
            (row["service"] or "unassigned", row["origin"] or "—"),
            {"revenue_cad": Decimal(0), "matched_cost_cad": Decimal(0)},
        )
        split["revenue_cad"] += row["revenue_cad"]
        split["matched_cost_cad"] += row["matched_cost_cad"]
    profit = summary["revenue_cad"] - summary["matched_cost_cad"]
    kg = summary["billable_kg"]
    return {
        "month": month,
        "state": period_state(db, month, now=now),
        "lock_date": lock_date(month),
        "summary": {
            **{k: v for k, v in summary.items() if k != "customers"},
            "customers": len(summary["customers"]),
            "profit_cad": profit,
            "margin_percent": _margin(profit, summary["revenue_cad"]),
            "revenue_per_kg_cad": _cents(summary["revenue_cad"] / kg) if kg else None,
            "cost_per_kg_cad": _cents(summary["matched_cost_cad"] / kg) if kg else None,
            "profit_per_kg_cad": _cents(profit / kg) if kg else None,
        },
        "masters": sorted(rows_out, key=lambda r: r["consolidation_reference"] or ""),
        "splits": [
            {
                "service": service,
                "origin": origin,
                **values,
                "profit_cad": values["revenue_cad"] - values["matched_cost_cad"],
            }
            for (service, origin), values in sorted(splits.items())
        ],
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


def normalise_month(month: str) -> str:
    """``YYYY-MM`` exactly; ``2026-1`` and other spellings are refused."""
    if not re.fullmatch(r"\d{4}-\d{2}", month or ""):
        raise ValidationError("A month is written YYYY-MM.", field="month")
    return month_of(_parse_month(month))


def close_month(
    db: Session, month: str, *, actor: User | None, now: datetime | None = None
) -> PeriodClose:
    now = now or utcnow()
    month = normalise_month(month)
    state = period_state(db, month, now=now)
    if state == "open":
        raise ConflictError(f"{month} locks on {lock_date(month).date()} (M+7); it is still open.")
    if state == "closed":
        raise ConflictError(f"{month} is already closed.")
    previous = latest_close(db, month)
    close = PeriodClose(
        month=month,
        version=(previous.version + 1) if previous else 1,
        closed_at=now,
        closed_by_user_id=actor.id if actor else None,
        snapshot_json=json.dumps(_jsonable(profitability(db, month, now=now)), ensure_ascii=False),
    )
    db.add(close)
    db.flush()
    audit_service.record_audit(
        db,
        action="period.close",
        entity_type="period",
        entity_id=month,
        summary=f"Closed {month} (version {close.version}); figures frozen",
        actor=actor,
        detail={"version": close.version},
    )
    return close


def reopen_month(
    db: Session, month: str, reason: Any, *, actor: User | None, now: datetime | None = None
) -> PeriodClose:
    now = now or utcnow()
    month = normalise_month(month)
    close = latest_close(db, month)
    if close is None or close.reopened_at is not None:
        raise ConflictError(f"{month} is not closed.")
    close.reopened_at = now
    close.reopened_by_user_id = actor.id if actor else None
    close.reopen_reason = _reason(reason)
    db.flush()
    audit_service.record_audit(
        db,
        action="period.reopen",
        entity_type="period",
        entity_id=month,
        summary=f"Reopened {month}",
        actor=actor,
        detail={"reason": close.reopen_reason, "version": close.version},
    )
    return close


def periods(db: Session, *, now: datetime | None = None, count: int = 12) -> list[dict[str, Any]]:
    """The last ``count`` months, newest first, with their lock state."""
    now = now or utcnow()
    month = month_of(now)
    out = []
    for _ in range(count):
        close = latest_close(db, month)
        out.append(
            {
                "month": month,
                "state": period_state(db, month, now=now),
                "lock_date": lock_date(month),
                "closed_at": close.closed_at if close else None,
                "version": close.version if close else None,
                "reopened_at": close.reopened_at if close else None,
                "reopen_reason": close.reopen_reason if close else None,
            }
        )
        first = _parse_month(month)
        month = month_of(date(first.year - (first.month == 1), (first.month - 2) % 12 + 1, 1))
    return out


def closed_snapshot(db: Session, month: str) -> dict[str, Any] | None:
    close = latest_close(db, month)
    if close is None or close.reopened_at is not None:
        return None
    return json.loads(close.snapshot_json)


def period_row(db: Session, month: str, *, now: datetime | None = None) -> dict[str, Any]:
    close = latest_close(db, month)
    return {
        "month": month,
        "state": period_state(db, month, now=now),
        "lock_date": lock_date(month),
        "closed_at": close.closed_at if close else None,
        "version": close.version if close else None,
        "reopened_at": close.reopened_at if close else None,
        "reopen_reason": close.reopen_reason if close else None,
    }
