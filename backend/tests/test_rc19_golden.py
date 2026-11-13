"""RC-UAT-19 golden tests (independent tester): owner answers of 2026-10-22, black box over HTTP.

1. GST/HST on the draft invoice (DEC-0223): 13 % included by default, backed out of the
   all-in lines (hand-checked with Decimal ROUND_HALF_UP), confirmation before Save and Send,
   the added-on-top mode, 0 %, documents and PDFs, reports, roles.
2. Customer-facing tracking (DEC-0224): generic leg names, carrier links visible even when
   the stored label names the vendor, a vendor-hosted link hidden, staff unchanged.
3. Costume jewellery, HCM air row 27 (DEC-0225): a manual VND amount per line, no kg.

The pricing world (tariff v1 freshly imported, exchange rate, shipments, the master) is
seeded through services as the RC-UAT-18 golden suite does; everything under test goes
through HTTP. Demo addresses only; air only; capture transport.
"""

from __future__ import annotations

import io
import unicodedata
from decimal import ROUND_HALF_UP, Decimal

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.core.config import settings
from app.core.enums import Role, RouteGroup
from app.main import app
from app.models import Customer, Shipment, ShipmentPackage
from app.services import consolidation_service as cs
from tests.conftest import booked_shipment, make_customer, see_committed_changes
from tests.test_account_profile import APPLICANT, _activate
from tests.test_rc18_golden import (
    VI_CUSTOMER,
    Me,
    Staff,
    _activate_vi_customer,
    _import_v1,
)

API = "/api/v1"
NEG_MARGIN = "golden rc19 test"
CENT = Decimal("0.01")
# RC-UAT-20 review (2026-10-24): a rate filled in from the province table prints that row's
# label -- these drafts are delivered in Ontario (HST); it read "GST/HST" in RC-UAT-19.
INCLUDED_EN = "Prices include HST 13 %"
INCLUDED_VI = "Giá đã bao gồm HST 13 %"
#: RC-UAT-23 (DEC-0235): the Solaris Invoicing layout prints no "Prices include" sentence; the
#: summary row of a 13 % invoice instead, in English for every customer.
ROW_13 = "HST ON @ 13%"
UPS = "https://www.ups.com/track?loc=en_CA&tracknum=1Z999AA10123456784"
VI_NAMES = {
    "Master Tracking": "Theo dõi chặng chính",
    "Last Mile Tracking": "Theo dõi chặng cuối",
}
CANADA_POST_SAFE = "https://www.canadapost-postescanada.ca/track-reperage/en?pin=7023210039414604"
VENDOR_HOST = "https://www.kangoexpress.ca/track?id=RC19-0001"
VENDOR_LABEL = "Kango Express"


def _d(value) -> Decimal:
    return Decimal(str(value))


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _included(total: Decimal, rate: int) -> tuple[Decimal, Decimal]:
    """The tester's own back-out of one all-in line (DEC-0235, per line): (net, tax), the net
    nudged by the cent so net + tax is the line."""
    net = _cents(total * 100 / (100 + rate))
    tax = _cents(net * rate / 100)
    return total - tax, tax


def _included_lines(amounts, rate: int) -> tuple[Decimal, Decimal]:
    """(subtotal, tax) of all-in lines, each backed out on its own (DEC-0235)."""
    parts = [_included(_d(amount), rate) for amount in amounts]
    return sum((p[0] for p in parts), Decimal(0)), sum((p[1] for p in parts), Decimal(0))


def _added_tax(amounts, rate: int) -> Decimal:
    """The tax charged on top of each line (DEC-0235)."""
    return sum((_cents(_d(amount) * rate / 100) for amount in amounts), Decimal(0))


def _shown(total, mode: str, rate: int) -> dict:
    """What the draft screen showed beside the ticked box (review, 2026-10-22): a save that
    changes the lines, the rate or the mode echoes it, and the server checks it."""
    return {
        "confirmed_total_cad": str(_cents(_d(total))),
        "confirmed_tax_mode": mode,
        "confirmed_tax_rate_percent": rate,
    }


def _pdf_text(content: bytes) -> str:
    assert content.startswith(b"%PDF"), content[:20]
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


# --- World -----------------------------------------------------------------------------------


