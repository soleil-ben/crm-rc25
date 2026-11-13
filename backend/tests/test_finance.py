"""Phase 13E finance: invoices, payments, refunds, vendor bills, actual cost, periods (air only)."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.core.enums import PaymentState, Role
from app.core.time_utils import utcnow
from app.models import AuditEvent, CostAllocation
from app.services import consolidation_service as cs
from app.services import finance_service as fs
from app.services import fx_service
from app.services import pricing_service as ps
from app.services.errors import ConflictError, ValidationError
from tests.test_quotes import _fee, priced_world  # noqa: F401  (fixture)


def _finalize(db, shipment, reason=None):
    ps.confirm_rate(db, shipment, rate=None, reason=None, actor=None)
    db.commit()
    version = ps.finalize(db, shipment, negative_margin_reason=reason, actor=None)
    db.commit()
    return version


@pytest.fixture
def invoiced(db, priced_world):  # noqa: F811
    con, kids = priced_world
    _finalize(db, kids[0])
    invoice = fs.issue_invoice(db, kids[0], actor=None)
    db.commit()
    return con, kids, invoice


# --- Invoices -----------------------------------------------------------------------------------


def test_an_invoice_needs_a_finalised_quote_and_carries_revenue_only(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    with pytest.raises(ConflictError, match="Finalise"):
        fs.issue_invoice(db, kids[0], actor=None)
    db.rollback()
    _finalize(db, kids[0])
    invoice = fs.issue_invoice(db, kids[0], actor=None)
    db.commit()
    assert invoice.public_id == "INV-000001"
    # 3 kg x CAD 19.00 (v0.5: under 21 kg, DEC-0252); GST/HST defaults to 0 % (OD-64).
    assert (invoice.total_cad, invoice.tax_cad, invoice.tax_status) == (
        Decimal("57.00"),
        Decimal("0.00"),
        "gst_hst_0",
    )
    assert [line.amount_cad for line in invoice.lines] == [Decimal("57.00")]
    assert kids[0].payment_state == PaymentState.UNPAID
    with pytest.raises(ConflictError, match="already has an invoice"):
        fs.issue_invoice(db, kids[0], actor=None)


def test_the_customer_document_is_an_allowlist(db, invoiced):
    _con, kids, invoice = invoiced
    document = fs.invoice_document(db, invoice)
    keys = set(document) | {k for line in document["lines"] for k in line}
    # Field names, not values: a random shipment reference may well contain "FX".
    for forbidden in ("cost", "margin", "fx", "rate", "vendor", "consolidation", "profit"):
        assert not any(forbidden in key for key in keys), forbidden
    assert "kango" not in str(document).lower()
    assert document["shipment_reference"] == kids[0].public_id


# --- Payments, refunds, voids -------------------------------------------------------------------


def test_payments_are_cad_never_exceed_the_balance_and_each_has_a_receipt(db, invoiced):
    _con, kids, invoice = invoiced
    first = fs.record_payment(
        db, invoice, {"amount_cad": "20.00", "method": "e_transfer"}, actor=None
    )
    db.commit()
    assert (invoice.status, invoice.paid_cad, first.receipt_public_id) == (
        "partially_paid",
        Decimal("20.00"),
        "RCT-000001",
    )
    with pytest.raises(ValidationError, match="credit"):
        fs.record_payment(db, invoice, {"amount_cad": "37.01", "method": "cash"}, actor=None)
    db.rollback()
    with pytest.raises(ValidationError, match="CAD or VND"):
        fs.record_payment(
            db, invoice, {"amount_cad": "1", "method": "cash", "currency": "USD"}, actor=None
        )
    db.rollback()
    with pytest.raises(ValidationError, match="future"):
        fs.record_payment(
            db,
            invoice,
            {"amount_cad": "1", "method": "cash", "received_at": utcnow() + timedelta(days=2)},
            actor=None,
        )
    db.rollback()
    fs.record_payment(db, invoice, {"amount_cad": "37.00", "method": "cash"}, actor=None)
    db.commit()
    assert invoice.status == "paid" and kids[0].payment_state == PaymentState.PAID
    receipt = fs.receipt_document(db, first)
    assert receipt["receipt_number"] == "RCT-000001" and receipt["balance_cad"] == 0


def test_refunds_are_bounded_and_a_void_needs_the_money_returned(db, invoiced):
    _con, kids, invoice = invoiced
    payment = fs.record_payment(db, invoice, {"amount_cad": "57.00", "method": "cash"}, actor=None)
    db.commit()
    with pytest.raises(ValidationError, match="At most"):
        fs.refund_payment(db, payment, {"amount_cad": "60", "reason": "x"}, actor=None)
    db.rollback()
    with pytest.raises(ValidationError, match="reason"):
        fs.refund_payment(db, payment, {"amount_cad": "10", "reason": " "}, actor=None)
    db.rollback()
    with pytest.raises(ConflictError, match="Refund"):
        fs.void_invoice(db, invoice, "wrong customer", actor=None)
    db.rollback()
    fs.refund_payment(db, payment, {"amount_cad": "57.00", "reason": "Cancelled"}, actor=None)
    db.commit()
    assert (invoice.status, invoice.paid_cad) == ("issued", Decimal("0.00"))
    assert kids[0].payment_state == PaymentState.REFUNDED
    fs.void_invoice(db, invoice, "Issued to the wrong payer", actor=None)
    db.commit()
    assert invoice.status == "void"
    second = fs.issue_invoice(db, kids[0], actor=None)
    db.commit()
    assert second.public_id == "INV-000002"  # numbers are never reused
    actions = [a.action for a in db.query(AuditEvent)]
    for action in ("invoice.issue", "invoice.payment", "invoice.refund", "invoice.void"):
        assert action in actions


# --- Vendor bills and actual cost ---------------------------------------------------------------


def _book(db, con):
    cs.book_consolidation(db, con, actor=None)
    db.commit()


def test_a_vendor_bill_is_reconciled_and_split_exactly(db, priced_world):  # noqa: F811
    con, kids = priced_world
    _fee(db, kids[1], "hcm_air", 14, description="Fake clothing")
    with pytest.raises(ConflictError, match="booked"):
        fs.enter_vendor_invoice(
            db, con, {"currency": "VND", "lines": [{"kind": "base", "amount": "1"}]}, actor=None
        )
    db.rollback()
    _book(db, con)
    est, _ = ps.estimate_for(db, con)
    fake = next(f for f in est.fees if f.stt == 14)
    bill = fs.enter_vendor_invoice(
        db,
        con,
        {
            "currency": "VND",
            "vendor_bill_number": "KG-7781",
            "lines": [
                {"kind": "base", "amount": "5103000"},
                {"kind": "surcharge", "fee_key": fake.key, "amount": "630000"},
                {"kind": "other", "description": "Late handling", "amount": "100000"},
            ],
        },
        actor=None,
    )
    db.commit()
    assert bill.public_id == "VB-000001" and bill.status == "entered"
    assert bill.variance_cad is not None and bill.variance_cad > 0  # the late line
    with pytest.raises(ValidationError, match="say why"):
        fs.approve_vendor_invoice(db, bill, {}, actor=None)
    db.rollback()
    fs.approve_vendor_invoice(db, bill, {"variance_reason": "Late handling fee"}, actor=None)
    db.commit()
    allocations = fs.allocations_for(db, bill.id)
    assert sum(allocations.values()) == bill.total_cad  # to the cent
    # The fake-clothing line follows the engine's split: 2/3 to the trigger.
    fake_line = next(line for line in bill.lines if line.kind == "surcharge")
    rows = db.query(CostAllocation).filter_by(vendor_invoice_line_id=fake_line.id).all()
    share = {r.shipment_id: r.amount_cad for r in rows}
    assert share[kids[1].id] > share[kids[0].id] and share[kids[0].id] == share[kids[2].id]
    assert fs.accounts_payable(db)["rows"][0]["public_id"] == "VB-000001"
    fs.mark_vendor_invoice_paid(db, bill, {"reference": "VCB-123"}, actor=None)
    db.commit()
    assert fs.accounts_payable(db)["rows"] == []


def test_a_cad_bill_is_not_converted_twice(db, priced_world):  # noqa: F811
    con, _kids = priced_world
    _book(db, con)
    bill = fs.enter_vendor_invoice(
        db, con, {"currency": "CAD", "lines": [{"kind": "base", "amount": "280.00"}]}, actor=None
    )
    assert (bill.total_cad, bill.fx_cash_buy_vnd) == (Decimal("280.00"), None)


# --- Periods (M+7) ------------------------------------------------------------------------------


def test_a_month_locks_seven_days_after_it_ends(db):
    assert fs.lock_date("2026-09") == datetime(2026, 10, 8)
    assert fs.lock_date("2026-12") == datetime(2027, 1, 8)
    assert fs.period_state(db, "2026-09", now=datetime(2026, 10, 7, 23, 59)) == "open"
    assert fs.period_state(db, "2026-09", now=datetime(2026, 10, 8)) == "locked"


def test_late_figures_become_next_month_adjustments(db, priced_world):  # noqa: F811
    con, kids = priced_world
    con.handed_over_at = datetime(2026, 8, 28)  # August locked on 8 September
    db.commit()
    _finalize(db, kids[0])
    now = datetime(2026, 10, 20)
    invoice = fs.issue_invoice(db, kids[0], actor=None, now=now)
    db.commit()
    assert (invoice.period_month, invoice.is_adjustment) == ("2026-10", True)
    with pytest.raises(ConflictError, match="closed"):
        fs.record_payment(
            db,
            invoice,
            {"amount_cad": "1", "method": "cash", "received_at": datetime(2026, 9, 2)},
            actor=None,
            now=now,
        )


def test_close_freezes_the_figures_and_reopen_is_reasoned(db, invoiced):
    _con, _kids, invoice = invoiced
    month = invoice.period_month
    early = fs.lock_date(month) - timedelta(days=1)
    with pytest.raises(ConflictError, match="still open"):
        fs.close_month(db, month, actor=None, now=early)
    db.rollback()
    later = fs.lock_date(month) + timedelta(days=1)
    close = fs.close_month(db, month, actor=None, now=later)
    db.commit()
    assert close.version == 1 and fs.period_state(db, month, now=later) == "closed"
    assert fs.closed_snapshot(db, month)["summary"]["revenue_cad"] == "57.00"
    with pytest.raises(ConflictError, match="closed"):
        fs.void_invoice(db, invoice, "late", actor=None, now=later)
    db.rollback()
    with pytest.raises(ValidationError, match="reason"):
        fs.reopen_month(db, month, "", actor=None, now=later)
    db.rollback()
    fs.reopen_month(db, month, "Late vendor credit", actor=None, now=later)
    db.commit()
    assert fs.period_state(db, month, now=later) == "reopened"
    assert fs.close_month(db, month, actor=None, now=later).version == 2


# --- Reports ------------------------------------------------------------------------------------


def test_profitability_uses_actual_cost_once_the_bill_is_approved(db, invoiced):
    con, _kids, invoice = invoiced
    report = fs.profitability(db, invoice.period_month)
    row = report["masters"][0]
    assert (row["revenue_cad"], row["cost_basis"]) == (Decimal("57.00"), "estimated")
    _book(db, con)
    bill = fs.enter_vendor_invoice(
        db, con, {"currency": "VND", "lines": [{"kind": "base", "amount": "5103000"}]}, actor=None
    )
    fs.approve_vendor_invoice(db, bill, {"variance_reason": "rate moved"}, actor=None)
    db.commit()
    report = fs.profitability(db, invoice.period_month)
    row = report["masters"][0]
    share = fs.allocations_for(db, bill.id)
    assert row["cost_basis"] == "actual"
    # Only the invoiced shipment's share is matched to its revenue; the other two shares
    # are shown as unmatched, never netted against this customer's revenue.
    assert row["matched_cost_cad"] == share[invoice.shipment_id]
    assert row["unmatched_cost_cad"] == bill.total_cad - share[invoice.shipment_id]
    assert report["summary"]["profit_cad"] == row["revenue_cad"] - share[invoice.shipment_id]


def test_ar_aging_buckets_by_days_overdue(db, invoiced):
    _con, _kids, invoice = invoiced
    report = fs.ar_aging(db, now=invoice.due_at + timedelta(days=45))
    assert report["rows"][0]["bucket"] == "31_60"
    assert report["totals"]["31_60"] == Decimal("57.00")


# --- HTTP and permissions -----------------------------------------------------------------------


def test_permissions_follow_revenue_cost_and_adjustment(api_for, db, invoiced):
    con, kids, invoice = invoiced
    ops = api_for(Role.OPERATIONS)
    assert ops.get(f"/api/v1/invoices/{invoice.id}").status_code == 200
    paid = ops.post(
        f"/api/v1/invoices/{invoice.id}/payments", json={"amount_cad": "57", "method": "cash"}
    )
    assert paid.status_code == 201
    payment_id = paid.json()["payments"][0]["id"]
    # Refunds, voids and reopening: Admin and Operations (OD-69).
    assert (
        ops.post(
            f"/api/v1/payments/{payment_id}/refund", json={"amount_cad": "1", "reason": "x"}
        ).status_code
        == 201
    )
    admin = api_for(Role.ADMIN)
    assert (
        admin.post(
            f"/api/v1/payments/{payment_id}/refund", json={"amount_cad": "1", "reason": "x"}
        ).status_code
        == 201
    )
    manager = api_for(Role.READ_ONLY_MANAGER)
    assert manager.get(f"/api/v1/invoices/{invoice.id}").status_code == 200
    assert manager.get("/api/v1/finance/ar-aging").status_code == 200
    assert manager.post(f"/api/v1/shipments/{kids[1].id}/invoice").status_code == 403
    # Cost: no tariff:read, no vendor bills or profitability.
    assert manager.get(f"/api/v1/consolidations/{con.id}/vendor-invoices").status_code == 403
    assert manager.get("/api/v1/finance/profitability?month=2026-10").status_code == 403
    marketing = api_for(Role.MARKETING)
    assert marketing.get(f"/api/v1/invoices/{invoice.id}").status_code == 403
    # Exports need export:reports (Admin) and are audited. (One cookie jar: each client is
    # used straight after it signs in.)
    ops = api_for(Role.OPERATIONS)
    assert ops.get("/api/v1/finance/ar-aging.csv").status_code == 403
    admin = api_for(Role.ADMIN)
    exported = admin.get("/api/v1/finance/ar-aging.csv")
    assert exported.status_code == 200 and exported.text.startswith("invoice,")


def test_the_document_route_never_carries_cost(api_for, db, invoiced):
    _con, _kids, invoice = invoiced
    body = api_for(Role.ADMIN).get(f"/api/v1/invoices/{invoice.id}/document").text.lower()
    for forbidden in ("cost", "margin", "cash_buy", "vendor", "kango", "mst-"):
        assert forbidden not in body, forbidden


# --- Independent review, 2026-10-20 -------------------------------------------------------------


def test_an_unpriced_direct_surcharge_is_billed_to_its_own_shipment_only(db, priced_world):  # noqa: F811
    con, kids = priced_world
    # A battery carton above 8 kg has no estimate price (blocking), but it is still one
    # customer's fee: the vendor's charge for it must not spread across the master.
    _fee(db, kids[1], "hcm_air", 3, description="Pin", weight_kg="9")
    _book(db, con)
    est, _ = ps.estimate_for(db, con)
    battery = next(f for f in est.fees if f.stt == 3)
    assert battery.vendor_fee_vnd is None
    bill = fs.enter_vendor_invoice(
        db,
        con,
        {
            "currency": "CAD",
            "lines": [{"kind": "surcharge", "fee_key": battery.key, "amount": "50"}],
        },
        actor=None,
    )
    fs.approve_vendor_invoice(db, bill, {"variance_reason": "quoted by vendor"}, actor=None)
    db.commit()
    assert fs.allocations_for(db, bill.id) == {kids[1].id: Decimal("50.00")}


def test_revenue_and_its_bill_share_one_month_when_hand_in_is_recorded_late(db, priced_world):  # noqa: F811
    con, kids = priced_world
    _finalize(db, kids[0])
    invoice = fs.issue_invoice(db, kids[0], actor=None, now=datetime(2026, 10, 28))
    db.commit()
    _book(db, con)
    con.handed_over_at = datetime(2026, 11, 2)  # recorded after the invoice
    db.commit()
    bill = fs.enter_vendor_invoice(
        db,
        con,
        {"currency": "CAD", "lines": [{"kind": "base", "amount": "280"}]},
        actor=None,
        now=datetime(2026, 11, 5),
    )
    assert bill.period_month == invoice.period_month


def test_months_must_be_written_yyyy_mm(db, api_for):
    with pytest.raises(ValidationError, match="YYYY-MM"):
        fs.close_month(db, "2026-1", actor=None)
    admin = api_for(Role.ADMIN)
    assert admin.post("/api/v1/finance/periods/2026-1/close").status_code == 422


def test_a_timezone_aware_payment_date_is_accepted_and_kept_as_its_written_date(db, invoiced):
    # RC-20: a received date is a plain date; the offset never moves it to another day.
    _con, _kids, invoice = invoiced
    payment = fs.record_payment(
        db,
        invoice,
        {"amount_cad": "1", "method": "cash", "received_at": "2026-10-15T03:00:00+07:00"},
        actor=None,
    )
    assert payment.received_at == datetime(2026, 10, 15)


def test_csv_cells_cannot_become_formulas(api_for, db, invoiced):
    _con, kids, invoice = invoiced
    from app.models import Customer

    db.get(Customer, invoice.customer_id).full_name = '=HYPERLINK("http://x")'
    db.commit()
    body = api_for(Role.ADMIN).get("/api/v1/finance/ar-aging.csv").text
    assert ",=HYPERLINK" not in body and "'=HYPERLINK" in body


def test_admin_can_void_a_bill_marked_paid_by_mistake(db, priced_world):  # noqa: F811
    con, _kids = priced_world
    _book(db, con)
    bill = fs.enter_vendor_invoice(
        db, con, {"currency": "CAD", "lines": [{"kind": "base", "amount": "280"}]}, actor=None
    )
    fs.approve_vendor_invoice(db, bill, {"variance_reason": "x"}, actor=None)
    fs.mark_vendor_invoice_paid(db, bill, {}, actor=None)
    fs.void_vendor_invoice(db, bill, "Marked paid by mistake", actor=None)
    db.commit()
    assert bill.status == "void" and fs.allocations_for(db, bill.id) == {}


# --- Owner answers, 2026-10-20 ------------------------------------------------------------------


def test_staff_choose_gst_hst_per_invoice(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    _finalize(db, kids[0])
    with pytest.raises(ValidationError, match="GST/HST"):
        fs.issue_invoice(db, kids[0], actor=None, tax_rate_percent=7)
    db.rollback()
    invoice = fs.issue_invoice(db, kids[0], actor=None, tax_rate_percent=13)
    db.commit()
    # 57.00 + 13 % = 7.41 tax.
    assert (invoice.subtotal_cad, invoice.tax_cad, invoice.total_cad) == (
        Decimal("57.00"),
        Decimal("7.41"),
        Decimal("64.41"),
    )
    document = fs.invoice_document(db, invoice)
    assert document["company_business_number"] == "795093756RT0001"
    assert "L5A 3K6" in document["company_address"]


def test_a_vnd_payment_converts_at_the_selling_rate_of_the_invoice_date(db, invoiced):
    _con, _kids, invoice = invoiced
    snapshot = fx_service.snapshot_on(db, invoice.issued_at.date())
    payment = fs.record_payment(
        db,
        invoice,
        {"currency": "VND", "amount_vnd": "500000", "method": "bank_transfer"},
        actor=None,
    )
    db.commit()
    assert payment.currency == "VND"
    assert payment.amount_cad == fs._cents(Decimal(500000) / snapshot.sell_vnd)
    receipt = fs.receipt_document(db, payment)
    assert receipt["amount_received_vnd"] == Decimal("500000.00")
    assert receipt["conversion_vnd_per_cad"] == snapshot.sell_vnd
    # Still no credit: a VND payment worth more than the balance is refused.
    with pytest.raises(ValidationError, match="credit"):
        fs.record_payment(
            db, invoice, {"currency": "VND", "amount_vnd": "5000000", "method": "cash"}, actor=None
        )


def test_profitability_revenue_excludes_gst_hst(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    _finalize(db, kids[0])
    invoice = fs.issue_invoice(db, kids[0], actor=None, tax_rate_percent=13)
    db.commit()
    row = fs.profitability(db, invoice.period_month)["masters"][0]
    assert row["revenue_cad"] == Decimal("57.00")  # not 64.41


def test_the_vnd_rate_is_frozen_per_invoice_and_a_full_payment_settles_exactly(
    db, invoiced, monkeypatch
):
    from datetime import timedelta

    from app.core.time_utils import utcnow
    from tests.test_fx_service import SAMPLE_XML

    _con, _kids, invoice = invoiced
    first = fs.record_payment(
        db, invoice, {"currency": "VND", "amount_vnd": "100000", "method": "cash"}, actor=None
    )
    db.commit()
    rate = fs._invoice_vnd_rate(db, invoice)[0]
    # A later reading on the same day does not move the rate for the next VND payment.
    newer = SAMPLE_XML.replace(b"18,645.39", b"19,000.00")
    fx_service.sync_once(
        db, fetcher=lambda _u: newer, clock=lambda: utcnow() + timedelta(minutes=1), worker_name="t"
    )
    db.commit()
    assert fs._invoice_vnd_rate(db, invoice)[0] == rate
    # Paying the rest in VND, rounded up to the dong, settles the balance exactly.
    remaining_vnd = (fs.balance(invoice) * rate).quantize(Decimal("1")) + 1
    fs.record_payment(
        db,
        invoice,
        {"currency": "VND", "amount_vnd": str(remaining_vnd), "method": "cash"},
        actor=None,
    )
    db.commit()
    assert fs.balance(invoice) == Decimal("0.00") and invoice.status == "paid"
    assert first.amount_cad > 0
