"""Vietcombank CAD exchange rates: fetch, verify, snapshot, and report freshness (Phase 13A).

What this does and refuses to do:

* **One source.** The bank's public XML feed, at a URL fixed in this module. The URL is
  not a setting, so a deployment cannot be pointed at a different provider by
  configuration; the directive forbids substituting another provider's number for a
  failed bank retrieval (v2.0 §12, handoff §6).
* **Both rates or nothing.** Cost converts at **cash buying**, customer surcharges at
  **selling** (handoff owner decision 10). A response missing either is a failed attempt.
* **Plausibility, not correction.** A CAD rate outside 1,000–100,000 VND, or a selling
  rate not above the cash-buying rate, is refused and recorded as a failure. Nothing is
  clamped or adjusted.
* **The fetch is guarded.** HTTPS only, the bank's exact host, no redirects followed, a
  bounded response size, a timeout, and no credential of any kind. The transport is
  injected, so the tests never touch the network and a production run never touches
  anything but the bank.
* **Snapshots are append-only.** A quotation records the snapshot it used; the row must
  still say the same thing later.
* **Nothing is logged but categories.** A failure is recorded as its exception type and a
  bounded message; never the response body.
"""

from __future__ import annotations

import hashlib
import re
import ssl
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import FxFreshness, FxSyncOutcome
from app.core.time_utils import utcnow
from app.models import VIETCOMBANK_KEY, FxRateSnapshot, FxSyncAttempt

#: The bank's published XML feed. Fixed on purpose; see the module docstring.
VIETCOMBANK_XML_URL = "https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx"
VIETCOMBANK_HOST = "portal.vietcombank.com.vn"
CURRENCY = "CAD"

MAX_RESPONSE_BYTES = 512 * 1024
TIMEOUT_SECONDS = 15.0
PLAUSIBLE_MIN = Decimal(1_000)
PLAUSIBLE_MAX = Decimal(100_000)

Fetcher = Callable[[str], bytes]
Clock = Callable[[], datetime]


class FxFetchError(RuntimeError):
    """The bank could not be read, or what it returned could not be trusted."""


@dataclass(frozen=True)
class ParsedFx:
    cash_buy: Decimal
    transfer_buy: Decimal | None
    sell: Decimal
    published_raw: str | None
    published_at: datetime | None


@dataclass(frozen=True)
class SyncResult:
    outcome: FxSyncOutcome
    snapshot: FxRateSnapshot | None
    error_summary: str | None


# --- Parsing -------------------------------------------------------------------------


def parse_vn_number(raw: str | None) -> Decimal | None:
    """``"18,123.45"`` → 18123.45; ``"18.123,45"`` → 18123.45; ``"-"`` or blank → None."""
    if raw is None:
        return None
    text = str(raw).strip().replace(" ", "")
    if not text or text == "-":
        return None
    if "," in text and "." in text:
        if text.rfind(".") > text.rfind(","):
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        parts = text.split(",")
        text = "".join(parts) if len(parts[-1]) == 3 else text.replace(",", ".")
    elif "." in text and len(text.split(".")[-1]) == 3 and text.count(".") >= 1:
        # "18.123" is a thousands-separated integer in Vietnamese notation.
        text = text.replace(".", "")
    try:
        return Decimal(text)
    except InvalidOperation as error:
        raise FxFetchError(f"unreadable number in bank response: {type(error).__name__}") from error


_BANK_STAMP_FORMATS = (
    "%m/%d/%Y %I:%M:%S %p",
    "%d/%m/%Y %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%d/%m/%Y %H:%M",
)


def parse_bank_stamp(raw: str | None) -> datetime | None:
    """The bank's own timestamp, when it parses. Kept raw beside it either way."""
    if not raw:
        return None
    text = raw.strip()
    for fmt in _BANK_STAMP_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_vietcombank_xml(payload: bytes) -> ParsedFx:
    """Read the CAD row out of the bank's XML. Refuses anything implausible."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise FxFetchError("bank response is not well-formed XML") from error

    row = next(
        (el for el in root.iter() if el.attrib.get("CurrencyCode", "").strip().upper() == CURRENCY),
        None,
    )
    if row is None:
        raise FxFetchError("CAD row not present in bank response")

    cash_buy = parse_vn_number(row.attrib.get("Buy"))
    transfer = parse_vn_number(row.attrib.get("Transfer"))
    sell = parse_vn_number(row.attrib.get("Sell"))
    if cash_buy is None or sell is None:
        raise FxFetchError("bank response lacks the CAD cash-buying or selling rate")
    for name, value in (("cash buying", cash_buy), ("selling", sell)):
        if not (PLAUSIBLE_MIN < value < PLAUSIBLE_MAX):
            raise FxFetchError(f"CAD {name} rate outside the plausible range; refusing to record")
    if sell <= cash_buy:
        raise FxFetchError("CAD selling rate is not above the cash-buying rate; refusing to record")

    stamp = (
        root.attrib.get("DateTime")
        or root.attrib.get("Datetime")
        or root.findtext("DateTime")
        or root.findtext("Datetime")
        or ""
    ).strip() or None
    return ParsedFx(cash_buy, transfer, sell, stamp, parse_bank_stamp(stamp))


# --- Transport -----------------------------------------------------------------------


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise FxFetchError(f"bank responded with a redirect ({code}); not followed")


def default_fetcher(url: str) -> bytes:
    """Fetch the bank's feed with the guards described in the module docstring."""
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname != VIETCOMBANK_HOST
        or parts.port not in (None, 443)
        or parts.username
        or parts.password
    ):
        raise FxFetchError("refusing to fetch anything but the bank's own HTTPS feed")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "SolarisExpressCRM/1.0 (+exchange-rate check)",
            "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.1",
        },
    )
    opener = urllib.request.build_opener(
        _NoRedirects(), urllib.request.HTTPSHandler(context=ssl.create_default_context())
    )
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            if "xml" not in content_type and "text" not in content_type:
                raise FxFetchError("bank response is not XML")
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.URLError as error:
        raise FxFetchError(f"bank unreachable: {type(error).__name__}") from error
    except TimeoutError as error:
        raise FxFetchError("bank request timed out") from error
    if len(body) > MAX_RESPONSE_BYTES:
        raise FxFetchError("bank response larger than the allowed size")
    return body


