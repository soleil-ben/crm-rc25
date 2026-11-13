"""Phase 13G: staff send a finalised quote; the customer accepts or declines it (OD-77, D-08).

Covers sending (only the latest finalised version, once), withdrawal by staff and by a newer
finalised version, the customer's answer (once, only on a current offer, only their own),
permissions, the quote-sent email (Vietnamese first, English for an English customer, never
to a suppressed address, as operational email, DEC-0143), no cost leakage on any account route, and the migration.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from app.core.enums import ConsentChannel, Role, RouteGroup
from app.core.time_utils import utcnow
from app.models import AuditEvent, Customer, QuoteOffer, ShipmentPackage
from app.services import consent_service, fx_service
from app.services import consolidation_service as cs
from app.services import pricing_service as ps
from app.services import quote_offer_service as qos
from app.services import shipment_item_service as items
from app.services import tariff_import_service as tis
from app.services.errors import ConflictError, NotFoundError, ValidationError
from tests.conftest import booked_shipment, make_customer, see_committed_changes
from tests.test_fx_service import SAMPLE_XML
from tests.test_migrations_phase13c import _alembic, _tables
from tests.test_quotes import WORKBOOK, priced_world  # noqa: F401 - fixture

#: Words that must never appear in anything a customer reads (vendor cost, FX, markup,
#: margin, tariff and vendor product codes, the vendor's name).
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
)


def _fee(db, shipment, section="hcm_air", stt=18, **extra):
    item = items.add_item(
        db, shipment, {"description": extra.pop("description", "Watch")}, actor=None
    )
    ps.add_fee_line(
        db, shipment, {"item_id": item.id, "section": section, "stt": stt, **extra}, actor=None
    )
    db.commit()


def _finalize(db, shipment):
    ps.reprice(db, shipment, actor=None)
    ps.confirm_rate(db, shipment, rate=None, reason=None, actor=None)
    version = ps.finalize(db, shipment, negative_margin_reason="test", actor=None)
    db.commit()
    return version


def _send(db, shipment):
    offer = qos.send_quote(db, shipment, actor=None)
    db.commit()
    return offer


def _assert_customer_safe(text: str) -> None:
    lowered = text.lower()
    for word in FORBIDDEN:
        assert word not in lowered, word


# --- Sending -------------------------------------------------------------------------------------


def test_only_the_latest_finalised_version_is_sent_once(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[2]
    with pytest.raises(ConflictError, match="finalised"):
        qos.send_quote(db, shipment, actor=None)
    db.rollback()
    _fee(db, shipment, quantity=1)
    version = _finalize(db, shipment)
    offer = _send(db, shipment)
    assert (offer.status, offer.quote_version_id, offer.customer_id) == (
        "sent",
        version.id,
        shipment.customer_id,
    )
    view = qos.customer_view(offer)
    assert view["service"] == "Air Standard" and view["currency"] == "CAD"
    # Method v0.5 (DEC-0252): CAD 19/kg under 21 kg of the customer's own weight.
    assert view["rate_per_kg_cad"] == "19.00" and view["billable_weight_kg"] == "12.000"
    assert view["base_charge_cad"] == "228.00"
    assert [s["name"] for s in view["surcharges"]] and all(
        Decimal(s["amount_cad"]) > 0 for s in view["surcharges"]
    )
    total = Decimal(view["base_charge_cad"]) + sum(
        Decimal(s["amount_cad"]) for s in view["surcharges"]
    )
    assert Decimal(view["total_cad"]) == total == version.total_revenue_cad
    _assert_customer_safe(offer.customer_view_json)
    assert db.query(AuditEvent).filter_by(action="quote.sent", entity_id=str(offer.id)).count() == 1

    with pytest.raises(ConflictError, match="already been sent"):
        qos.send_quote(db, shipment, actor=None)
    db.rollback()
    # An open draft after the finalised version: staff are re-pricing; finalise first.
    ps.reprice(db, shipment, actor=None)
    db.commit()
    with pytest.raises(ConflictError, match="finalised"):
        qos.send_quote(db, shipment, actor=None)
    db.rollback()


def test_a_shipment_without_a_customer_cannot_be_sent(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    _finalize(db, kids[0])
    kids[0].customer_id = None
    with pytest.raises(ConflictError, match="no customer"):
        qos.send_quote(db, kids[0], actor=None)
    db.rollback()


def test_a_newer_finalised_version_withdraws_the_sent_offer(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[2]
    _finalize(db, shipment)
    first = _send(db, shipment)
    _fee(db, shipment, quantity=1)
    second_version = _finalize(db, shipment)
    db.refresh(first)
    assert first.status == "withdrawn" and first.withdrawn_reason == "superseded by v2"
    assert not qos.is_current(db, first)
    second = _send(db, shipment)
    assert second.status == "sent" and second.quote_version_id == second_version.id
    assert qos.version_number(second) == 2
    # Two sent offers for one shipment are refused by the partial unique index.
    first.status = "sent"
    with pytest.raises(Exception, match="UNIQUE"):
        db.flush()
    db.rollback()


def test_an_offer_whose_version_is_no_longer_latest_cannot_be_accepted(db, priced_world):  # noqa: F811
    """Belt and braces: even if a sent offer survived a re-finalisation, it is refused."""
    _con, kids = priced_world
    shipment = kids[1]
    customer = db.get(Customer, shipment.customer_id)
    identity = _identity_for(db, customer)
    _finalize(db, shipment)
    offer = _send(db, shipment)
    _fee(db, shipment, quantity=1)
    _finalize(db, shipment)
    db.refresh(offer)
    offer.status = "sent"  # as if the finalise hook had not run
    offer.withdrawn_reason = None
    db.commit()
    with pytest.raises(ConflictError, match="replaced"):
        qos.accept(db, offer, identity)
    db.rollback()


def test_staff_withdraw_needs_a_reason_and_only_a_sent_offer(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    _finalize(db, kids[0])
    offer = _send(db, kids[0])
    with pytest.raises(ValidationError):
        qos.withdraw(db, offer, reason="  ", actor=None)
    qos.withdraw(db, offer, reason="Customer called: wrong weight", actor=None)
    db.commit()
    assert offer.status == "withdrawn" and offer.withdrawn_at is not None
    with pytest.raises(ConflictError):
        qos.withdraw(db, offer, reason="again", actor=None)
    db.rollback()
    assert db.query(AuditEvent).filter_by(action="quote.withdrawn").count() == 1


# --- Email ---------------------------------------------------------------------------------------


def test_the_quote_email_is_vietnamese_by_default_and_carries_no_amount(
    db,
    priced_world,  # noqa: F811
    captured_mail,
):
    _con, kids = priced_world
    _finalize(db, kids[2])
    offer = _send(db, kids[2])
    assert qos.send_email(db, offer.id) == "sent"
    db.refresh(offer)
    assert offer.email_status == "sent"
    message = captured_mail.messages[-1]
    assert message["template_key"] == "quote.sent.vi" and message["language"] == "vi"
    assert kids[2].public_id in message["subject"] and "/account/quotes" in message["body"]
    assert "216" not in message["body"] and "CAD" not in message["body"]
    assert message["to_email"] == "c2@demo.example.com"


def test_an_english_customer_gets_english(db, priced_world, captured_mail):  # noqa: F811
    _con, kids = priced_world
    customer = db.get(Customer, kids[1].customer_id)
    customer.preferred_language = "en"
    db.commit()
    _finalize(db, kids[1])
    offer = _send(db, kids[1])
    qos.send_email(db, offer.id)
    message = captured_mail.messages[-1]
    assert message["template_key"] == "quote.sent.en"
    assert message["subject"].startswith("Your Solaris Express quote")


def test_a_suppressed_address_still_gets_the_quote_email(db, priced_world, captured_mail):  # noqa: F811
    """A quote is operational email; a suppression blocks marketing only (DEC-0143)."""
    _con, kids = priced_world
    consent_service.add_suppression(
        db,
        channel=ConsentChannel.EMAIL,
        address_value="c0@demo.example.com",
        reason="Customer asked",
        actor=None,
    )
    db.commit()
    _finalize(db, kids[0])
    offer = _send(db, kids[0])
    assert qos.send_email(db, offer.id) == "sent"
    db.refresh(offer)
    assert offer.email_status == "sent" and offer.status == "sent"
    assert [m["to_email"] for m in captured_mail.messages] == ["c0@demo.example.com"]


def test_a_transport_fault_is_recorded_and_the_offer_stands(db, priced_world):  # noqa: F811
    from app.services import account_email_service

    class Broken:
        name = "capture"

        def send(self, message):
            raise OSError("disk full")

    _con, kids = priced_world
    _finalize(db, kids[0])
    offer = _send(db, kids[0])
    account_email_service.set_transport(Broken())
    try:
        assert qos.send_email(db, offer.id) == "failed"
    finally:
        account_email_service.reset_transport()
    db.refresh(offer)
    assert (offer.status, offer.email_status) == ("sent", "failed")


# --- Staff HTTP and permissions ------------------------------------------------------------------


def test_staff_send_list_and_withdraw_over_http(api_for, db, priced_world):  # noqa: F811
    _con, kids = priced_world
    _finalize(db, kids[0])
    see_committed_changes(db)
    ops = api_for(Role.OPERATIONS)
    sent = ops.post(f"/api/v1/shipments/{kids[0].id}/quotes/send")
    assert sent.status_code == 201, sent.text
    body = sent.json()
    assert body["status"] == "sent" and body["is_current"] is True
    assert body["email_status"] == "recorded"  # the null transport: nothing is sent
    assert ops.post(f"/api/v1/shipments/{kids[0].id}/quotes/send").status_code == 409
    listed = ops.get(f"/api/v1/shipments/{kids[0].id}/quote-offers")
    assert [o["status"] for o in listed.json()] == ["sent"]

    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        other = api_for(role)
        assert other.post(f"/api/v1/shipments/{kids[0].id}/quotes/send").status_code == 403
        assert (
            other.post(
                f"/api/v1/quote-offers/{body['id']}/withdraw", json={"reason": "x"}
            ).status_code
            == 403
        )
        assert other.get(f"/api/v1/shipments/{kids[0].id}/quote-offers").status_code == 403

    ops = api_for(Role.OPERATIONS)
    assert ops.post(f"/api/v1/quote-offers/{body['id']}/withdraw", json={}).status_code == 422
    withdrawn = ops.post(
        f"/api/v1/quote-offers/{body['id']}/withdraw", json={"reason": "Wrong weight"}
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["status"] == "withdrawn"
    assert withdrawn.json()["withdrawn_reason"] == "Wrong weight"
    assert ops.post("/api/v1/quote-offers/999999/withdraw", json={"reason": "x"}).status_code == 404


# --- Customer Account ----------------------------------------------------------------------------


def _identity_for(db, customer):
    """An identity row for a service-level answer (the route enforces the active link)."""
    from app.models import CustomerIdentity

    identity = CustomerIdentity(
        public_id=f"CA-T{customer.id:05d}",
        email_normalized=f"identity{customer.id}@demo.example.com",
        email_entered=f"identity{customer.id}@demo.example.com",
        password_hash="x",
        status="active",
    )
    db.add(identity)
    db.commit()
    return identity


def _account_world(db, owner):
    """The pricing world of ``priced_world`` in the account database; the 12 kg shipment
    belongs to ``owner`` (the signed-in customer), the others to other customers."""
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
        customer = owner if kg == 12 else make_customer(db, email=f"other{i}@demo.example.com")
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
    return kids


def test_the_customer_reads_accepts_and_cannot_answer_twice(
    account_client, account_db, account_users, captured_mail
):
    from tests.test_account_profile import _customer, _setup

    _reference, me = _setup(account_client, account_users, captured_mail)
    owner = _customer(account_db)
    kids = _account_world(account_db, owner)
    mine, theirs = kids[2], kids[0]
    _fee(account_db, mine, quantity=2)
    _finalize(account_db, mine)
    _finalize(account_db, theirs)
    my_offer, their_offer = _send(account_db, mine), _send(account_db, theirs)
    my_id, their_id = my_offer.id, their_offer.id

    listed = me.get("/quotes")
    assert listed.status_code == 200, listed.text
    assert listed.headers["Cache-Control"].startswith("no-store")
    items_ = listed.json()["items"]
    assert [(i["id"], i["status"], i["shipment_reference"]) for i in items_] == [
        (my_id, "sent", mine.public_id)
    ]
    detail = me.get(f"/quotes/{my_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["can_answer"] is True and body["service"] == "Air Standard"
    assert body["surcharges"] and body["total_cad"] == qos.customer_view(my_offer)["total_cad"]

    # Another customer's offer, an unknown one and a malformed id: the same 404.
    for wrong in (their_id, 999999, "abc", "-1"):
        refused = me.get(f"/quotes/{wrong}")
        assert refused.status_code == 404, (wrong, refused.text)
        assert me.post(f"/quotes/{wrong}/accept").status_code == 404
    assert me.get(f"/quotes/{their_id}").json() == me.get("/quotes/999999").json()

    # CSRF is required on the answer, as on every account POST.
    no_csrf = account_client.post(f"/api/v1/account/quotes/{my_id}/accept")
    assert no_csrf.status_code == 403

    accepted = me.post(f"/quotes/{my_id}/accept")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted" and accepted.json()["can_answer"] is False
    again = me.post(f"/quotes/{my_id}/accept")
    assert again.status_code == 409
    assert me.post(f"/quotes/{my_id}/decline", {"reason": "changed my mind"}).status_code == 409

    see_committed_changes(account_db)
    row = account_db.get(QuoteOffer, my_id)
    assert row.status == "accepted" and row.responded_identity_id is not None
    audit = account_db.query(AuditEvent).filter_by(action="quote.accepted").one()
    assert audit.actor_label.startswith("customer_account:CA-")
    assert json.loads(audit.detail_json)["account"].startswith("CA-")

    # Every account route the customer used: nothing cost-derived.
    for path in ("/quotes", f"/quotes/{my_id}"):
        _assert_customer_safe(me.get(path).text)
    _assert_customer_safe(accepted.text)

    # The staff side sees the answer.
    from tests.approval_fixtures import staff

    ops = staff(account_client, account_users[Role.OPERATIONS].email)
    offers = ops.get(f"/api/v1/shipments/{mine.id}/quote-offers").json()
    assert offers[0]["status"] == "accepted" and offers[0]["responded_by"].startswith("CA-")


def test_the_customer_declines_with_an_optional_reason(
    account_client, account_db, account_users, captured_mail
):
    from tests.test_account_profile import _customer, _setup

    _reference, me = _setup(account_client, account_users, captured_mail)
    owner = _customer(account_db)
    kids = _account_world(account_db, owner)
    mine = kids[2]
    _finalize(account_db, mine)
    offer_id = _send(account_db, mine).id
    assert me.post(f"/quotes/{offer_id}/decline", {"reason": 5}).status_code in (400, 422)
    assert me.post(f"/quotes/{offer_id}/decline", {"other": "x"}).status_code in (400, 422)
    assert me.post(f"/quotes/{offer_id}/decline", {"reason": "x" * 401}).status_code in (400, 422)
    declined = me.post(f"/quotes/{offer_id}/decline", {"reason": "  Too expensive  "})
    assert declined.status_code == 200, declined.text
    assert declined.json()["status"] == "declined"
    assert declined.json()["decline_reason"] == "Too expensive"
    _assert_customer_safe(declined.text)
    assert me.post(f"/quotes/{offer_id}/accept").status_code == 409

    # A second version is sent; declining it without a reason works too.
    _fee(account_db, mine, quantity=1)
    _finalize(account_db, mine)
    second = _send(account_db, mine).id
    plain = me.client.post(f"/api/v1/account/quotes/{second}/decline", headers=me.headers)
    assert plain.status_code == 200, plain.text
    assert plain.json()["decline_reason"] is None


def test_a_withdrawn_or_replaced_offer_cannot_be_accepted_and_hides_the_staff_reason(
    account_client, account_db, account_users, captured_mail
):
    from tests.test_account_profile import _customer, _setup

    _reference, me = _setup(account_client, account_users, captured_mail)
    owner = _customer(account_db)
    kids = _account_world(account_db, owner)
    mine = kids[2]
    _finalize(account_db, mine)
    first = _send(account_db, mine)
    _fee(account_db, mine, quantity=1)
    _finalize(account_db, mine)  # withdraws the first
    refused = me.post(f"/quotes/{first.id}/accept")
    assert refused.status_code == 409
    second = _send(account_db, mine)
    qos.withdraw(account_db, second, reason="INTERNAL-SENTINEL wrong weight", actor=None)
    account_db.commit()
    detail = me.get(f"/quotes/{second.id}")
    assert detail.json()["status"] == "withdrawn" and detail.json()["can_answer"] is False
    assert "INTERNAL-SENTINEL" not in me.get("/quotes").text + detail.text
    assert me.post(f"/quotes/{second.id}/accept").status_code == 409


def test_an_unlinked_account_cannot_read_quotes(account_client, account_users, captured_mail):
    from tests.account_fixtures import csrf_headers, sign_in
    from tests.approval_fixtures import pending_identity

    pending_identity(account_client, captured_mail, "pending.quotes@demo.example.com")
    account_client.cookies.clear()
    signed = sign_in(account_client, "pending.quotes@demo.example.com")
    assert account_client.get("/api/v1/account/quotes").status_code == 403
    assert (
        account_client.post(
            "/api/v1/account/quotes/1/accept", headers=csrf_headers(signed)
        ).status_code
        == 403
    )


# --- Migration -----------------------------------------------------------------------------------

PHASE_13G_REVISION = "b7d2e9a4c1f6"
MARKUP_REVISION = "a3c9e7f1b5d2"


def test_the_migration_only_adds_quote_offers(tmp_path):
    path = tmp_path / "m.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", MARKUP_REVISION).returncode == 0
    before = _tables(path)
    with sqlite3.connect(path) as c:
        schema_before = dict(c.execute("select name, sql from sqlite_master where sql is not null"))
    # 13G's own revision: later phases add their own tables on top (13H).
    assert _alembic(url, "upgrade", PHASE_13G_REVISION).returncode == 0
    assert PHASE_13G_REVISION in _alembic(url, "current").stdout
    assert _tables(path) - before == {"quote_offers"}
    with sqlite3.connect(path) as c:
        schema_after = dict(c.execute("select name, sql from sqlite_master where sql is not null"))
        fks = {r[3]: (r[2], r[6]) for r in c.execute("pragma foreign_key_list(quote_offers)")}
    for name, sql in schema_before.items():
        assert schema_after[name] == sql, name  # nothing existing altered
    assert fks["quote_version_id"] == ("quote_versions", "RESTRICT")
    assert fks["shipment_id"] == ("shipments", "RESTRICT")
    assert fks["customer_id"] == ("customers", "SET NULL")
    assert fks["responded_identity_id"] == ("customer_identities", "SET NULL")
    assert _alembic(url, "upgrade", "head").returncode == 0  # check compares against head
    check = _alembic(url, "check")
    assert check.returncode == 0, check.stdout + check.stderr
    assert _alembic(url, "downgrade", MARKUP_REVISION).returncode == 0
    assert "quote_offers" not in _tables(path)
    assert _alembic(url, "upgrade", "head").returncode == 0


def test_unknown_offer_is_not_found(db):
    with pytest.raises(NotFoundError):
        qos.get(db, 12345)
    with pytest.raises(NotFoundError):
        qos.owned_offer(db, "x", 1)


# --- Independent review, 2026-10-20 --------------------------------------------------------------


def test_an_answer_is_refused_while_staff_have_a_newer_draft_open(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[1]
    identity = _identity_for(db, db.get(Customer, shipment.customer_id))
    _finalize(db, shipment)
    offer = _send(db, shipment)
    ps.reprice(db, shipment, actor=None)  # draft v2 opened by staff
    db.commit()
    assert qos.closed_reason(db, offer) == "updating"
    with pytest.raises(ConflictError, match="updating") as raised:
        qos.accept(db, offer, identity)
    assert raised.value.detail == {"status": "updating"}
    db.rollback()
    with pytest.raises(ConflictError, match="updating"):
        qos.decline(db, offer, identity, reason=None)
    db.rollback()
    db.refresh(offer)
    assert offer.status == "sent"


def test_finalising_after_an_acceptance_is_flagged_for_staff(api_for, db, priced_world):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[2]
    identity = _identity_for(db, db.get(Customer, shipment.customer_id))
    _finalize(db, shipment)
    offer = _send(db, shipment)
    qos.accept(db, offer, identity)
    db.commit()
    _fee(db, shipment, quantity=1)
    _finalize(db, shipment)
    db.refresh(offer)
    assert offer.status == "accepted"  # the customer's answer stands
    assert offer.superseded_by_version == 2 and offer.superseded_at is not None
    audit = db.query(AuditEvent).filter_by(action="quote.accepted_superseded").one()
    assert json.loads(audit.detail_json) == {
        "shipment_id": shipment.id,
        "accepted_version": 1,
        "new_version": 2,
    }
    see_committed_changes(db)
    staff = api_for(Role.OPERATIONS).get(f"/api/v1/shipments/{shipment.id}/quote-offers")
    assert staff.json()[0]["superseded_by_version"] == 2


def test_a_customer_merge_withdraws_sent_offers_and_moves_answered_ones(db, priced_world):  # noqa: F811
    from app.services import customer_service

    _con, kids = priced_world
    shipment = kids[0]
    source = db.get(Customer, shipment.customer_id)
    target = db.get(Customer, kids[1].customer_id)
    identity = _identity_for(db, source)
    _finalize(db, shipment)
    answered = _send(db, shipment)
    qos.accept(db, answered, identity)
    db.commit()
    _fee(db, shipment, quantity=1)
    _finalize(db, shipment)
    waiting = _send(db, shipment)
    customer_service.merge_customers(db, source=source, target=target)
    db.commit()
    db.refresh(answered)
    db.refresh(waiting)
    assert (waiting.status, waiting.withdrawn_code, waiting.withdrawn_reason) == (
        "withdrawn",
        "customer_merged",
        "customer merged",
    )
    assert waiting.customer_id == target.id and answered.customer_id == target.id
    assert answered.status == "accepted"
    assert qos.closed_reason(db, waiting) == "withdrawn"


def test_a_customer_change_withdraws_the_sent_offer(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[0]
    _finalize(db, shipment)
    offer = _send(db, shipment)
    other = kids[1].customer_id
    identity = _identity_for(db, db.get(Customer, shipment.customer_id))
    # Before any hook runs, an answer is refused once the shipment's customer differs.
    shipment.customer_id = other
    db.flush()
    assert qos.closed_reason(db, offer) == "withdrawn"
    with pytest.raises(ConflictError, match="withdrew"):
        qos.accept(db, offer, identity)
    db.rollback()
    shipment.customer_id = other
    qos.withdraw_for_customer_change(db, shipment.id, new_customer_id=other, actor=None)
    db.commit()
    db.refresh(offer)
    assert (offer.status, offer.withdrawn_code, offer.customer_id) == (
        "withdrawn",
        "customer_changed",
        other,
    )
    assert qos.closed_reason(db, offer) == "withdrawn"


def test_closed_reasons_tell_withdrawn_from_replaced(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[2]
    _finalize(db, shipment)
    first = _send(db, shipment)
    _fee(db, shipment, quantity=1)
    _finalize(db, shipment)
    second = _send(db, shipment)
    qos.withdraw(db, second, reason="INTERNAL wrong weight", actor=None)
    db.commit()
    assert qos.closed_reason(db, first) == "replaced"
    assert qos.closed_reason(db, second) == "withdrawn"
