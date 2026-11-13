"""RC-UAT-25 items 7 and 8 (Ben 2026-10-25): the shipment page's Financials tab.

7. Ben added financial info to a shipment and ``/shipments/<id>?tab=financials`` went blank.
   The recorded-amounts form stored the currency exactly as typed (any 1-3 characters, e.g.
   ``CA`` or ``$``); the tab formats every amount with that code and the browser's currency
   formatter throws on it, so the render failed and, with no error boundary, the whole page
   unmounted. The route now refuses anything but a three-letter code (upper-cased; blank is
   Unknown); the screen also copes with a code stored before the fix.
8. Right after booking, staff see the quoted / cost summary and the next step on the tab:
   price, finalise, issue the invoice (manual path), review the draft prepared on
   acceptance, or open the issued invoice; a blocked Issue invoice says why with the refusal
   Issue invoice itself returns. Vendor cost only for a role with ``tariff:read``.

Every endpoint the tab calls (the shipment detail and the financial summary), and the
invoice / draft reads its links lead to, answer 200 for a shipment in each financial shape the
app produces. ``RC25_FIXTURE_OUT=<file>`` saves the captured responses as JSON (the vitest
fixtures in ``frontend/tests/fixtures/rc25Financials.json`` were made that way).
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

from app.core.enums import Role, RouteGroup
from app.models import CustomerInvoice, Shipment
from app.services import consolidation_service as cs
from app.services import finance_service as fs
from app.services import pricing_service as ps
from app.services import quote_deletion_service as qds
from tests.conftest import booked_shipment, make_customer, see_committed_changes
from tests.test_fixpack_f_lock_expiry_drafts import _accepted, _confirm_tax, _new_tariff
from tests.test_quote_offers import _finalize
from tests.test_quotes import _fee, priced_world  # noqa: F401 - fixture

D = Decimal

SUMMARY_KEYS = {
    "shipment_id",
    "master",
    "quote",
    "finalised_quote",
    "invoice",
    "draft_invoice",
    "next_step",
    "invoice_blocked_reason",
    "invoice_blocked_code",
    "cost_visible",
    "can_issue_invoice",
    "can_price",
}
FINANCIAL_KEYS = {
    "currency",
    "selling_amount",
    "discount_amount",
    "refund_amount",
    "declared_value",
    "declared_value_currency",
    "payment_state",
    "coverage_note",
}


def _route(db, shipment, origin, destination, province=None):
    shipment.origin_country_code = origin
    shipment.destination_country_code = destination
    shipment.sender_country_code = origin
    shipment.recipient_country_code = destination
    shipment.recipient_province_state = province
    shipment.recipient_postal_code = None
    db.commit()
    return shipment


class Capture:
    """Reads every endpoint the tab (and its links) use; asserts 200 and the shape."""

    def __init__(self, api):
        self.api = api
        self.shapes: dict[str, dict] = {}

    def read(self, db, name: str, shipment: Shipment) -> dict:
        see_committed_changes(db)
        base = f"/api/v1/shipments/{shipment.id}"
        detail = self.api.get(base)
        assert detail.status_code == 200, (name, detail.text)
        summary = self.api.get(f"{base}/financial-summary")
        assert summary.status_code == 200, (name, summary.text)
        body = summary.json()
        assert set(body) == SUMMARY_KEYS, name
        financials = detail.json()["financials"]
        assert set(financials) >= FINANCIAL_KEYS, name
        # Where the tab's links lead: the live invoice and the draft, each 200 (or null).
        invoice = self.api.get(f"{base}/invoice")
        assert invoice.status_code == 200, (name, invoice.text)
        draft = self.api.get(f"{base}/invoice-draft")
        assert draft.status_code == 200, (name, draft.text)
        if body["invoice"]:
            page = self.api.get(f"/api/v1/invoices/{body['invoice']['id']}")
            assert page.status_code == 200, (name, page.text)
        if body["draft_invoice"]:
            page = self.api.get(f"/api/v1/invoice-drafts/{body['draft_invoice']['id']}")
            assert page.status_code == 200, (name, page.text)
        self.shapes[name] = {
            "shipment": detail.json(),
            "summary": body,
            "invoice": invoice.json(),
            "invoice_draft": draft.json(),
        }
        return body

    def save(self) -> None:
        target = os.environ.get("RC25_FIXTURE_OUT")
        if target:
            Path(target).write_text(
                json.dumps(self.shapes, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )


# === 7. The recorded currency =====================================================================


def test_the_recorded_currency_must_be_a_three_letter_code(db, api_for):
    shipment = booked_shipment(db, make_customer(db), RouteGroup.VCA)
    admin = api_for(Role.ADMIN)
    url = f"/api/v1/shipments/{shipment.id}/financials"
    for typed in ("CA", "$", "C$", "1AB", "VN ", "ĐỒN"):
        refused = admin.patch(url, json={"currency": typed, "selling_amount": "120"})
        assert refused.status_code == 422, typed
        assert refused.json()["field"] == "currency"
        assert "three-letter currency code" in refused.json()["message"]
    see_committed_changes(db)
    db.refresh(shipment)
    assert shipment.currency is None and shipment.selling_amount is None  # nothing half-saved

    saved = admin.patch(url, json={"currency": "vnd", "selling_amount": "120"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["financials"]["currency"] == "VND"
    cleared = admin.patch(url, json={"currency": ""})
    assert cleared.status_code == 200 and cleared.json()["financials"]["currency"] is None


def test_a_currency_stored_before_the_fix_still_reads(db, api_for):
    """Ben's shipment kept the code it was saved with; the API must still answer (the screen
    shows it, unformatted, and asks for a correction)."""
    shipment = booked_shipment(db, make_customer(db), RouteGroup.VCA)
    shipment.currency = "CA"
    shipment.selling_amount = D("120.00")
    shipment.shipping_cost = D("70.00")
    db.commit()
    admin = api_for(Role.ADMIN)
    body = admin.get(f"/api/v1/shipments/{shipment.id}").json()
    assert body["financials"]["currency"] == "CA"
    assert D(body["financials"]["costs"]["gross_profit"]) == D("50.00")
    assert admin.get(f"/api/v1/shipments/{shipment.id}/financial-summary").status_code == 200


# === 7 + 8. Every shape, every endpoint ==========================================================


def test_every_financial_shape_reads_200_with_the_next_step(
    db,
    priced_world,  # noqa: F811
    api_for,
):
    con, kids = priced_world
    manual, accepted, jewellery = kids
    capture = Capture(api_for(Role.ADMIN))

    # Booked, in no master, nothing recorded: pricing needs a master first.
    loose = booked_shipment(db, make_customer(db, email="loose@demo.example.com"), RouteGroup.VCA)
    body = capture.read(db, "no_master", loose)
    assert (body["master"], body["quote"], body["next_step"]) == (None, None, "add_to_master")
    assert body["invoice_blocked_reason"] == (
        "Finalise the shipment's quote before issuing an invoice."
    )
    # Missing currency, a selling amount only (the manual "recorded amounts" form).
    loose.selling_amount = D("88.50")
    db.commit()
    body = capture.read(db, "no_master_amount_only", loose)
    detail = capture.shapes["no_master_amount_only"]["shipment"]["financials"]
    assert detail["currency"] is None and D(detail["selling_amount"]) == D("88.50")
    assert detail["costs"]["gross_profit"] is None

    # In the master, not priced yet.
    body = capture.read(db, "unpriced", manual)
    assert body["master"]["public_id"] == con.public_id and body["master"]["locked"] is False
    assert body["next_step"] == "price" and body["quote"] is None

    # A draft quote: finalise it.
    ps.reprice(db, manual, actor=None)
    db.commit()
    body = capture.read(db, "draft_quote", manual)
    assert (body["quote"]["status"], body["next_step"]) == ("draft", "finalise_quote")

    # Finalised: ready to invoice, revenue and (Admin) cost.
    _finalize(db, manual)
    body = capture.read(db, "finalised", manual)
    assert body["next_step"] == "issue_invoice" and body["invoice_blocked_reason"] is None
    assert D(body["quote"]["total_revenue_cad"]) == D("57.00")  # 3 kg x 19 (v0.5, DEC-0252)
    assert body["quote"]["allocated_cost_cad"] is not None and body["cost_visible"] is True

    # Issued on the manual path (zero-rated, the invoicing_v1 layout), a payment and a refund.
    admin = capture.api
    issued = admin.post(f"/api/v1/shipments/{manual.id}/invoice", json={"tax_rate_percent": 0})
    assert issued.status_code == 201, issued.text
    invoice_id = issued.json()["id"]
    paid = admin.post(
        f"/api/v1/invoices/{invoice_id}/payments", json={"amount_cad": "57.00", "method": "cash"}
    )
    assert paid.status_code in (200, 201), paid.text
    payment_id = paid.json()["id"]
    refunded = admin.post(
        f"/api/v1/payments/{payment_id}/refund", json={"amount_cad": "4.00", "reason": "Goodwill"}
    )
    assert refunded.status_code in (200, 201), refunded.text
    body = capture.read(db, "issued_paid_refunded", manual)
    assert body["next_step"] == "open_invoice"
    assert body["invoice"]["public_id"] == issued.json()["public_id"]
    assert D(body["invoice"]["balance_cad"]) == D("4.00")
    assert capture.shapes["issued_paid_refunded"]["invoice"]["tax_layout"] == "invoicing_v1"

    # The same invoice as one issued before the layout (no tax_layout / tax_lines / tax_rows).
    see_committed_changes(db)
    invoice = db.get(CustomerInvoice, invoice_id)
    document = json.loads(invoice.document_json)
    for key in ("tax_layout", "tax_lines", "tax_rows", "tax_mode"):
        document.pop(key, None)
    invoice.document_json = json.dumps(document)
    db.commit()
    body = capture.read(db, "legacy_invoice", manual)
    assert capture.shapes["legacy_invoice"]["invoice"]["tax_rows"] is None

    # Voided (the money returned first): back to ready-to-invoice on the same quote.
    refund_rest = admin.post(
        f"/api/v1/payments/{payment_id}/refund", json={"amount_cad": "53.00", "reason": "Void"}
    )
    assert refund_rest.status_code in (200, 201), refund_rest.text
    voided = admin.post(f"/api/v1/invoices/{invoice.id}/void", json={"reason": "Wrong payer"})
    assert voided.status_code == 200, voided.text
    body = capture.read(db, "voided", manual)
    assert (body["invoice"], body["next_step"]) == (None, "issue_invoice")

    # Accepted quote, domestic with GST/HST included (Nova Scotia): the live draft.
    _route(db, accepted, "CA", "CA", "NS")
    _offer, draft = _accepted(db, accepted)
    body = capture.read(db, "accepted_draft_included_tax", accepted)
    assert body["next_step"] == "review_draft" and body["draft_invoice"]["id"] == draft.id
    assert body["invoice_blocked_reason"] is None
    # Sent: the issued invoice with tax_rows.
    from app.services import invoice_draft_service as drafts  # noqa: PLC0415

    _confirm_tax(db, draft)
    drafts.send(db, draft, expected_revision=draft.revision, actor=None)
    db.commit()
    body = capture.read(db, "issued_included_tax", accepted)
    assert body["next_step"] == "open_invoice"
    assert capture.shapes["issued_included_tax"]["invoice"]["tax_rows"]

    # Costume jewellery priced by hand (vendor VND, customer CAD); domestic, province unknown:
    # the draft has no rate yet.
    line = _fee(db, jewellery, "hcm_air", 27, description="Bông tai mỹ ký")
    ps.set_fee_line_amount(db, jewellery, line.id, "400000", customer_price_cad="41", actor=None)
    db.commit()
    _route(db, jewellery, "CA", "CA", None)
    _offer, unknown_draft = _accepted(db, jewellery)
    body = capture.read(db, "draft_no_rate_jewellery", jewellery)
    assert body["next_step"] == "review_draft"

    # Vendor bill entered and approved on the booked master: cost allocated, master locked.
    cs.book_consolidation(db, con, actor=None)
    db.commit()
    bill = fs.enter_vendor_invoice(
        db, con, {"currency": "VND", "lines": [{"kind": "base", "amount": "5103000"}]}, actor=None
    )
    db.commit()
    fs.approve_vendor_invoice(db, bill, {"variance_reason": "Test bill"}, actor=None)
    db.commit()
    body = capture.read(db, "vendor_bill_master_locked", jewellery)
    assert body["master"]["locked"] is True

    capture.save()


# === 8. Roles: who sees the cost, who may invoice ================================================


def test_cost_and_the_invoice_action_follow_the_roles(db, priced_world, api_for):  # noqa: F811
    _con, kids = priced_world
    _finalize(db, kids[0])
    url = f"/api/v1/shipments/{kids[0].id}/financial-summary"

    ops = api_for(Role.OPERATIONS).get(url).json()
    assert ops["cost_visible"] and ops["quote"]["allocated_cost_cad"] is not None
    assert ops["can_issue_invoice"] and ops["can_price"]

    manager = api_for(Role.READ_ONLY_MANAGER).get(url).json()
    assert manager["cost_visible"] is False
    assert manager["quote"]["allocated_cost_cad"] is None
    assert manager["quote"]["gross_profit_cad"] is None
    assert manager["finalised_quote"]["allocated_cost_cad"] is None
    assert manager["quote"]["total_revenue_cad"] is not None
    assert (manager["can_issue_invoice"], manager["can_price"]) == (False, False)

    assert api_for(Role.MARKETING).get(url).status_code == 403


# === 8. A blocked invoice says why, in Issue invoice's own words ==================================


def test_an_expired_quote_blocks_with_the_issue_invoice_refusal(db, priced_world, api_for):  # noqa: F811
    _con, kids = priced_world
    version = _finalize(db, kids[0])
    _new_tariff(db)
    admin = api_for(Role.ADMIN)
    body = admin.get(f"/api/v1/shipments/{kids[0].id}/financial-summary").json()
    assert body["next_step"] == "requote" and body["invoice_blocked_code"] == "quote_expired"
    assert body["quote"]["expired"] is True
    refused = admin.post(f"/api/v1/shipments/{kids[0].id}/invoice", json={})
    assert refused.status_code == 409
    assert refused.json()["message"] == body["invoice_blocked_reason"]
    assert f"Quote v{version.version} expired" in body["invoice_blocked_reason"]


def test_a_soft_deleted_latest_quote_blocks_with_the_issue_invoice_refusal(
    db,
    priced_world,  # noqa: F811
    api_for,
):
    _con, kids = priced_world
    version = _finalize(db, kids[0])
    qds.soft_delete(db, version, reason="Wrong weight", actor=None)
    db.commit()
    admin = api_for(Role.ADMIN)
    body = admin.get(f"/api/v1/shipments/{kids[0].id}/financial-summary").json()
    assert body["next_step"] == "requote" and body["invoice_blocked_code"] == "quote_deleted"
    assert body["quote"] is None  # a deleted version is not listed
    refused = admin.post(f"/api/v1/shipments/{kids[0].id}/invoice", json={})
    assert refused.status_code == 409
    assert refused.json()["message"] == body["invoice_blocked_reason"]
