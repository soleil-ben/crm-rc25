"""The air dataset for UAT (Phase 17): pricing, quotes, acceptance, finance, tariffs, emails.

Run by ``scripts/uat_env.py`` after ``app.seed`` and its augmentation, in a subprocess whose
environment points ``DATABASE_URL`` at the UAT database, ``ACCOUNT_EMAIL_CAPTURE_DIR`` at the
UAT capture folder and ``TARIFF_INTAKE_DIR`` at the UAT intake folder. It is not meant to be
run by hand.

Everything is added **through the services and the HTTP routes**, never by writing rows (one
guard is widened for the domestic shipments; see below), so
the data obeys the rules a tester is checking. Air only (OD-49): every master is Air Standard
from Hồ Chí Minh City, every shipment Vietnam to Canada -- except the three domestic ones below.

What it adds, on top of P1-P5 and the base seed (which it does not touch)
--------------------------------------------------------------------------
* Settings: the 2 % default surcharge markup and the CAD 18.00 Air Standard rate saved by the
  demo Admin; the tariff approver list set to the demo Admin only; one allowed vendor sender
  domain, ``vendor-rates.example.com``.
* The sanitized Kango tariff (``backend/tests/fixtures``), active; demo Vietcombank readings
  (source ``demo://fixture``): one in the closed month, one now.
* Four customers, A1-A4, on ``example.com``. **A1** (Vietnamese) and **A2** (English) have
  Customer Accounts, registered, verified and linked by Operations through the real routes;
  A2 has turned off the "in transit" milestone email in their account.
* Five air masters, by vendor reference:

  ``UAT-AWB-OPEN``     open; A3 and A4, items and surcharge lines, draft quotes
  ``UAT-AWB-BOOKED``   booked; A1's quote finalised and sent, **awaiting the customer**;
                       A4's quote finalised, not sent
  ``UAT-AWB-TRANSIT``  booked, received / departed / in transit published; A2 accepted
                       (not invoiced, so Finance shows "Accepted, not invoiced"); A1 accepted
                       and invoiced from the draft at GST/HST 0 % (VN-CA, zero-rated by
                       route, DEC-0227), unpaid
  ``UAT-AWB-DELIVERED`` completed after delivery; A3 invoiced (0 %) and part-paid in CAD;
                       A4 invoiced (5 %), paid in VND at the sell rate, then part-refunded;
                       a VND vendor bill above the estimate, approved with a variance reason
                       and marked paid
  ``UAT-AWB-CLOSED``   the last month past M+7: invoiced, paid, billed at the estimate, and
                       the month **closed**

* Three **domestic** Canada -> Canada shipments for A2 (route group CAD, sent from Toronto) for
  the GST/HST-by-route cases (DEC-0227: a domestic draft auto-fills the *destination*
  province's rate, included in the price), each quoted, sent and **accepted in A2's account**,
  so each has a draft invoice, left unsent:

  ``UAT-AIR-DOM-NS``   to Halifax, NS, B3H 1A1: draft at 14 % HST
  ``UAT-AIR-DOM-NB``   to Moncton, NB, E1C 4M3: draft at 15 % HST
  ``UAT-AIR-DOM-UNK``  no province and no postal code: no rate suggested, staff must choose

  Province and postal code agree on NS and NB (the province may be read from the postal
  code's first letter or from the text); UNK has neither. **The one stand-in:** a quote needs a
  master (``pricing_service``) and only Vietnam -> Canada shipments may join one (OD-43,
  ``consolidation_service.CONSOLIDATABLE_ROUTE_GROUPS``), so there is no service path that
  prices a domestic shipment. The seed widens that one guard to CAD for the single
  ``add_member`` call and puts the three on their own booked master, ``UAT-DOM-AWB`` (outside
  the five ``UAT-AWB-*``), priced like the others at the Air Standard default rate; every row
  is still written by the services and the routes. Their prices mean nothing: only the tax
  does.

* Milestone emails for TRANSIT and DELIVERED, dispatched to the capture folder (Vietnamese
  for A1, A3, A4; English for A2; A2's "in transit" skipped as opted out).
* Two vendor rate emails built now from the sanitized fixture and read by the intake worker
  from the UAT intake folder: one from the allowed domain with three prices changed (a draft
  awaiting the approver) and one from an unknown sender (held). Copies of both stay in
  ``samples/`` for re-upload cases.

``--refresh-fx`` (``uat_env.py --refresh-fx``) adds only a new demo exchange-rate reading:
a reading counts as live for a day, and the real FX worker would call the bank.

Idempotent: a database that already holds ``UAT-AWB-OPEN`` is left alone. Deterministic: the
same names, references, amounts and order every time; only dates follow the day it runs.

Refuses: production; demo seeding off; a database that is not a ``.uat.db`` file; the
development database; a capture or intake folder outside the UAT database's own directory.
"""

from __future__ import annotations

import io
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from sqlalchemy import select  # noqa: E402

#: The marker: present means the dataset is already there.
MARKER_REFERENCE = "UAT-AWB-OPEN"
DEV_DB = REPO_ROOT / "data" / "solaris_crm.db"
UAT_SUFFIX = ".uat.db"

