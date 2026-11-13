"""Vietcombank exchange rates: parsing, plausibility, snapshots, freshness, the worker.

No test here opens a network connection. The transport is injected, and the one test of
the real transport asserts that it refuses anything that is not the bank's own HTTPS feed
before it would ever connect.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.core.config import settings
from app.core.enums import FxFreshness, FxSyncOutcome
from app.models import FxRateSnapshot, FxSyncAttempt
from app.services import fx_service
from app.workers import fx_worker

#: The shape of the bank's public feed: an ``Exrate`` element per currency with the three
#: rates as attributes and a ``DateTime`` child. Numbers in the bank's own notation.
SAMPLE_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<ExrateList>
  <DateTime>10/19/2026 8:30:00 AM</DateTime>
  <Exrate CurrencyCode="USD" CurrencyName="US DOLLAR" Buy="25,100.00" Transfer="25,130.00" Sell="25,470.00"/>
  <Exrate CurrencyCode="CAD" CurrencyName="CANADIAN DOLLAR" Buy="17,886.61" Transfer="18,067.28" Sell="18,645.39"/>
  <Source>Vietcombank</Source>
</ExrateList>
"""


def _xml(buy: str, transfer: str, sell: str) -> bytes:
    return (
        b'<ExrateList><DateTime>19/10/2026 08:30:00</DateTime><Exrate CurrencyCode="CAD" Buy="'
        + buy.encode()
        + b'" Transfer="'
        + transfer.encode()
        + b'" Sell="'
        + sell.encode()
        + b'"/></ExrateList>'
    )


# --- Parsing ------------------------------------------------------------------------------------


def test_the_cad_row_is_read_with_all_three_rates_and_the_bank_stamp():
    parsed = fx_service.parse_vietcombank_xml(SAMPLE_XML)
    assert parsed.cash_buy == Decimal("17886.61")
    assert parsed.transfer_buy == Decimal("18067.28")
    assert parsed.sell == Decimal("18645.39")
    assert parsed.published_raw == "10/19/2026 8:30:00 AM"
    assert parsed.published_at == datetime(2026, 10, 19, 8, 30)


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("17,886.61", Decimal("17886.61")),
        ("17.886,61", Decimal("17886.61")),
        ("17886.61", Decimal("17886.61")),
        ("17.886", Decimal("17886")),
        ("-", None),
        ("", None),
        (None, None),
    ],
)
def test_vietnamese_and_english_number_notations(raw, value):
    assert fx_service.parse_vn_number(raw) == value


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        (b"<ExrateList/>", "CAD row not present"),
        (_xml("-", "-", "18,645.39"), "lacks the CAD cash-buying"),
        (_xml("17,886.61", "-", "-"), "lacks the CAD cash-buying or selling"),
        (_xml("178.86", "-", "186.45"), "outside the plausible range"),
        (_xml("178,866,100", "-", "186,453,900"), "outside the plausible range"),
        (_xml("18,645.39", "-", "17,886.61"), "not above the cash-buying"),
        (b"<not xml", "not well-formed"),
    ],
)
def test_implausible_or_incomplete_responses_are_refused(payload, fragment):
    with pytest.raises(fx_service.FxFetchError, match=fragment):
        fx_service.parse_vietcombank_xml(payload)


# --- Transport guard ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx",  # not https
        "https://portal.vietcombank.com.vn.attacker.test/pXML.aspx",  # suffix, not the host
        "https://user:pass@portal.vietcombank.com.vn/pXML.aspx",  # credentials
        "https://www.vietcombank.com.vn/",  # another host on the same domain
        "https://portal.vietcombank.com.vn:8443/pXML.aspx",  # not the HTTPS port
    ],
)
def test_the_fetcher_refuses_anything_but_the_banks_own_feed(url):
    with pytest.raises(fx_service.FxFetchError, match="refusing"):
        fx_service.default_fetcher(url)


# --- Snapshots and attempts ---------------------------------------------------------------------------


