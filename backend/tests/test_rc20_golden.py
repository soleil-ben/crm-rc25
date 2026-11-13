"""RC-UAT-20 golden tests (independent tester): owner answers of 2026-10-23, black box over HTTP.

1. GST/HST by route on the draft created by a customer acceptance (DEC-0227): international
   0 %, domestic included at the destination province's rate (hand-checked back-out with
   Decimal ROUND_HALF_UP), unknown province, the Admin rate table, the direct-issue path.
2. Download of a draft needs the GST/HST confirmed for the saved revision (DEC-0229 s.2).
3. A payment's received date is a plain date (DEC-0229 s.1).
4. Costume jewellery, HCM air row 27: VND cost and CAD customer price (DEC-0228).
5. Legs: the vendor on the final delivery leg, generic tracking names (DEC-0229 s.3-4).
6. Settings > Tariffs: 39 warnings and 3 confirmed price steps apart (DEC-0229 s.5).
7. Wording kept (OD-108), read-only checks of the frontend strings.

The pricing world (tariff v1 imported, FX, shipments, one HCM air master) is seeded through
services as the RC-UAT-18/19 golden suites do; route fields on a shipment are set directly
(no staff screen edits them). Everything under test goes through HTTP. Demo data; air only.
"""

from __future__ import annotations

import io
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.core.enums import Role, RouteGroup
from app.main import app
from app.models import Customer, Shipment, ShipmentPackage
from app.services import consolidation_service as cs
from app.services import finance_service
from tests.conftest import booked_shipment, see_committed_changes
from tests.test_account_profile import APPLICANT, _activate
from tests.test_rc18_golden import Me, Staff, _import_v1

API = "/api/v1"
NEG_MARGIN = "golden rc20 test"
CENT = Decimal("0.01")
VENDOR = "Kango Logistics"
UPS = "https://www.ups.com/track?loc=en_CA&tracknum=1Z999AA10123456784"
CANADA_POST = "https://www.canadapost-postescanada.ca/track-reperage/en?pin=7023210039414604"
REPO = Path(__file__).resolve().parents[2]
PROVINCES = {
    "ON": 13,
    "NS": 14,
    "NB": 15,
    "NL": 15,
    "PE": 15,
    "AB": 5,
    "BC": 5,
    "MB": 5,
    "QC": 5,
    "SK": 5,
    "NT": 5,
    "NU": 5,
    "YT": 5,
}


def _d(value) -> Decimal:
    return Decimal(str(value))


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _back_out(total: Decimal, rate: int) -> tuple[Decimal, Decimal]:
    """The tester's own back-out of one all-in line (RC-UAT-23, DEC-0235: per line): (net,
    tax), the net nudged by the cent so net + tax is the line."""
    net = _cents(total * 100 / (100 + rate))
    tax = _cents(net * rate / 100)
    return total - tax, tax


def _back_out_lines(amounts, rate: int) -> tuple[Decimal, Decimal]:
    """(subtotal, tax) of all-in lines, each backed out on its own (DEC-0235)."""
    parts = [_back_out(_d(amount), rate) for amount in amounts]
    return sum((p[0] for p in parts), Decimal(0)), sum((p[1] for p in parts), Decimal(0))


#: DEC-0235: the summary row of the Solaris Invoicing layout, by rate.
ROWS = {0: "GST @ 0%", 5: "GST @ 5%", 13: "HST ON @ 13%", 14: "HST @ 14%", 15: "HST @ 15%"}


def _shown(total, rate: int, mode: str = "included") -> dict:
    return {
        "confirmed_total_cad": str(_cents(_d(total))),
        "confirmed_tax_mode": mode,
        "confirmed_tax_rate_percent": rate,
    }


def _pdf_text(content: bytes) -> str:
    assert content.startswith(b"%PDF"), content[:20]
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)


# --- World -----------------------------------------------------------------------------------