STAFF_PASSWORD = "SolarisDemo!2026"
ADMIN_EMAIL = "admin@demo.example.com"
OPS_EMAIL = "ops@demo.example.com"
#: The password of the two seeded Customer Accounts. Printed by ``uat_env.py --check`` and
#: written in ``docs/UAT/ENVIRONMENT.md`` beside the staff password; like it, refused in
#: production because the addresses are on reserved domains.
ACCOUNT_PASSWORD = "SolarisUatCustomer!2026"

ALLOWED_VENDOR_DOMAIN = "vendor-rates.example.com"
#: The rate-email mailbox shown in UAT. A reserved test address: the UAT database never
#: holds the production default.
INTAKE_MAILBOX = "tariffs@demo.example.com"
ALLOWED_VENDOR_SENDER = f"rates@{ALLOWED_VENDOR_DOMAIN}"
UNKNOWN_SENDER = "rates@unknown-forwarder.example.com"
#: Brackets (by position among the active tariff's air brackets) whose price the allowed
#: email changes, and by how much (VND); the held email changes one other.
CHANGED_BRACKETS = ((10, 5000), (40, 5000), (70, -3000))
HELD_BRACKETS = ((100, 7000),)


@dataclass(frozen=True)
class Person:
    ref: str
    full_name: str
    email: str
    phone: str
    city: str
    postal_code: str
    address: str
    language: str
    account: bool


PEOPLE = (
    Person(
        "A1",
        "Phạm Thị Thu Trang",
        "trang.air@example.com",
        "+1 416 555 0141",
        "Toronto",
        "M6H 2X4",
        "101 Test Data Lane (UAT)",
        "vi",
        True,
    ),
    Person(
        "A2",
        "Emily Carter",
        "emily.air@example.com",
        "+1 613 555 0142",
        "Ottawa",
        "K1N 5T5",
        "202 Sample Street (UAT)",
        "en",
        True,
    ),
    Person(
        "A3",
        "Võ Minh Khoa",
        "khoa.air@example.com",
        "+1 905 555 0143",
        "Mississauga",
        "L5B 3C2",
        "303 Placeholder Avenue (UAT)",
        "vi",
        False,
    ),
    Person(
        "A4",
        "Đỗ Ngọc Lan",
        "lan.air@example.com",
        "+1 647 555 0144",
        "Toronto",
        "M2N 6K1",
        "404 Fictional Road (UAT)",
        "vi",
        False,
    ),
)

VN_SENDER = {
    "name": "Nguyễn Văn Hùng (UAT)",
    "phone_entered": "+84 90 555 0101",
    "address_line1": "1 Đường Thử Nghiệm (UAT)",
    "city": "Thành phố Hồ Chí Minh",
    "province_state": "Hồ Chí Minh",
    "postal_code": "700000",
    "country_code": "VN",
}


#: Domestic Canada -> Canada (route group CAD) shipments for the GST/HST-by-route cases
#: (DEC-0227): the draft invoice auto-fills the *destination* province's rate, included in the
#: price. All for A2 (English Customer Account), sent from Toronto. Key, booking reference,
#: recipient city, province, postal code. NS and NB carry a matching postal code and province
#: (the first letter of the postal code and the text agree); UNK carries neither, so no
#: province is recognised and staff must choose the rate.
DOMESTIC = (
    ("DOM-NS", "UAT-AIR-DOM-NS", "Halifax", "NS", "B3H 1A1"),
    ("DOM-NB", "UAT-AIR-DOM-NB", "Moncton", "NB", "E1C 4M3"),
    ("DOM-UNK", "UAT-AIR-DOM-UNK", "Halifax", None, None),
)
DOMESTIC_MASTER = "UAT-DOM-AWB"
CA_SENDER = {
    "name": "Solaris Express Toronto desk (UAT)",
    "phone_entered": "+1 416 555 0150",
    "address_line1": "500 Test Depot Road (UAT)",
    "city": "Toronto",
    "province_state": "ON",
    "postal_code": "M5V 2T6",
    "country_code": "CA",
}


class Refused(RuntimeError):
    """A guard refused before anything was written."""


def guard() -> Path:
    """Refuse anything but a ``.uat.db`` database with its folders beside it."""
    if settings.is_production or not settings.allow_demo_seed:
        raise Refused("demo seeding is off or this is production")
    path = settings.sqlite_path
    if path is None or not path.name.endswith(UAT_SUFFIX):
        raise Refused(f"{path or settings.database_url} is not a {UAT_SUFFIX} database")
    resolved = path.resolve()
    if resolved == DEV_DB.resolve():
        raise Refused(f"{resolved} is the development database")
    home = resolved.parent
    for name, folder in (
        ("ACCOUNT_EMAIL_CAPTURE_DIR", settings.account_email_capture_path),
        ("TARIFF_INTAKE_DIR", settings.tariff_intake_path),
    ):
        try:
            folder.resolve().relative_to(home)
        except ValueError:
            raise Refused(f"{name} ({folder}) is outside {home}") from None
    return resolved


# --- Helpers --------------------------------------------------------------------------------


def _months_back(today: date, n: int) -> str:
    index = today.year * 12 + today.month - 1 - n
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def closed_month(now: datetime) -> str:
    """The latest month already past M+7, so it can be closed today."""
    from app.services import finance_service as fs

    for back in (1, 2):
        month = _months_back(now.date(), back)
        if now >= fs.lock_date(month):
            return month
    raise RuntimeError("no month is past M+7")  # pragma: no cover - two back always is