def test_a_verified_reading_writes_one_snapshot_and_one_ok_attempt(db):
    clock = lambda: datetime(2026, 10, 19, 13, 0)  # noqa: E731
    result = fx_service.sync_once(db, fetcher=lambda _url: SAMPLE_XML, clock=clock, worker_name="t")
    db.commit()

    assert result.outcome == FxSyncOutcome.OK
    snapshots = db.query(FxRateSnapshot).all()
    attempts = db.query(FxSyncAttempt).all()
    assert len(snapshots) == 1 and len(attempts) == 1
    assert snapshots[0].cash_buy_vnd == Decimal("17886.61")
    assert snapshots[0].sell_vnd == Decimal("18645.39")
    assert snapshots[0].retrieved_at == datetime(2026, 10, 19, 13, 0)
    assert snapshots[0].source_url == fx_service.VIETCOMBANK_XML_URL
    assert len(snapshots[0].content_sha256) == 64
    assert attempts[0].snapshot_id == snapshots[0].id
    assert attempts[0].outcome == FxSyncOutcome.OK and attempts[0].error_summary is None


def test_a_failed_reading_writes_an_attempt_and_no_snapshot_and_no_substitute(db):
    def broken(_url: str) -> bytes:
        raise fx_service.FxFetchError("bank unreachable: URLError")

    result = fx_service.sync_once(db, fetcher=broken, worker_name="t")
    db.commit()

    assert result.outcome == FxSyncOutcome.FAILED
    assert db.query(FxRateSnapshot).count() == 0
    attempt = db.query(FxSyncAttempt).one()
    assert attempt.outcome == FxSyncOutcome.FAILED
    assert attempt.error_summary == "bank unreachable: URLError"
    assert attempt.snapshot_id is None


def test_an_unexpected_transport_exception_is_recorded_by_type_only(db):
    def exploding(_url: str) -> bytes:
        raise RuntimeError("secret-looking detail that must not be stored")

    result = fx_service.sync_once(db, fetcher=exploding, worker_name="t")
    assert result.outcome == FxSyncOutcome.FAILED
    assert result.error_summary == "RuntimeError"


def test_snapshots_are_append_only_and_the_latest_is_by_retrieval_time(db):
    t0 = datetime(2026, 10, 19, 9, 0)
    for minutes, sell in ((0, "18,600.00"), (60, "18,650.00"), (30, "18,620.00")):
        fx_service.sync_once(
            db,
            fetcher=lambda _url, s=sell: _xml("17,886.61", "18,000.00", s),
            clock=lambda m=minutes: t0 + timedelta(minutes=m),
            worker_name="t",
        )
    db.commit()
    assert db.query(FxRateSnapshot).count() == 3
    assert fx_service.latest_snapshot(db).sell_vnd == Decimal("18650.00")


def test_freshness_is_none_then_live_then_stale(db):
    assert fx_service.freshness(None) == FxFreshness.NONE
    now = datetime(2026, 10, 19, 12, 0)
    fx_service.sync_once(db, fetcher=lambda _u: SAMPLE_XML, clock=lambda: now, worker_name="t")
    snapshot = fx_service.latest_snapshot(db)
    assert fx_service.freshness(snapshot, now=now + timedelta(minutes=5)) == FxFreshness.LIVE
    just_inside = now + timedelta(minutes=settings.fx_stale_after_minutes)
    assert fx_service.freshness(snapshot, now=just_inside) == FxFreshness.LIVE
    assert (
        fx_service.freshness(snapshot, now=just_inside + timedelta(minutes=1)) == FxFreshness.STALE
    )


# --- Worker ---------------------------------------------------------------------------------------------


def test_the_worker_once_mode_exit_code_reports_the_outcome(monkeypatch):
    monkeypatch.setattr(fx_service, "default_fetcher", lambda _url: SAMPLE_XML)
    assert fx_worker.main(["--once", "--worker-name", "test-fx"]) == 0

    def broken(_url: str) -> bytes:
        raise fx_service.FxFetchError("bank unreachable: URLError")

    monkeypatch.setattr(fx_service, "default_fetcher", broken)
    assert fx_worker.main(["--once", "--worker-name", "test-fx"]) == 1