def _build(account_client, account_db, account_users, captured_mail, names):
    db = account_db
    _activate(account_client, account_users, captured_mail)
    see_committed_changes(db)
    owner = db.query(Customer).filter_by(email_normalized=APPLICANT).one()
    version = _import_v1(db)
    kids = {}
    for name in names:
        shipment = booked_shipment(db, owner, RouteGroup.VCA)
        for package in db.query(ShipmentPackage).filter_by(shipment_id=shipment.id):
            package.weight_kg = package.weight_value = Decimal(1)
            package.length_cm = package.width_cm = package.height_cm = None
        kids[name] = (shipment.id, shipment.public_id)
    db.commit()
    con = cs.create_consolidation(
        db,
        {
            "solaris_service": "air_standard",
            "origin": "HCM",
            "vendor_reference": "RC20G",
            "actual_weight_kg": str(len(names)),
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
        "version": version.id,
        "users": account_users,
        "ops": Staff(account_users[Role.OPERATIONS].email),
        "admin": Staff(account_users[Role.ADMIN].email),
        "me": Me(APPLICANT),
    }


TAX_KIDS = ["vnca", "cavn", "caus", *PROVINCES, "unknown", "on_after", "ns_name"]


@pytest.fixture
def tax_world(account_client, account_db, account_users, captured_mail):
    return _build(account_client, account_db, account_users, captured_mail, TAX_KIDS)


@pytest.fixture
def small_world(account_client, account_db, account_users, captured_mail):
    return _build(account_client, account_db, account_users, captured_mail, ["s1", "s2", "s3"])


def _route(g, kid: str, origin: str, destination: str, province: str | None = None) -> None:
    db = g["db"]
    see_committed_changes(db)
    shipment = db.get(Shipment, g["kids"][kid][0])
    shipment.origin_country_code = shipment.sender_country_code = origin
    shipment.destination_country_code = shipment.recipient_country_code = destination
    shipment.recipient_province_state = province
    # Review 2026-10-24: the postal code is read first, so the fixture's Ontario postal code
    # (L4W) is cleared to test the province text alone.
    shipment.recipient_postal_code = None
    db.commit()


def _finalize(ops: Staff, sid: int):
    assert ops.post(f"/shipments/{sid}/quotes").status_code == 201
    assert ops.post(f"/shipments/{sid}/quotes/confirm-rate", {}).status_code == 200
    return ops.post(f"/shipments/{sid}/quotes/finalize", {"negative_margin_reason": NEG_MARGIN})


def _accept(g, kid: str) -> tuple[dict, int]:
    """Finalise, send, accept in the Customer Account; returns (draft view, offer id)."""
    ops = g["ops"]
    sid, _ref = g["kids"][kid]
    final = _finalize(ops, sid)
    assert final.status_code == 200, (kid, final.text)
    sent = ops.post(f"/shipments/{sid}/quotes/send")
    assert sent.status_code == 201, (kid, sent.text)
    offer_id = sent.json()["id"]
    accepted = g["me"].post(f"/quotes/{offer_id}/accept")
    assert accepted.status_code == 200, (kid, accepted.text)
    found = ops.get(f"/shipments/{sid}/invoice-draft")
    assert found.status_code == 200 and found.json(), (kid, found.text)
    return found.json(), offer_id


def _assert_view(body: dict, rate: int) -> None:
    total = _d(body["lines_total_cad"])
    subtotal, tax = _back_out_lines([x["amount_cad"] for x in body["lines"]], rate)
    assert (body["tax_rate_percent"], body["tax_mode"]) == (rate, "included"), body
    assert body["tax_rate_required"] is False
    assert (_d(body["subtotal_cad"]), _d(body["tax_cad"]), _d(body["total_cad"])) == (
        subtotal,
        tax,
        total,
    ), body


def _set_lines(ops: Staff, draft: dict, amounts: list[str], rate: int) -> dict:
    lines = [
        {"description": f"Air freight {i + 1}", "amount_cad": a} for i, a in enumerate(amounts)
    ]
    total = sum((_d(a) for a in amounts), Decimal(0))
    saved = ops.patch(
        f"/invoice-drafts/{draft['id']}",
        {
            "expected_revision": draft["revision"],
            "lines": lines,
            "total_change_reason": "Hand check",
            "tax_confirmed": True,
            **_shown(total, rate),
        },
    )
    assert saved.status_code == 200, (amounts, rate, saved.text)
    return saved.json()


def _send(ops: Staff, draft: dict) -> dict:
    sent = ops.post(f"/invoice-drafts/{draft['id']}/send", {"expected_revision": draft["revision"]})
    assert sent.status_code == 200, sent.text
    return ops.get(f"/invoices/{sent.json()['invoice_id']}").json()


# === 1. GST/HST by route ======================================================================


def test_international_routes_are_zero_rated_with_no_included_sentence(tax_world):
    g = tax_world
    ops = g["ops"]
    for kid, (origin, destination) in {
        "vnca": ("VN", "CA"),
        "cavn": ("CA", "VN"),
        "caus": ("CA", "US"),
    }.items():
        # A Canadian province on the address never makes an international route domestic.
        _route(g, kid, origin, destination, "ON")
        draft, offer_id = _accept(g, kid)
        _assert_view(draft, 0)
        assert _d(draft["tax_cad"]) == 0, (kid, draft)
        assert draft["tax_route"]["route_band"] == "international", (kid, draft["tax_route"])
        assert draft["tax_confirmed"] is False
        if kid != "vnca":
            continue
        # OD-108: the customer's quote still says tax is not included.
        quote = g["me"].get(f"/quotes/{offer_id}")
        assert quote.status_code == 200 and quote.json()["tax_included"] is False, quote.text
        ticked = ops.patch(
            f"/invoice-drafts/{draft['id']}", {"expected_revision": 1, "tax_confirmed": True}
        )
        assert ticked.status_code == 200, ticked.text
        invoice = _send(ops, ticked.json())
        assert invoice["tax_status"] == "gst_hst_0"
        assert _d(invoice["tax_cad"] or 0) == 0
        assert _d(invoice["subtotal_cad"]) == _d(invoice["total_cad"]) == _d(draft["total_cad"])
        doc = ops.get(f"/invoices/{invoice['id']}/document").json()
        assert not doc.get("tax_included_note"), doc.get("tax_included_note")
        text = _pdf_text(ops.get(f"/invoices/{invoice['id']}/pdf").content)
        assert "Prices include" not in text and "bao gồm" not in text


def test_domestic_rates_by_destination_province_hand_checked_and_sent(tax_world):
    g = tax_world
    ops = g["ops"]
    drafts = {}
    for province, rate in PROVINCES.items():
        # The origin province never counts: every sender is in Quebec (5 %).
        _route(g, province, "CA", "CA", province)
        see_committed_changes(g["db"])
        g["db"].get(Shipment, g["kids"][province][0]).sender_province_state = "QC"
        g["db"].commit()
        draft, _ = _accept(g, province)
        _assert_view(draft, rate)
        route = draft["tax_route"]
        assert (route["route_band"], route["destination_province"]) == ("domestic", province)
        assert rate in draft["allowed_tax_rates"]
        drafts[province] = draft
    # A province written as a French name.
    _route(g, "ns_name", "CA", "CA", "Nouvelle-Écosse")
    _assert_view(_accept(g, "ns_name")[0], 14)

    # The owner's figures, hand-checked, then several odd totals per band.
    assert _back_out(Decimal("115.00"), 15) == (Decimal("100.00"), Decimal("15.00"))
    assert _back_out(Decimal("114.00"), 14) == (Decimal("100.00"), Decimal("14.00"))
    assert _back_out(Decimal("105.00"), 5) == (Decimal("100.00"), Decimal("5.00"))
    assert _back_out(Decimal("113.00"), 13) == (Decimal("100.00"), Decimal("13.00"))
    assert _back_out(Decimal("0.07"), 15)[1] == Decimal("0.01")  # 0.00913
    assert _back_out(Decimal("0.05"), 14)[1] == Decimal("0.01")  # 0.00614
    # DEC-0235 (per line): net 0.04 -> tax 0.01, the net nudged to 0.03 (the whole-total rule
    # of DEC-0223 read 0.00491 -> 0.00).
    assert _back_out(Decimal("0.04"), 14) == (Decimal("0.03"), Decimal("0.01"))
    assert _back_out(Decimal("0.11"), 5)[1] == Decimal("0.01")  # 0.005238
    assert _back_out(Decimal("10.00"), 5)[1] == Decimal("0.48")  # 0.4761
    cases = {
        "PE": ["115.00", "100.00", "0.07", "33.33", "1234.57"],
        "NS": ["114.00", "100.00", "0.05", "0.04", "99.99"],
        "ON": ["113.00", "99.99", "0.01", "200.05"],
        "AB": ["105.00", "10.00", "0.11", "0.10", "77.77"],
    }
    for province, totals in cases.items():
        draft, rate = drafts[province], PROVINCES[province]
        for amount in totals:
            # One line, then the same total split in two lines.
            draft = _set_lines(ops, draft, [amount], rate)
            _assert_view(draft, rate)
            if _d(amount) >= Decimal("1.00"):
                half = _cents(_d(amount) / 3)
                draft = _set_lines(ops, draft, [str(half), str(_d(amount) - half)], rate)
                _assert_view(draft, rate)
        invoice = _send(ops, draft)
        total = _d(totals[-1])
        subtotal, tax = _back_out_lines([x["amount_cad"] for x in draft["lines"]], rate)
        assert (
            _d(invoice["subtotal_cad"]),
            _d(invoice["tax_cad"]),
            _d(invoice["total_cad"]),
        ) == (subtotal, tax, total), (province, invoice)
        assert invoice["tax_status"] == f"gst_hst_{rate}", invoice["tax_status"]
        doc = ops.get(f"/invoices/{invoice['id']}/document").json()
        # DEC-0235: no "Prices include" sentence; the summary row of the province's rate.
        assert doc["tax_included_note"] is None, doc
        assert doc["tax_line_label"] == ROWS[rate], doc
    # The drafts of the other provinces send as auto-filled once ticked.
    for province in ("NB", "NL", "BC", "YT"):
        draft = drafts[province]
        ticked = ops.patch(
            f"/invoice-drafts/{draft['id']}", {"expected_revision": 1, "tax_confirmed": True}
        )
        assert ticked.status_code == 200, ticked.text
        invoice = _send(ops, ticked.json())
        rate = PROVINCES[province]
        assert invoice["tax_status"] == f"gst_hst_{rate}"
        assert _d(invoice["subtotal_cad"]) + _d(invoice["tax_cad"]) == _d(invoice["total_cad"])


def test_unknown_province_needs_a_staff_choice_before_save_send_download(tax_world):
    g = tax_world
    ops = g["ops"]
    _route(g, "unknown", "CA", "CA", "Atlantis")
    draft, _ = _accept(g, "unknown")
    url = f"/invoice-drafts/{draft['id']}"
    assert draft["tax_rate_percent"] is None and draft["tax_rate_required"] is True
    assert draft["subtotal_cad"] is None and draft["tax_cad"] is None
    assert draft["total_cad"] is None
    assert draft["tax_route"]["destination_province"] is None
    saved = ops.patch(url, {"expected_revision": 1, "tax_confirmed": True})
    assert saved.status_code == 422, saved.text
    assert saved.json()["detail"]["code"] == "tax_rate_required"
    for refused in (
        ops.post(f"{url}/send", {"expected_revision": 1}),
        ops.get(f"{url}/pdf", params={"revision": 1}),
    ):
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"]["code"] == "tax_unconfirmed"
    assert ops.get(f"/shipments/{g['kids']['unknown'][0]}/invoice").json() is None

    # Staff choose 15 % (with the echoed figures), then confirm and send.
    total = _d(draft["lines_total_cad"])
    chosen = ops.patch(
        url,
        {
            "expected_revision": 1,
            "tax_rate_percent": 15,
            "tax_confirmed": True,
            **_shown(total, 15),
        },
    )
    assert chosen.status_code == 200, chosen.text
    _assert_view(chosen.json(), 15)
    assert ops.get(f"{url}/pdf", params={"revision": chosen.json()["revision"]}).status_code == 200
    invoice = _send(ops, chosen.json())
    subtotal, tax = _back_out_lines([x["amount_cad"] for x in chosen.json()["lines"]], 15)
    assert (_d(invoice["subtotal_cad"]), _d(invoice["tax_cad"])) == (subtotal, tax)
    assert _d(invoice["subtotal_cad"]) + _d(invoice["tax_cad"]) == _d(invoice["total_cad"])
    assert invoice["tax_status"] == "gst_hst_15"


def test_admin_rate_edit_applies_to_new_drafts_only_and_only_admin_edits(tax_world):
    g = tax_world
    ops, admin = g["ops"], g["admin"]
    _route(g, "ON", "CA", "CA", "ON")
    before, _ = _accept(g, "ON")
    _assert_view(before, 13)

    for role in (Role.OPERATIONS, Role.READ_ONLY_MANAGER, Role.MARKETING):
        other = ops if role == Role.OPERATIONS else Staff(g["users"][role].email)
        assert other.patch("/finance/tax-rates/ON", {"rate_percent": 15}).status_code == 403
    assert Staff(g["users"][Role.MARKETING].email).get("/finance/tax-rates").status_code == 403
    listed = ops.get("/finance/tax-rates")
    assert listed.status_code == 200
    table = {
        r["province_code"]: (r["rate_percent"], r["tax_label"]) for r in listed.json()["items"]
    }
    assert {code: rate for code, (rate, _label) in table.items()} == PROVINCES
    assert table["ON"][1] == "HST" and table["AB"][1] == "GST"

    edited = admin.patch("/finance/tax-rates/ON", {"rate_percent": 15})
    assert edited.status_code == 200, edited.text
    _route(g, "on_after", "CA", "CA", "Toronto, ON")
    after, _ = _accept(g, "on_after")
    _assert_view(after, 15)
    # The existing draft keeps its rate.
    _assert_view(ops.get(f"/invoice-drafts/{before['id']}").json(), 13)


def test_directly_issued_invoice_path_is_unchanged(small_world):
    g = small_world
    ops = g["ops"]
    sid, _ = g["kids"]["s1"]
    _route(g, "s1", "CA", "CA", "NS")  # a route rate does not apply to the manual path
    assert _finalize(ops, sid).status_code == 200
    for bad in (14, 15, 7):
        refused = ops.post(f"/shipments/{sid}/invoice", {"tax_rate_percent": bad})
        assert refused.status_code == 422, (bad, refused.text)
    issued = ops.post(f"/shipments/{sid}/invoice", {"tax_rate_percent": 13})
    assert issued.status_code == 201, issued.text
    body = issued.json()
    lines = sum((_d(x["amount_cad"]) for x in body["lines"]), Decimal(0))
    tax = _cents(lines * 13 / 100)
    assert (_d(body["subtotal_cad"]), _d(body["tax_cad"]), _d(body["total_cad"])) == (
        lines,
        tax,
        lines + tax,
    )
    assert body["tax_status"] == "gst_hst_13"
    assert _finalize(ops, g["kids"]["s2"][0]).status_code == 200
    zero = ops.post(f"/shipments/{g['kids']['s2'][0]}/invoice")
    assert zero.status_code == 201, zero.text
    assert zero.json()["tax_status"] == "gst_hst_0"


# === 2. Download of a draft ===================================================================


def test_draft_download_needs_the_saved_revision_confirmed(small_world):
    g = small_world
    ops = g["ops"]
    draft, _ = _accept(g, "s1")
    url = f"/invoice-drafts/{draft['id']}"
    refused = ops.get(f"{url}/pdf", params={"revision": 1})
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == "tax_unconfirmed"
    # Read-only manager is refused the same way.
    manager = Staff(g["users"][Role.READ_ONLY_MANAGER].email)
    assert manager.get(f"{url}/pdf", params={"revision": 1}).status_code == 422
    # An unticked save is refused and confirms nothing.
    assert ops.patch(url, {"expected_revision": 1, "notes": "x"}).status_code == 422
    assert ops.get(f"{url}/pdf", params={"revision": 1}).status_code == 422

    assert ops.patch(url, {"expected_revision": 1, "tax_confirmed": True}).status_code == 200
    ok = ops.get(f"{url}/pdf", params={"revision": 1})
    assert ok.status_code == 200 and ok.content.startswith(b"%PDF")
    assert manager.get(f"{url}/pdf", params={"revision": 1}).status_code == 200

    # An edit after confirming: the old revision is refused (stale), the new one confirmed.
    edited = _set_lines(ops, ops.get(url).json(), ["150.00"], 0)
    assert edited["revision"] == 2
    stale = ops.get(f"{url}/pdf", params={"revision": 1})
    assert stale.status_code in (409, 422), stale.text
    assert ops.get(f"{url}/pdf", params={"revision": 2}).status_code == 200


# === 3. Payment received date =================================================================


def test_payment_received_date_is_a_plain_date_everywhere(small_world, monkeypatch):
    g = small_world
    ops, admin = g["ops"], g["admin"]
    sid, _ = g["kids"]["s3"]
    assert _finalize(ops, sid).status_code == 200
    clock = {"now": datetime(2026, 9, 16, 15)}
    monkeypatch.setattr(finance_service, "utcnow", lambda: clock["now"])
    issued = ops.post(f"/shipments/{sid}/invoice", {"tax_rate_percent": 0})
    assert issued.status_code == 201, issued.text
    invoice_id = issued.json()["id"]
    assert issued.json()["period_month"] == "2026-09"
    url = f"/invoices/{invoice_id}/payments"

    clock["now"] = datetime(2026, 9, 25, 12)  # 08:00 in Toronto
    written = [
        "2026-09-20",
        "2026-09-20T00:00:00",
        "2026-09-20T00:00:00-04:00",
        "2026-09-20T00:00:00Z",
        "2026-09-20T22:30:00-04:00",
    ]
    for value in written:
        paid = ops.post(url, {"amount_cad": "1.00", "method": "cash", "received_at": value})
        assert paid.status_code == 201, (value, paid.text)
    assert ops.post(
        url, {"amount_cad": "1.00", "method": "cash", "received_at": "2026-09-26"}
    ).status_code in (409, 422)

    detail = ops.get(f"/invoices/{invoice_id}").json()
    assert [p["received_at"] for p in detail["payments"]] == ["2026-09-20T00:00:00"] * 5
    for payment in detail["payments"]:
        receipt = ops.get(f"/payments/{payment['id']}/receipt")
        assert receipt.status_code == 200, receipt.text
        assert receipt.json()["received_at"] == "2026-09-20T00:00:00"
    assert _d(detail["paid_cad"]) == Decimal("5.00")
    aging = ops.get("/finance/ar-aging").json()["report"]["rows"]
    row = next(r for r in aging if r["invoice_id"] == invoice_id)
    assert _d(row["balance_cad"]) == _d(detail["total_cad"]) - Decimal("5.00")
    listed = ops.get("/invoices").json()["items"]
    assert next(i for i in listed if i["id"] == invoice_id)["period_month"] == "2026-09"

    # From 8 October September is locked: an offset never moves a date across the month.
    clock["now"] = datetime(2026, 10, 10, 12)
    for value in ("2026-09-20", "2026-09-30T22:00:00-04:00", "2026-09-30T23:30:00Z"):
        locked = ops.post(url, {"amount_cad": "1.00", "method": "cash", "received_at": value})
        assert locked.status_code == 409, (value, locked.text)
    october = ops.post(
        url, {"amount_cad": "1.00", "method": "cash", "received_at": "2026-10-01T00:00:00+05:00"}
    )
    assert october.status_code == 201, october.text
    assert october.json()["payments"][-1]["received_at"] == "2026-10-01T00:00:00"
    # Closed explicitly: still refused.
    closed = admin.post("/finance/periods/2026-09/close")
    assert closed.status_code == 200, closed.text
    again = ops.post(url, {"amount_cad": "1.00", "method": "cash", "received_at": "2026-09-20"})
    assert again.status_code == 409, again.text


# === 4. Costume jewellery (HCM air row 27) ====================================================


def _row27(ops: Staff, sid: int, description: str) -> tuple[int, str]:
    item = ops.post(f"/shipments/{sid}/items", {"description": description, "weight_kg": "1"})
    assert item.status_code == 201, item.text
    added = ops.post(
        f"/shipments/{sid}/fee-lines",
        {"item_id": item.json()["id"], "section": "hcm_air", "stt": 27, "quantity": 1},
    )
    assert added.status_code == 201, added.text
    return added.json()["id"], f"/shipments/{sid}/fee-lines/{added.json()['id']}"


def _issues(g, line_id: int) -> list[str]:
    estimate = g["ops"].get(f"/consolidations/{g['con']}/pricing").json()["estimate"]
    return [i["message"] for i in estimate["blocking"] if i.get("fee_line_id") == line_id]


def test_costume_jewellery_needs_both_cost_and_price_charged_exactly(small_world):
    g = small_world
    ops = g["ops"]
    s1, s2 = g["kids"]["s1"][0], g["kids"]["s2"][0]
    vnd_line, vnd_url = _row27(ops, s1, "Bông tai mỹ ký")
    cad_line, cad_url = _row27(ops, s2, "Vòng cổ mỹ ký")

    # Validation of the customer price.
    for bad in ("-1", "0", "abc", "NaN", "Infinity", "", None, "1,000", "0.001", "0.004"):
        refused = ops.patch(cad_url, {"customer_price_cad": bad})
        assert refused.status_code == 422, (bad, refused.status_code, refused.text)
    for big in ("10000000000.00", "1e30"):
        try:
            status = ops.patch(cad_url, {"customer_price_cad": big}).status_code
        except Exception as exc:  # the TestClient re-raises a server error
            status = type(exc).__name__
        assert status == 422, (big, status)
    assert ops.patch(cad_url, {}).status_code == 422
    marketing = Staff(g["users"][Role.MARKETING].email)
    assert marketing.patch(cad_url, {"customer_price_cad": "10.00"}).status_code == 403
    item = ops.post(f"/shipments/{s1}/items", {"description": "Watch"}).json()["id"]
    plain = ops.post(
        f"/shipments/{s1}/fee-lines",
        {"item_id": item, "section": "hcm_air", "stt": 18, "quantity": 1},
    )
    assert plain.status_code == 201, plain.text
    not_manual = ops.patch(
        f"/shipments/{s1}/fee-lines/{plain.json()['id']}", {"customer_price_cad": "10.00"}
    )
    assert not_manual.status_code == 422, not_manual.text

    # Only the VND cost: blocked, naming the customer price only.
    assert ops.patch(vnd_url, {"manual_unit_price_vnd": "450000"}).status_code == 200
    (message,) = _issues(g, vnd_line)
    assert "customer price" in message and "vendor's cost" not in message, message
    blocked = _finalize(ops, s1)
    assert blocked.status_code in (409, 422) and "customer price" in blocked.text, blocked.text
    # Only the CAD price: blocked, naming the cost only.
    assert ops.patch(cad_url, {"customer_price_cad": "42.50"}).status_code == 200
    (message,) = _issues(g, cad_line)
    assert "vendor's cost" in message and "customer price" not in message, message
    blocked = _finalize(ops, s2)
    assert blocked.status_code in (409, 422) and "vendor's cost" in blocked.text, blocked.text

    # Both: the charge is exactly the price, the cost the VND at the buy rate.
    both = ops.patch(vnd_url, {"customer_price_cad": "37.13"})
    assert both.status_code == 200 and _d(both.json()["customer_price_cad"]) == Decimal("37.13")
    assert ops.patch(cad_url, {"manual_unit_price_vnd": "300000"}).status_code == 200
    assert not _issues(g, vnd_line) and not _issues(g, cad_line)
    buy = Decimal(19500)  # method v0.5 costs at Kango's fixed rate (DEC-0252)
    estimate = ops.get(f"/consolidations/{g['con']}/pricing").json()["estimate"]
    row27 = {
        tuple(f["cost_alloc_vnd"]): f
        for f in estimate["fees"]
        if f["section"] == "hcm_air" and f["stt"] == 27
    }
    for sid, vnd, price in ((s1, 450000, "37.13"), (s2, 300000, "42.50")):
        fee = row27[(str(sid),)]
        assert _d(fee["customer_total_cad"]) == _d(fee["customer_base_cad"]) == _d(price), fee
        assert {k: _d(v) for k, v in fee["cost_alloc_cad"].items()} == {
            str(sid): _cents(Decimal(vnd) / buy)
        }
        final = _finalize(ops, sid)
        assert final.status_code == 200, final.text
        lines = [x for x in final.json()["lines"] if x["section"] == "hcm_air" and x["stt"] == 27]
        assert [_d(x["revenue_cad"]) for x in lines] == [_d(price)], lines

    # A locked master refuses both inputs.
    assert ops.post(f"/consolidations/{g['con']}/book").status_code == 200
    for body in ({"customer_price_cad": "50.00"}, {"manual_unit_price_vnd": "500000"}):
        locked = ops.patch(vnd_url, body)
        assert locked.status_code == 409, (body, locked.text)


# === 5. Legs ===================================================================================


def test_final_delivery_offers_the_vendor_and_labels_are_generic(small_world):
    g = small_world
    ops = g["ops"]
    meta = ops.get("/shipments/meta").json()
    assert VENDOR in meta["leg_providers"]["final_delivery"], meta["leg_providers"]
    assert all(VENDOR in providers for providers in meta["leg_providers"].values())

    (s1, ref1), (s2, ref2) = g["kids"]["s1"], g["kids"]["s2"]
    # s1: a master leg without a link, then the last-mile leg (Canada Post link); s2: a master
    # leg with a UPS link. The customer sees one link per shipment.
    plan = [
        (s1, "consolidation_linehaul", 1, None, None),
        (s1, "final_delivery", 2, "Canada Post", CANADA_POST),
        (s2, "consolidation_linehaul", 1, "UPS", UPS),
    ]
    for sid, leg_type, sequence, carrier, link in plan:
        leg = ops.post(
            f"/shipments/{sid}/legs",
            {"leg_type": leg_type, "sequence": sequence, "provider_name": VENDOR},
        )
        assert leg.status_code == 201, leg.text
        if link is None:
            continue
        tracking = ops.post(
            f"/legs/{leg.json()['id']}/tracking-references",
            {
                "carrier_name": carrier,
                "tracking_number": f"RC20TN{sid}{sequence}",
                "public_url": link,
                "source_mode": "external_link",
            },
        )
        assert tracking.status_code == 201, tracking.text

    staff_legs = ops.get(f"/shipments/{s1}/legs").json()
    keys = {leg["leg_type"]: leg["tracking_name_key"] for leg in staff_legs}
    assert keys == {
        "consolidation_linehaul": "master_tracking",
        "final_delivery": "last_mile_tracking",
    }
    assert {leg["provider_name"] for leg in staff_legs} == {VENDOR}  # staff still see it

    names = {"Master Tracking", "Last Mile Tracking", "Theo dõi chặng chính", "Theo dõi chặng cuối"}
    for ref, expected in ((ref1, "Last Mile Tracking"), (ref2, "Master Tracking")):
        for label, response in (
            ("public", TestClient(app).get(f"{API}/public/track/{ref}")),
            ("account", g["me"].get(f"/shipments/{ref}")),
        ):
            assert response.status_code == 200, (label, response.text)
            link = response.json()["carrier_link"]
            assert link and link["carrier_name"] == expected, (label, link)
            assert link["carrier_name"] in names
            for word in ("Kango", "UPS", "Canada Post"):
                assert word.lower() not in link["carrier_name"].lower(), (label, link)
            assert "kango" not in response.text.lower(), (label, "vendor leaked")

    # The staff screen's labels are fixed strings (frontend, read-only).
    en = (REPO / "frontend/src/i18n/en.js").read_text(encoding="utf-8")
    vi = (REPO / "frontend/src/i18n/vi.js").read_text(encoding="utf-8")
    assert "master_tracking: 'Master Tracking'," in en
    assert "last_mile_tracking: 'Last Mile Tracking'," in en
    assert "master_tracking: 'Theo dõi chặng chính'," in vi
    assert "last_mile_tracking: 'Theo dõi chặng cuối'," in vi


# === 6. Settings > Tariffs ======================================================================


def test_seeded_tariff_has_39_warnings_and_3_confirmed_steps_apart(small_world):
    g = small_world
    url = f"/tariffs/versions/{g['version']}/warnings"
    full = g["admin"].get(url, params={"limit": 500})
    assert full.status_code == 200, full.text
    body = full.json()
    assert body["count"] == 39 and len(body["items"]) == 39, body["counts_by_code"]
    assert body["counts_by_code"] == {
        "express_zone_below_ground": 35,
        "trucking_pallet_fees_not_imported": 2,
        "duplicate_fsa": 1,
        "beyond_code_without_rate": 1,
    }
    steps = {f"{s['sheet']}!{s['cell']}" for s in body["confirmed_price_steps"]}
    assert steps == {"HCM-AIR-CAD!F39", "HN-AIR-CAD!F38", "HN-AIR-CAD!G38"}, steps
    listed = {(i["sheet"], i["cell"]) for i in body["items"]}
    assert not {tuple(s.split("!")) for s in steps} & listed  # not counted as warnings
    page = g["ops"].get(url, params={"limit": 25, "offset": 25})
    assert page.status_code == 200 and len(page.json()["items"]) == 14
    assert page.json()["count"] == 39
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        assert Staff(g["users"][role].email).get(url).status_code == 403
    assert TestClient(app).get(f"{API}{url}").status_code == 401
    assert g["admin"].get(f"/tariffs/versions/{g['version'] + 999}/warnings").status_code == 404
    # The screen shows the tab for tariff:read, the same permission as the route.
    page_src = (REPO / "frontend/src/features/settings/SettingsPage.jsx").read_text("utf-8")
    assert "can(P.TARIFF_READ) ? [{ id: 'tariff-browser'" in page_src


# === 7. Wording ===================================================================================


def test_customer_quote_tax_wording_and_staff_note():
    """ "Tổng cộng" and the staff note label are kept; the tax note follows the invoice rule
    since RC-UAT-21 (P-9 stand-in, pending Ben) -- AS-39 in SUPERSEDED_ASSERTIONS.md."""
    vi = (REPO / "frontend/src/account/i18n/vi.js").read_text(encoding="utf-8")
    assert "'quotes.colTotal': 'Tổng cộng'," in vi
    assert "'quotes.taxIncluded': 'Giá đã bao gồm {label} {rate} %'," in vi
    assert "'detail.staffNote': 'Ghi chú từ Solaris Express'," in vi
    page = (REPO / "frontend/src/account/pages/QuoteDetailPage.jsx").read_text(encoding="utf-8")
    assert "t('quotes.colTotal')" in page and "quoteTaxSentence(t, data.tax)" in page
    detail = (REPO / "frontend/src/account/pages/ShipmentDetailPage.jsx").read_text("utf-8")
    assert "t('detail.staffNote')" in detail