def _demo_fx(db, moment: datetime) -> None:
    from app.seed_pricing import DEMO_FX_SOURCE, _demo_xml
    from app.services import fx_service

    result = fx_service.sync_once(
        db,
        fetcher=lambda _url: _demo_xml(moment),
        clock=lambda: moment,
        worker_name="uat-seed",
        url=DEMO_FX_SOURCE,
    )
    if result.snapshot is None:
        raise RuntimeError(f"the demo exchange rate was refused: {result.error}")


def _customer(db, person: Person, owner_id: int, admin):
    from app.core.enums import (
        ContactChannel,
        CustomerCategory,
        RouteGroup,
        ShippingFrequency,
        ShippingPurpose,
    )
    from app.models import Customer
    from app.services import customer_service

    existing = db.scalar(select(Customer).where(Customer.email_normalized == person.email))
    if existing is not None:
        return existing
    return customer_service.create_customer(
        db,
        {
            "full_name": person.full_name,
            "phone": person.phone,
            "email": person.email,
            "city": person.city,
            "province_state": "ON",
            "country_code": "CA",
            "preferred_language": person.language,
            "category": CustomerCategory.INDIVIDUAL.value,
            "primary_shipping_purpose": ShippingPurpose.GIFTS_FAMILY_SUPPORT.value,
            "primary_route_group": RouteGroup.VCA.value,
            "shipping_frequency": ShippingFrequency.OCCASIONAL.value,
            "preferred_contact_channel": ContactChannel.EMAIL.value,
            "owner_user_id": owner_id,
            "notes": f"UAT air customer {person.ref} (docs/UAT/AIR_UAT_PACK.md). Seeded.",
        },
        actor=admin,
        is_demo_record=True,
    )


def _shipment(
    db,
    customer,
    person: Person,
    reference: str,
    kg: str,
    ops,
    *,
    route_group: str | None = None,
    sender: dict | None = None,
    recipient: dict | None = None,
):
    """A confirmed air booking, Vietnam -> Canada unless a route and addresses are given.
    A1's and A2's are not demo records, because the Customer Account shows no demo shipment."""
    from app.core.enums import RouteGroup
    from app.services import booking_service

    recipient = recipient or {
        "name": person.full_name,
        "phone_entered": person.phone,
        "address_line1": person.address,
        "city": person.city,
        "province_state": "ON",
        "postal_code": person.postal_code,
        "country_code": "CA",
    }
    draft = booking_service.create_draft(
        db,
        {
            "customer_id": customer.id,
            "route_group": route_group or RouteGroup.VCA.value,
            "service_type": "standard_parcel",
            "transport_mode": "air",
            "contents_description": "Family parcel: clothing, a watch, dried fruit (UAT)",
            "sender": dict(sender or VN_SENDER),
            "recipient": recipient,
            "booking_reference": reference,
            "is_demo_record": not person.account,
            "owner_user_id": ops.id,
            "packages": [
                {
                    "length_value": "40",
                    "width_value": "30",
                    "height_value": "20",
                    "dimension_unit": "cm",
                    "weight_value": kg,
                    "weight_unit": "kg",
                    "contents_summary": "Carton 1 (UAT)",
                }
            ],
        },
        actor=ops,
    )
    db.flush()
    result = booking_service.confirm_booking(
        db, shipment_id=draft.id, idempotency_key=f"uat-air-{reference}", actor=ops
    )
    db.flush()
    return result.shipment


def _items(db, shipment, lines, ops) -> None:
    """``lines``: (description, quantity, unit, kg, surcharge stt or None)."""
    from app.services import pricing_service as ps
    from app.services import shipment_item_service as items

    for description, quantity, unit, kg, stt in lines:
        item = items.add_item(
            db,
            shipment,
            {
                "description": description,
                "quantity": Decimal(quantity),
                "unit": unit,
                "weight_kg": Decimal(kg),
            },
            actor=ops,
        )
        if stt is not None:
            ps.add_fee_line(
                db, shipment, {"item_id": item.id, "section": "hcm_air", "stt": stt}, actor=ops
            )
    db.flush()


def _master(db, reference: str, members, kg: str, ops):
    from app.services import consolidation_service as cs

    master = cs.create_consolidation(
        db,
        {
            "solaris_service": "air_standard",
            "origin": "HCM",
            "vendor_reference": reference,
            "actual_weight_kg": kg,
            "carton_count": len(members),
        },
        actor=ops,
    )
    for shipment in members:
        cs.add_member(db, master, shipment, actor=ops)
    db.flush()
    return master


def _domestic_master(db, members, kg: str, ops):
    """The one stand-in of this seed (see the docstring): a quote needs a master, and only
    Vietnam -> Canada shipments may join one (OD-43), so the domestic shipments join
    ``UAT-DOM-AWB`` with that one guard widened to CAD for the call. Every row is still
    written by ``consolidation_service``; the guard is restored at once."""
    from app.core.enums import RouteGroup
    from app.services import consolidation_service as cs

    allowed = cs.CONSOLIDATABLE_ROUTE_GROUPS
    cs.CONSOLIDATABLE_ROUTE_GROUPS = (*allowed, RouteGroup.CAD)
    try:
        return _master(db, DOMESTIC_MASTER, members, kg, ops)
    finally:
        cs.CONSOLIDATABLE_ROUTE_GROUPS = allowed