# --- Persistence ---------------------------------------------------------------------


def snapshot_on(db: Session, day: date, *, end: datetime | None = None) -> FxRateSnapshot | None:
    """The reading in force on ``day``: the latest one retrieved before that day ended.

    Used where the owner fixed a rate "on the invoice date" (OD-66, OD-73). A day with no
    reading of its own (a weekend, an outage) takes the last one before it. ``end`` is the
    stored (UTC) moment the day ends, for a day in the business's own time zone; without it
    the day ends at midnight UTC.
    """
    if end is None:
        end = datetime(day.year, day.month, day.day) + timedelta(days=1)
    return db.scalars(
        select(FxRateSnapshot)
        .where(
            FxRateSnapshot.bank == VIETCOMBANK_KEY,
            FxRateSnapshot.currency == CURRENCY,
            FxRateSnapshot.retrieved_at < end,
        )
        .order_by(FxRateSnapshot.retrieved_at.desc(), FxRateSnapshot.id.desc())
        .limit(1)
    ).first()


def latest_snapshot(db: Session) -> FxRateSnapshot | None:
    return db.scalars(
        select(FxRateSnapshot)
        .where(FxRateSnapshot.bank == VIETCOMBANK_KEY, FxRateSnapshot.currency == CURRENCY)
        .order_by(FxRateSnapshot.retrieved_at.desc(), FxRateSnapshot.id.desc())
        .limit(1)
    ).first()


def latest_attempt(db: Session) -> FxSyncAttempt | None:
    return db.scalars(
        select(FxSyncAttempt)
        .where(FxSyncAttempt.bank == VIETCOMBANK_KEY, FxSyncAttempt.currency == CURRENCY)
        .order_by(FxSyncAttempt.attempted_at.desc(), FxSyncAttempt.id.desc())
        .limit(1)
    ).first()


def freshness(snapshot: FxRateSnapshot | None, *, now: datetime | None = None) -> FxFreshness:
    if snapshot is None:
        return FxFreshness.NONE
    now = now or utcnow()
    age_minutes = (now - snapshot.retrieved_at).total_seconds() / 60
    return FxFreshness.LIVE if age_minutes <= settings.fx_stale_after_minutes else FxFreshness.STALE


def _bounded(text: str, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def sync_once(
    db: Session,
    *,
    fetcher: Fetcher | None = None,
    clock: Clock | None = None,
    worker_name: str,
    url: str = VIETCOMBANK_XML_URL,
) -> SyncResult:
    """One attempt: fetch, parse, verify, snapshot. Always writes an attempt row.

    The caller commits. A failure is a recorded failure, never an exception out of here,
    so a worker loop keeps going and the operator sees the run of failures.
    """
    now = clock() if clock else utcnow()
    # Resolved at call time so a test can substitute the transport through the module.
    fetch = fetcher or default_fetcher
    try:
        payload = fetch(url)
        parsed = parse_vietcombank_xml(payload)
    except FxFetchError as error:
        return _record_failure(db, now, worker_name, _bounded(str(error)))
    except Exception as error:  # a transport bug must not take the worker down
        return _record_failure(db, now, worker_name, _bounded(f"{type(error).__name__}"))

    snapshot = FxRateSnapshot(
        bank=VIETCOMBANK_KEY,
        currency=CURRENCY,
        cash_buy_vnd=parsed.cash_buy,
        transfer_buy_vnd=parsed.transfer_buy,
        sell_vnd=parsed.sell,
        bank_published_raw=parsed.published_raw[:60] if parsed.published_raw else None,
        bank_published_at=parsed.published_at,
        retrieved_at=now,
        content_sha256=hashlib.sha256(payload).hexdigest(),
        source_url=url,
    )
    db.add(snapshot)
    db.flush()
    db.add(
        FxSyncAttempt(
            bank=VIETCOMBANK_KEY,
            currency=CURRENCY,
            attempted_at=now,
            outcome=FxSyncOutcome.OK,
            error_summary=None,
            snapshot_id=snapshot.id,
            worker_name=worker_name,
        )
    )
    db.flush()
    return SyncResult(FxSyncOutcome.OK, snapshot, None)


def _record_failure(db: Session, now: datetime, worker_name: str, summary: str) -> SyncResult:
    db.add(
        FxSyncAttempt(
            bank=VIETCOMBANK_KEY,
            currency=CURRENCY,
            attempted_at=now,
            outcome=FxSyncOutcome.FAILED,
            error_summary=summary,
            snapshot_id=None,
            worker_name=worker_name,
        )
    )
    db.flush()
    return SyncResult(FxSyncOutcome.FAILED, None, summary)