@pytest.fixture
def world(account_client, account_db, account_users, captured_mail):
    """English owner (``a1``, ``a2``), Vietnamese customer (``vi``), one customer without an
    account (``b``); tariff v1 freshly imported (row 27 read as a manual amount), FX, one
    open 20 kg HCM air-standard master (VN-CA)."""
    db = account_db
    _activate(account_client, account_users, captured_mail)
    _activate_vi_customer(account_client, account_users, captured_mail)
    see_committed_changes(db)
    owner = db.query(Customer).filter_by(email_normalized=APPLICANT).one()
    vi = db.query(Customer).filter_by(email_normalized=VI_CUSTOMER).one()
    _import_v1(db)
    plan = {
        "a1": (owner, 5),
        "a2": (owner, 5),
        "vi": (vi, 5),
        "b": (make_customer(db, email="rc19.b@demo.example.com"), 5),
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
            "vendor_reference": "RC19A",
            "actual_weight_kg": "20",
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
        "users": account_users,
        "ops": Staff(account_users[Role.OPERATIONS].email),
    }


def _item(ops: Staff, shipment_id: int, description: str, weight=None) -> int:
    body = {"description": description}
    if weight is not None:
        body["weight_kg"] = str(weight)
    response = ops.post(f"/shipments/{shipment_id}/items", body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _finalize(ops: Staff, shipment_id: int):
    draft = ops.post(f"/shipments/{shipment_id}/quotes")
    assert draft.status_code == 201, draft.text
    confirmed = ops.post(f"/shipments/{shipment_id}/quotes/confirm-rate", {})
    assert confirmed.status_code == 200, confirmed.text
    return ops.post(
        f"/shipments/{shipment_id}/quotes/finalize", {"negative_margin_reason": NEG_MARGIN}
    )


def _accepted_draft(g, kid: str, email: str) -> dict:
    ops = g["ops"]
    sid, _ref = g["kids"][kid]
    # RC-UAT-20 (owner, 2026-10-23; DEC-0227): the draft's GST/HST follows the route. The
    # 13 % included figures pinned here are a domestic shipment delivered in Ontario's; the
    # VN-CA world shipment itself is zero-rated (tests/test_rc20_tax_by_route.py).
    see_committed_changes(g["db"])
    shipment = g["db"].get(Shipment, sid)
    shipment.origin_country_code = shipment.destination_country_code = "CA"
    shipment.recipient_country_code, shipment.recipient_province_state = "CA", "ON"
    g["db"].commit()
    final = _finalize(ops, sid)
    assert final.status_code == 200, final.text
    sent = ops.post(f"/shipments/{sid}/quotes/send")
    assert sent.status_code == 201, sent.text
    me = Me(email)
    accepted = me.post(f"/quotes/{sent.json()['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    found = ops.get(f"/shipments/{sid}/invoice-draft")
    assert found.status_code == 200, found.text
    return found.json()


def _assert_included(body: dict, rate: int = 13) -> None:
    lines_total = sum((_d(x["amount_cad"]) for x in body["lines"]), Decimal(0))
    subtotal, tax = _included_lines([x["amount_cad"] for x in body["lines"]], rate)
    assert body["tax_mode"] == "included" and body["tax_rate_percent"] == rate, body
    assert _d(body["lines_total_cad"]) == lines_total
    assert (_d(body["subtotal_cad"]), _d(body["tax_cad"]), _d(body["total_cad"])) == (
        subtotal,
        tax,
        lines_total,
    ), body


# === 1. GST/HST on the draft invoice =========================================================


def test_draft_tax_included_hand_checked_confirmation_send_and_reports(world):
    g = world
    ops = g["ops"]
    draft = _accepted_draft(g, "a1", APPLICANT)
    url = f"/invoice-drafts/{draft['id']}"

    # Default: 13 %, included, unconfirmed; the total is the accepted all-in sum of lines.
    assert draft["tax_confirmed"] is False
    _assert_included(draft)

    # Marketing and the read-only manager cannot confirm, save or send.
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        other = Staff(g["users"][role].email)
        assert other.patch(url, {"expected_revision": 1, "tax_confirmed": True}).status_code == 403
        assert other.post(f"{url}/send", {"expected_revision": 1}).status_code == 403
    assert ops.get(url).json()["tax_confirmed"] is False

    # Send before any confirmation: 422 tax_unconfirmed, nothing issued.
    refused = ops.post(f"{url}/send", {"expected_revision": 1})
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == "tax_unconfirmed"
    sid, _ = g["kids"]["a1"]
    assert ops.get(f"/shipments/{sid}/invoice").json() is None

    # Save without the tick: 422; with it: 200, no new revision when nothing else changed.
    for body in ({"expected_revision": 1}, {"expected_revision": 1, "tax_confirmed": False}):
        unticked = ops.patch(url, body)
        assert unticked.status_code == 422, unticked.text
        assert unticked.json()["detail"]["code"] == "tax_unconfirmed"
    ticked = ops.patch(url, {"expected_revision": 1, "tax_confirmed": True})
    assert ticked.status_code == 200, ticked.text
    assert ticked.json()["revision"] == 1 and ticked.json()["tax_confirmed"] is True

    # A field error is reported before the missing tick.
    named = [{"description": "Phí xử lý KANGO Express", "amount_cad": "5.00"}]
    field_first = ops.patch(
        url, {"expected_revision": 1, "lines": named, "total_change_reason": "x"}
    )
    assert field_first.status_code == 422, field_first.text
    assert field_first.json().get("field") == "lines", field_first.text

    # Hand-checked back-out on several all-in totals (one line, then several lines).
    revision = 1
    cases = [
        ["113.00"],
        ["100.00"],
        ["0.01"],
        ["99.99"],
        ["10.00"],
        ["33.33", "33.33", "33.34", "0.05"],
        ["1234.56", "0.07", "45.10"],
    ]
    for amounts in cases:
        lines = [
            {"description": f"Air freight part {i + 1}", "amount_cad": a}
            for i, a in enumerate(amounts)
        ]
        change = {"lines": lines, "total_change_reason": "Hand check"}
        # A line change without the tick is refused and saves nothing.
        stale_tick = ops.patch(url, {"expected_revision": revision, **change})
        assert stale_tick.status_code == 422, (amounts, stale_tick.text)
        assert stale_tick.json()["detail"]["code"] == "tax_unconfirmed"
        shown = _shown(sum((_d(a) for a in amounts), Decimal(0)), "included", 13)
        saved = ops.patch(
            url, {"expected_revision": revision, **change, "tax_confirmed": True, **shown}
        )
        assert saved.status_code == 200, (amounts, saved.text)
        body = saved.json()
        assert body["revision"] == revision + 1 and body["tax_confirmed"] is True
        revision = body["revision"]
        _assert_included(body)
    # The explicit owner figures.
    total, expected = Decimal("113.00"), (Decimal("100.00"), Decimal("13.00"))
    assert _included(total, 13) == expected
    # DEC-0235: net 88.50 + tax 11.51 is a cent over; the net is nudged (was 88.50 / 11.50).
    assert _included(Decimal("100.00"), 13) == (Decimal("88.49"), Decimal("11.51"))
    assert _included(Decimal("0.01"), 13) == (Decimal("0.01"), Decimal("0.00"))
    assert _included(Decimal("99.99"), 13) == (Decimal("88.49"), Decimal("11.50"))

    # 0 %: nothing backed out.
    zero = ops.patch(
        url,
        {
            "expected_revision": revision,
            "tax_rate_percent": 0,
            "tax_confirmed": True,
            **_shown(body["lines_total_cad"], "included", 0),
        },
    )
    assert zero.status_code == 200, zero.text
    revision = zero.json()["revision"]
    _assert_included(zero.json(), 0)
    assert _d(zero.json()["tax_cad"]) == 0
    # An unsupported rate or mode is refused.
    for bad in ({"tax_rate_percent": 7}, {"tax_mode": "bogus"}):
        wrong = ops.patch(url, {"expected_revision": revision, **bad, "tax_confirmed": True})
        assert wrong.status_code == 422, (bad, wrong.text)

    # Back to 13 % with a multi-line all-in total; Send issues subtotal + tax = total = lines.
    lines = [
        {"description": "Air freight", "amount_cad": "187.45"},
        {"description": "Handling", "amount_cad": "12.60"},
    ]
    final = ops.patch(
        url,
        {
            "expected_revision": revision,
            "tax_rate_percent": 13,
            "lines": lines,
            "total_change_reason": "Final figures",
            "tax_confirmed": True,
            **_shown("200.05", "included", 13),
        },
    )
    assert final.status_code == 200, final.text
    revision = final.json()["revision"]
    _assert_included(final.json())
    lines_total = Decimal("200.05")
    # Per line (DEC-0235): 187.45 -> 165.89 + 21.56 (nudged), 12.60 -> 11.15 + 1.45.
    subtotal, tax = _included_lines(["187.45", "12.60"], 13)
    assert (subtotal, tax) == (Decimal("177.04"), Decimal("23.01"))

    draft_pdf = ops.get(f"{url}/pdf", params={"revision": revision})
    assert draft_pdf.status_code == 200, draft_pdf.text
    draft_text = _pdf_text(draft_pdf.content)
    assert ROW_13 in draft_text and INCLUDED_EN not in draft_text

    assert ops.post(f"{url}/send", {"expected_revision": revision - 1}).status_code == 409
    sent = ops.post(f"{url}/send", {"expected_revision": revision})
    assert sent.status_code == 200, sent.text
    invoice_id = sent.json()["invoice_id"]
    invoice = ops.get(f"/invoices/{invoice_id}").json()
    # DEC-0235: each issued line holds its net; the all-in amount is beside it.
    assert sum(_d(x["amount_cad"]) for x in invoice["lines"]) == subtotal
    assert sum(_d(x["gross_cad"]) for x in invoice["lines"]) == lines_total
    assert (_d(invoice["subtotal_cad"]), _d(invoice["tax_cad"]), _d(invoice["total_cad"])) == (
        subtotal,
        tax,
        lines_total,
    )
    assert _d(invoice["subtotal_cad"]) + _d(invoice["tax_cad"]) == _d(invoice["total_cad"])

    document = ops.get(f"/invoices/{invoice_id}/document")
    assert document.status_code == 200, document.text
    doc = document.json()
    assert doc["tax_mode"] == "included" and doc["tax_included_note"] is None
    assert doc["tax_line_label"] == ROW_13
    assert _d(doc["total_cad"]) == lines_total and _d(doc["tax_cad"]) == tax
    issued_text = _pdf_text(ops.get(f"/invoices/{invoice_id}/pdf").content)
    assert ROW_13 in issued_text and "DRAFT" not in issued_text
    assert INCLUDED_EN not in issued_text and "Subtotal before GST/HST" not in issued_text

    # Reports: profitability revenue excludes the tax; AR owes the all-in total.
    month = invoice["period_month"]
    report = ops.get("/finance/profitability", params={"month": month})
    assert report.status_code == 200, report.text
    assert _d(report.json()["report"]["summary"]["revenue_cad"]) == subtotal
    aging = ops.get("/finance/ar-aging")
    assert aging.status_code == 200, aging.text
    row = next(r for r in aging.json()["report"]["rows"] if r["invoice_id"] == invoice_id)
    assert _d(row["total_cad"]) == lines_total and _d(row["balance_cad"]) == lines_total


def test_added_mode_vietnamese_note_and_reports_sum_both_modes(world):
    g = world
    ops = g["ops"]

    # a2 (English): switched to added on top at 5 %.
    added = _accepted_draft(g, "a2", APPLICANT)
    url = f"/invoice-drafts/{added['id']}"
    lines_total = _d(added["lines_total_cad"])
    # DEC-0235: the tax on top of each line.
    tax5 = _added_tax([x["amount_cad"] for x in added["lines"]], 5)
    saved = ops.patch(
        url,
        {
            "expected_revision": 1,
            "tax_mode": "added",
            "tax_rate_percent": 5,
            "tax_confirmed": True,
            **_shown(lines_total + tax5, "added", 5),
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert (_d(body["subtotal_cad"]), _d(body["tax_cad"]), _d(body["total_cad"])) == (
        lines_total,
        tax5,
        lines_total + tax5,
    )
    sent = ops.post(f"{url}/send", {"expected_revision": body["revision"]})
    assert sent.status_code == 200, sent.text
    added_id = sent.json()["invoice_id"]
    added_invoice = ops.get(f"/invoices/{added_id}").json()
    assert _d(added_invoice["total_cad"]) == lines_total + tax5
    doc = ops.get(f"/invoices/{added_id}/document").json()
    assert doc["tax_mode"] == "added" and doc["tax_included_note"] is None
    pdf = _pdf_text(ops.get(f"/invoices/{added_id}/pdf").content)
    assert "include GST/HST" not in pdf and "bao gồm" not in pdf

    # vi (Vietnamese by default): included; since DEC-0235 the invoice is in English for every
    # customer, with no "Prices include" sentence (it read INCLUDED_VI).
    vi_draft = _accepted_draft(g, "vi", VI_CUSTOMER)
    vi_url = f"/invoice-drafts/{vi_draft['id']}"
    _assert_included(vi_draft)
    assert ops.patch(vi_url, {"expected_revision": 1, "tax_confirmed": True}).status_code == 200
    vi_sent = ops.post(f"{vi_url}/send", {"expected_revision": 1})
    assert vi_sent.status_code == 200, vi_sent.text
    vi_id = vi_sent.json()["invoice_id"]
    vi_doc = ops.get(f"/invoices/{vi_id}/document").json()
    assert vi_doc["tax_mode"] == "included" and vi_doc["tax_included_note"] is None
    vi_text = _pdf_text(ops.get(f"/invoices/{vi_id}/pdf").content)
    assert ROW_13 in vi_text and INCLUDED_VI not in vi_text
    vi_invoice = ops.get(f"/invoices/{vi_id}").json()
    vi_total = _d(vi_draft["lines_total_cad"])
    vi_sub, vi_tax = _included_lines([x["amount_cad"] for x in vi_draft["lines"]], 13)
    assert (_d(vi_invoice["subtotal_cad"]), _d(vi_invoice["tax_cad"])) == (vi_sub, vi_tax)

    # Profitability: revenue = the two subtotals (tax excluded either way).
    month = vi_invoice["period_month"]
    assert added_invoice["period_month"] == month
    report = ops.get("/finance/profitability", params={"month": month}).json()["report"]
    assert _d(report["summary"]["revenue_cad"]) == lines_total + vi_sub
    aging = ops.get("/finance/ar-aging").json()["report"]
    owed = {r["invoice_id"]: _d(r["balance_cad"]) for r in aging["rows"]}
    assert owed[added_id] == lines_total + tax5 and owed[vi_id] == vi_total


# === 2. Customer-facing tracking ===============================================================


def _leg(ops: Staff, shipment_id: int, leg_type: str, sequence: int, links: list[str]) -> int:
    leg = ops.post(
        f"/shipments/{shipment_id}/legs",
        {"leg_type": leg_type, "sequence": sequence, "provider_name": VENDOR_LABEL},
    )
    assert leg.status_code == 201, leg.text
    leg_id = leg.json()["id"]
    for index, url in enumerate(links):
        ref = ops.post(
            f"/legs/{leg_id}/tracking-references",
            {
                "carrier_name": VENDOR_LABEL,
                "tracking_number": f"RC19TN{sequence}{index}77",
                "public_url": url,
                "source_mode": "external_link",
            },
        )
        assert ref.status_code == 201, ref.text
    return leg_id


def _assert_customer_safe(label: str, text: str) -> None:
    folded = _fold(text)
    assert "kango" not in folded, (label, text[:1500])
    assert "rc19tn" not in folded, (label, "tracking number leaked")


def test_tracking_links_generic_names_vendor_host_hidden_staff_unchanged(world, monkeypatch):
    g = world
    ops = g["ops"]
    monkeypatch.setattr(
        settings,
        "public_carrier_link_hosts",
        settings.public_carrier_link_hosts + ",www.kangoexpress.ca",
    )
    a1, a1_ref = g["kids"]["a1"]
    a2, a2_ref = g["kids"]["a2"]
    # a1: a master leg whose only link is on the vendor's own host (hidden), then a last-mile
    # leg labelled with the vendor's name, linking to Canada Post.
    _leg(ops, a1, "consolidation_linehaul", 1, [VENDOR_HOST])
    _leg(ops, a1, "final_delivery", 2, [CANADA_POST_SAFE])
    # a2: a master leg labelled with the vendor's name, linking to UPS.
    _leg(ops, a2, "consolidation_linehaul", 1, [UPS])

    public = TestClient(app)
    me = Me(APPLICANT)
    expected = {
        a1_ref: ("Last Mile Tracking", "last_mile_tracking", CANADA_POST_SAFE),
        a2_ref: ("Master Tracking", "master_tracking", UPS),
    }
    for ref, (name, key, url) in expected.items():
        for label, response in (
            ("public", public.get(f"{API}/public/track/{ref}")),
            (
                "public vi",
                public.get(f"{API}/public/track/{ref}", headers={"Accept-Language": "vi"}),
            ),
            ("account", me.get(f"/shipments/{ref}")),
        ):
            assert response.status_code == 200, (label, response.text)
            link = response.json()["carrier_link"]
            assert link is not None, (label, ref)
            assert link["tracking_name_key"] == key, (label, link)
            # The API sends the English generic name; the page localises from the key.
            assert link["carrier_name"] in (name, VI_NAMES[name]), (label, link)
            assert link["url"] == url, (label, link)
            assert "kangoexpress" not in response.text, (label, "vendor host leaked")
            _assert_customer_safe(f"{label} {ref}", response.text)

    # Staff routes still show the stored labels and links as typed.
    legs = ops.get(f"/shipments/{a1}/legs")
    assert legs.status_code == 200, legs.text
    staff_legs = legs.json()
    assert [leg["provider_name"] for leg in staff_legs] == [VENDOR_LABEL, VENDOR_LABEL]
    refs = [r for leg in staff_legs for r in leg["tracking_references"]]
    assert {r["carrier_name"] for r in refs} == {VENDOR_LABEL}
    assert {r["public_url"] for r in refs} == {VENDOR_HOST, CANADA_POST_SAFE}
    assert [leg["leg_type"] for leg in staff_legs] == ["consolidation_linehaul", "final_delivery"]


def test_vendor_hosted_link_alone_shows_no_link(world, monkeypatch):
    g = world
    ops = g["ops"]
    monkeypatch.setattr(
        settings,
        "public_carrier_link_hosts",
        settings.public_carrier_link_hosts + ",www.kangoexpress.ca",
    )
    sid, ref = g["kids"]["a1"]
    _leg(ops, sid, "final_delivery", 1, [VENDOR_HOST])
    body = TestClient(app).get(f"{API}/public/track/{ref}")
    assert body.status_code == 200, body.text
    assert body.json()["carrier_link"] is None
    _assert_customer_safe("public", body.text)
    account = Me(APPLICANT).get(f"/shipments/{ref}")
    assert account.status_code == 200, account.text
    assert account.json()["carrier_link"] is None
    _assert_customer_safe("account", account.text)


# === 3. Costume jewellery (HCM air row 27) ====================================================


def _row27_fee(estimate: dict) -> dict:
    return next(f for f in estimate["fees"] if f["section"] == "hcm_air" and f["stt"] == 27)


def test_row_27_manual_amount_blocks_then_prices_without_kg(world):
    g = world
    ops = g["ops"]
    sid, _ref = g["kids"]["b"]
    other_sid, _ = g["kids"]["a1"]
    item_id = _item(ops, sid, "Bông tai mỹ ký", weight="2.5")

    added = ops.post(
        f"/shipments/{sid}/fee-lines",
        {"item_id": item_id, "section": "hcm_air", "stt": 27, "quantity": 1},
    )
    assert added.status_code == 201, added.text
    line = added.json()
    assert line["manual_unit_price_vnd"] is None and line["weight_kg"] is None
    fee_url = f"/shipments/{sid}/fee-lines/{line['id']}"

    # Without an amount: a clear blocking issue, finalising refused.
    estimate = ops.get(f"/consolidations/{g['con']}/pricing").json()["estimate"]
    issues = [i for i in estimate["blocking"] if i.get("fee_line_id") == line["id"]]
    # RC-UAT-20 (DEC-0228): the vendor's cost (VND) and the customer price (CAD) are named.
    assert issues and (
        "enter the vendor's cost (VND) and the customer price (CAD)" in issues[0]["message"]
    ), estimate["blocking"]
    blocked = _finalize(ops, sid)
    assert blocked.status_code in (409, 422), blocked.text
    assert "quoted case by case" in blocked.text, blocked.text

    # Garbage amounts are refused; Marketing cannot write; another shipment's path 404s.
    for bad in ("-1", "0", "abc", "NaN", "Infinity", "-Infinity", "", None, "1,000"):
        refused = ops.patch(fee_url, {"manual_unit_price_vnd": bad})
        assert refused.status_code == 422, (bad, refused.status_code, refused.text)
    assert ops.patch(fee_url, {}).status_code == 422
    assert (
        ops.patch(fee_url, {"manual_unit_price_vnd": "1000", "weight_kg": "2"}).status_code == 422
    )
    marketing = Staff(g["users"][Role.MARKETING].email)
    assert marketing.patch(fee_url, {"manual_unit_price_vnd": "450000"}).status_code == 403
    wrong_shipment = ops.patch(
        f"/shipments/{other_sid}/fee-lines/{line['id']}", {"manual_unit_price_vnd": "1000"}
    )
    assert wrong_shipment.status_code == 404, wrong_shipment.text
    assert ops.get(f"/shipments/{sid}/fee-lines").json()[0]["manual_unit_price_vnd"] is None

    # Operations enters the vendor's cost and (RC-UAT-20, DEC-0228) the customer price: the
    # cost is the VND at the buy rate; the charge is exactly the CAD price, no 2 % markup.
    entered = ops.patch(fee_url, {"manual_unit_price_vnd": "450000"})
    assert entered.status_code == 200, entered.text
    assert _d(entered.json()["manual_unit_price_vnd"]) == Decimal(450000)
    priced = ops.patch(fee_url, {"customer_price_cad": "42.50"})
    assert priced.status_code == 200, priced.text
    assert _d(priced.json()["customer_price_cad"]) == Decimal("42.50")
    buy = Decimal(19500)  # method v0.5 costs at Kango's fixed rate (DEC-0252)
    settings_out = ops.get("/pricing/settings").json()
    assert (settings_out["default_markup_kind"], _d(settings_out["default_markup_value"])) == (
        "percent",
        Decimal(2),
    )
    cost_cad = _cents(Decimal(450000) / buy)
    charge = Decimal("42.50")

    estimate = ops.get(f"/consolidations/{g['con']}/pricing").json()["estimate"]
    assert not [i for i in estimate["blocking"] if i.get("fee_line_id") == line["id"]]
    fee = _row27_fee(estimate)
    assert _d(fee["vendor_fee_vnd"]) == Decimal(450000)
    assert {k: _d(v) for k, v in fee["cost_alloc_vnd"].items()} == {str(sid): Decimal(450000)}
    assert {k: _d(v) for k, v in fee["cost_alloc_cad"].items()} == {str(sid): cost_cad}
    assert _d(fee["customer_base_cad"]) == charge
    assert _d(fee["customer_total_cad"]) == charge

    # No kg dependence: change the item's weight, the charge is the same.
    reweighed = ops.patch(f"/shipments/{sid}/items/{item_id}", {"weight_kg": "9.5"})
    assert reweighed.status_code == 200, reweighed.text
    again = _row27_fee(ops.get(f"/consolidations/{g['con']}/pricing").json()["estimate"])
    assert _d(again["vendor_fee_vnd"]) == Decimal(450000)
    assert _d(again["customer_total_cad"]) == charge

    # Finalising is allowed now; the quote line carries the charge.
    final = _finalize(ops, sid)
    assert final.status_code == 200, final.text
    row27 = [x for x in final.json()["lines"] if x["section"] == "hcm_air" and x["stt"] == 27]
    assert len(row27) == 1 and _d(row27[0]["revenue_cad"]) == charge, row27

    # A locked (booked) master refuses the PATCH.
    booked = ops.post(f"/consolidations/{g['con']}/book")
    assert booked.status_code == 200, booked.text
    locked = ops.patch(fee_url, {"manual_unit_price_vnd": "500000"})
    assert locked.status_code == 409, locked.text
    assert "locked" in locked.text.lower()
    see_committed_changes(g["db"])
    assert _d(ops.get(f"/shipments/{sid}/fee-lines").json()[0]["manual_unit_price_vnd"]) == (
        Decimal(450000)
    )


def test_row_27_amount_that_rounds_to_zero_or_overflows_is_refused(world):
    """Defect probe: the API refuses 0, but 0.001 is stored as 0.00 (an unblocked free line),
    and 1e30 crashes the request (decimal.InvalidOperation, a 500) instead of a 422."""
    g = world
    ops = g["ops"]
    sid, _ref = g["kids"]["b"]
    item_id = _item(ops, sid, "Nhẫn mỹ ký", weight="1")
    added = ops.post(
        f"/shipments/{sid}/fee-lines",
        {"item_id": item_id, "section": "hcm_air", "stt": 27, "quantity": 1},
    )
    assert added.status_code == 201, added.text
    fee_url = f"/shipments/{sid}/fee-lines/{added.json()['id']}"
    outcomes = {}
    for value in ("0.001", "1e-9", "1e30"):
        try:
            response = ops.patch(fee_url, {"manual_unit_price_vnd": value})
            outcomes[value] = (response.status_code, response.json().get("manual_unit_price_vnd"))
        except Exception as exc:  # the TestClient re-raises a server error
            outcomes[value] = (500, type(exc).__name__)
    assert all(status == 422 for status, _ in outcomes.values()), outcomes