def _finalize(db, shipment, ops, now=None):
    from app.services import pricing_service as ps

    ps.reprice(db, shipment, actor=ops, now=now)
    ps.confirm_rate(db, shipment, rate=None, reason=None, actor=ops, now=now)
    return ps.finalize(
        db,
        shipment,
        negative_margin_reason="UAT seed: surcharge policy per OD-44 stand-in",
        actor=ops,
        now=now,
    )


def _send(db, shipment, ops):
    from app.core.db import commit_with_retry
    from app.services import quote_offer_service as qos

    offer = qos.send_quote(db, shipment, actor=ops)
    commit_with_retry(db)
    qos.send_email(db, offer.id)
    db.commit()
    return offer


def _milestones(db, master, steps, ops, start, end):
    """Publish each master milestone in order, spread evenly between ``start`` and ``end``.

    ``steps``: (event type, staff wording or None). With no wording the standard update is
    published; with wording, staff's own sentence is published, which the Customer Account
    shows beneath the standard sentence (it differs from it, so it is visible: UAT-VIA-02).
    """
    from app.services import consolidation_service as cs
    from app.services import notification_service
    from app.services import public_update_templates as templates

    for index, (event_type, wording) in enumerate(steps, start=1):
        payload = {
            "event_type": event_type,
            "occurred_at": start + (end - start) * index / (len(steps) + 1),
            "is_public_update": True,
        }
        if wording:
            payload["public_update_text"] = wording
        else:
            payload["public_update_template_key"] = templates.keys_for_event_type(event_type)[0]
        cs.record_master_event(db, master, payload, actor=ops)
        db.commit()
    notification_service.dispatch_pending(db)


#: Staff's own wording on TRANSIT's departure, so the account shows it under the standard
#: sentence (UAT-VIA-02). Fictitious flight.
TRANSIT_DEPARTURE_WORDING = (
    "Chuyến bay UAT-101 đã cất cánh từ Tân Sơn Nhất lúc 23:40; dự kiến đến Toronto sau hai ngày."
)


def current_month_anchor(now: datetime) -> datetime:
    """Nine days back, but never before this month began, so the DELIVERED master's revenue
    month is always the current one and a reset near the 8th never changes the closed
    month's figures (UAT-FIN-06)."""
    month_start = datetime(now.year, now.month, 1, 0, 1)
    return max(now - timedelta(days=9), min(month_start, now - timedelta(minutes=10)))


# --- Customer Accounts, through the real routes ----------------------------------------------


def _registration(person: Person) -> dict:
    return {
        "email": person.email,
        "password": ACCOUNT_PASSWORD,
        "password_confirmation": ACCOUNT_PASSWORD,
        "accept_terms": True,
        "accept_privacy": True,
        "billing_same_as_shipping": True,
        "idempotency_key": f"uat-air-registration-{person.ref.lower()}",
        "customer": {
            "customer_type": "individual",
            "legal_name": person.full_name,
            "display_name": person.full_name.split()[-1],
            "primary_contact_name": person.full_name,
            "phone_country_code": "CA",
            "phone": person.phone.replace("+1 ", "").replace(" ", ""),
            "preferred_language": person.language,
            "marketing_consent": False,
            "pickup_address.1.contact_name": person.full_name,
            "pickup_address.1.address_line1": person.address,
            "pickup_address.1.city": person.city,
            "pickup_address.1.province_state": "ON",
            "pickup_address.1.postal_code": person.postal_code,
            "pickup_address.1.country_code": "CA",
        },
        "notification_topics": ["shipment_milestones"],
    }


