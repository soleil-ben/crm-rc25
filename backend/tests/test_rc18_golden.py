"""RC-UAT-18 golden tests (independent tester): owner answers OD-81 .. OD-90, black box over HTTP.

Journeys, end to end through the staff, Customer Account and public routes:

1. A booked master locks its members' items and fee lines (OD-88): Admin unlock with a reason,
   audited edits, relock by Operations, automatic relock on finalising a member's quote.
2. Acceptance prepares a draft invoice (OD-89/OD-90): revision-checked Save and Send, DRAFT
   PDF, the issued invoice, the Vietnamese invoice email.
3. Quote expiry on a new tariff version before the goods are received (OD-89).
4. No vendor name in anything customer-facing (OD-84).
5. Tariff readings: the confirmed Express 16 kg steps (OD-81) and HCM row 41 (OD-82).

The pricing world (tariff v1, exchange rate, shipments, the master) is seeded through
services, as the other pricing golden suites do; a vendor-worded rule name is test data.
Everything under test goes through HTTP. Demo addresses only; air only; capture transport.
"""

from __future__ import annotations

import io
import json
import unicodedata
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.core.config import settings
from app.core.enums import Role, RouteGroup
from app.core.time_utils import utcnow
from app.main import app
from app.models import (
    AuditEvent,
    Customer,
    QuoteExpiry,
    Shipment,
    ShipmentPackage,
    TariffSurchargeRule,
)
from app.services import consolidation_service as cs
from app.services import fx_service, tariff_intake_service
from app.services import tariff_import_service as tis
from tests.account_fixtures import (
    REGISTRATION_BODY,
    csrf_headers,
    register,
    sign_in,
    verification_token,
    verify,
)
from tests.approval_fixtures import acknowledged_preview, approve_create, staff
from tests.conftest import booked_shipment, make_customer, see_committed_changes, shown_tax
from tests.test_account_profile import APPLICANT, _activate
from tests.test_fx_service import SAMPLE_XML
from tests.test_quotes import WORKBOOK

API = "/api/v1"
ACCOUNT = "/api/v1/account"
STAFF_PASSWORD = "TestPassword!2026"
VI_CUSTOMER = "rc18.vi@demo.example.com"
NEG_MARGIN = "golden rc18 test"


# --- Callers -------------------------------------------------------------------------------


class Staff:
    """A staff caller on its own TestClient (shared app overrides, its own cookie jar)."""

    def __init__(self, email: str) -> None:
        self.client = TestClient(app)
        response = self.client.post(
            f"{API}/auth/login", json={"email": email, "password": STAFF_PASSWORD}
        )
        assert response.status_code == 200, response.text
        self.headers = {settings.csrf_header_name: response.json()["csrf_token"]}

    def get(self, url: str, **kwargs):
        return self.client.get(f"{API}{url}", **kwargs)

    def post(self, url: str, body=None, **kwargs):
        return self.client.post(f"{API}{url}", json=body, headers=self.headers, **kwargs)

    def patch(self, url: str, body=None):
        return self.client.patch(f"{API}{url}", json=body, headers=self.headers)


class Me:
    """A signed-in customer on its own TestClient."""

    def __init__(self, email: str) -> None:
        self.client = TestClient(app)
        response = sign_in(self.client, email)
        assert response.status_code == 200, response.text
        self.headers = csrf_headers(response)

    def get(self, path: str):
        return self.client.get(f"{ACCOUNT}{path}")

    def post(self, path: str, body=None):
        return self.client.post(f"{ACCOUNT}{path}", json=body, headers=self.headers)


# --- World -----------------------------------------------------------------------------------


def _activate_vi_customer(client, users, mail) -> None:
    """Register (no language chosen), verify and approve a second account (create new)."""
    customer = dict(REGISTRATION_BODY["customer"])
    customer.pop("preferred_language")
    customer["legal_name"] = customer["primary_contact_name"] = "Trần Văn Bình"
    customer["display_name"] = "Bình"
    customer["phone"] = "0907654321"
    response = register(client, email=VI_CUSTOMER, customer=customer)
    assert response.status_code == 200, response.text
    verify(client, verification_token(mail, VI_CUSTOMER)).raise_for_status()
    signed = sign_in(client, VI_CUSTOMER)
    assert signed.status_code == 200, signed.text
    reference = signed.json()["account_reference"]
    client.cookies.clear()
    api = staff(client, users[Role.OPERATIONS].email)
    fingerprint = acknowledged_preview(api, reference, "create_new")
    approved = approve_create(api, reference, fingerprint)
    assert approved.status_code == 200, approved.text
    client.cookies.clear()


