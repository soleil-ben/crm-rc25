# ruff: noqa: F811 - `priced_world` is an imported fixture used as a parameter
"""Phase 15: resend a failed (or address-less) quote email; accepted quotes not yet invoiced."""

from __future__ import annotations

import pytest

from app.core.enums import Role
from app.models import AuditEvent, Customer
from app.services import account_email_service, finance_service
from app.services import quote_offer_service as qos
from app.services.errors import ConflictError
from tests.conftest import see_committed_changes
from tests.test_quote_offers import (
    FORBIDDEN,
    _fee,
    _finalize,
    _identity_for,
    _send,
)
from tests.test_quotes import priced_world  # noqa: F401 - fixture


class Broken:
    name = "capture"

    def send(self, message):
        raise OSError("disk full")


def _failed_offer(db, shipment):
    _finalize(db, shipment)
    offer = _send(db, shipment)
    account_email_service.set_transport(Broken())
    try:
        assert qos.send_email(db, offer.id) == "failed"
    finally:
        account_email_service.reset_transport()
    db.refresh(offer)
    return offer


def _resend_url(offer_id):
    return f"/api/v1/quote-offers/{offer_id}/resend-email"


# --- Resend --------------------------------------------------------------------------------------


def test_a_failed_quote_email_is_resent_once_and_audited(
    api_for,
    db,
    priced_world,
    captured_mail,
):
    _con, kids = priced_world
    offer = _failed_offer(db, kids[0])
    account_email_service.set_transport(captured_mail)  # _failed_offer put the null one back
    see_committed_changes(db)
    ops = api_for(Role.OPERATIONS)
    response = ops.post(_resend_url(offer.id))
    assert response.status_code == 200, response.text
    assert response.json()["email_status"] == "sent"  # the capture transport took it
    assert captured_mail.messages[-1]["template_key"] == "quote.sent.vi"
    see_committed_changes(db)
    audit = db.query(AuditEvent).filter_by(action="quote.email_resent").one()
    assert str(audit.entity_id) == str(offer.id)
    assert '"previous_email_status": "failed"' in audit.detail_json
    # Sent now: a second resend is refused, and nothing more is captured.
    count = len(captured_mail.messages)
    assert ops.post(_resend_url(offer.id)).status_code == 409
    assert len(captured_mail.messages) == count


def test_a_resend_that_fails_again_is_recorded_failed_and_can_be_retried(
    api_for,
    db,
    priced_world,
):
    _con, kids = priced_world
    offer = _failed_offer(db, kids[0])
    see_committed_changes(db)
    ops = api_for(Role.OPERATIONS)
    account_email_service.set_transport(Broken())
    try:
        response = ops.post(_resend_url(offer.id))
    finally:
        account_email_service.reset_transport()
    assert response.status_code == 200, response.text
    assert response.json()["email_status"] == "failed" and response.json()["status"] == "sent"
    assert ops.post(_resend_url(offer.id)).json()["email_status"] == "recorded"


def test_no_email_is_resent_only_after_an_address_is_added(db, priced_world):
    _con, kids = priced_world
    customer = db.get(Customer, kids[1].customer_id)
    customer.email_normalized = None
    customer.email_entered = None
    db.commit()
    _finalize(db, kids[1])
    offer = _send(db, kids[1])
    assert qos.send_email(db, offer.id) == "no_email"
    db.refresh(offer)
    with pytest.raises(ConflictError, match="no email address"):
        qos.prepare_resend(db, offer, actor=None)
    db.rollback()
    customer = db.get(Customer, kids[1].customer_id)
    customer.email_entered = "added.later@demo.example.com"
    customer.email_normalized = "added.later@demo.example.com"
    db.commit()
    qos.prepare_resend(db, offer, actor=None)
    db.commit()
    assert qos.send_email(db, offer.id) == "recorded"


def test_only_an_unanswered_offer_with_a_failed_email_is_resent(db, priced_world):
    _con, kids = priced_world
    _finalize(db, kids[0])
    offer = _send(db, kids[0])
    qos.send_email(db, offer.id)
    db.refresh(offer)
    assert offer.email_status == "recorded"
    with pytest.raises(ConflictError, match="failed or had no address"):
        qos.prepare_resend(db, offer, actor=None)
    db.rollback()
    offer.email_status = "failed"
    qos.withdraw(db, offer, reason="Wrong weight", actor=None)
    db.commit()
    with pytest.raises(ConflictError, match="waiting for the customer"):
        qos.prepare_resend(db, offer, actor=None)
    db.rollback()


def test_two_resends_at_once_claim_once(db, priced_world):
    _con, kids = priced_world
    offer = _failed_offer(db, kids[0])
    qos.prepare_resend(db, offer, actor=None)
    db.commit()
    assert offer.email_status == "resending"
    with pytest.raises(ConflictError):
        qos.prepare_resend(db, offer, actor=None)
    db.rollback()


def test_resend_permissions(api_for, db, priced_world):
    _con, kids = priced_world
    offer = _failed_offer(db, kids[0])
    see_committed_changes(db)
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        assert api_for(role).post(_resend_url(offer.id)).status_code == 403
    assert api_for(Role.OPERATIONS).post(_resend_url(999999)).status_code == 404


# --- Accepted, not invoiced ----------------------------------------------------------------------

#: Fields whose values are generated identifiers, not wording a customer or staff reads.
_ID_FIELDS = ("public_id", "reference", "_id", "number", "token")


