"""Phase 13E finance, written independently from the owner's rules (DEC-0201..0204, OD-64..69).

Scenario tests over the service and the HTTP surface, air only. Time is controlled with the
services' ``now=`` parameters wherever a period boundary matters. The HTTP routes take the
real clock, so the HTTP period tests use a month two months back, which is always locked.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import OperationalError

from app.core.db import run_unit_with_retry
from app.core.enums import PaymentState, Role
from app.core.time_utils import utcnow
from app.models import AuditEvent, CostAllocation, CustomerInvoice
from app.services import audit_service, booking_service, fx_service
from app.services import consolidation_service as cs
from app.services import finance_service as fs
from app.services import pricing_method_service as pms
from app.services import pricing_service as ps
from app.services.errors import ConflictError, ValidationError
from tests.conftest import make_customer, see_committed_changes
from tests.test_fx_service import SAMPLE_XML
from tests.test_quotes import _fee, priced_world  # noqa: F401  (fixture)

CASH_BUY = Decimal("17886.61")  # SAMPLE_XML's CAD cash-buying rate
SELL = Decimal("18645.39")  # its selling rate: VND customer payments (OD-66)
FORBIDDEN_DOCUMENT_NAMES = (
    "cost",
    "margin",
    "fx",
    "rate",
    "vendor",
    "master",
    "consolidation",
    "profit",
    "allocat",
    "cash_buy",
    "variance",
    "quote",
)


def _finalize(db, shipment, reason="test: pass-through policy pending"):
    ps.confirm_rate(db, shipment, rate=None, reason=None, actor=None)
    db.commit()
    version = ps.finalize(db, shipment, negative_margin_reason=reason, actor=None)
    db.commit()
    return version


def _book(db, con, now=None):
    cs.book_consolidation(db, con, actor=None, now=now)
    db.commit()


def _months_back(n: int) -> str:
    today = utcnow().date()
    index = today.year * 12 + today.month - 1 - n
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _mid(month: str) -> datetime:
    year, number = (int(p) for p in month.split("-"))
    return datetime(year, number, 15, 12)


def _names(document) -> set[str]:
    names: set[str] = set()
    if isinstance(document, dict):
        for key, value in document.items():
            names.add(key.lower())
            names |= _names(value)
    elif isinstance(document, list):
        for value in document:
            names |= _names(value)
    return names


def _bill(db, con, lines, currency="CAD", now=None):
    bill = fs.enter_vendor_invoice(
        db, con, {"currency": currency, "lines": lines}, actor=None, now=now
    )
    db.commit()
    return bill


# --- Invoices -----------------------------------------------------------------------------------


def test_the_invoice_comes_from_the_latest_finalised_version_not_a_newer_draft(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    first = _finalize(db, kids[2])
    # A later change opens a draft; the invoice still comes from the finalised version.
    _fee(db, kids[2], "hcm_air", 18, description="Watch", quantity=1)
    draft, _ = ps.reprice(db, kids[2], actor=None)
    db.commit()
    assert draft.status == "draft"
    invoice = fs.issue_invoice(db, kids[2], actor=None)
    db.commit()
    assert invoice.quote_version_id == first.id
    assert invoice.total_cad == first.total_revenue_cad == Decimal("228.00")  # 12 kg x 19
    # Void it and finalise the new version: the reissue follows the newer finalised one.
    fs.void_invoice(db, invoice, "re-quoted", actor=None)
    db.commit()
    second = _finalize(db, kids[2])
    reissued = fs.issue_invoice(db, kids[2], actor=None)
    db.commit()
    assert reissued.quote_version_id == second.id
    assert reissued.total_cad == second.total_revenue_cad > first.total_revenue_cad


def test_only_revenue_lines_reach_the_invoice(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    # kids[1] triggers fake clothing; kids[0] carries a cost share with no revenue. v0.5 bills
    # a non-trigger its share by default (DEC-0252), so the RC-UAT-25 "triggers only" setting
    # is chosen here to keep a zero-revenue line in the scenario.
    pms.update_method_settings(db, {"pkg_surcharge_billing": "triggers_only"}, actor=None)
    _fee(db, kids[1], "hcm_air", 14, description="Fake clothing")
    version = _finalize(db, kids[0])
    zero = [line for line in version.lines if not line.revenue_cad]
    assert zero, "the scenario needs a zero-revenue quote line"
    invoice = fs.issue_invoice(db, kids[0], actor=None)
    db.commit()
    expected = [line for line in version.lines if line.revenue_cad and line.revenue_cad > 0]
    assert [(line.description, line.amount_cad) for line in invoice.lines] == [
        (line.description, line.revenue_cad) for line in expected
    ]
    assert all(line.amount_cad > 0 for line in invoice.lines)
    assert invoice.subtotal_cad == invoice.total_cad == sum(line.revenue_cad for line in expected)


def test_the_payer_is_the_recorded_payer_else_the_customer(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    payer = make_customer(db, email="payer@demo.example.com", full_name="Paying Relative")
    booking_service.set_payer(db, kids[0], payer.id)
    db.commit()
    _finalize(db, kids[0])
    _finalize(db, kids[1])
    paid_by_other = fs.issue_invoice(db, kids[0], actor=None)
    paid_by_self = fs.issue_invoice(db, kids[1], actor=None)
    db.commit()
    assert paid_by_other.customer_id == payer.id
    assert fs.invoice_document(db, paid_by_other)["customer_name"] == "Paying Relative"
    assert paid_by_self.customer_id == kids[1].customer_id


def test_invoice_numbers_are_sequential_and_never_reused(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    numbers = []
    for kid in kids:
        _finalize(db, kid)
        numbers.append(fs.issue_invoice(db, kid, actor=None))
        db.commit()
    assert [i.public_id for i in numbers] == ["INV-000001", "INV-000002", "INV-000003"]
    fs.void_invoice(db, numbers[0], "wrong payer", actor=None)
    db.commit()
    assert kids[0].payment_state == PaymentState.UNRECORDED
    again = fs.issue_invoice(db, kids[0], actor=None)
    db.commit()
    assert again.public_id == "INV-000004"
    assert numbers[0].public_id == "INV-000001" and numbers[0].status == "void"
    # One live invoice per shipment.
    with pytest.raises(ConflictError):
        fs.issue_invoice(db, kids[0], actor=None)
    db.rollback()
    live = db.query(CustomerInvoice).filter(
        CustomerInvoice.shipment_id == kids[0].id, CustomerInvoice.status != "void"
    )
    assert live.count() == 1


def test_no_tax_is_computed_and_due_date_follows_the_setting(db, priced_world, users):  # noqa: F811
    _con, kids = priced_world
    _finalize(db, kids[0])
    _finalize(db, kids[1])
    issued = datetime(2026, 10, 2, 9, 30)
    first = fs.issue_invoice(db, kids[0], actor=None, now=issued)
    db.commit()
    # OD-64: staff choose GST/HST per invoice; the default is 0 % (international move).
    assert first.tax_cad == Decimal("0.00") and first.tax_status == "gst_hst_0"
    assert first.due_at == issued + timedelta(days=fs.get_settings(db).invoice_due_days)
    fs.update_settings(db, {"invoice_due_days": 21}, actor=users[Role.ADMIN])
    db.commit()
    second = fs.issue_invoice(db, kids[1], actor=None, now=issued)
    db.commit()
    assert second.due_at == issued + timedelta(days=21)
    with pytest.raises(ValidationError):
        fs.update_settings(db, {"invoice_due_days": 366}, actor=None)


def test_due_days_are_admins_to_change_over_http(api_for, db, priced_world):  # noqa: F811
    _con, kids = priced_world
    _finalize(db, kids[0])
    ops = api_for(Role.OPERATIONS)
    assert ops.patch("/api/v1/finance/settings", json={"invoice_due_days": 5}).status_code == 403
    admin = api_for(Role.ADMIN)
    changed = admin.patch("/api/v1/finance/settings", json={"invoice_due_days": 30})
    assert changed.status_code == 200 and changed.json()["invoice_due_days"] == 30
    assert (
        admin.patch("/api/v1/finance/settings", json={"invoice_due_days": 400}).status_code == 422
    )
    issued = admin.post(f"/api/v1/shipments/{kids[0].id}/invoice")
    assert issued.status_code == 201, issued.text
    body = issued.json()
    gap = datetime.fromisoformat(body["due_at"]) - datetime.fromisoformat(body["issued_at"])
    assert gap == timedelta(days=30)
    assert body["tax_cad"] == "0.00" and body["tax_status"] == "gst_hst_0"


# --- Payments, receipts, refunds, voids ---------------------------------------------------------


@pytest.fixture
def invoice57(db, priced_world):  # noqa: F811
    con, kids = priced_world
    _finalize(db, kids[0])
    invoice = fs.issue_invoice(db, kids[0], actor=None)
    db.commit()
    assert invoice.total_cad == Decimal("57.00")  # 3 kg x CAD 19 (v0.5, DEC-0252)
    return con, kids, invoice


def test_payment_rules_and_payment_state(db, invoice57):
    _con, kids, invoice = invoice57
    assert kids[0].payment_state == PaymentState.UNPAID
    for bad in (
        {"amount_cad": "10", "method": "cash", "currency": "VND"},
        {"amount_cad": "57.01", "method": "cash"},
        {"amount_cad": "0", "method": "cash"},
        {"amount_cad": "1.005", "method": "cash"},
        {"amount_cad": "1", "method": "cheque_in_crayon"},
        # RC-20: a received date is a plain date, so "the future" is a later date, not a
        # later hour of today.
        {"amount_cad": "1", "method": "cash", "received_at": utcnow() + timedelta(days=2)},
    ):
        with pytest.raises(ValidationError):
            fs.record_payment(db, invoice, bad, actor=None)
        db.rollback()
    one = fs.record_payment(db, invoice, {"amount_cad": "10.00", "method": "cash"}, actor=None)
    db.commit()
    assert one.receipt_public_id == "RCT-000001"
    assert (invoice.status, kids[0].payment_state) == (
        "partially_paid",
        PaymentState.PARTIALLY_PAID,
    )
    two = fs.record_payment(db, invoice, {"amount_cad": "47.00", "method": "card"}, actor=None)
    db.commit()
    assert two.receipt_public_id == "RCT-000002"
    assert (invoice.status, kids[0].payment_state) == ("paid", PaymentState.PAID)
    assert fs.balance(invoice) == 0
    # Nothing more can be paid: no credit on account.
    with pytest.raises(ValidationError):
        fs.record_payment(db, invoice, {"amount_cad": "0.01", "method": "cash"}, actor=None)
    db.rollback()


def test_refunds_are_against_one_payment_and_bounded_by_what_it_brought(db, invoice57):
    _con, kids, invoice = invoice57
    p1 = fs.record_payment(db, invoice, {"amount_cad": "30.00", "method": "cash"}, actor=None)
    p2 = fs.record_payment(db, invoice, {"amount_cad": "24.00", "method": "card"}, actor=None)
    db.commit()
    fs.refund_payment(db, p2, {"amount_cad": "20.00", "reason": "damaged"}, actor=None)
    db.commit()
    assert (invoice.paid_cad, invoice.status) == (Decimal("34.00"), "partially_paid")
    assert kids[0].payment_state == PaymentState.PARTIALLY_PAID
    # p2 brought 24 and has had 20 back: at most 4 more, even though p1 brought 30.
    with pytest.raises(ValidationError):
        fs.refund_payment(db, p2, {"amount_cad": "4.01", "reason": "more"}, actor=None)
    db.rollback()
    refund = fs.refund_payment(db, p2, {"amount_cad": "4.00", "reason": "rest"}, actor=None)
    db.commit()
    # A refund is not a payment and cannot itself be refunded, nor carry a receipt.
    assert refund.receipt_public_id is None
    with pytest.raises(ConflictError):
        fs.refund_payment(db, refund, {"amount_cad": "1", "reason": "x"}, actor=None)
    db.rollback()
    # Void refused while money is held.
    with pytest.raises(ConflictError):
        fs.void_invoice(db, invoice, "wrong", actor=None)
    db.rollback()
    fs.refund_payment(db, p1, {"amount_cad": "30.00", "reason": "cancelled"}, actor=None)
    db.commit()
    assert (invoice.paid_cad, invoice.status) == (Decimal("0.00"), "issued")
    assert kids[0].payment_state == PaymentState.REFUNDED
    fs.void_invoice(db, invoice, "cancelled shipment", actor=None)
    db.commit()
    assert kids[0].payment_state == PaymentState.UNRECORDED
    with pytest.raises(ConflictError):
        fs.record_payment(db, invoice, {"amount_cad": "1", "method": "cash"}, actor=None)


def test_payment_dates_and_voids_respect_locked_months(db, priced_world):  # noqa: F811
    con, kids = priced_world
    con.handed_over_at = datetime(2026, 8, 20)
    db.commit()
    _finalize(db, kids[0])
    invoice = fs.issue_invoice(db, kids[0], actor=None, now=datetime(2026, 8, 25))
    db.commit()
    assert (invoice.period_month, invoice.is_adjustment) == ("2026-08", False)
    # Before 8 September August is open: an August-dated payment is fine.
    fs.record_payment(
        db,
        invoice,
        {"amount_cad": "4.00", "method": "cash", "received_at": datetime(2026, 8, 30)},
        actor=None,
        now=datetime(2026, 9, 7, 23),
    )
    db.commit()
    # From 8 September August is locked.
    with pytest.raises(ConflictError):
        fs.record_payment(
            db,
            invoice,
            {"amount_cad": "1.00", "method": "cash", "received_at": date(2026, 8, 31)},
            actor=None,
            now=datetime(2026, 9, 8),
        )
    db.rollback()
    late = fs.record_payment(
        db,
        invoice,
        {"amount_cad": "1.00", "method": "cash"},
        actor=None,
        now=datetime(2026, 9, 8, 10),
    )
    db.commit()
    # RC-20: undated means today in Toronto (06:00 on 8 September), stored as its midnight.
    assert late.received_at == datetime(2026, 9, 8)
    for payment in fs.payments_for(db, invoice.id):
        fs.refund_payment(
            db, payment, {"amount_cad": str(payment.amount_cad), "reason": "x"}, actor=None
        )
    db.commit()
    assert invoice.paid_cad == 0
    # Net paid is zero, but the invoice's month is locked: no void.
    with pytest.raises(ConflictError):
        fs.void_invoice(db, invoice, "late", actor=None, now=datetime(2026, 9, 8))
    db.rollback()
    fs.void_invoice(db, invoice, "in time", actor=None, now=datetime(2026, 9, 7))
    db.commit()
    assert invoice.status == "void"


def test_a_timezone_aware_payment_date_over_http_is_not_a_server_error(as_admin, db, invoice57):
    _con, _kids, invoice = invoice57
    yesterday = (utcnow() - timedelta(days=1)).replace(microsecond=0).isoformat() + "Z"
    response = as_admin.post(
        f"/api/v1/invoices/{invoice.id}/payments",
        json={"amount_cad": "5.00", "method": "cash", "received_at": yesterday},
    )
    assert response.status_code == 201, response.text


def test_payments_over_http_and_the_receipt(api_for, db, invoice57):
    _con, _kids, invoice = invoice57
    ops = api_for(Role.OPERATIONS)
    refused = ops.post(
        f"/api/v1/invoices/{invoice.id}/payments",
        json={"amount_cad": "5", "method": "cash", "currency": "VND"},
    )
    assert refused.status_code == 422
    over = ops.post(
        f"/api/v1/invoices/{invoice.id}/payments", json={"amount_cad": "60", "method": "cash"}
    )
    assert over.status_code == 422
    paid = ops.post(
        f"/api/v1/invoices/{invoice.id}/payments",
        json={"amount_cad": "20.00", "method": "e_transfer", "reference": "ET-1"},
    )
    assert paid.status_code == 201, paid.text
    body = paid.json()
    assert body["status"] == "partially_paid" and body["balance_cad"] == "37.00"
    payment = body["payments"][0]
    assert payment["receipt_public_id"].startswith("RCT-")
    receipt = ops.get(f"/api/v1/payments/{payment['id']}/receipt")
    assert receipt.status_code == 200
    document = receipt.json()
    assert document["receipt_number"] == payment["receipt_public_id"]
    assert document["balance_cad"] == "37.00"
    for name in _names(document):
        for forbidden in FORBIDDEN_DOCUMENT_NAMES:
            assert forbidden not in name, (forbidden, name)
    # Refund and void: Admin and Operations (OD-69); the read-only manager may not.
    manager = api_for(Role.READ_ONLY_MANAGER)
    assert (
        manager.post(
            f"/api/v1/payments/{payment['id']}/refund", json={"amount_cad": "1", "reason": "x"}
        ).status_code
        == 403
    )
    assert (
        manager.post(f"/api/v1/invoices/{invoice.id}/void", json={"reason": "x"}).status_code == 403
    )
    admin = api_for(Role.ADMIN)
    refunded = admin.post(
        f"/api/v1/payments/{payment['id']}/refund", json={"amount_cad": "20.00", "reason": "dup"}
    )
    assert refunded.status_code == 201
    voided = admin.post(f"/api/v1/invoices/{invoice.id}/void", json={"reason": "wrong payer"})
    assert voided.status_code == 200 and voided.json()["status"] == "void"


def test_customer_documents_carry_no_internal_field_names(api_for, db, priced_world):  # noqa: F811
    con, kids = priced_world
    _fee(db, kids[1], "hcm_air", 14, description="Fake clothing")
    _finalize(db, kids[1])
    invoice = fs.issue_invoice(db, kids[1], actor=None)
    db.commit()
    payment = fs.record_payment(db, invoice, {"amount_cad": "10", "method": "cash"}, actor=None)
    db.commit()
    for document in (fs.invoice_document(db, invoice), fs.receipt_document(db, payment)):
        for name in _names(json.loads(json.dumps(document, default=str))):
            for forbidden in FORBIDDEN_DOCUMENT_NAMES:
                assert forbidden not in name, (forbidden, name)
    manager = api_for(Role.READ_ONLY_MANAGER)
    for url in (
        f"/api/v1/invoices/{invoice.id}/document",
        f"/api/v1/payments/{payment.id}/receipt",
    ):
        response = manager.get(url)
        assert response.status_code == 200
        for name in _names(response.json()):
            for forbidden in FORBIDDEN_DOCUMENT_NAMES:
                assert forbidden not in name, (forbidden, name)
        # Nor a sibling shipment or the master's reference.
        text = response.text
        assert con.public_id not in text
        for sibling in (kids[0], kids[2]):
            assert sibling.public_id not in text


# --- Vendor bills -------------------------------------------------------------------------------


def test_a_bill_needs_a_booked_or_completed_master_and_only_one_lives(db, priced_world):  # noqa: F811
    con, _kids = priced_world
    line = [{"kind": "base", "amount": "100.00"}]
    with pytest.raises(ConflictError):
        _bill(db, con, line)
    db.rollback()
    _book(db, con)
    first = _bill(db, con, line)
    with pytest.raises(ConflictError):
        _bill(db, con, line)
    db.rollback()
    fs.void_vendor_invoice(db, first, "keyed twice", actor=None)
    db.commit()
    second = _bill(db, con, line)
    assert second.public_id != first.public_id
    fs.void_vendor_invoice(db, second, "again", actor=None)
    db.commit()
    cs.complete_consolidation(db, con, actor=None)
    db.commit()
    assert _bill(db, con, line).status == "entered"


def test_a_vnd_bill_is_converted_at_the_rate_frozen_on_it(db, priced_world):  # noqa: F811
    con, _kids = priced_world
    _book(db, con)
    lines = [
        {"kind": "base", "amount": "5103000"},
        {"kind": "other", "description": "Handling", "amount": "123457"},
    ]
    bill = _bill(db, con, lines, currency="VND")
    snapshot = fx_service.latest_snapshot(db)
    assert snapshot.cash_buy_vnd == CASH_BUY
    # OD-73 (superseding OD-67): VND -> CAD at the buy rate on the bill date, frozen on the bill.
    assert bill.fx_cash_buy_vnd == CASH_BUY and bill.fx_snapshot_id == snapshot.id
    expected_total = sum(
        (fs._cents(Decimal(line["amount"]) / CASH_BUY) for line in lines), Decimal(0)
    )
    assert bill.total_cad == expected_total
    assert bill.total_amount == Decimal("5226457")
    assert bill.variance_cad == bill.total_cad - bill.expected_cad
    # A newer bank reading does not move the bill.
    newer = SAMPLE_XML.replace(b"17,886.61", b"18,500.00")
    fx_service.sync_once(
        db, fetcher=lambda _u: newer, clock=lambda: utcnow() + timedelta(minutes=5), worker_name="t"
    )
    db.commit()
    assert fx_service.latest_snapshot(db).cash_buy_vnd == Decimal("18500.00")
    fs.approve_vendor_invoice(db, bill, {"variance_reason": "handling"}, actor=None)
    db.commit()
    db.refresh(bill)
    assert bill.fx_cash_buy_vnd == CASH_BUY and bill.total_cad == expected_total
    assert sum(fs.allocations_for(db, bill.id).values()) == bill.total_cad


def test_variance_needs_a_reason_unless_the_bill_matches_the_estimate(db, priced_world):  # noqa: F811
    con, _kids = priced_world
    _book(db, con)
    probe = _bill(db, con, [{"kind": "base", "amount": "1.00"}])
    expected = probe.expected_cad
    assert expected is not None and expected > 0
    assert probe.variance_cad == Decimal("1.00") - expected
    for blank in ({}, {"variance_reason": "   "}):
        with pytest.raises(ValidationError):
            fs.approve_vendor_invoice(db, probe, blank, actor=None)
        db.rollback()
    fs.void_vendor_invoice(db, probe, "probe", actor=None)
    db.commit()
    exact = _bill(db, con, [{"kind": "base", "amount": str(expected)}])
    assert exact.variance_cad == 0 and exact.total_cad == expected
    fs.approve_vendor_invoice(db, exact, {}, actor=None)
    db.commit()
    assert exact.status == "approved" and exact.variance_reason is None


def test_allocations_split_exactly_by_weight_and_by_the_fee_split(db, priced_world):  # noqa: F811
    con, kids = priced_world
    _fee(db, kids[1], "hcm_air", 14, description="Fake clothing")
    _book(db, con)
    est, _ = ps.estimate_for(db, con)
    fake = next(f for f in est.fees if f.stt == 14)
    bill = _bill(
        db,
        con,
        [
            {"kind": "base", "amount": "100.00"},
            {"kind": "piece_fee", "amount": "21.00"},
            {"kind": "other", "description": "Storage", "amount": "7.00"},
            {"kind": "surcharge", "fee_key": fake.key, "amount": "90.00"},
            {"kind": "surcharge", "description": "Unkeyed extra", "amount": "0.10"},
        ],
    )
    assert bill.total_cad == Decimal("218.10")
    with pytest.raises(ConflictError):
        fs.mark_vendor_invoice_paid(db, bill, {}, actor=None)  # not approved yet
    db.rollback()
    fs.approve_vendor_invoice(db, bill, {"variance_reason": "test bill"}, actor=None)
    db.commit()
    per_line: dict[str, dict[int, Decimal]] = {}
    for line in bill.lines:
        rows = db.query(CostAllocation).filter_by(vendor_invoice_line_id=line.id).all()
        per_line[line.description] = {r.shipment_id: r.amount_cad for r in rows}
        assert sum(r.amount_cad for r in rows) == line.amount
    a, b, c = (k.id for k in kids)
    # 3 : 6 : 12 kg; largest remainder at one cent.
    assert per_line["base"] == {a: Decimal("14.29"), b: Decimal("28.57"), c: Decimal("57.14")}
    assert per_line["piece_fee"] == {a: Decimal("3.00"), b: Decimal("6.00"), c: Decimal("12.00")}
    assert per_line["Storage"] == {a: Decimal("1.00"), b: Decimal("2.00"), c: Decimal("4.00")}
    # The keyed surcharge follows the engine: 2/3 to the single trigger, the rest shared.
    assert per_line["surcharge"] == {a: Decimal("15.00"), b: Decimal("60.00"), c: Decimal("15.00")}
    assert per_line["Unkeyed extra"] == {a: Decimal("0.01"), b: Decimal("0.03"), c: Decimal("0.06")}
    assert sum(fs.allocations_for(db, bill.id).values()) == bill.total_cad


def test_mark_paid_after_approval_and_ap_lists_open_bills_only(db, priced_world):  # noqa: F811
    con, _kids = priced_world
    _book(db, con)
    bill = _bill(db, con, [{"kind": "base", "amount": "50.00"}])
    assert [r["public_id"] for r in fs.accounts_payable(db)["rows"]] == [bill.public_id]
    assert fs.accounts_payable(db)["rows"][0]["status"] == "entered"
    fs.approve_vendor_invoice(db, bill, {"variance_reason": "x"}, actor=None)
    db.commit()
    assert fs.accounts_payable(db)["rows"][0]["status"] == "approved"
    assert fs.accounts_payable(db)["total_cad"] == Decimal("50.00")
    fs.mark_vendor_invoice_paid(db, bill, {"reference": "VCB-1"}, actor=None)
    db.commit()
    assert bill.status == "paid" and fs.accounts_payable(db)["rows"] == []
    with pytest.raises(ConflictError):
        fs.mark_vendor_invoice_paid(db, bill, {}, actor=None)
    db.rollback()
    # Admin may void a paid bill (with a reason): its cost allocations go with it.
    assert fs.allocations_for(db, bill.id)
    with pytest.raises(ValidationError):
        fs.void_vendor_invoice(db, bill, " ", actor=None)
    db.rollback()
    fs.void_vendor_invoice(db, bill, "vendor credited the whole bill", actor=None)
    db.commit()
    assert bill.status == "void" and fs.allocations_for(db, bill.id) == {}
    assert "vendor_invoice.void" in [a.action for a in db.query(AuditEvent)]
    with pytest.raises(ConflictError):
        fs.void_vendor_invoice(db, bill, "again", actor=None)


# --- Periods ------------------------------------------------------------------------------------


def test_lock_dates_and_states(db):
    assert fs.lock_date("2026-02") == datetime(2026, 3, 8)
    assert fs.lock_date("2026-12") == datetime(2027, 1, 8)
    assert fs.period_state(db, "2026-02", now=datetime(2026, 3, 7, 23, 59, 59)) == "open"
    assert fs.period_state(db, "2026-02", now=datetime(2026, 3, 8, 0, 0)) == "locked"
    with pytest.raises(ConflictError):
        fs.close_month(db, "2026-02", actor=None, now=datetime(2026, 3, 7))
    db.rollback()
    first = fs.close_month(db, "2026-02", actor=None, now=datetime(2026, 3, 9))
    db.commit()
    assert first.version == 1 and fs.period_state(db, "2026-02") == "closed"
    with pytest.raises(ConflictError):
        fs.close_month(db, "2026-02", actor=None, now=datetime(2026, 3, 9))
    db.rollback()
    with pytest.raises(ValidationError):
        fs.reopen_month(db, "2026-02", "  ", actor=None)
    db.rollback()
    fs.reopen_month(db, "2026-02", "late credit", actor=None)
    db.commit()
    assert fs.period_state(db, "2026-02", now=datetime(2026, 4, 1)) == "reopened"
    assert fs.close_month(db, "2026-02", actor=None, now=datetime(2026, 4, 1)).version == 2
    db.commit()
    actions = [a.action for a in db.query(AuditEvent)]
    assert actions.count("period.close") == 2 and actions.count("period.reopen") == 1


def test_figures_for_a_locked_month_are_next_open_month_adjustments(db, priced_world):  # noqa: F811
    con, kids = priced_world
    _finalize(db, kids[0])
    _finalize(db, kids[1])
    _book(db, con, now=datetime(2026, 7, 20))  # hand-in in July
    # 3 August: July still open.
    on_time = fs.issue_invoice(db, kids[0], actor=None, now=datetime(2026, 8, 3))
    db.commit()
    assert (on_time.period_month, on_time.is_adjustment) == ("2026-07", False)
    # 9 September: July and August are both locked; booked in September.
    fs.close_month(db, "2026-08", actor=None, now=datetime(2026, 9, 9))
    db.commit()
    late = fs.issue_invoice(db, kids[1], actor=None, now=datetime(2026, 9, 9))
    db.commit()
    assert (late.period_month, late.is_adjustment) == ("2026-09", True)
    bill = _bill(db, con, [{"kind": "base", "amount": "40.00"}], now=datetime(2026, 9, 9))
    assert (bill.period_month, bill.is_adjustment) == ("2026-09", True)
    # Approved after September locked: moved to October as an adjustment.
    fs.approve_vendor_invoice(
        db, bill, {"variance_reason": "x"}, actor=None, now=datetime(2026, 10, 9)
    )
    db.commit()
    assert (bill.period_month, bill.is_adjustment) == ("2026-10", True)


def test_an_entered_bill_in_an_open_month_is_not_an_adjustment(db, priced_world):  # noqa: F811
    con, _kids = priced_world
    _book(db, con, now=datetime(2026, 9, 25))
    bill = _bill(db, con, [{"kind": "base", "amount": "40.00"}], now=datetime(2026, 10, 7))
    assert (bill.period_month, bill.is_adjustment) == ("2026-09", False)


def test_closing_freezes_profitability_and_reopening_is_admins(api_for, db, priced_world):  # noqa: F811
    con, kids = priced_world
    month = _months_back(2)
    con.handed_over_at = _mid(month)
    db.commit()
    _finalize(db, kids[0])
    invoice = fs.issue_invoice(db, kids[0], actor=None, now=_mid(month))
    db.commit()
    assert invoice.period_month == month
    admin = api_for(Role.ADMIN)
    assert admin.post(f"/api/v1/finance/periods/{_months_back(0)}/close").status_code == 409
    closed = admin.post(f"/api/v1/finance/periods/{month}/close")
    assert closed.status_code == 200, closed.text
    assert closed.json()["state"] == "closed" and closed.json()["version"] == 1
    report = admin.get(f"/api/v1/finance/profitability?month={month}").json()["report"]
    assert report["from_snapshot"] is True and report["state"] == "closed"
    assert Decimal(report["summary"]["revenue_cad"]) == Decimal("57.00")
    # The live figure changes underneath; the closed month keeps answering from the snapshot.
    see_committed_changes(db)
    changed = db.get(CustomerInvoice, invoice.id)
    changed.subtotal_cad = changed.total_cad = Decimal("99.00")
    db.commit()
    report = admin.get(f"/api/v1/finance/profitability?month={month}").json()["report"]
    assert Decimal(report["summary"]["revenue_cad"]) == Decimal("57.00")
    manager = api_for(Role.READ_ONLY_MANAGER)
    assert (
        manager.post(f"/api/v1/finance/periods/{month}/reopen", json={"reason": "x"}).status_code
        == 403
    )
    admin = api_for(Role.ADMIN)
    assert (
        admin.post(f"/api/v1/finance/periods/{month}/reopen", json={"reason": ""}).status_code
        == 422
    )
    assert (
        admin.post(f"/api/v1/finance/periods/{month}/reopen", json={"reason": " "}).status_code
        == 422
    )
    reopened = admin.post(f"/api/v1/finance/periods/{month}/reopen", json={"reason": "late credit"})
    assert reopened.status_code == 200 and reopened.json()["state"] == "reopened"
    live = admin.get(f"/api/v1/finance/profitability?month={month}").json()["report"]
    assert live["from_snapshot"] is False
    assert Decimal(live["summary"]["revenue_cad"]) == Decimal("99.00")
    again = admin.post(f"/api/v1/finance/periods/{month}/close")
    assert again.status_code == 200 and again.json()["version"] == 2


# --- Profitability ------------------------------------------------------------------------------


def test_profitability_matches_cost_to_invoiced_shipments_only(db, priced_world):  # noqa: F811
    con, kids = priced_world
    v0 = _finalize(db, kids[0])
    v1 = _finalize(db, kids[1])
    _book(db, con, now=datetime(2026, 10, 1))
    now = datetime(2026, 10, 5)
    for kid in kids[:2]:
        fs.issue_invoice(db, kid, actor=None, now=now)
    db.commit()
    estimated = fs.profitability(db, "2026-10", now=now)
    row = estimated["masters"][0]
    assert row["revenue_cad"] == Decimal("171.00")  # 57 + 114
    assert row["matched_cost_cad"] == v0.allocated_cost_cad + v1.allocated_cost_cad
    assert row["cost_basis"] == "estimated" and row["unmatched_cost_cad"] == 0

    bill = _bill(db, con, [{"kind": "base", "amount": "210.00"}], now=now)
    fs.approve_vendor_invoice(db, bill, {"variance_reason": "x"}, actor=None, now=now)
    db.commit()
    report = fs.profitability(db, "2026-10", now=now)
    row = report["masters"][0]
    # 3 : 6 : 12 -> 30 / 60 / 120. kids[2] is not invoiced: its 120 is unmatched.
    assert row["matched_cost_cad"] == Decimal("90.00")
    assert row["unmatched_cost_cad"] == Decimal("120.00")
    assert row["cost_basis"] == "actual"
    assert row["profit_cad"] == Decimal("81.00")
    assert row["margin_percent"] == Decimal("47.4")
    summary = report["summary"]
    assert (summary["revenue_cad"], summary["profit_cad"], summary["margin_percent"]) == (
        Decimal("171.00"),
        Decimal("81.00"),
        Decimal("47.4"),
    )
    assert summary["unmatched_cost_cad"] == Decimal("120.00")
    # A void invoice leaves the month's revenue.
    invoice = fs.live_invoice(db, kids[1].id)
    fs.void_invoice(db, invoice, "x", actor=None, now=now)
    db.commit()
    report = fs.profitability(db, "2026-10", now=now)
    row = report["masters"][0]
    assert row["revenue_cad"] == Decimal("57.00")
    assert row["matched_cost_cad"] == Decimal("30.00")
    assert row["unmatched_cost_cad"] == Decimal("180.00")
    assert row["margin_percent"] == Decimal("47.4")  # 27 / 57


def test_profitability_mixed_basis_and_one_decimal_margin(db, priced_world):  # noqa: F811
    con, kids = priced_world
    for kid in kids:
        _finalize(db, kid)
    _book(db, con, now=datetime(2026, 10, 1))
    now = datetime(2026, 10, 5)
    for kid in kids:
        fs.issue_invoice(db, kid, actor=None, now=now)
    db.commit()
    revenue = Decimal("399.00")  # 3 + 6 + 12 kg x 19.00 (each under 21 kg, DEC-0252)
    bill = _bill(db, con, [{"kind": "base", "amount": "100.00"}], now=now)
    fs.approve_vendor_invoice(db, bill, {"variance_reason": "x"}, actor=None, now=now)
    db.commit()
    row = fs.profitability(db, "2026-10", now=now)["masters"][0]
    assert row["cost_basis"] == "actual" and row["matched_cost_cad"] == Decimal("100.00")
    assert row["unmatched_cost_cad"] == 0
    assert row["profit_cad"] == revenue - Decimal("100.00")
    assert row["margin_percent"] == (Decimal("299") / revenue * 100).quantize(Decimal("0.1"))
    assert row["margin_percent"] == Decimal("74.9")


# --- Permissions --------------------------------------------------------------------------------


def test_role_boundaries(api_for, db, invoice57):
    con, kids, invoice = invoice57
    _finalize(db, kids[1])
    manager = api_for(Role.READ_ONLY_MANAGER)
    assert manager.get("/api/v1/invoices").status_code == 200
    assert manager.get(f"/api/v1/invoices/{invoice.id}").status_code == 200
    assert manager.get("/api/v1/finance/ar-aging").status_code == 200
    assert manager.get(f"/api/v1/consolidations/{con.id}/vendor-invoices").status_code == 403
    assert manager.get("/api/v1/finance/ap").status_code == 403
    assert manager.get("/api/v1/finance/profitability?month=2026-10").status_code == 403
    assert manager.post(f"/api/v1/shipments/{kids[1].id}/invoice").status_code == 403
    assert (
        manager.post(
            f"/api/v1/invoices/{invoice.id}/payments", json={"amount_cad": "1", "method": "cash"}
        ).status_code
        == 403
    )
    assert (
        manager.patch("/api/v1/finance/settings", json={"invoice_due_days": 3}).status_code == 403
    )
    marketing = api_for(Role.MARKETING)
    for url in (
        "/api/v1/invoices",
        f"/api/v1/invoices/{invoice.id}",
        f"/api/v1/invoices/{invoice.id}/document",
        "/api/v1/finance/ar-aging",
        "/api/v1/finance/ap",
        "/api/v1/finance/periods",
        "/api/v1/finance/settings",
        "/api/v1/finance/profitability?month=2026-10",
    ):
        assert marketing.get(url).status_code == 403, url
    ops = api_for(Role.OPERATIONS)
    assert ops.get("/api/v1/finance/ap").status_code == 200
    assert ops.get("/api/v1/finance/ar-aging.csv").status_code == 403
    assert ops.get("/api/v1/finance/profitability.csv?month=2026-10").status_code == 403
    manager = api_for(Role.READ_ONLY_MANAGER)
    assert manager.get("/api/v1/finance/ar-aging.csv").status_code == 403
    admin = api_for(Role.ADMIN)
    ar = admin.get("/api/v1/finance/ar-aging.csv")
    assert ar.status_code == 200 and invoice.public_id in ar.text
    profit = admin.get(f"/api/v1/finance/profitability.csv?month={invoice.period_month}")
    assert profit.status_code == 200 and profit.text.startswith("month,")
    see_committed_changes(db)
    actions = [a.action for a in db.query(AuditEvent)]
    assert "export.ar_aging" in actions and "export.profitability" in actions


def test_vendor_bills_over_http(api_for, db, priced_world):  # noqa: F811
    con, kids = priced_world
    _book(db, con)
    ops = api_for(Role.OPERATIONS)
    entered = ops.post(
        f"/api/v1/consolidations/{con.id}/vendor-invoices",
        json={"currency": "CAD", "lines": [{"kind": "base", "amount": "21.00"}]},
    )
    assert entered.status_code == 201, entered.text
    bill = entered.json()
    assert bill["fx_rate_vnd"] is None and bill["total_cad"] == "21.00"
    early = ops.post(f"/api/v1/vendor-invoices/{bill['id']}/paid", json={})
    assert early.status_code == 409
    no_reason = ops.post(f"/api/v1/vendor-invoices/{bill['id']}/approve", json={})
    assert no_reason.status_code == 422
    approved = ops.post(
        f"/api/v1/vendor-invoices/{bill['id']}/approve", json={"variance_reason": "flat rate"}
    )
    assert approved.status_code == 200
    allocations = approved.json()["allocations"]
    assert allocations == {
        str(kids[0].id): "3.00",
        str(kids[1].id): "6.00",
        str(kids[2].id): "12.00",
    }
    # Operations may void a bill (OD-69); the read-only manager may not even see it.
    voided = ops.post(f"/api/v1/vendor-invoices/{bill['id']}/void", json={"reason": "x"})
    assert voided.status_code == 200 and voided.json()["status"] == "void"
    manager = api_for(Role.READ_ONLY_MANAGER)
    assert (
        manager.post(f"/api/v1/vendor-invoices/{bill['id']}/void", json={"reason": "x"}).status_code
        == 403
    )


# --- Concurrency helper -------------------------------------------------------------------------


class _FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _locked():
    return OperationalError("INSERT ...", {}, Exception("database is locked"))


def test_run_unit_with_retry_reruns_the_whole_unit_once_locked():
    session = _FakeSession()
    calls = []

    def work():
        calls.append(len(calls))
        if len(calls) == 1:
            raise _locked()
        return "done"

    assert run_unit_with_retry(session, work, base_delay=0) == "done"
    assert len(calls) == 2
    assert (session.rollbacks, session.commits) == (1, 1)


def test_run_unit_with_retry_propagates_other_errors_and_gives_up():
    session = _FakeSession()
    calls = []

    def other():
        calls.append(1)
        raise OperationalError("SELECT", {}, Exception("no such table: invoices"))

    with pytest.raises(OperationalError, match="no such table"):
        run_unit_with_retry(session, other, base_delay=0)
    assert len(calls) == 1 and session.commits == 0

    def plain():
        raise ValueError("not a database problem")

    with pytest.raises(ValueError):
        run_unit_with_retry(_FakeSession(), plain, base_delay=0)

    stuck = _FakeSession()
    tries = []

    def always_locked():
        tries.append(1)
        raise _locked()

    with pytest.raises(OperationalError, match="database is locked"):
        run_unit_with_retry(stuck, always_locked, attempts=3, base_delay=0)
    assert len(tries) == 3 and stuck.commits == 0 and stuck.rollbacks == 3


def test_run_unit_with_retry_commits_nothing_half_done(db):
    attempts = []

    def work():
        attempts.append(1)
        audit_service.record_audit(
            db,
            action="test.unit",
            entity_type="test",
            entity_id="1",
            summary="unit of work",
            actor=None,
        )
        db.flush()
        if len(attempts) == 1:
            raise _locked()
        return len(attempts)

    assert run_unit_with_retry(db, work, base_delay=0) == 2
    assert db.query(AuditEvent).filter_by(action="test.unit").count() == 1


# --- Review changes (coordinator, 2026-10-20) ---------------------------------------------------


def test_one_master_books_its_invoices_in_one_month(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    _finalize(db, kids[0])
    _finalize(db, kids[1])
    first = fs.issue_invoice(db, kids[0], actor=None, now=datetime(2026, 9, 30, 20))
    db.commit()
    assert (first.period_month, first.is_adjustment) == ("2026-09", False)
    second = fs.issue_invoice(db, kids[1], actor=None, now=datetime(2026, 10, 2))
    db.commit()
    # September is still open on 2 October: the sibling joins the master's month.
    assert (second.period_month, second.is_adjustment) == ("2026-09", False)


def test_a_fee_key_gone_from_the_estimate_refuses_approval(db, priced_world):  # noqa: F811
    con, kids = priced_world
    line = _fee(db, kids[1], "hcm_air", 14, description="Fake clothing")
    _book(db, con)
    est, _ = ps.estimate_for(db, con)
    fake = next(f for f in est.fees if f.stt == 14)
    bill = _bill(db, con, [{"kind": "surcharge", "fee_key": fake.key, "amount": "30.00"}])
    # A booked master's fees are locked (owner decision 8): an Admin unlocks it first.
    from app.services import master_lock_service

    master_lock_service.unlock(db, con, reason="fee entered by mistake", actor=None)
    ps.remove_fee_line(db, kids[1], line.id, actor=None)
    db.commit()
    with pytest.raises(ConflictError):
        fs.approve_vendor_invoice(db, bill, {"variance_reason": "x"}, actor=None)
    db.rollback()
    assert bill.status == "entered" and fs.allocations_for(db, bill.id) == {}


def test_period_routes_need_a_month_and_bills_take_aware_dates(as_admin, db, priced_world):  # noqa: F811
    con, _kids = priced_world
    for bad in ("2026-9", "202609", "latest"):
        assert as_admin.post(f"/api/v1/finance/periods/{bad}/close").status_code == 422, bad
        reopened = as_admin.post(f"/api/v1/finance/periods/{bad}/reopen", json={"reason": "x"})
        assert reopened.status_code == 422, bad
    _book(db, con)
    yesterday = (utcnow() - timedelta(days=1)).replace(microsecond=0)
    entered = as_admin.post(
        f"/api/v1/consolidations/{con.id}/vendor-invoices",
        json={
            "currency": "CAD",
            "billed_at": yesterday.isoformat() + "+00:00",
            "lines": [{"kind": "base", "amount": "21.00"}],
        },
    )
    assert entered.status_code == 201, entered.text
    assert datetime.fromisoformat(entered.json()["billed_at"]).replace(tzinfo=None) == yesterday
    future = (utcnow() + timedelta(days=2)).isoformat() + "Z"
    bill_id = entered.json()["id"]
    as_admin.post(f"/api/v1/vendor-invoices/{bill_id}/approve", json={"variance_reason": "x"})
    paid = as_admin.post(f"/api/v1/vendor-invoices/{bill_id}/paid", json={"paid_at": future})
    assert paid.status_code == 422, paid.text