def _import_v1(db):
    version = tis.import_workbook(
        db,
        WORKBOOK.read_bytes(),
        file_name="k.xlsx",
        effective_from=date(2026, 10, 12),
        label=None,
        actor=None,
    )
    tis.activate_version(db, version, actor=None)
    fx_service.sync_once(db, fetcher=lambda _u: SAMPLE_XML, clock=utcnow, worker_name="t")
    db.commit()
    return version


@pytest.fixture
def world(account_client, account_db, account_users, captured_mail):
    """Two linked accounts (English owner; Vietnamese-by-default customer), tariff v1, FX,
    one open 21 kg HCM air-standard master (VN-CA) with five members:

    ``a1``, ``a2`` -- the English owner's; ``vi`` -- the Vietnamese customer's;
    ``b``, ``d`` -- two customers without an account.
    """
    db = account_db
    _activate(account_client, account_users, captured_mail)
    _activate_vi_customer(account_client, account_users, captured_mail)
    see_committed_changes(db)
    owner = db.query(Customer).filter_by(email_normalized=APPLICANT).one()
    vi = db.query(Customer).filter_by(email_normalized=VI_CUSTOMER).one()
    v1 = _import_v1(db)
    tariff_intake_service.update_settings(
        db, approver_emails=[account_users[Role.ADMIN].email], actor=None
    )
    db.commit()
    plan = {
        "a1": (owner, 4),
        "a2": (owner, 4),
        "vi": (vi, 5),
        "b": (make_customer(db, email="rc18.b@demo.example.com"), 4),
        "d": (make_customer(db, email="rc18.d@demo.example.com"), 4),
    }
    kids = {}
    for name, (customer, kg) in plan.items():
        shipment = booked_shipment(db, customer, RouteGroup.VCA)
        for package in db.query(ShipmentPackage).filter_by(shipment_id=shipment.id):
            package.weight_kg = package.weight_value = Decimal(kg)
            package.length_cm = package.width_cm = package.height_cm = None
        kids[name] = (shipment.id, shipment.public_id)
    db.commit()
    con = cs.create_consolidation(
        db,
        {
            "solaris_service": "air_standard",
            "origin": "HCM",
            "vendor_reference": "RC18A",
            "actual_weight_kg": "21",
        },
        actor=None,
    )
    for shipment_id, _ref in kids.values():
        cs.add_member(db, con, db.get(Shipment, shipment_id), actor=None)
    db.commit()
    return {
        "db": db,
        "con": con.id,
        "kids": kids,
        "v1": v1.id,
        "users": account_users,
        "mail": captured_mail,
        "client": account_client,
        "ops": Staff(account_users[Role.OPERATIONS].email),
        "admin": Staff(account_users[Role.ADMIN].email),
    }


def _item(ops: Staff, shipment_id: int, description: str = "Watch") -> int:
    response = ops.post(f"/shipments/{shipment_id}/items", {"description": description})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _fee(ops: Staff, shipment_id: int, item_id: int, stt: int = 18) -> int:
    response = ops.post(
        f"/shipments/{shipment_id}/fee-lines",
        {"item_id": item_id, "section": "hcm_air", "stt": stt, "quantity": 1},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _finalize(ops: Staff, shipment_id: int) -> dict:
    draft = ops.post(f"/shipments/{shipment_id}/quotes")
    assert draft.status_code == 201, draft.text
    confirmed = ops.post(f"/shipments/{shipment_id}/quotes/confirm-rate", {})
    assert confirmed.status_code == 200, confirmed.text
    final = ops.post(
        f"/shipments/{shipment_id}/quotes/finalize", {"negative_margin_reason": NEG_MARGIN}
    )
    assert final.status_code == 200, final.text
    assert final.json()["status"] == "finalized"
    return final.json()


def _send(ops: Staff, shipment_id: int) -> dict:
    sent = ops.post(f"/shipments/{shipment_id}/quotes/send")
    assert sent.status_code == 201, sent.text
    return sent.json()


def _audits(db, action: str) -> list[AuditEvent]:
    see_committed_changes(db)
    return db.query(AuditEvent).filter_by(action=action).order_by(AuditEvent.id).all()


def _detail(event: AuditEvent) -> dict:
    return json.loads(event.detail_json or "{}")


def _pdf_text(content: bytes) -> str:
    assert content.startswith(b"%PDF"), content[:20]
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), ROUND_HALF_UP)


# === 1. The master lock ========================================================================