def _scannable(node, key: str = ""):
    """Every key, and every string value outside an identifier field, of a JSON body."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield str(k)
            yield from _scannable(v, str(k))
    elif isinstance(node, list):
        for v in node:
            yield from _scannable(v, key)
    elif isinstance(node, str) and not key.endswith(_ID_FIELDS):
        yield node


def test_an_accepted_quote_is_listed_until_the_invoice_is_issued(
    api_for,
    db,
    priced_world,
):
    _con, kids = priced_world
    shipment = kids[2]
    _fee(db, shipment, quantity=1)
    _finalize(db, shipment)
    offer = _send(db, shipment)
    _finalize(db, kids[0])
    other = _send(db, kids[0])  # sent, not answered: not listed
    qos.accept(db, offer, _identity_for(db, db.get(Customer, shipment.customer_id)))
    db.commit()
    see_committed_changes(db)

    finance = api_for(Role.OPERATIONS)
    listed = finance.get("/api/v1/finance/accepted-not-invoiced")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["offer_id"] == offer.id and item["shipment_id"] == shipment.id
    assert item["version"] == 1 and item["total_cad"] == qos.customer_view(offer)["total_cad"]
    assert item["consolidation_id"] == _con.id
    # Scan every key and every text value, but not the values of identifier fields: a random
    # public id ("SX-VCA-MMNXYFBM5EFX") can spell "fx" by chance (flaky before DEC-0269).
    lowered = " ".join(_scannable(body)).lower()
    for word in FORBIDDEN:
        assert word not in lowered.replace("total_cad", ""), word
    assert other.id not in [i["offer_id"] for i in body["items"]]

    # Owner decision 9a (2026-10-21): acceptance prepared a draft (listed with the row), not
    # an invoice; the manual Issue invoice routes to it, and sending it removes the row.
    assert finance_service.live_invoice(db, shipment.id) is None
    draft_id = item["invoice_draft_id"]
    assert draft_id is not None and item["invoice_draft_revision"] == 1
    manual = finance.post(f"/api/v1/shipments/{shipment.id}/invoice", json={"tax_rate_percent": 0})
    assert manual.status_code == 409 and manual.json()["detail"]["invoice_draft_id"] == draft_id
    # RC-UAT-19: staff confirm the draft's GST/HST before Send.
    confirm = {"expected_revision": 1, "tax_confirmed": True}
    assert finance.patch(f"/api/v1/invoice-drafts/{draft_id}", json=confirm).status_code == 200
    sent = finance.post(f"/api/v1/invoice-drafts/{draft_id}/send", json={"expected_revision": 1})
    assert sent.status_code == 200, sent.text
    issued = finance.get(f"/api/v1/invoices/{sent.json()['invoice_id']}")
    assert finance.get("/api/v1/finance/accepted-not-invoiced").json()["total"] == 0

    # A voided invoice brings the prompt back.
    admin = api_for(Role.ADMIN)
    voided = admin.post(
        f"/api/v1/invoices/{issued.json()['id']}/void", json={"reason": "Wrong tax"}
    )
    assert voided.status_code == 200, voided.text
    assert admin.get("/api/v1/finance/accepted-not-invoiced").json()["total"] == 1


def test_the_list_needs_finance_read(api_for):
    assert api_for(Role.MARKETING).get("/api/v1/finance/accepted-not-invoiced").status_code == 403


# --- Review fixes (2026-10-21) -------------------------------------------------------------------


def test_a_claim_in_flight_is_refused_and_an_abandoned_one_is_taken_over(
    db, priced_world, captured_mail
):
    from datetime import timedelta

    _con, kids = priced_world
    offer = _failed_offer(db, kids[0])
    qos.prepare_resend(db, offer, actor=None)
    db.commit()
    with pytest.raises(ConflictError, match="already being sent again"):
        qos.prepare_resend(db, offer, actor=None)
    db.rollback()
    # The process that claimed it died: after the timeout a new press takes it over.
    offer.updated_at = offer.updated_at - qos.RESEND_CLAIM_TIMEOUT - timedelta(seconds=1)
    db.commit()
    qos.prepare_resend(db, offer, actor=None)
    db.commit()
    account_email_service.set_transport(captured_mail)
    assert qos.send_email(db, offer.id) == "sent"


def test_an_offer_answered_or_withdrawn_before_the_send_gets_nothing(
    db, priced_world, captured_mail
):
    _con, kids = priced_world
    offer = _failed_offer(db, kids[0])
    qos.prepare_resend(db, offer, actor=None)
    db.commit()
    qos.withdraw(db, offer, reason="Re-pricing", actor=None)
    db.commit()
    account_email_service.set_transport(captured_mail)
    before = len(captured_mail.messages)
    assert qos.send_email(db, offer.id) == "skipped"
    assert len(captured_mail.messages) == before
    db.refresh(offer)
    assert offer.email_status == "skipped"


def test_the_accepted_list_is_limited_in_sql_with_a_true_total(api_for, db, priced_world):
    _con, kids = priced_world
    for shipment in kids[:2]:
        _finalize(db, shipment)
        offer = _send(db, shipment)
        qos.accept(db, offer, _identity_for(db, db.get(Customer, shipment.customer_id)))
        db.commit()
    see_committed_changes(db)
    body = api_for(Role.OPERATIONS).get("/api/v1/finance/accepted-not-invoiced?limit=1").json()
    assert body["total"] == 2 and len(body["items"]) == 1
    assert body["items"][0]["customer_name"] and body["items"][0]["consolidation_id"] == _con.id


def test_the_leak_scan_ignores_identifiers_but_not_keys_or_text():
    body = {"items": [{"shipment_public_id": "SX-VCA-MMNXYFBM5EFX", "note": "ok"}]}
    assert "fx" not in " ".join(_scannable(body)).lower()
    assert "fx" in " ".join(_scannable({"fx_rate": 1})).lower()
    assert "vendor" in " ".join(_scannable({"name": "vendor price"})).lower()