class Http:
    """The application in process, against the UAT database the environment names."""

    def __init__(self, mail) -> None:
        from app.main import app
        from fastapi.testclient import TestClient

        self.mail = mail
        self.client = TestClient(app)
        self.client.__enter__()

    def close(self) -> None:
        self.client.__exit__(None, None, None)

    def _ok(self, response, what: str):
        if response.status_code >= 400:
            raise RuntimeError(f"{what}: {response.status_code} {response.text[:300]}")
        return response.json()

    def staff(self, email: str) -> dict[str, str]:
        self.client.cookies.clear()
        body = self._ok(
            self.client.post(
                "/api/v1/auth/login", json={"email": email, "password": STAFF_PASSWORD}
            ),
            "staff sign-in",
        )
        return {settings.csrf_header_name: body["csrf_token"]}

    def customer(self, email: str) -> tuple[dict[str, str], str]:
        self.client.cookies.clear()
        body = self._ok(
            self.client.post(
                "/api/v1/account/sign-in", json={"email": email, "password": ACCOUNT_PASSWORD}
            ),
            "account sign-in",
        )
        return {settings.account_csrf_header_name: body["csrf_token"]}, body["account_reference"]

    def link_account(self, person: Person, customer_public_id: str) -> str:
        """Register, verify from the captured link, and have Operations link it."""
        self.client.cookies.clear()
        self._ok(
            self.client.post("/api/v1/account/register", json=_registration(person)),
            f"registration of {person.ref}",
        )
        token = None
        for message in reversed(self.mail.messages):
            if message["to_email"].lower() == person.email and "token=" in message["body"]:
                token = message["body"].split("token=")[1].split()[0]
                break
        if token is None:
            raise RuntimeError(f"no verification message was captured for {person.ref}")
        self._ok(
            self.client.post("/api/v1/account/verify-email", json={"token": token}),
            f"verification of {person.ref}",
        )
        headers, reference = self.customer(person.email)
        self.client.post("/api/v1/account/sign-out", headers=headers)

        staff = self.staff(OPS_EMAIL)
        base = f"/api/v1/customer-account/registrations/{reference}"
        preview = self._ok(
            self.client.get(
                f"{base}/preview",
                params={"action": "link_existing", "customer_public_id": customer_public_id},
            ),
            "link preview",
        )
        self._ok(
            self.client.post(
                f"{base}/disclosure-acknowledgement",
                headers=staff,
                json={
                    "action": "link_existing",
                    "customer_public_id": customer_public_id,
                    "fingerprint": preview["fingerprint"],
                },
            ),
            "preview acknowledgement",
        )
        self._ok(
            self.client.post(
                f"{base}/approve/link-existing",
                headers=staff,
                json={
                    "customer_public_id": customer_public_id,
                    "preview_fingerprint": preview["fingerprint"],
                    "idempotency_key": f"uat-air-link-{person.ref.lower()}",
                },
            ),
            "link approval",
        )
        self.client.cookies.clear()
        return reference

    def opt_out(self, person: Person, milestone: str) -> None:
        headers, _ = self.customer(person.email)
        self._ok(
            self.client.post(
                "/api/v1/account/notifications/preferences",
                headers=headers,
                json={"preferences": {milestone: False}},
            ),
            "milestone choice",
        )
        self.client.post("/api/v1/account/sign-out", headers=headers)

    def accept(self, person: Person, offer_id: int) -> None:
        headers, _ = self.customer(person.email)
        self._ok(
            self.client.post(f"/api/v1/account/quotes/{offer_id}/accept", headers=headers),
            "quote acceptance",
        )
        self.client.post("/api/v1/account/sign-out", headers=headers)


# --- Vendor rate emails ------------------------------------------------------------------------


def _changed_workbook(db, changes) -> bytes:
    import openpyxl
    from app.models import TariffProduct, TariffRateBracket
    from app.seed_pricing import WORKBOOK
    from app.services import tariff_import_service as tis

    active = tis.active_version(db, tis.KANGO_VENDOR_KEY)
    brackets = list(
        db.scalars(
            select(TariffRateBracket)
            .join(TariffProduct)
            .where(TariffProduct.version_id == active.id, TariffProduct.mode == "air")
            .order_by(TariffRateBracket.id)
        )
    )
    workbook = openpyxl.load_workbook(WORKBOOK)
    for position, delta in changes:
        bracket = brackets[position]
        workbook[bracket.source_sheet][bracket.source_cell] = float(bracket.price_vnd + delta)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _eml(sender: str, subject: str, message_id: str, workbook: bytes, sent: datetime) -> bytes:
    message = EmailMessage()
    message["From"] = f"Vendor Rates (UAT) <{sender}>"
    message["To"] = INTAKE_MAILBOX
    message["Subject"] = subject
    message["Message-ID"] = message_id
    message["Date"] = format_datetime(sent)
    message.set_content("Synthetic UAT rate email. The new rates are attached.")
    message.add_attachment(
        workbook,
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="Kango Canada rates (UAT).xlsx",
    )
    return message.as_bytes()


def rate_emails(db, now: datetime) -> list[tuple[str, bytes]]:
    stamp = now.strftime("%Y%m%d")
    return [
        (
            "uat-rates-allowed.eml",
            _eml(
                ALLOWED_VENDOR_SENDER,
                "Kango Canada air rates, three prices updated (UAT)",
                f"<uat-rates-allowed-{stamp}@{ALLOWED_VENDOR_DOMAIN}>",
                _changed_workbook(db, CHANGED_BRACKETS),
                now - timedelta(hours=2),
            ),
        ),
        (
            "uat-rates-unknown-sender.eml",
            _eml(
                UNKNOWN_SENDER,
                "Fwd: Kango Canada air rates (UAT)",
                f"<uat-rates-held-{stamp}@unknown-forwarder.example.com>",
                _changed_workbook(db, HELD_BRACKETS),
                now - timedelta(hours=1),
            ),
        ),
    ]


# --- The build ---------------------------------------------------------------------------------