def _locked_attempts(ops: Staff, shipment_id: int, item_id: int, fee_id: int):
    return {
        "add item": ops.post(f"/shipments/{shipment_id}/items", {"description": "Late"}),
        "edit item": ops.patch(f"/shipments/{shipment_id}/items/{item_id}", {"quantity": 3}),
        "remove item": ops.post(f"/shipments/{shipment_id}/items/{item_id}/remove"),
        "add fee": ops.post(
            f"/shipments/{shipment_id}/fee-lines",
            {"item_id": item_id, "section": "hcm_air", "stt": 18},
        ),
        "remove fee": ops.post(f"/shipments/{shipment_id}/fee-lines/{fee_id}/remove"),
    }


def _assert_all_locked(ops: Staff, shipment_id: int, item_id: int, fee_id: int, state: str):
    for label, response in _locked_attempts(ops, shipment_id, item_id, fee_id).items():
        assert response.status_code == 409, (state, label, response.status_code, response.text)
        assert "locked" in response.text.lower(), (state, label, response.text)


def test_booked_master_locks_items_and_fees_admin_unlock_relock_and_auto_relock(world):
    g = world
    ops, admin, db, con = g["ops"], g["admin"], g["db"], g["con"]
    sid, _ref = g["kids"]["a1"]
    item_id = _item(ops, sid, "Shoes")
    fee_id = _fee(ops, sid, item_id)
    spare_fee = _fee(ops, sid, _item(ops, sid, "Bag"))
    url = f"/consolidations/{con}"
    assert ops.get(url).json()["edit_lock"]["locked"] is False

    booked = ops.post(f"{url}/book")
    assert booked.status_code == 200, booked.text
    assert booked.json()["state"] == "booked"
    assert ops.get(url).json()["edit_lock"]["locked"] is True
    _assert_all_locked(ops, sid, item_id, fee_id, "booked")
    # Nothing changed: the item and both fee lines are still there.
    assert {f["id"] for f in ops.get(f"/shipments/{sid}/fee-lines").json()} == {
        fee_id,
        spare_fee,
    }

    # Operations cannot unlock; Admin needs a reason.
    assert ops.post(f"{url}/unlock", {"reason": "Customer added shoes"}).status_code == 403
    for body in ({}, {"reason": ""}, {"reason": "   "}, None):
        refused = admin.post(f"{url}/unlock", body)
        assert refused.status_code == 422, (body, refused.status_code, refused.text)
    assert not _audits(db, "master.unlocked")
    reason = "Customer added a second pair of shoes"
    opened = admin.post(f"{url}/unlock", {"reason": reason})
    assert opened.status_code == 200, opened.text
    lock = opened.json()["edit_lock"]
    assert lock["locked"] is False and lock["unlock"]["reason"] == reason
    unlock_id = lock["unlock"]["id"]
    unlocked = _audits(db, "master.unlocked")
    assert len(unlocked) == 1 and reason in (unlocked[0].summary + unlocked[0].detail_json)

    # While unlocked, Operations' edits go through and every audit row names the unlock.
    first_audit = max((e.id for e in _audits(db, "master.unlocked")), default=0)
    edited = ops.patch(f"/shipments/{sid}/items/{item_id}", {"quantity": 2})
    assert edited.status_code == 200, edited.text
    added = _item(ops, sid, "Sandals")
    new_fee = _fee(ops, sid, added)
    removed_fee = ops.post(f"/shipments/{sid}/fee-lines/{spare_fee}/remove")
    assert removed_fee.status_code == 200, removed_fee.text
    socks = _item(ops, sid, "Socks")
    removed_item = ops.post(f"/shipments/{sid}/items/{socks}/remove")
    assert removed_item.status_code == 200, removed_item.text
    see_committed_changes(db)
    edit_actions = (
        "shipment.item_update",
        "shipment.item_add",
        "shipment.item_remove",
        "shipment.fee_line_add",
        "shipment.fee_line_remove",
    )
    for action in edit_actions:
        rows = [e for e in _audits(db, action) if e.id > first_audit]
        assert rows, action
        assert all(_detail(e).get("master_unlock_id") == unlock_id for e in rows), (
            action,
            [e.detail_json for e in rows],
        )

    # Read-only roles cannot relock; Operations locks it again; edits are refused again.
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        other = Staff(g["users"][role].email)
        assert other.post(f"{url}/relock", {}).status_code == 403, role
        assert other.post(f"{url}/unlock", {"reason": "x"}).status_code == 403, role
    relocked = ops.post(f"{url}/relock", {"reason": "Shoes added"})
    assert relocked.status_code == 200, relocked.text
    assert relocked.json()["edit_lock"]["locked"] is True
    assert len(_audits(db, "master.relocked")) == 1
    _assert_all_locked(ops, sid, item_id, new_fee, "booked, relocked")

    # A second unlock; finalising a member's quote locks the master by itself.
    assert admin.post(f"{url}/unlock", {"reason": "Re-weigh the watch"}).status_code == 200
    assert ops.patch(f"/shipments/{sid}/items/{item_id}", {"quantity": 1}).status_code == 200
    _finalize(ops, sid)
    assert ops.get(url).json()["edit_lock"]["locked"] is True
    relocks = _audits(db, "master.relocked")
    assert len(relocks) == 2 and _detail(relocks[-1]).get("automatic") is True
    _assert_all_locked(ops, sid, item_id, new_fee, "booked, auto-relocked")

    # Completed is still locked.
    completed = ops.post(f"{url}/complete")
    assert completed.status_code == 200, completed.text
    assert completed.json()["state"] == "completed"
    _assert_all_locked(ops, sid, item_id, new_fee, "completed")
    other_sid, _ = g["kids"]["b"]
    assert ops.post(f"/shipments/{other_sid}/items", {"description": "x"}).status_code == 409, (
        "every member of a completed master is locked"
    )


