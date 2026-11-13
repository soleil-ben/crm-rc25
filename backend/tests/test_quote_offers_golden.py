"""Phase 13G golden tests (independent tester): customer quote acceptance, black box over HTTP.

OD-77 (D-08): staff send the finalised quote; the linked customer accepts or declines it in
the Customer Account. Pricing world (tariff, exchange rate, consolidation) is seeded through
services as in the other pricing suites; everything under test -- items, fee lines,
re-pricing, finalising, sending, withdrawing, reading and answering -- goes through the
staff and account HTTP routes. Every account response body is collected and deep-scanned
for anything cost-derived or internal.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.enums import ConsentChannel, Role, RouteGroup
from app.core.time_utils import utcnow
from app.main import app
from app.models import AuditEvent, Customer, ShipmentPackage
from app.services import consent_service, fx_service
from app.services import consolidation_service as cs
from app.services import tariff_import_service as tis
from tests.account_fixtures import csrf_headers, sign_in
from tests.approval_fixtures import pending_identity
from tests.conftest import booked_shipment, make_customer, see_committed_changes
from tests.test_account_profile import APPLICANT, _activate
from tests.test_fx_service import SAMPLE_XML
from tests.test_quotes import WORKBOOK

ACCOUNT = "/api/v1/account"
STAFF_PASSWORD = "TestPassword!2026"
OVERRIDE_RATE = Decimal("19.50")
OVERRIDE_REASON = "Loyalty-SENTINEL special price"
NEG_MARGIN_REASON = "Promo-SENTINEL accepted loss"
WITHDRAW_REASON = "STAFF-SECRET-SENTINEL wrong weight keyed"

#: Substrings that must never appear (case-insensitive) in anything the customer reads.
FORBIDDEN = (
    "cost",
    "vendor",
    "markup",
    "margin",
    "fx",
    "cash_buy",
    "sell_vnd",
    "tariff",
    "air-cad",
    "kango",
    "override",
    "negative_margin",
    "sentinel",
    "loyalty",
    "promo",
    "staff-secret",
    "email_status",
    "withdrawn_reason",
)


# --- Helpers ---------------------------------------------------------------------------------


class Staff:
    """A staff caller on its own TestClient (same app and overrides, its own cookie jar)."""

    def __init__(self, email: str) -> None:
        self.client = TestClient(app)
        response = self.client.post(
            "/api/v1/auth/login", json={"email": email, "password": STAFF_PASSWORD}
        )
        assert response.status_code == 200, response.text
        self.headers = {settings.csrf_header_name: response.json()["csrf_token"]}

    def get(self, url: str):
        return self.client.get(f"/api/v1{url}")

    def post(self, url: str, body=None):
        return self.client.post(f"/api/v1{url}", json=body, headers=self.headers)


class Me:
    """The signed-in customer. Every response is kept for the deep scan."""

    def __init__(self, client: TestClient, email: str = APPLICANT) -> None:
        client.cookies.clear()
        response = sign_in(client, email)
        assert response.status_code == 200, response.text
        self.client = client
        self.headers = csrf_headers(response)
        self.responses: list = []

    def get(self, path: str):
        response = self.client.get(f"{ACCOUNT}{path}")
        self.responses.append(response)
        return response

    def post(self, path: str, body=None, headers=None):
        response = self.client.post(
            f"{ACCOUNT}{path}",
            json=body,
            headers=self.headers if headers is None else headers,
        )
        self.responses.append(response)
        return response


def _walk(value, path="$"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield f"{path}.{key}#key", str(key)
            yield from _walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from _walk(child, f"{path}[{i}]")
    elif value is not None:
        yield path, str(value)


def deep_scan(responses, extra=(), skip_values=()):
    """Every key and string value of every JSON response: no forbidden substring.

    ``skip_values`` are exact values that are random identifiers (a shipment reference made
    of random letters could spell ``FX``); they are skipped only for the substring words, not
    for the ``extra`` sentinels.
    """
    scanned = 0
    for response in responses:
        try:
            body = response.json()
        except ValueError:
            body = response.text
        for where, text in _walk(body):
            scanned += 1
            lowered = text.lower()
            if text not in skip_values:
                for word in FORBIDDEN:
                    assert word not in lowered, (word, where, text, response.request.url)
            for needle in extra:
                assert needle not in text, (needle, where, text, response.request.url)
    assert scanned


def _world(db, owner: Customer):
    """Active tariff + live FX; three VCA children (3/6/12 kg) on one 21 kg HCM master.
    The 12 kg shipment belongs to ``owner``; the 3 and 6 kg ones to two other customers
    (no language set: Vietnamese)."""
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
    kids = []
    for i, kg in enumerate((3, 6, 12)):
        customer = owner if kg == 12 else make_customer(db, email=f"golden{i}@demo.example.com")
        shipment = booked_shipment(db, customer, RouteGroup.VCA)
        for package in db.query(ShipmentPackage).filter_by(shipment_id=shipment.id):
            package.weight_kg = Decimal(kg)
            package.weight_value = Decimal(kg)
            package.length_cm = package.width_cm = package.height_cm = None
        kids.append(shipment)
    db.commit()
    con = cs.create_consolidation(
        db,
        {
            "solaris_service": "air_standard",
            "origin": "HCM",
            "vendor_reference": "AAAAA",
            "actual_weight_kg": "21",
        },
        actor=None,
    )
    for shipment in kids:
        cs.add_member(db, con, shipment, actor=None)
    db.commit()
    return [(s.id, s.public_id, s.customer_id) for s in kids]


def _add_fee(ops: Staff, shipment_id: int, quantity: int = 1) -> None:
    item = ops.post(f"/shipments/{shipment_id}/items", {"description": "Watch"})
    assert item.status_code == 201, item.text
    fee = ops.post(
        f"/shipments/{shipment_id}/fee-lines",
        {"item_id": item.json()["id"], "section": "hcm_air", "stt": 18, "quantity": quantity},
    )
    assert fee.status_code == 201, fee.text


def _finalize(ops: Staff, shipment_id: int, rate: Decimal | None = None, reason=None) -> dict:
    draft = ops.post(f"/shipments/{shipment_id}/quotes")
    assert draft.status_code == 201, draft.text
    body = {"rate": str(rate), "reason": reason} if rate is not None else {}
    confirmed = ops.post(f"/shipments/{shipment_id}/quotes/confirm-rate", body)
    assert confirmed.status_code == 200, confirmed.text
    final = ops.post(
        f"/shipments/{shipment_id}/quotes/finalize", {"negative_margin_reason": NEG_MARGIN_REASON}
    )
    assert final.status_code == 200, final.text
    assert final.json()["status"] == "finalized"
    return final.json()


def _send(ops: Staff, shipment_id: int) -> dict:
    sent = ops.post(f"/shipments/{shipment_id}/quotes/send")
    assert sent.status_code == 201, sent.text
    return sent.json()


def _cost_amounts(version: dict) -> set[str]:
    """The cost-side figures of a staff quote version, as the strings they would print as."""
    out = set()
    for line in version["lines"]:
        for key in ("cost_vnd", "cost_cad"):
            if line.get(key) not in (None, "0", "0.00", 0):
                value = Decimal(str(line[key]))
                if value > 100:  # small numbers coincide with weights and rates by chance
                    out.add(str(value.normalize()) if value == value.to_integral() else str(value))
                    out.add(str(int(value)) if value == value.to_integral() else str(value))
    for key in ("allocated_cost_cad", "gross_profit_cad"):
        if version.get(key) is not None and abs(Decimal(str(version[key]))) > 100:
            out.add(str(Decimal(str(version[key]))))
    return out


@pytest.fixture
def golden(account_client, account_db, account_users, captured_mail):
    """An approved, linked customer (English, from the registration body) and the world."""
    _activate(account_client, account_users, captured_mail)
    see_committed_changes(account_db)
    owner = account_db.query(Customer).filter_by(email_normalized=APPLICANT).one()
    kids = _world(account_db, owner)
    ops = Staff(account_users[Role.OPERATIONS].email)
    me = Me(account_client)
    return {
        "db": account_db,
        "kids": kids,
        "ops": ops,
        "me": me,
        "mail": captured_mail,
        "users": account_users,
        "client": account_client,
    }


def _refs(g) -> tuple[str, ...]:
    return tuple(public_id for _id, public_id, _c in g["kids"])


# --- Happy path ------------------------------------------------------------------------------


def test_happy_path_totals_match_the_finalised_quote_and_are_customer_safe(golden):
    g = golden
    ops, me, db = g["ops"], g["me"], g["db"]
    ship_id, reference, _cust = g["kids"][2]
    _add_fee(ops, ship_id, quantity=2)
    version = _finalize(ops, ship_id, rate=OVERRIDE_RATE, reason=OVERRIDE_REASON)

    # Hand-check the finalised quote itself: base = billable kg x selling rate.
    assert Decimal(version["billable_weight_kg"]) == Decimal("12")
    assert Decimal(version["selling_rate_cad"]) == OVERRIDE_RATE
    expected_base = (Decimal("12") * OVERRIDE_RATE).quantize(Decimal("0.01"), ROUND_HALF_UP)
    assert expected_base == Decimal("234.00")
    base_lines = [x for x in version["lines"] if x["kind"] == "base_freight"]
    assert len(base_lines) == 1 and Decimal(base_lines[0]["revenue_cad"]) == expected_base
    paid_surcharges = [
        (x["description"], Decimal(x["revenue_cad"]).quantize(Decimal("0.01")))
        for x in version["lines"]
        if x["kind"] == "surcharge" and Decimal(x["revenue_cad"]) > 0
    ]
    assert paid_surcharges, "the hcm_air/18 fee line should give a surcharge the customer pays"
    expected_total = expected_base + sum(amount for _n, amount in paid_surcharges)
    assert Decimal(version["total_revenue_cad"]) == expected_total

    sent = _send(ops, ship_id)
    assert sent["status"] == "sent" and sent["is_current"] is True
    assert sent["email_status"] == "sent"  # capture transport installed

    listed = me.get("/quotes")
    assert listed.status_code == 200, listed.text
    assert listed.headers["Cache-Control"].startswith("no-store")
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == sent["id"] and items[0]["shipment_reference"] == reference
    assert items[0]["total_cad"] == f"{expected_total:.2f}" and items[0]["currency"] == "CAD"

    detail = me.get(f"/quotes/{sent['id']}")
    assert detail.status_code == 200, detail.text
    d = detail.json()
    assert d["service"] == "Air Standard" and d["version"] == 1 and d["status"] == "sent"
    assert d["billable_weight_kg"] == "12.000"
    assert d["rate_per_kg_cad"] == "19.50"
    assert d["base_charge_cad"] == "234.00"
    assert [(s["name"], Decimal(s["amount_cad"])) for s in d["surcharges"]] == paid_surcharges
    assert d["total_cad"] == f"{expected_total:.2f}"
    assert Decimal(d["base_charge_cad"]) + sum(
        Decimal(s["amount_cad"]) for s in d["surcharges"]
    ) == Decimal(d["total_cad"])
    assert d["tax_included"] is False and d["can_answer"] is True
    assert set(d) == {
        "id",
        "shipment_reference",
        "version",
        "service",
        "status",
        "sent_at",
        "total_cad",
        "currency",
        "billable_weight_kg",
        "rate_per_kg_cad",
        "base_charge_cad",
        "surcharges",
        "tax_included",
        "responded_at",
        "decline_reason",
        "can_answer",
        # 13G review fix: why an offer cannot be answered, as a customer-safe code.
        "closed_reason",
        # RC-UAT-21 (P-9 stand-in): the GST/HST wording -- AS-40 in SUPERSEDED_ASSERTIONS.md.
        "tax",
    }

    accepted = me.post(f"/quotes/{sent['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    a = accepted.json()
    assert a["status"] == "accepted" and a["can_answer"] is False and a["responded_at"]
    assert a["total_cad"] == d["total_cad"]

    # Staff see the answer.
    offers = ops.get(f"/shipments/{ship_id}/quote-offers").json()
    assert offers[0]["status"] == "accepted" and offers[0]["responded_by"].startswith("CA-")

    # Accepting does not change the quote (still finalised, same total).
    quotes = ops.get(f"/shipments/{ship_id}/quotes").json()
    assert [q["status"] for q in quotes if q["version"] == 1] == ["finalized"]

    me.get("/quotes")
    me.get(f"/quotes/{sent['id']}")
    costs = _cost_amounts(version)
    assert costs, "the fee line should carry a vendor cost to look for"
    deep_scan(
        me.responses,
        extra=tuple(costs) + (OVERRIDE_REASON, NEG_MARGIN_REASON),
        skip_values=_refs(g),
    )
    see_committed_changes(db)


# --- Decline ---------------------------------------------------------------------------------


def test_decline_with_and_without_reason(golden):
    g = golden
    ops, me = g["ops"], g["me"]
    ship_id, _ref, _c = g["kids"][2]
    _finalize(ops, ship_id)
    first = _send(ops, ship_id)
    declined = me.post(f"/quotes/{first['id']}/decline", {"reason": "  Too   expensive  "})
    assert declined.status_code == 200, declined.text
    assert declined.json()["status"] == "declined"
    assert declined.json()["decline_reason"] == "Too expensive"
    assert declined.json()["can_answer"] is False
    assert me.post(f"/quotes/{first['id']}/accept").status_code == 409
    assert me.post(f"/quotes/{first['id']}/decline", {}).status_code == 409

    staff_view = ops.get(f"/shipments/{ship_id}/quote-offers").json()
    assert staff_view[0]["status"] == "declined"
    assert staff_view[0]["decline_reason"] == "Too expensive"

    # A new version; decline without a body at all, then (on a third) with an empty body.
    _add_fee(ops, ship_id)
    _finalize(ops, ship_id)
    second = _send(ops, ship_id)
    plain = me.client.post(f"{ACCOUNT}/quotes/{second['id']}/decline", headers=me.headers)
    me.responses.append(plain)
    assert plain.status_code == 200, plain.text
    assert plain.json()["status"] == "declined" and plain.json()["decline_reason"] is None

    _add_fee(ops, ship_id)
    _finalize(ops, ship_id)
    third = _send(ops, ship_id)
    empty = me.post(f"/quotes/{third['id']}/decline", {"reason": "   "})
    assert empty.status_code == 200, empty.text
    assert empty.json()["decline_reason"] is None
    deep_scan(me.responses, extra=(NEG_MARGIN_REASON,), skip_values=_refs(g))


# --- Withdraw and re-finalise ----------------------------------------------------------------


def test_staff_withdraw_then_accept_is_refused_and_the_reason_is_hidden(golden):
    g = golden
    ops, me = g["ops"], g["me"]
    ship_id, _ref, _c = g["kids"][2]
    _finalize(ops, ship_id)
    offer = _send(ops, ship_id)
    withdrawn = ops.post(f"/quote-offers/{offer['id']}/withdraw", {"reason": WITHDRAW_REASON})
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["status"] == "withdrawn"

    refused = me.post(f"/quotes/{offer['id']}/accept")
    assert refused.status_code == 409, refused.text
    assert me.post(f"/quotes/{offer['id']}/decline", {"reason": "x"}).status_code == 409
    detail = me.get(f"/quotes/{offer['id']}")
    assert detail.json()["status"] == "withdrawn" and detail.json()["can_answer"] is False
    me.get("/quotes")
    # The same version cannot simply be re-sent.
    assert ops.post(f"/shipments/{ship_id}/quotes/send").status_code == 409
    deep_scan(me.responses, extra=(WITHDRAW_REASON, "wrong weight"), skip_values=_refs(g))


def test_refinalising_withdraws_the_old_offer_and_the_new_one_can_be_sent(golden):
    g = golden
    ops, me = g["ops"], g["me"]
    ship_id, _ref, _c = g["kids"][2]
    _finalize(ops, ship_id)
    old = _send(ops, ship_id)
    _add_fee(ops, ship_id)
    v2 = _finalize(ops, ship_id)
    assert v2["version"] == 2

    staff_old = ops.get(f"/shipments/{ship_id}/quote-offers").json()
    assert [(o["id"], o["status"], o["is_current"]) for o in staff_old] == [
        (old["id"], "withdrawn", False)
    ]
    assert staff_old[0]["withdrawn_reason"] == "superseded by v2"

    old_detail = me.get(f"/quotes/{old['id']}")
    assert old_detail.json()["status"] == "withdrawn" and old_detail.json()["can_answer"] is False
    assert me.post(f"/quotes/{old['id']}/accept").status_code == 409

    new = _send(ops, ship_id)
    assert new["version"] == 2 and new["status"] == "sent" and new["is_current"] is True
    listed = me.get("/quotes").json()["items"]
    assert [(i["id"], i["status"], i["version"]) for i in listed] == [
        (new["id"], "sent", 2),
        (old["id"], "withdrawn", 1),
    ]
    assert Decimal(listed[0]["total_cad"]) == Decimal(str(v2["total_revenue_cad"]))
    ok = me.post(f"/quotes/{new['id']}/accept")
    assert ok.status_code == 200, ok.text
    # The old one stays refused even after the new one is answered.
    assert me.post(f"/quotes/{old['id']}/accept").status_code == 409
    deep_scan(me.responses, extra=("superseded",), skip_values=_refs(g))


def test_an_open_draft_after_finalising_blocks_sending(golden):
    g = golden
    ops = g["ops"]
    ship_id, _ref, _c = g["kids"][2]
    assert ops.post(f"/shipments/{ship_id}/quotes/send").status_code == 409  # nothing final
    _finalize(ops, ship_id)
    assert ops.post(f"/shipments/{ship_id}/quotes").status_code == 201  # a new draft
    assert ops.post(f"/shipments/{ship_id}/quotes/send").status_code == 409


# --- Second answer, ownership, sign-in -------------------------------------------------------


def test_a_second_accept_is_a_conflict(golden):
    g = golden
    ops, me = g["ops"], g["me"]
    ship_id, _ref, _c = g["kids"][2]
    _finalize(ops, ship_id)
    offer = _send(ops, ship_id)
    assert me.post(f"/quotes/{offer['id']}/accept").status_code == 200
    again = me.post(f"/quotes/{offer['id']}/accept")
    assert again.status_code == 409, again.text
    assert me.post(f"/quotes/{offer['id']}/decline").status_code == 409
    assert me.get(f"/quotes/{offer['id']}").json()["status"] == "accepted"
    deep_scan(me.responses, skip_values=_refs(g))


def test_another_customers_offer_is_404_on_read_accept_and_decline(golden):
    g = golden
    ops, me = g["ops"], g["me"]
    their_id, _ref, _c = g["kids"][0]
    _finalize(ops, their_id)
    theirs = _send(ops, their_id)
    unknown = me.get("/quotes/987654")
    assert unknown.status_code == 404
    for call in (
        lambda: me.get(f"/quotes/{theirs['id']}"),
        lambda: me.post(f"/quotes/{theirs['id']}/accept"),
        lambda: me.post(f"/quotes/{theirs['id']}/decline", {"reason": "no"}),
    ):
        response = call()
        assert response.status_code == 404, response.text
        assert response.json() == unknown.json()
    assert me.get("/quotes").json()["items"] == []
    # Untouched for its owner.
    assert ops.get(f"/shipments/{their_id}/quote-offers").json()[0]["status"] == "sent"


def test_unlinked_and_signed_out_are_refused(golden):
    g = golden
    ops, me, client, mail = g["ops"], g["me"], g["client"], g["mail"]
    ship_id, _ref, _c = g["kids"][2]
    _finalize(ops, ship_id)
    offer = _send(ops, ship_id)

    # Signed out: the old CSRF header and no session.
    out = me.post("/sign-out")
    assert out.status_code in (200, 204), out.text
    assert client.get(f"{ACCOUNT}/quotes").status_code == 401
    assert client.get(f"{ACCOUNT}/quotes/{offer['id']}").status_code == 401
    assert client.post(
        f"{ACCOUNT}/quotes/{offer['id']}/accept", headers=me.headers
    ).status_code in (
        401,
        403,
    )

    # Unlinked (verified, pending approval).
    pending_identity(client, mail, "golden.pending@demo.example.com")
    client.cookies.clear()
    signed = sign_in(client, "golden.pending@demo.example.com")
    assert signed.status_code == 200, signed.text
    assert client.get(f"{ACCOUNT}/quotes").status_code == 403
    assert client.get(f"{ACCOUNT}/quotes/{offer['id']}").status_code == 403
    for action in ("accept", "decline"):
        refused = client.post(
            f"{ACCOUNT}/quotes/{offer['id']}/{action}", headers=csrf_headers(signed)
        )
        assert refused.status_code == 403, refused.text
    assert ops.get(f"/shipments/{ship_id}/quote-offers").json()[0]["status"] == "sent"


def test_csrf_is_required_like_other_account_posts(golden):
    g = golden
    ops, me = g["ops"], g["me"]
    ship_id, _ref, _c = g["kids"][2]
    _finalize(ops, ship_id)
    offer = _send(ops, ship_id)
    bad_headers = (
        {},
        {settings.account_csrf_header_name: "not-the-token"},
        # The staff header name on an account route authenticates nothing.
        {settings.csrf_header_name: next(iter(me.headers.values()))},
    )
    for headers in bad_headers:
        for action in ("accept", "decline"):
            response = me.client.post(f"{ACCOUNT}/quotes/{offer['id']}/{action}", headers=headers)
            assert response.status_code == 403, (headers, action, response.text)
    # Compare: another account POST (sign-out) is refused the same way without CSRF.
    assert me.client.post(f"{ACCOUNT}/sign-out").status_code == 403
    assert ops.get(f"/shipments/{ship_id}/quote-offers").json()[0]["status"] == "sent"
    assert me.post(f"/quotes/{offer['id']}/accept").status_code == 200


# --- Staff permissions -----------------------------------------------------------------------


def test_marketing_and_read_only_manager_cannot_send_or_withdraw(golden):
    g = golden
    ops = g["ops"]
    ship_id, _ref, _c = g["kids"][2]
    _finalize(ops, ship_id)
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        other = Staff(g["users"][role].email)
        assert other.post(f"/shipments/{ship_id}/quotes/send").status_code == 403
    offer = _send(ops, ship_id)
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        other = Staff(g["users"][role].email)
        response = other.post(f"/quote-offers/{offer['id']}/withdraw", {"reason": "x"})
        assert response.status_code == 403, response.text
    assert ops.get(f"/shipments/{ship_id}/quote-offers").json()[0]["status"] == "sent"
    admin = Staff(g["users"][Role.ADMIN].email)
    assert (
        admin.post(f"/quote-offers/{offer['id']}/withdraw", {"reason": "admin"}).status_code == 200
    )


# --- Audit -----------------------------------------------------------------------------------


def test_audit_events_are_recorded_without_cost_amounts(golden):
    g = golden
    ops, me, db = g["ops"], g["me"], g["db"]
    ship_id, _ref, _c = g["kids"][2]
    _add_fee(ops, ship_id)
    v1 = _finalize(ops, ship_id)
    first = _send(ops, ship_id)
    assert me.post(f"/quotes/{first['id']}/decline", {"reason": "Pricey"}).status_code == 200
    _add_fee(ops, ship_id)
    v2 = _finalize(ops, ship_id)
    second = _send(ops, ship_id)
    assert me.post(f"/quotes/{second['id']}/accept").status_code == 200

    see_committed_changes(db)
    events = {
        action: db.query(AuditEvent).filter_by(action=action, entity_type="quote_offer").all()
        for action in ("quote.sent", "quote.accepted", "quote.declined")
    }
    assert {a: sorted(int(e.entity_id) for e in rows) for a, rows in events.items()} == {
        "quote.sent": sorted([first["id"], second["id"]]),
        "quote.accepted": [second["id"]],
        "quote.declined": [first["id"]],
    }
    assert events["quote.accepted"][0].actor_label.startswith("customer_account:CA-")
    assert json.loads(events["quote.declined"][0].detail_json)["decline_reason"] == "Pricey"
    costs = _cost_amounts(v1) | _cost_amounts(v2)
    for rows in events.values():
        for event in rows:
            text = f"{event.summary} {event.detail_json}"
            for word in ("cost", "markup", "margin", "fx_", "vendor", "tariff"):
                assert word not in text.lower(), (event.action, word, text)
            for amount in costs:
                assert amount not in text, (event.action, amount, text)


# --- Email -----------------------------------------------------------------------------------


def _quote_mails(mail):
    return [m for m in mail.messages if m["template_key"].startswith("quote.sent")]


def test_email_vietnamese_by_default_english_for_english_sent_even_when_suppressed(golden):
    g = golden
    ops, db, mail = g["ops"], g["db"], g["mail"]
    (vi_id, vi_ref, vi_cust), (sup_id, _sr, sup_cust), (en_id, en_ref, _en) = g["kids"]
    see_committed_changes(db)
    customer = db.get(Customer, sup_cust)
    suppressed_address = customer.email_normalized
    consent_service.add_suppression(
        db,
        channel=ConsentChannel.EMAIL,
        address_value=suppressed_address,
        reason="Customer asked",
        actor=None,
    )
    db.commit()

    v_vi = _finalize(ops, vi_id)
    sent_vi = _send(ops, vi_id)
    assert sent_vi["email_status"] == "sent"
    vi_mail = _quote_mails(mail)[-1]
    assert vi_mail["template_key"] == "quote.sent.vi" and vi_mail["language"] == "vi"
    assert vi_mail["to_email"] == "golden0@demo.example.com"
    assert vi_ref in vi_mail["subject"] + vi_mail["body"]
    assert "/account/quotes" in vi_mail["body"]

    _add_fee(ops, en_id)
    v_en = _finalize(ops, en_id)
    sent_en = _send(ops, en_id)
    assert sent_en["email_status"] == "sent"
    en_mail = _quote_mails(mail)[-1]
    assert en_mail["template_key"] == "quote.sent.en" and en_mail["language"] == "en"
    assert en_mail["to_email"].lower() == APPLICANT
    assert en_ref in en_mail["subject"] + en_mail["body"]

    # No amount in either email.
    for message, version in ((vi_mail, v_vi), (en_mail, v_en)):
        text = message["subject"] + "\n" + message["body"]
        assert "CAD" not in text and "$" not in text
        for key in ("total_revenue_cad", "base_revenue_cad", "selling_rate_cad"):
            figure = Decimal(str(version[key]))
            assert f"{figure:.2f}" not in text, (key, figure)
            assert f"{figure:,.2f}" not in text, (key, figure)
        for amount in _cost_amounts(version):
            assert amount not in text
        for word in ("cost", "markup", "margin", "vendor", "tariff", "kango"):
            assert word not in text.lower()

    # A suppressed address still gets the quote: operational email, suppression blocks
    # marketing only (DEC-0143; owner decision of 2026-10-20 review).
    before = len(_quote_mails(mail))
    _finalize(ops, sup_id)
    sent_sup = _send(ops, sup_id)
    assert sent_sup["status"] == "sent" and sent_sup["email_status"] == "sent"
    assert len(_quote_mails(mail)) == before + 1
    assert any(m["to_email"] == suppressed_address for m in _quote_mails(mail))
    assert vi_cust != sup_cust
