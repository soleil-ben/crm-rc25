"""RC-20 (owner, 2026-10-23): a payment received on 20 September showed as 19 September.

The received date is a plain calendar date. It is stored as midnight of that date in the
``received_at`` DateTime column, never shifted between time zones, and it is the same date
on the stored row, the staff API, the receipt document and the payment's period month.
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.models import PaymentConversion
from app.services import finance_service as fs
from app.services.errors import ConflictError, ValidationError
from tests.test_finance import _finalize
from tests.test_quotes import priced_world  # noqa: F401  (fixture)

SEPT_20 = datetime(2026, 9, 20)
#: 08:00 on 25 September in Toronto (EDT, UTC-4), as the naive UTC the service is given.
SEPT_25 = datetime(2026, 9, 25, 12)


@pytest.fixture(autouse=True)
def toronto(monkeypatch):
    """Run as the business does: the business zone America/Toronto, and the process zone
    too where the platform lets a test change it (``time.tzset`` is POSIX only)."""
    monkeypatch.setattr(settings, "default_timezone", "America/Toronto")
    if hasattr(time, "tzset"):
        monkeypatch.setenv("TZ", "America/Toronto")
        time.tzset()
    yield
    if hasattr(time, "tzset"):
        os.environ.pop("TZ", None)
        time.tzset()


@pytest.fixture
def sept_invoice(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    _finalize(db, kids[0])
    invoice = fs.issue_invoice(db, kids[0], actor=None, now=datetime(2026, 9, 16, 15))
    db.commit()
    return invoice


@pytest.mark.parametrize(
    "entered",
    [
        "2026-09-20",
        "2026-09-20T00:00:00",
        "2026-09-20T00:00:00-04:00",
        # Late evening in Toronto is already 21 September in UTC: still the 20th.
        "2026-09-20T22:30:00-04:00",
        date(2026, 9, 20),
    ],
)
def test_the_received_date_is_stored_and_read_back_as_written(db, sept_invoice, entered):
    payment = fs.record_payment(
        db,
        sept_invoice,
        {"amount_cad": "5.00", "method": "cash", "received_at": entered},
        actor=None,
        now=SEPT_25,
    )
    db.commit()
    db.refresh(payment)
    assert payment.received_at == SEPT_20
    assert payment.received_at.date().isoformat() == "2026-09-20"
    assert fs.month_of(payment.received_at) == "2026-09"
    receipt = fs.receipt_document(db, payment)
    assert receipt["received_at"].date() == date(2026, 9, 20)


def test_the_api_sends_and_returns_the_same_plain_date(as_admin, db, sept_invoice, monkeypatch):
    monkeypatch.setattr(fs, "utcnow", lambda: SEPT_25)
    response = as_admin.post(
        f"/api/v1/invoices/{sept_invoice.id}/payments",
        json={"amount_cad": "5.00", "method": "cash", "received_at": "2026-09-20"},
    )
    assert response.status_code == 201, response.text
    (payment,) = response.json()["payments"]
    # Naive midnight of the date, no designator: the UI formats its YYYY-MM-DD part as is.
    assert payment["received_at"] == "2026-09-20T00:00:00"
    receipt = as_admin.get(f"/api/v1/payments/{payment['id']}/receipt")
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["received_at"] == "2026-09-20T00:00:00"


def test_an_offset_cannot_move_a_payment_into_the_next_month(db, sept_invoice):
    """30 September 22:00 in Toronto is 1 October in UTC. The old conversion booked it in
    October, past the September lock; the payment belongs to September."""
    entered = "2026-09-30T22:00:00-04:00"
    payment = fs.record_payment(
        db,
        sept_invoice,
        {"amount_cad": "1.00", "method": "cash", "received_at": entered},
        actor=None,
        now=datetime(2026, 10, 7, 12),
    )
    db.commit()
    assert payment.received_at == datetime(2026, 9, 30)
    assert fs.month_of(payment.received_at) == "2026-09"
    # From 8 October September is locked (M+7): the same entry is refused, not re-dated.
    with pytest.raises(ConflictError, match="2026-09 is closed"):
        fs.record_payment(
            db,
            sept_invoice,
            {"amount_cad": "1.00", "method": "cash", "received_at": entered},
            actor=None,
            now=datetime(2026, 10, 8, 12),
        )
    db.rollback()


def test_today_entered_on_a_toronto_evening_is_accepted(db, sept_invoice):
    # 21:30 on 23 October in Toronto is 01:30 on 24 October UTC.
    evening = datetime(2026, 10, 24, 1, 30)
    payment = fs.record_payment(
        db,
        sept_invoice,
        {"amount_cad": "1.00", "method": "cash", "received_at": "2026-10-23"},
        actor=None,
        now=evening,
    )
    db.commit()
    assert payment.received_at == datetime(2026, 10, 23)
    # With no date given, it is today in Toronto, not the UTC date.
    default = fs.record_payment(
        db, sept_invoice, {"amount_cad": "1.00", "method": "cash"}, actor=None, now=evening
    )
    db.commit()
    assert default.received_at == datetime(2026, 10, 23)
    # Tomorrow in Toronto is still the future.
    with pytest.raises(ValidationError, match="future"):
        fs.record_payment(
            db,
            sept_invoice,
            {"amount_cad": "1.00", "method": "cash", "received_at": "2026-10-24"},
            actor=None,
            now=evening,
        )
    db.rollback()


def test_a_staff_member_ahead_of_toronto_may_enter_their_own_today():
    evening = datetime(2026, 10, 24, 1, 30)  # 08:30 on 24 October in Ho Chi Minh City
    vietnam = SimpleNamespace(timezone="Asia/Ho_Chi_Minh")
    assert fs._received_on("2026-10-24", "received_at", evening, vietnam) == datetime(2026, 10, 24)
    with pytest.raises(ValidationError, match="future"):
        fs._received_on("2026-10-25", "received_at", evening, vietnam)
    with pytest.raises(ValidationError, match="valid date"):
        fs._received_on("20/09/2026", "received_at", evening)


def test_a_refund_is_dated_today_in_toronto(db, sept_invoice):
    payment = fs.record_payment(
        db,
        sept_invoice,
        {"amount_cad": "5.00", "method": "cash", "received_at": "2026-09-20"},
        actor=None,
        now=SEPT_25,
    )
    db.commit()
    evening = datetime(2026, 10, 24, 1, 30)
    refund = fs.refund_payment(
        db, payment, {"amount_cad": "1.00", "reason": "test"}, actor=None, now=evening
    )
    db.commit()
    assert refund.received_at == datetime(2026, 10, 23)
    assert refund.recorded_at == evening


def test_a_vnd_payment_keeps_its_plain_date_and_the_invoice_date_rate(db, priced_world):  # noqa: F811
    """The conversion's ``rate_day`` is the invoice date in Toronto as a plain midnight
    (OD-66), independent of the payment's own received date."""
    from app.core.time_utils import utcnow

    _con, kids = priced_world
    _finalize(db, kids[0])
    invoice = fs.issue_invoice(db, kids[0], actor=None)
    db.commit()
    today = fs._local_date(utcnow())
    payment = fs.record_payment(
        db,
        invoice,
        {
            "currency": "VND",
            "amount_vnd": "100000",
            "method": "bank_transfer",
            "received_at": f"{today.isoformat()}T00:00:00-04:00",
        },
        actor=None,
    )
    db.commit()
    assert payment.received_at == datetime(today.year, today.month, today.day)
    conversion = db.query(PaymentConversion).filter_by(payment_id=payment.id).one()
    issued_day = fs._local_date(invoice.issued_at)
    assert conversion.rate_day == datetime(issued_day.year, issued_day.month, issued_day.day)
    assert fs.receipt_document(db, payment)["amount_received_vnd"] == Decimal("100000.00")