# === 2. Acceptance -> draft invoice ==========================================================


def test_acceptance_creates_a_draft_staff_edit_and_send_it(world):
    g = world
    ops, db, mail = g["ops"], g["db"], g["mail"]
    sid, ref = g["kids"]["vi"]
    _fee(ops, sid, _item(ops, sid, "Đồng hồ"))
    version = _finalize(ops, sid)
    offer = _send(ops, sid)
    me = Me(VI_CUSTOMER)
    accepted = me.post(f"/quotes/{offer['id']}/accept")
    assert accepted.status_code == 200, accepted.text

    # A draft exists, with no invoice number and no invoice.
    found = ops.get(f"/shipments/{sid}/invoice-draft")
    assert found.status_code == 200, found.text
    draft = found.json()
    assert draft["status"] == "draft" and draft["revision"] == 1
    assert draft["issued_invoice_id"] is None and draft["issued_invoice_public_id"] is None
    assert "INV-" not in found.text
    assert ops.get(f"/shipments/{sid}/invoice").json() is None
    # RC-UAT-19 (owner, 2026-10-22): included in the accepted all-in total, unconfirmed.
    # RC-UAT-20 (owner, 2026-10-23; DEC-0227): the rate follows the route, and this VN-CA
    # shipment is zero-rated (0 %; was 13 % under the RC-UAT-19 stand-in).
    assert Decimal(draft["total_cad"]) == _money(version["total_revenue_cad"])
    assert (draft["tax_rate_percent"], draft["tax_mode"]) == (0, "included")
    assert draft["tax_confirmed"] is False
    created = _audits(db, "invoice.draft_created")
    assert len(created) == 1 and created[0].actor_label.startswith("customer_account:CA-")
    # The manual Issue invoice routes to the draft.
    assert ops.post(f"/shipments/{sid}/invoice", {"tax_rate_percent": 0}).status_code == 409

    url = f"/invoice-drafts/{draft['id']}"
    # Marketing and the read-only manager cannot edit or send.
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        other = Staff(g["users"][role].email)
        assert other.patch(url, {"expected_revision": 1, "notes": "x"}).status_code == 403
        assert other.post(f"{url}/send", {"expected_revision": 1}).status_code == 403

    # Tax 13 %, added on top (staff switch the mode and confirm the tax; RC-UAT-19). RC-UAT-20
    # (DEC-0227): this VN-CA draft starts at 0 %, so staff choose 13 % as well.
    shown = shown_tax(draft["lines"], 13, "added")
    taxed = ops.patch(
        url,
        {
            "expected_revision": 1,
            "tax_mode": "added",
            "tax_rate_percent": 13,
            "tax_confirmed": True,
            **shown,
        },
    )
    assert taxed.status_code == 200, taxed.text
    assert taxed.json()["revision"] == 2
    # A line amount change: a reason is required; a stale revision is refused.
    lines = taxed.json()["lines"]
    lines[0]["amount_cad"] = str(_money(lines[0]["amount_cad"]) + Decimal("12.50"))
    no_reason = ops.patch(url, {"expected_revision": 2, "lines": lines})
    assert no_reason.status_code == 422, no_reason.text
    change = {
        "lines": lines,
        "total_change_reason": "Extra packing requested",
        "tax_confirmed": True,
        **shown_tax(lines, 13, "added"),
    }
    stale = ops.patch(url, {"expected_revision": 1, **change})
    assert stale.status_code == 409, stale.text
    saved = ops.patch(url, {"expected_revision": 2, **change})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["revision"] == 3
    edits = _audits(db, "invoice.draft_edited")
    assert len(edits) == 2
    tax_diff = _detail(edits[0])["changes"]
    assert tax_diff["tax_mode"] == {"from": "included", "to": "added"}
    assert tax_diff["tax_rate_percent"] == {"from": 0, "to": 13}
    line_diff = _detail(edits[1])["changes"]
    assert "lines" in line_diff and "tax_mode" not in line_diff

    expected_subtotal = sum(_money(line["amount_cad"]) for line in body["lines"])
    expected_tax = (expected_subtotal * Decimal("0.13")).quantize(Decimal("0.01"), ROUND_HALF_UP)
    assert Decimal(body["subtotal_cad"]) == expected_subtotal
    assert Decimal(body["total_cad"]) == expected_subtotal + expected_tax

    # The draft PDF of the saved revision says DRAFT; a stale revision has no PDF.
    assert ops.get(f"{url}/pdf", params={"revision": 2}).status_code == 409
    draft_pdf = ops.get(f"{url}/pdf", params={"revision": 3})
    assert draft_pdf.status_code == 200, draft_pdf.text
    assert "DRAFT" in _pdf_text(draft_pdf.content)

    # Send with a stale revision is refused and issues nothing.
    assert ops.post(f"{url}/send", {"expected_revision": 2}).status_code == 409
    assert ops.get(f"/shipments/{sid}/invoice").json() is None

    before = len(mail.messages)
    sent = ops.post(f"{url}/send", {"expected_revision": 3})
    assert sent.status_code == 200, sent.text
    result = sent.json()
    number = result["invoice_public_id"]
    assert number.startswith("INV-")
    assert result["draft"]["status"] == "issued"
    assert result["draft"]["issued_invoice_public_id"] == number

    invoice = ops.get(f"/invoices/{result['invoice_id']}").json()
    assert invoice["public_id"] == number and invoice["status"] == "issued"
    assert [(x["description"], _money(x["amount_cad"])) for x in invoice["lines"]] == [
        (x["description"], _money(x["amount_cad"])) for x in body["lines"]
    ]
    assert _money(invoice["subtotal_cad"]) == expected_subtotal
    assert _money(invoice["tax_cad"]) == expected_tax
    assert _money(invoice["total_cad"]) == expected_subtotal + expected_tax

    # The invoice email, in Vietnamese (no language chosen), captured to a file.
    new = mail.messages[before:]
    invoice_mails = [m for m in new if m["template_key"].startswith("invoice.sent")]
    assert len(invoice_mails) == 1, [m["template_key"] for m in new]
    message = invoice_mails[0]
    assert message["template_key"] == "invoice.sent.vi" and message["language"] == "vi"
    assert message["to_email"].lower() == VI_CUSTOMER
    assert number in message["subject"] + message["body"]
    files = [p for p in mail.directory.rglob("*") if p.is_file()]
    assert any(number in p.read_text(encoding="utf-8", errors="replace") for p in files)

    # The draft is issued and no longer editable or sendable; its PDF is gone.
    assert ops.patch(url, {"expected_revision": 4, "notes": "late"}).status_code == 409
    assert ops.post(f"{url}/send", {"expected_revision": 4}).status_code == 409
    assert ops.get(url).json()["status"] == "issued"

    issued_pdf = ops.get(f"/invoices/{result['invoice_id']}/pdf")
    assert issued_pdf.status_code == 200, issued_pdf.text
    text = _pdf_text(issued_pdf.content)
    assert "DRAFT" not in text and number in text
    assert ref  # the reference exists; the PDF is about this shipment's invoice