def build() -> list[str]:  # noqa: PLR0915 - one linear story, told in order
    from app.core.db import SessionLocal, commit_with_retry
    from app.core.enums import ShipmentEventType as Ev
    from app.core.time_utils import utcnow
    from app.models import Consolidation, User
    from app.seed_pricing import import_tariff
    from app.services import account_email_service
    from app.services import consolidation_service as cs
    from app.services import finance_service as fs
    from app.services import pricing_service as ps
    from app.services import tariff_intake_service as intake
    from app.workers import tariff_intake_worker

    mail = account_email_service.CaptureEmailTransport(settings.account_email_capture_path)
    account_email_service.set_transport(mail)
    out: list[str] = []
    db = SessionLocal()
    try:
        if db.scalar(
            select(Consolidation).where(Consolidation.vendor_reference == MARKER_REFERENCE)
        ):
            return [f"already present ({MARKER_REFERENCE}); nothing added"]
        admin = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        ops = db.scalar(select(User).where(User.email == OPS_EMAIL))
        if admin is None or ops is None:
            raise RuntimeError("the base seed's Admin and Operations accounts are missing")
        now = utcnow()

        # Settings and the tariff.
        ps.update_settings(
            db,
            {"air_standard_default_rate_cad": "18.00", "defaults_owner_confirmed": True},
            actor=admin,
        )
        ps.update_markup_default(db, "percent", "2.00", actor=admin)
        intake.update_settings(
            db,
            approver_emails=[ADMIN_EMAIL],
            allowed_sender_domains=[ALLOWED_VENDOR_DOMAIN],
            mailbox_address=INTAKE_MAILBOX,
            actor=None,
        )
        import_tariff(db)
        db.commit()
        out.append("pricing settings saved: Air Standard CAD 18.00/kg, default markup 2 %")
        out.append(f"tariff approvers: {ADMIN_EMAIL}; allowed sender: {ALLOWED_VENDOR_DOMAIN}")
        out.append("sanitized Kango tariff active")

        # Customers A1-A4 and their shipments.
        people = {p.ref: p for p in PEOPLE}
        customers = {p.ref: _customer(db, p, ops.id, admin) for p in PEOPLE}
        db.commit()
        kg = {"A1": "6", "A2": "8", "A3": "5", "A4": "7"}
        ship = {}
        for ref, number in (
            ("A3", 1),
            ("A4", 1),
            ("A1", 2),
            ("A4", 2),
            ("A1", 1),
            ("A2", 1),
            ("A3", 2),
            ("A4", 3),
            ("A3", 3),
        ):
            key = f"{ref}-{number}"
            ship[key] = _shipment(db, customers[ref], people[ref], f"UAT-AIR-{key}", kg[ref], ops)
        db.commit()
        out.append(
            "customers A1-A4 with 9 air shipments (booking references UAT-AIR-A1-1 ... A4-3)"
        )

        # The closed month first, while the only exchange rate is that month's.
        month = closed_month(now)
        year, number = (int(part) for part in month.split("-"))
        mid = datetime(year, number, 15, 15, 0)
        _demo_fx(db, mid)
        _items(db, ship["A3-3"], [("Áo khoác (UAT)", "2", "piece", "2.0", None)], ops)
        closed = _master(db, "UAT-AWB-CLOSED", [ship["A3-3"]], "5", ops)
        cs.book_consolidation(db, closed, actor=ops, now=mid)
        _finalize(db, ship["A3-3"], ops, now=mid)
        db.commit()
        invoice = fs.issue_invoice(db, ship["A3-3"], actor=ops, now=mid)
        fs.record_payment(
            db,
            invoice,
            {"currency": "CAD", "amount_cad": str(invoice.total_cad), "method": "e_transfer"},
            actor=ops,
            now=mid + timedelta(days=2),
        )
        est, _ = ps.estimate_for(db, closed, now=mid)
        expected_cad = fs._expected(est)[1]
        bill = fs.enter_vendor_invoice(
            db,
            closed,
            {
                "currency": "CAD",
                "vendor_bill_number": "UAT-BILL-CLOSED",
                "lines": [{"kind": "base", "amount": str(expected_cad)}],
            },
            actor=ops,
            now=mid + timedelta(days=3),
        )
        fs.approve_vendor_invoice(
            db,
            bill,
            {"variance_reason": None if bill.variance_cad == 0 else "UAT seed: rounding"},
            actor=admin,
            now=mid + timedelta(days=3),
        )
        fs.mark_vendor_invoice_paid(
            db, bill, {"reference": "UAT-PAID-CLOSED"}, actor=admin, now=mid + timedelta(days=4)
        )
        cs.complete_consolidation(db, closed, actor=ops)
        db.commit()

        # A fresh exchange rate for everything from here on.
        _demo_fx(db, now)
        db.commit()
        out.append("demo exchange rates recorded (source demo://fixture): one now, one in " + month)

        # Customer Accounts (A1 Vietnamese, A2 English); A2 turns "in transit" off.
        db.commit()  # end the read snapshot: the routes write through their own sessions
        http = Http(mail)
        try:
            references = {
                ref: http.link_account(people[ref], customers[ref].public_id)
                for ref in ("A1", "A2")
            }
            http.opt_out(people["A2"], "in_transit")
        finally:
            http.close()
        db.rollback()  # a fresh snapshot that sees what the routes wrote
        out.append(
            "Customer Accounts linked: "
            + ", ".join(f"{ref} {references[ref]} ({people[ref].email})" for ref in references)
            + "; A2 turned off the 'in transit' email"
        )

        # OPEN: items and surcharge lines, draft quotes only.
        _items(
            db,
            ship["A3-1"],
            [
                ("Quần áo (UAT)", "4", "piece", "2.5", None),
                ("Đồng hồ đeo tay (UAT)", "1", "piece", "0.4", 18),
            ],
            ops,
        )
        _items(db, ship["A4-1"], [("Cà phê rang xay (UAT)", "3", "box", "1.5", None)], ops)
        _master(db, "UAT-AWB-OPEN", [ship["A3-1"], ship["A4-1"]], "12", ops)
        for key in ("A3-1", "A4-1"):
            ps.reprice(db, ship[key], actor=ops)
        db.commit()

        # BOOKED: A1's quote sent and awaiting the customer; A4's finalised, not sent.
        _items(db, ship["A1-2"], [("Đồng hồ (UAT)", "1", "piece", "0.3", 18)], ops)
        _items(db, ship["A4-2"], [("Bánh kẹo (UAT)", "5", "box", "2.0", None)], ops)
        booked = _master(db, "UAT-AWB-BOOKED", [ship["A1-2"], ship["A4-2"]], "13", ops)
        cs.book_consolidation(db, booked, actor=ops)
        _finalize(db, ship["A1-2"], ops)
        _finalize(db, ship["A4-2"], ops)
        db.commit()
        awaiting = _send(db, ship["A1-2"], ops).id

        # TRANSIT: both quotes accepted in the account; A1's invoiced (0 %: VN-CA, DEC-0227).
        _items(db, ship["A1-1"], [("Quần áo trẻ em (UAT)", "6", "piece", "3.0", None)], ops)
        _items(db, ship["A2-1"], [("Wristwatch (UAT)", "1", "piece", "0.5", 18)], ops)
        transit = _master(db, "UAT-AWB-TRANSIT", [ship["A1-1"], ship["A2-1"]], "14", ops)
        cs.book_consolidation(db, transit, actor=ops)
        _finalize(db, ship["A1-1"], ops)
        _finalize(db, ship["A2-1"], ops)
        db.commit()
        offers = {key: _send(db, ship[key], ops).id for key in ("A1-1", "A2-1")}
        db.commit()  # end the read snapshot: the routes write through their own sessions
        http = Http(mail)
        try:
            http.accept(people["A1"], offers["A1-1"])
            http.accept(people["A2"], offers["A2-1"])
        finally:
            http.close()
        db.rollback()  # a fresh snapshot that sees what the routes wrote
        # Owner decision 9a (2026-10-21): acceptance prepared each invoice as a draft. A1's is
        # sent at the GST/HST its route filled in -- VN-CA is zero-rated, 0 % (owner Ben,
        # 2026-10-23, DEC-0227) -- after staff confirm it (owner, 2026-10-22: the tax is
        # confirmed before Save and Send); A2's stays a draft for the tester to review and send.
        from app.services import invoice_draft_service as drafts

        draft = drafts.live_for_shipment(db, ship["A1-1"].id)
        drafts.update_draft(
            db,
            draft,
            {"tax_confirmed": True},
            expected_revision=draft.revision,
            actor=ops,
        )
        drafts.send(db, draft, expected_revision=draft.revision, actor=ops)
        db.commit()
        _milestones(
            db,
            transit,
            [
                (Ev.RECEIVED_AT_SOLARIS, None),
                (Ev.DEPARTED_ORIGIN, TRANSIT_DEPARTURE_WORDING),
                (Ev.IN_TRANSIT, None),
            ],
            ops,
            now - timedelta(days=4),
            now - timedelta(hours=1),
        )

        # DOMESTIC (DEC-0227): three Canada -> Canada shipments for A2, priced on UAT-DOM-AWB,
        # sent and accepted in A2's account; each acceptance prepared a draft invoice at the
        # destination province's rate, included: NS 14 %, NB 15 %, unknown -> staff choose.
        from app.core.enums import RouteGroup

        for key, reference, city, province, postal in DOMESTIC:
            ship[key] = _shipment(
                db,
                customers["A2"],
                people["A2"],
                reference,
                "4",
                ops,
                route_group=RouteGroup.CAD.value,
                sender=CA_SENDER,
                recipient={
                    "name": people["A2"].full_name,
                    "phone_entered": people["A2"].phone,
                    "address_line1": "12 Domestic Test Way (UAT)",
                    "city": city,
                    "province_state": province,
                    "postal_code": postal,
                    "country_code": "CA",
                },
            )
            _items(db, ship[key], [("Books (UAT)", "4", "piece", "2.0", None)], ops)
        domestic = _domestic_master(db, [ship[key] for key, *_ in DOMESTIC], "12", ops)
        cs.book_consolidation(db, domestic, actor=ops)
        for key, *_ in DOMESTIC:
            _finalize(db, ship[key], ops)
        db.commit()
        domestic_offers = [_send(db, ship[key], ops).id for key, *_ in DOMESTIC]
        db.commit()  # end the read snapshot: the routes write through their own sessions
        http = Http(mail)
        try:
            for offer_id in domestic_offers:
                http.accept(people["A2"], offer_id)
        finally:
            http.close()
        db.rollback()  # a fresh snapshot that sees what the routes wrote
        out.append(
            f"domestic shipments on {DOMESTIC_MASTER}, accepted by A2, drafts unsent: "
            + ", ".join(reference for _key, reference, *_ in DOMESTIC)
        )

        # DELIVERED: milestones to delivery, invoices, payments, a refund, a vendor bill.
        _items(db, ship["A3-2"], [("Sơn móng tay (UAT)", "12", "bottle", "1.8", None)], ops)
        _items(db, ship["A4-3"], [("Thuốc bổ (UAT)", "2", "box", "0.8", None)], ops)
        delivered = _master(db, "UAT-AWB-DELIVERED", [ship["A3-2"], ship["A4-3"]], "12", ops)
        anchor = current_month_anchor(now)
        cs.book_consolidation(db, delivered, actor=ops, now=anchor)
        _finalize(db, ship["A3-2"], ops)
        _finalize(db, ship["A4-3"], ops)
        db.commit()
        _milestones(
            db,
            delivered,
            [
                (Ev.RECEIVED_AT_SOLARIS, None),
                (Ev.DEPARTED_ORIGIN, None),
                (Ev.IN_TRANSIT, None),
                (Ev.OUT_FOR_DELIVERY, None),
                (Ev.DELIVERED_TO_RECIPIENT, None),
            ],
            ops,
            anchor,
            now - timedelta(minutes=1),
        )
        part_paid = fs.issue_invoice(db, ship["A3-2"], actor=ops)
        fs.record_payment(
            db,
            part_paid,
            {
                "currency": "CAD",
                "amount_cad": "50.00",
                "method": "e_transfer",
                "reference": "UAT-ETR-0001",
            },
            actor=ops,
        )
        vnd_paid = fs.issue_invoice(db, ship["A4-3"], actor=ops, tax_rate_percent=5)
        db.flush()
        sell = fs._invoice_vnd_rate(db, vnd_paid)[0]
        vnd_amount = (vnd_paid.total_cad * sell).quantize(Decimal("1"), rounding=ROUND_CEILING)
        payment = fs.record_payment(
            db,
            vnd_paid,
            {
                "currency": "VND",
                "amount_vnd": str(vnd_amount),
                "method": "bank_transfer",
                "reference": "UAT-VCB-0001",
            },
            actor=ops,
        )
        fs.refund_payment(
            db,
            payment,
            {"amount_cad": "10.00", "reason": "UAT seed: goodwill for a late delivery"},
            actor=admin,
        )
        est, _ = ps.estimate_for(db, delivered)
        expected_vnd = fs._expected(est)[0]
        bill = fs.enter_vendor_invoice(
            db,
            delivered,
            {
                "currency": "VND",
                "vendor_bill_number": "UAT-BILL-DELIVERED",
                "lines": [
                    {"kind": "base", "amount": str(expected_vnd)},
                    {
                        "kind": "other",
                        "amount": "350000",
                        "description": "Weekend handling (UAT)",
                    },
                ],
            },
            actor=ops,
        )
        fs.approve_vendor_invoice(
            db,
            bill,
            {"variance_reason": "UAT seed: vendor added weekend handling, agreed by phone"},
            actor=admin,
        )
        fs.mark_vendor_invoice_paid(db, bill, {"reference": "UAT-PAID-DELIVERED"}, actor=admin)
        cs.complete_consolidation(db, delivered, actor=ops)
        db.commit()

        # Close the month whose figures were recorded above.
        fs.close_month(db, month, actor=admin)
        commit_with_retry(db)

        # Vendor rate emails, read by the intake worker from the UAT intake folder.
        folder = settings.tariff_intake_path
        samples = folder / "samples"
        samples.mkdir(parents=True, exist_ok=True)
        for name, raw in rate_emails(db, now):
            (folder / name).write_bytes(raw)
            (samples / name).write_bytes(raw)
        db.close()
        outcomes = tariff_intake_worker.run_once(folder)
        db = SessionLocal()

        out += summary(db, month, awaiting, {str(k): v for k, v in outcomes.items()})
        db.commit()
        return out
    finally:
        db.close()
        account_email_service.reset_transport()