# === 3. Expiry on a new tariff version =========================================================


def _new_tariff(admin: Staff, suffix: bytes, effective: str) -> int:
    imported = admin.client.post(
        f"{API}/tariffs/versions/import",
        headers=admin.headers,
        files={
            "file": (
                "v-next.xlsx",
                WORKBOOK.read_bytes() + suffix,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"effective_from": effective, "label": f"rc18 {effective}"},
    )
    assert imported.status_code == 201, imported.text
    return imported.json()["id"]


def test_new_tariff_expires_only_unreceived_uninvoiced_quotes(world):
    g = world
    ops, admin, db = g["ops"], g["admin"], g["db"]
    kids = g["kids"]
    a1, a1_ref = kids["a1"]
    a2, _ = kids["a2"]
    b, _ = kids["b"]
    d, _ = kids["d"]

    # (a) a1: sent, not received.
    _finalize(ops, a1)
    a1_offer = _send(ops, a1)
    # (b) b: sent, then a published received milestone.
    _finalize(ops, b)
    b_offer = _send(ops, b)
    received = ops.post(
        f"/shipments/{b}/events",
        {
            "event_type": "received_at_solaris",
            "is_public_update": True,
            "public_update_text": "Your parcel has arrived at our warehouse.",
        },
    )
    assert received.status_code == 201, received.text
    # (c) a2: accepted in the account, with a draft invoice.
    _finalize(ops, a2)
    a2_offer = _send(ops, a2)
    me = Me(APPLICANT)
    assert me.post(f"/quotes/{a2_offer['id']}/accept").status_code == 200
    a2_draft = ops.get(f"/shipments/{a2}/invoice-draft").json()
    assert a2_draft["status"] == "draft"
    # (d) d: an issued invoice.
    d_version = _finalize(ops, d)
    issued = ops.post(f"/shipments/{d}/invoice", {"tax_rate_percent": 0})
    assert issued.status_code == 201, issued.text
    d_invoice = issued.json()

    # The approver activates a new tariff version.
    new_id = _new_tariff(admin, b"\n", "2026-11-01")
    assert ops.post(f"/tariffs/versions/{new_id}/approve").status_code == 403
    approved = admin.post(f"/tariffs/versions/{new_id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "active"

    # (a) expired, shown expired to the customer, cannot be accepted.
    detail = me.get(f"/quotes/{a1_offer['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "expired"
    assert detail.json()["can_answer"] is False
    listed = {i["id"]: i["status"] for i in me.get("/quotes").json()["items"]}
    assert listed[a1_offer["id"]] == "expired"
    refused = me.post(f"/quotes/{a1_offer['id']}/accept")
    assert refused.status_code == 409, refused.text
    assert "tariff" not in refused.text.lower() and "kango" not in refused.text.lower()
    staff_offers = ops.get(f"/shipments/{a1}/quote-offers").json()
    assert staff_offers[0]["status"] == "expired"
    a1_quotes = ops.get(f"/shipments/{a1}/quotes").json()
    assert [q["expiry"] is not None for q in a1_quotes if q["version"] == 1] == [True]

    # (b) received: unchanged.
    assert ops.get(f"/shipments/{b}/quote-offers").json()[0]["status"] == b_offer["status"]
    assert b_offer["status"] == "sent"
    # (c) the accepted quote expired and its draft was withdrawn.
    assert ops.get(f"/shipments/{a2}/quote-offers").json()[0]["status"] == "expired"
    withdrawn = ops.get(f"/invoice-drafts/{a2_draft['id']}").json()
    assert withdrawn["status"] == "discarded" and withdrawn["discard_reason"]
    assert (
        ops.post(
            f"/invoice-drafts/{a2_draft['id']}/send", {"expected_revision": withdrawn["revision"]}
        ).status_code
        == 409
    )
    discarded = _audits(db, "invoice.draft_discarded")
    assert len(discarded) == 1
    # (d) the issued invoice and its quote are untouched.
    still = ops.get(f"/invoices/{d_invoice['id']}").json()
    assert still["status"] == "issued" and still["total_cad"] == d_invoice["total_cad"]
    d_quotes = ops.get(f"/shipments/{d}/quotes").json()
    assert [q["expiry"] for q in d_quotes if q["version"] == d_version["version"]] == [None]

    see_committed_changes(db)
    expired_ships = sorted(row.shipment_id for row in db.query(QuoteExpiry))
    assert expired_ships == sorted([a1, a2])
    assert len(_audits(db, "quote.expired")) == 2

    # (e) activating again changes nothing.
    again = admin.post(f"/tariffs/versions/{new_id}/activate")
    assert again.status_code in (200, 409), again.text
    reapprove = admin.post(f"/tariffs/versions/{new_id}/approve")
    assert reapprove.status_code in (200, 409), reapprove.text
    see_committed_changes(db)
    assert db.query(QuoteExpiry).count() == 2
    assert len(_audits(db, "quote.expired")) == 2
    assert len(_audits(db, "invoice.draft_discarded")) == 1

    # Staff re-price a1 on the new rate and send a new quote, which the customer can answer.
    v2 = _finalize(ops, a1)
    assert v2["version"] == 2 and v2["tariff_version_id"] == new_id and v2["expiry"] is None
    new_offer = _send(ops, a1)
    fresh = me.get(f"/quotes/{new_offer['id']}").json()
    assert fresh["status"] == "sent" and fresh["can_answer"] is True
    assert me.get(f"/quotes/{a1_offer['id']}").json()["status"] == "expired"
    assert a1_ref


# === 4. No vendor name in anything customer-facing ============================================

VENDOR_RULE_NAMES = {
    18: "Phụ thu Kango đồng hồ",
    14: "KANGO Express phụ thu hàng giả",
    15: "Phụ thu Kangô túi xách",
}
STAFF_FEE_DESCRIPTION = "Phí xử lý KANGO Express"
NEUTRAL_FEE_DESCRIPTION = "Phí xử lý nhanh"


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _assert_no_vendor(label: str, text: str) -> None:
    folded = _fold(text)
    assert "kango" not in folded, (label, text[:2000])


def test_no_customer_facing_output_names_the_vendor(world):
    g = world
    ops, db, mail, client = g["ops"], g["db"], g["mail"], g["client"]
    sid, ref = g["kids"]["a1"]
    see_committed_changes(db)
    for stt, name in VENDOR_RULE_NAMES.items():
        rule = (
            db.query(TariffSurchargeRule)
            .filter_by(version_id=g["v1"], section="hcm_air", stt=stt)
            .one()
        )
        rule.name = name
    db.commit()
    for stt in VENDOR_RULE_NAMES:
        _fee(ops, sid, _item(ops, sid, f"Goods {stt}"), stt=stt)
    version = _finalize(ops, sid)
    paid = [x for x in version["lines"] if x["kind"] == "surcharge" and Decimal(x["revenue_cad"])]
    assert paid, "the vendor-worded rules should give customer surcharges"

    # Staff still see the vendor's wording.
    staff_quote = ops.get(f"/shipments/{sid}/quotes")
    assert "kango" in _fold(staff_quote.text)

    outputs: dict[str, str] = {}
    offer = _send(ops, sid)
    me = Me(APPLICANT)
    for path in ("/quotes", f"/quotes/{offer['id']}", "/shipments", f"/shipments/{ref}"):
        response = me.get(path)
        assert response.status_code == 200, (path, response.text)
        outputs[f"account {path}"] = response.text
    names = {s["name"] for s in json.loads(outputs[f"account /quotes/{offer['id']}"])["surcharges"]}
    assert names and names <= {"Surcharge", "Phụ phí"}, names
    document = ops.get(f"/shipments/{sid}/quotes/{version['version']}/document")
    assert document.status_code == 200, document.text
    outputs["printable quote"] = document.text
    accepted = me.post(f"/quotes/{offer['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    outputs["accept"] = accepted.text

    draft = ops.get(f"/shipments/{sid}/invoice-draft").json()
    outputs["staff draft view (customer lines)"] = json.dumps(draft["lines"], ensure_ascii=False)
    url = f"/invoice-drafts/{draft['id']}"
    # A staff line naming the vendor is refused on save (review M3); a neutral one is saved.
    named = [*draft["lines"], {"description": STAFF_FEE_DESCRIPTION, "amount_cad": "7.00"}]
    refused = ops.patch(
        url,
        {"expected_revision": draft["revision"], "lines": named, "total_change_reason": "fee"},
    )
    assert refused.status_code == 422 and refused.json()["field"] == "lines", refused.text
    lines = [*draft["lines"], {"description": NEUTRAL_FEE_DESCRIPTION, "amount_cad": "7.00"}]
    saved = ops.patch(
        url,
        {
            "expected_revision": draft["revision"],
            "lines": lines,
            "total_change_reason": "fee",
            "tax_confirmed": True,
            # The draft's own rate (RC-UAT-20: 0 % on this VN-CA shipment, DEC-0227).
            **shown_tax(lines, draft["tax_rate_percent"], "included"),
        },
    )
    assert saved.status_code == 200, saved.text
    revision = saved.json()["revision"]
    draft_pdf = ops.get(f"{url}/pdf", params={"revision": revision})
    assert draft_pdf.status_code == 200, draft_pdf.text
    outputs["draft pdf"] = _pdf_text(draft_pdf.content)
    sent = ops.post(f"{url}/send", {"expected_revision": revision})
    assert sent.status_code == 200, sent.text
    invoice_id = sent.json()["invoice_id"]
    issued_pdf = ops.get(f"/invoices/{invoice_id}/pdf")
    assert issued_pdf.status_code == 200, issued_pdf.text
    outputs["invoice pdf"] = _pdf_text(issued_pdf.content)
    invoice_doc = ops.get(f"/invoices/{invoice_id}/document")
    assert invoice_doc.status_code == 200, invoice_doc.text
    outputs["invoice document"] = invoice_doc.text
    payment = ops.post(f"/invoices/{invoice_id}/payments", {"amount_cad": "5.00", "method": "cash"})
    assert payment.status_code == 201, payment.text
    payment_id = payment.json()["payments"][0]["id"]
    receipt = ops.get(f"/payments/{payment_id}/receipt")
    assert receipt.status_code == 200, receipt.text
    outputs["receipt"] = receipt.text

    # A published milestone: the notification email and public tracking.
    event = ops.post(
        f"/shipments/{sid}/events",
        {
            "event_type": "received_at_solaris",
            "is_public_update": True,
            "public_update_text": "Your parcel has arrived at our warehouse.",
        },
    )
    assert event.status_code == 201, event.text
    public = TestClient(app).get(f"{API}/public/track/{ref}")
    assert public.status_code == 200, public.text
    outputs["public tracking"] = public.text
    outputs["account shipment after milestone"] = me.get(f"/shipments/{ref}").text
    assert client  # the shared fixture client stays untouched

    keys = [m["template_key"] for m in mail.messages]
    assert any(k.startswith("quote.sent") for k in keys), keys
    assert any(k.startswith("invoice.sent") for k in keys), keys
    notification_keys = [
        k for k in keys if not k.startswith(("quote.", "invoice.")) and "verif" not in k
    ]
    assert any("received" in k for k in notification_keys), keys
    for index, message in enumerate(mail.messages):
        outputs[f"email {index} {message['template_key']}"] = json.dumps(
            message, ensure_ascii=False
        )

    for label, text in outputs.items():
        _assert_no_vendor(label, text)
    # The staff's own invoice screen keeps the wording they typed.
    assert NEUTRAL_FEE_DESCRIPTION in ops.get(f"/invoices/{invoice_id}").text


# === 5. Tariff readings ========================================================================


def test_import_report_lists_confirmed_steps_and_no_falling_price_anomaly(world):
    g = world
    admin = g["admin"]
    new_id = _new_tariff(admin, b"\n\n", "2026-12-01")
    detail = admin.get(f"/tariffs/versions/{new_id}")
    assert detail.status_code == 200, detail.text
    report = detail.json()["report"]
    steps = report.get("confirmed_price_steps")
    assert steps is not None, sorted(report)
    cells = {(s["sheet"], s["cell"]) for s in steps}
    assert cells == {
        ("HCM-AIR-CAD", "F39"),
        ("HN-AIR-CAD", "F38"),
        ("HN-AIR-CAD", "G38"),
    }, steps
    assert all(s["product_code"] == "AIR-CAD EXPRESS" for s in steps)
    assert "price_falls_with_weight" not in report.get("anomaly_counts", {})
    falling = [a for a in report.get("anomalies", []) if a["code"] == "price_falls_with_weight"]
    assert falling == []
    for anomaly in report.get("anomalies", []):
        assert (anomaly.get("sheet"), anomaly.get("cell")) not in cells, anomaly


def test_hcm_row_41_is_20000_vnd_per_kg_on_a_vn_ca_master(world):
    """The RC-UAT-25 method: full carton (DEC-0222). Method v0.5 prices row 41 on the item's
    own kg (DEC-0252, open question M-3): ``test_owner_answers_2026_10_21``."""
    g = world
    ops = g["ops"]
    from app.services import pricing_method_service as pms

    see_committed_changes(g["db"])
    pms.update_method_settings(g["db"], {"pricing_method": "rc25"}, actor=None)
    g["db"].commit()
    rules = ops.get(f"/tariffs/versions/{g['v1']}/surcharges", params={"section": "hcm_air"})
    assert rules.status_code == 200, rules.text
    row = next(r for r in rules.json()["items"] if r["stt"] == 41)
    assert Decimal(str(row["unit_price_vnd"])) == Decimal(20_000)
    assert row["scope"] == "full_carton" and row["basis"] == "per_kg"
    assert row["applies_to_canada"] is True

    sid, ref = g["kids"]["vi"]
    assert ref.startswith("SX-VCA-")  # Vietnam to Canada
    _fee(ops, sid, _item(ops, sid, "Thịt bò khô"), stt=41)
    version = _finalize(ops, sid)
    meat = [x for x in version["lines"] if x["section"] == "hcm_air" and x["stt"] == 41]
    assert len(meat) == 1, version["lines"]
    assert Decimal(str(meat[0]["revenue_cad"])) > 0
    # One 21 kg master, one carton: the vendor charges the full carton's kg x 20,000 VND,
    # shared out over the members (the trigger's quote line carries its share).
    estimate = ops.get(f"/consolidations/{g['con']}/pricing").json()["estimate"]
    assert Decimal(estimate["master_chargeable_kg"]) == Decimal(21)
    fee = next(f for f in estimate["fees"] if f["section"] == "hcm_air" and f["stt"] == 41)
    assert Decimal(fee["vendor_fee_vnd"]) == Decimal(21 * 20_000)
    shares = sum(Decimal(v) for v in fee["cost_alloc_vnd"].values())
    assert shares == Decimal(21 * 20_000)
    assert Decimal(str(meat[0]["cost_vnd"])) == Decimal(fee["cost_alloc_vnd"][str(sid)])