def summary(db, month: str, awaiting_offer: int, outcomes: dict) -> list[str]:
    from app.models import Consolidation, CustomerInvoice, NotificationOutbox, QuoteOffer
    from app.services import finance_service as fs

    lines = []
    for master in db.scalars(
        select(Consolidation)
        .where(Consolidation.vendor_reference.like("UAT-AWB-%"))
        .order_by(Consolidation.id)
    ):
        lines.append(f"master {master.public_id} {master.vendor_reference}: {master.state}")
    offers = {}
    for offer in db.scalars(select(QuoteOffer)):
        offers[offer.status] = offers.get(offer.status, 0) + 1
    lines.append(f"quote offers by status: {dict(sorted(offers.items()))}")
    lines.append(f"quote offer awaiting the customer: id {awaiting_offer}")
    invoices = db.scalars(select(CustomerInvoice).order_by(CustomerInvoice.id)).all()
    lines.append(
        "invoices: "
        + ", ".join(f"{i.public_id} {i.tax_status} CAD {i.total_cad} {i.status}" for i in invoices)
    )
    sent = {}
    for row in db.scalars(select(NotificationOutbox)):
        label = row.status if row.status != "skipped" else f"skipped:{row.skip_reason}"
        sent[label] = sent.get(label, 0) + 1
    lines.append(f"milestone emails: {dict(sorted(sent.items()))}")
    lines.append(f"month {month}: {fs.period_state(db, month)}")
    lines.append(f"rate emails read by the intake worker: {dict(sorted(outcomes.items()))}")
    return lines


def refresh_fx() -> str:
    """One new demo Vietcombank reading, now. No network: the reading is the fixture's."""
    from app.core.db import SessionLocal
    from app.core.time_utils import utcnow

    with SessionLocal() as db:
        _demo_fx(db, utcnow())
        db.commit()
    return "added a fresh demo exchange-rate reading (source demo://fixture)"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        guard()
    except Refused as refused:
        print(f"Refused: {refused}", file=sys.stderr)
        return 2
    if args == ["--refresh-fx"]:
        print(refresh_fx())
        return 0
    if args:
        print(f"Unknown arguments: {' '.join(args)}", file=sys.stderr)
        return 2
    for line in build():
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
