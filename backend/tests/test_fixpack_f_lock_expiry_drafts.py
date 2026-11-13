"""Owner answers 8, 9 and 9a (Louis Tong, 2026-10-21): fix pack F.

* **8** -- a booked (or completed) master locks its shipments' items and fee lines; an Admin
  unlocks it with a reason (audited), Admin or Operations lock it again, and finalising a
  member's quote locks it again by itself. Every edit made while unlocked names the unlock.
* **9** -- a new tariff version expires the finalised quotes of shipments whose goods have not
  been received; received shipments, issued invoices and booked masters keep theirs. An
  expired offer cannot be accepted or invoiced, its draft invoice is withdrawn, and the
  Customer Account shows it as expired.
* **9a** -- acceptance prepares the invoice as a draft; staff save it (revision-checked,
  diff-audited), download it as a watermarked PDF, and send it, which issues the numbered
  invoice and emails the customer (Vietnamese by default) with no vendor name anywhere.
"""

from __future__ import annotations

import io
import json
import sqlite3
from datetime import date

import pytest
from pypdf import PdfReader

from app.core.enums import ConsolidationState, OperationalState, Role
from app.models import (
    AuditEvent,
    Customer,
    CustomerInvoice,
    InvoiceDraft,
    MasterEditUnlock,
    QuoteExpiry,
    QuoteLine,
    QuoteOffer,
    QuoteVersion,
)
from app.services import consolidation_service as cs
from app.services import finance_service as fs
from app.services import invoice_draft_service as drafts
from app.services import invoice_pdf_service as pdfs
from app.services import master_lock_service as locks
from app.services import pricing_service as ps
from app.services import quote_expiry_service as expiry
from app.services import quote_offer_service as qos
from app.services import shipment_item_service as items
from app.services import tariff_import_service as tis
from app.services.errors import ConflictError, ValidationError
from tests.conftest import see_committed_changes, shown_tax
from tests.test_migrations_phase13c import _alembic, _tables
from tests.test_quote_offers import _account_world, _fee, _finalize, _identity_for, _send
from tests.test_quotes import WORKBOOK, priced_world  # noqa: F401 - fixture


def _book(db, con):
    cs.book_consolidation(db, con, actor=None)
    db.commit()
    return con


def _audits(db, action):
    return db.query(AuditEvent).filter_by(action=action).all()


def _new_tariff(db, suffix=b"\n"):
    version = tis.import_workbook(
        db,
        WORKBOOK.read_bytes() + suffix,
        file_name="v2.xlsx",
        effective_from=date(2026, 11, 1),
        label="v2",
        actor=None,
    )
    db.commit()
    tis.activate_version(db, version, actor=None)
    db.commit()
    return version


def _confirm_tax(db, draft):
    """Staff tick "I have checked the GST/HST" on the saved draft (RC-UAT-19, 2026-10-22):
    Send needs it."""
    drafts.update_draft(
        db, draft, {"tax_confirmed": True}, expected_revision=draft.revision, actor=None
    )
    db.commit()
    return draft


def _accepted(db, shipment):
    """Finalise, send and accept the shipment's quote; returns (offer, draft)."""
    _finalize(db, shipment)
    offer = _send(db, shipment)
    identity = _identity_for(db, db.get(Customer, shipment.customer_id))
    qos.accept(db, offer, identity)
    db.commit()
    return offer, drafts.live_for_shipment(db, shipment.id)


# === 8: the master edit lock ===================================================================


def test_items_and_fees_lock_when_the_master_is_booked_in_every_locked_state(db, priced_world):  # noqa: F811
    con, kids = priced_world
    shipment = kids[2]
    # Open: edits are allowed and their audit names no unlock.
    item = items.add_item(db, shipment, {"description": "Shoes"}, actor=None)
    line = ps.add_fee_line(
        db, shipment, {"item_id": item.id, "section": "hcm_air", "stt": 18}, actor=None
    )
    db.commit()
    assert "master_unlock_id" not in json.loads(_audits(db, "shipment.item_add")[-1].detail_json)

    _book(db, con)
    for state in (ConsolidationState.BOOKED, ConsolidationState.COMPLETED):
        con.state = state
        db.commit()
        refusals = (
            lambda: items.add_item(db, shipment, {"description": "More"}, actor=None),
            lambda: items.update_item(db, shipment, item, {"quantity": 3}, actor=None),
            lambda: items.remove_item(db, shipment, item, actor=None),
            lambda: ps.add_fee_line(
                db, shipment, {"item_id": item.id, "section": "hcm_air", "stt": 19}, actor=None
            ),
            lambda: ps.remove_fee_line(db, shipment, line.id, actor=None),
        )
        for attempt in refusals:
            with pytest.raises(ConflictError, match="locked") as caught:
                attempt()
            assert caught.value.detail["code"] == "master_locked"
            db.rollback()
    # Cancelled releases the members: their items are theirs again.
    con.state = ConsolidationState.BOOKED
    db.commit()
    cs.cancel_consolidation(db, con, reason="vendor refused", actor=None)
    db.commit()
    items.update_item(db, shipment, item, {"quantity": 2}, actor=None)
    db.commit()


def test_http_refusal_is_a_409_with_a_clear_message(db, priced_world, api_for):  # noqa: F811
    con, kids = priced_world
    item = items.add_item(db, kids[0], {"description": "Tea"}, actor=None)
    db.commit()
    _book(db, con)
    ops = api_for(Role.OPERATIONS)
    for response in (
        ops.post(f"/api/v1/shipments/{kids[0].id}/items", json={"description": "x"}),
        ops.patch(f"/api/v1/shipments/{kids[0].id}/items/{item.id}", json={"quantity": 2}),
        ops.post(f"/api/v1/shipments/{kids[0].id}/items/{item.id}/remove"),
        ops.post(
            f"/api/v1/shipments/{kids[0].id}/fee-lines",
            json={"item_id": item.id, "section": "hcm_air", "stt": 18},
        ),
    ):
        assert response.status_code == 409, response.text
        assert "locked" in response.json()["message"]
    master = ops.get(f"/api/v1/consolidations/{con.id}").json()
    assert master["edit_lock"] == {"locked": True, "lockable": True, "unlock": None}


def test_admin_unlocks_with_a_reason_edits_are_audited_and_staff_lock_again(
    db,
    priced_world,  # noqa: F811
    api_for,
):
    con, kids = priced_world
    item = items.add_item(db, kids[1], {"description": "Tea"}, actor=None)
    db.commit()
    url = f"/api/v1/consolidations/{con.id}"
    admin = api_for(Role.ADMIN)
    # An open master has nothing to unlock.
    assert admin.post(f"{url}/unlock", json={"reason": "fix"}).status_code == 409
    _book(db, con)

    ops = api_for(Role.OPERATIONS)
    assert ops.post(f"{url}/unlock", json={"reason": "fix weight"}).status_code == 403
    admin = api_for(Role.ADMIN)
    assert admin.post(f"{url}/unlock", json={"reason": ""}).status_code == 422
    assert admin.post(f"{url}/unlock", json={"reason": "   "}).status_code == 422
    assert admin.post(f"{url}/unlock", json={"reason": "x" * 401}).status_code == 422
    opened = admin.post(f"{url}/unlock", json={"reason": "Customer added a pair of shoes"})
    assert opened.status_code == 200, opened.text
    lock = opened.json()["edit_lock"]
    assert lock["locked"] is False and lock["unlock"]["reason"] == "Customer added a pair of shoes"
    assert admin.post(f"{url}/unlock", json={"reason": "again"}).status_code == 409

    # While unlocked, edits are allowed and each audit row names the unlock.
    ops = api_for(Role.OPERATIONS)
    added = ops.post(f"/api/v1/shipments/{kids[1].id}/items", json={"description": "Shoes"})
    assert added.status_code == 201, added.text
    edited = ops.patch(f"/api/v1/shipments/{kids[1].id}/items/{item.id}", json={"quantity": 4})
    assert edited.status_code == 200, edited.text
    see_committed_changes(db)
    unlock_id = lock["unlock"]["id"]
    for action in ("shipment.item_add", "shipment.item_update"):
        assert json.loads(_audits(db, action)[-1].detail_json)["master_unlock_id"] == unlock_id
    unlocked = _audits(db, "master.unlocked")
    assert len(unlocked) == 1 and unlocked[0].actor_label == "admin@demo.example.com"

    # Operations locks it again; edits are refused again; a second relock is a conflict.
    relocked = ops.post(f"{url}/relock", json={"reason": "done"})
    assert relocked.status_code == 200, relocked.text
    assert relocked.json()["edit_lock"]["locked"] is True
    assert (
        ops.post(f"/api/v1/shipments/{kids[1].id}/items", json={"description": "x"}).status_code
        == 409
    )
    assert ops.post(f"{url}/relock", json={}).status_code == 409
    see_committed_changes(db)
    row = db.query(MasterEditUnlock).one()
    assert row.relocked_at is not None and row.relock_reason == "done"
    assert len(_audits(db, "master.relocked")) == 1


def test_finalising_a_member_quote_locks_the_master_again(db, priced_world):  # noqa: F811
    con, kids = priced_world
    _book(db, con)
    locks.unlock(db, con, reason="re-weigh", actor=None)
    db.commit()
    _fee(db, kids[2], quantity=1)  # allowed while unlocked
    _finalize(db, kids[2])
    row = db.query(MasterEditUnlock).one()
    assert row.relocked_at is not None and row.relock_reason.startswith("quote v1 finalised")
    audit = _audits(db, "master.relocked")[-1]
    assert json.loads(audit.detail_json)["automatic"] is True
    with pytest.raises(ConflictError, match="locked"):
        items.add_item(db, kids[2], {"description": "late"}, actor=None)
    db.rollback()


def test_the_unlock_reason_is_required_and_bounded_at_the_service(db, priced_world):  # noqa: F811
    con, _kids = priced_world
    _book(db, con)
    for bad in (None, "", "  ", "x" * 401, 5):
        with pytest.raises(ValidationError):
            locks.unlock(db, con, reason=bad, actor=None)
        db.rollback()


# === 9: quote expiry =============================================================================


def test_a_new_tariff_expires_quotes_for_goods_not_yet_received(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    sent, received, unsent = kids
    _finalize(db, sent)
    offer = _send(db, sent)
    _finalize(db, received)
    received_offer = _send(db, received)
    received.operational_state = OperationalState.RECEIVED_AT_SOLARIS
    unsent_version = _finalize(db, unsent)  # finalised, never sent
    db.commit()

    new = _new_tariff(db)
    db.refresh(offer)
    db.refresh(received_offer)
    assert offer.status == "expired"
    assert received_offer.status == "sent"  # received goods: never expires
    assert expiry.is_expired(db, unsent_version.id)  # with or without an offer
    rows = {row.shipment_id: row for row in db.query(QuoteExpiry)}
    assert set(rows) == {sent.id, unsent.id}
    assert rows[sent.id].tariff_version_id == new.id
    assert rows[sent.id].previous_offer_status == "sent"
    assert len(_audits(db, "quote.expired")) == 2

    # Idempotent: the approval, the route and the activation all call it.
    assert expiry.expire_for_new_tariff(db, new, actor=None) == []

    # An expired quote is not answered, re-sent or invoiced; staff re-price on the new rate.
    identity = _identity_for(db, db.get(Customer, sent.customer_id))
    with pytest.raises(ConflictError, match="expired") as caught:
        qos.accept(db, offer, identity)
    assert caught.value.detail["status"] == "expired"
    db.rollback()
    with pytest.raises(ConflictError, match="expired"):
        fs.issue_invoice(db, unsent, actor=None)
    db.rollback()
    with pytest.raises(ConflictError):
        qos.send_quote(db, unsent, actor=None)
    db.rollback()
    version = _finalize(db, unsent)
    assert version.version == 2 and version.tariff_version_id == new.id
    assert not expiry.is_expired(db, version.id)
    assert _send(db, unsent).status == "sent"


def test_a_published_received_milestone_keeps_the_quote(db, priced_world):  # noqa: F811
    from app.services import event_service

    _con, kids = priced_world
    shipment = kids[0]
    _finalize(db, shipment)
    offer = _send(db, shipment)
    event_service.record_event(
        db,
        shipment,
        {
            "event_type": "received_at_solaris",
            "is_public_update": True,
            "public_update_text": "Your parcel is with us.",
        },
        actor=None,
    )
    db.commit()
    shipment.operational_state = OperationalState.BOOKED  # the event alone must be enough
    db.commit()
    _new_tariff(db)
    db.refresh(offer)
    assert offer.status == "sent"


def test_an_issued_invoice_is_never_touched_and_its_quote_does_not_expire(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[1]
    version = _finalize(db, shipment)
    invoice = fs.issue_invoice(db, shipment, actor=None)
    db.commit()
    _new_tariff(db)
    db.refresh(invoice)
    assert invoice.status == "issued" and not expiry.is_expired(db, version.id)


def test_a_booked_master_keeps_its_quotes(db, priced_world):  # noqa: F811
    con, kids = priced_world
    version = _finalize(db, kids[0])
    _book(db, con)
    _new_tariff(db)
    assert not expiry.is_expired(db, version.id)


def test_the_shipments_current_master_decides_the_booked_stand_in(db, priced_world):  # noqa: F811
    """Review M4: the master the shipment rides in now, not the one the version was priced in."""
    from app.models import ConsolidationMembership

    con, kids = priced_world
    moved, joined = kids[0], kids[1]
    moved_version = _finalize(db, moved)
    # ``moved`` leaves the master before it is booked: its version still names the master.
    cs.remove_member(db, con, moved, reason="moved to another master", actor=None)
    db.commit()
    assert moved_version.consolidation_id == con.id
    # ``joined`` is priced while its version names no master, then rides in the booked one.
    joined_version = _finalize(db, joined)
    joined_version.consolidation_id = None
    db.commit()
    _book(db, con)
    assert db.query(ConsolidationMembership).filter_by(shipment_id=joined.id).count() >= 1

    _new_tariff(db)
    assert expiry.is_expired(db, moved_version.id)  # its master was never its booked one
    assert not expiry.is_expired(db, joined_version.id)  # it rides in a booked master now


def test_expiry_sees_an_acceptance_that_committed_a_moment_ago(db, priced_world):  # noqa: F811
    """Review M5: the session still holds the offer as ``sent`` while the database has the
    customer's acceptance (and its draft). The conditional UPDATE records the true previous
    status and the just-created draft is withdrawn with the quote."""
    from sqlalchemy.orm.attributes import set_committed_value

    _con, kids = priced_world
    offer, draft = _accepted(db, kids[2])
    assert offer.status == "accepted" and draft is not None
    set_committed_value(offer, "status", "sent")  # the stale read the race produces
    _new_tariff(db)
    db.refresh(offer)
    db.refresh(draft)
    assert offer.status == "expired"
    row = db.query(QuoteExpiry).one()
    assert row.previous_offer_status == "accepted"
    assert draft.status == "discarded" and row.invoice_draft_id == draft.id


def test_expiry_never_overwrites_a_declined_offer(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    _finalize(db, kids[0])
    offer = _send(db, kids[0])
    identity = _identity_for(db, db.get(Customer, kids[0].customer_id))
    qos.decline(db, offer, identity, reason=None)
    db.commit()
    from sqlalchemy.orm.attributes import set_committed_value

    set_committed_value(offer, "status", "sent")  # stale in the session
    _new_tariff(db)
    db.refresh(offer)
    assert offer.status == "declined"
    assert db.query(QuoteExpiry).one().previous_offer_status is None


def test_expiry_withdraws_the_draft_invoice_of_an_accepted_quote(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    offer, draft = _accepted(db, kids[2])
    assert draft is not None and draft.status == "draft"
    _new_tariff(db)
    db.refresh(offer)
    db.refresh(draft)
    assert offer.status == "expired"
    assert draft.status == "discarded" and "expired" in draft.discard_reason
    assert db.query(QuoteExpiry).one().invoice_draft_id == draft.id
    assert len(_audits(db, "invoice.draft_discarded")) == 1
    with pytest.raises(ConflictError):
        drafts.send(db, draft, expected_revision=draft.revision, actor=None)
    db.rollback()
    # No longer in the accepted-not-invoiced list (the offer is expired).
    rows, _total = qos.accepted_not_invoiced(db)
    assert all(row[0].id != offer.id for row in rows)


def test_the_account_shows_an_expired_quote_neutrally(
    account_client, account_db, account_users, captured_mail
):
    from tests.test_account_profile import _customer, _setup

    _reference, me = _setup(account_client, account_users, captured_mail)
    owner = _customer(account_db)
    kids = _account_world(account_db, owner)
    mine = kids[2]
    _finalize(account_db, mine)
    offer_id = _send(account_db, mine).id
    _new_tariff(account_db)
    detail = me.get(f"/quotes/{offer_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["status"] == "expired"
    assert body["closed_reason"] == "expired" and body["can_answer"] is False
    assert "tariff" not in detail.text.lower() and "kango" not in detail.text.lower()
    refused = me.post(f"/quotes/{offer_id}/accept")
    assert refused.status_code == 409
    assert "expired" in refused.json()["message"] and "tariff" not in refused.text.lower()
    assert me.get("/quotes").json()["items"][0]["status"] == "expired"


# === 9a: draft invoices ===========================================================================


def _kango_line(db, shipment):
    """Make one of the finalised version's customer lines name the vendor."""
    version = db.query(QuoteVersion).filter_by(shipment_id=shipment.id, status="finalized").one()
    line = next(line for line in version.lines if line.kind == "surcharge" and line.revenue_cad)
    line.description = "Phụ thu Kango xử lý đặc biệt"
    db.commit()
    return line


def test_acceptance_prepares_a_draft_invoice_with_no_number_and_no_vendor_name(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[2]
    _fee(db, shipment, quantity=1)
    _finalize(db, shipment)
    _kango_line(db, shipment)
    offer = _send(db, shipment)
    identity = _identity_for(db, db.get(Customer, shipment.customer_id))
    qos.accept(db, offer, identity)
    db.commit()
    draft = drafts.live_for_shipment(db, shipment.id)
    assert draft.status == "draft" and draft.revision == 1 and draft.offer_id == offer.id
    assert draft.issued_invoice_id is None and db.query(CustomerInvoice).count() == 0
    lines = drafts.lines_of(draft)
    assert "kango" not in json.dumps(lines, ensure_ascii=False).lower()
    assert any(line["description"] == "Phụ phí" for line in lines)
    assert drafts.subtotal_of(lines) == offer_total(offer)
    audit = _audits(db, "invoice.draft_created")[0]
    assert audit.actor_label == f"customer_account:{identity.public_id}"

    # The manual Issue invoice path routes to the draft.
    with pytest.raises(ConflictError, match="draft") as caught:
        fs.issue_invoice(db, shipment, actor=None)
    assert caught.value.detail["invoice_draft_id"] == draft.id
    db.rollback()
    rows, _ = qos.accepted_not_invoiced(db)
    assert [row[0].id for row in rows] == [offer.id]


def offer_total(offer):
    from decimal import Decimal

    return Decimal(qos.customer_view(offer)["total_cad"])


def test_save_send_and_download_refuse_a_stale_revision_and_edits_are_diff_audited(
    db,
    priced_world,  # noqa: F811
    api_for,
    captured_mail,
):
    _con, kids = priced_world
    shipment = kids[2]
    _offer, draft = _accepted(db, shipment)
    url = f"/api/v1/invoice-drafts/{draft.id}"
    ops = api_for(Role.OPERATIONS)
    read = ops.get(url).json()
    # RC-UAT-19: 13 % included in the price, so the accepted total is the draft's total.
    assert read["revision"] == 1 and read["quote_total_cad"] == read["total_cad"]
    assert ops.get(f"/api/v1/shipments/{shipment.id}/invoice-draft").json()["id"] == draft.id

    saved = ops.patch(
        url,
        json={
            "expected_revision": 1,
            "bill_to_name": "Nguyễn Văn A",
            "bill_to_address": "12 Main St\nToronto ON",
            "customer_reference": "PO-778",
            "tax_rate_percent": 5,
            "tax_confirmed": True,
            **shown_tax(read["lines"], 5, "included"),
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2
    see_committed_changes(db)
    edit = _audits(db, "invoice.draft_edited")[-1]
    changes = json.loads(edit.detail_json)["changes"]
    assert changes["customer_reference"] == {"from": None, "to": "PO-778"}
    # RC-UAT-20 (DEC-0227): a VN-CA draft starts zero-rated (it started at 13 % in RC-UAT-19).
    assert changes["tax_rate_percent"] == {"from": 0, "to": 5}

    # A stale revision: nothing saved, sent or printed.
    stale = ops.patch(url, json={"expected_revision": 1, "notes": "late"})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale_revision"
    assert ops.get(f"{url}/pdf", params={"revision": 1}).status_code == 409
    assert ops.post(f"{url}/send", json={"expected_revision": 1}).status_code == 409
    see_committed_changes(db)
    assert db.query(CustomerInvoice).count() == 0

    # A total different from the accepted quote needs a reason.
    lines = saved.json()["lines"]
    lines[0]["amount_cad"] = str(float(lines[0]["amount_cad"]) + 10)
    # A line naming the vendor is refused on save (owner, OD-84; review M3).
    named = ops.patch(
        url,
        json={
            "expected_revision": 2,
            "lines": [*lines, {"description": "Kango express handling", "amount_cad": "5.00"}],
            "total_change_reason": "extra packing",
        },
    )
    assert named.status_code == 422 and named.json()["field"] == "lines"
    lines.append({"description": "Express handling", "amount_cad": "5.00"})
    refused = ops.patch(url, json={"expected_revision": 2, "lines": lines})
    assert refused.status_code == 422 and refused.json()["field"] == "total_change_reason"
    priced = ops.patch(
        url,
        json={
            "expected_revision": 2,
            "lines": lines,
            "total_change_reason": "extra packing",
            "tax_confirmed": True,
            **shown_tax(lines, 5, "included"),
        },
    )
    assert priced.status_code == 200, priced.text
    revision = priced.json()["revision"]
    assert revision == 3

    # Download the saved draft: a PDF, watermarked DRAFT, with no vendor name.
    pdf = ops.get(f"{url}/pdf", params={"revision": revision})
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "DRAFT" in text and "kango" not in text.lower()
    assert "795093756RT0001" in text and "PO-778" in text and "Express handling" in text

    # Send: the numbered invoice from the saved fields, then the email, in Vietnamese.
    sent = ops.post(f"{url}/send", json={"expected_revision": revision})
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert body["invoice_public_id"].startswith("INV-") and body["draft"]["status"] == "issued"
    assert body["email_status"] == "sent"
    see_committed_changes(db)
    invoice = db.get(CustomerInvoice, body["invoice_id"])
    assert invoice.tax_status == "gst_hst_5"
    assert str(invoice.total_cad) == body["draft"]["total_cad"]
    assert [line.description for line in invoice.lines][-1] == "Express handling"
    message = captured_mail.messages[-1]
    assert message["template_key"] == "invoice.sent.vi" and message["language"] == "vi"
    assert invoice.public_id in message["body"] and "kango" not in message["body"].lower()
    assert invoice.due_at.date().isoformat() in message["body"]
    assert db.get(InvoiceDraft, draft.id).email_status == "sent"
    # Sent once: the draft is no longer a draft.
    assert ops.post(f"{url}/send", json={"expected_revision": revision + 1}).status_code == 409
    assert ops.patch(url, json={"expected_revision": revision + 1, "notes": "x"}).status_code == 409

    # The issued invoice's PDF: no watermark, no vendor name.
    issued = ops.get(f"/api/v1/invoices/{invoice.id}/pdf")
    assert issued.status_code == 200 and issued.content.startswith(b"%PDF")
    text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(issued.content)).pages)
    assert "DRAFT" not in text and "kango" not in text.lower()
    # DEC-0235: the PDF prints names without diacritics (English, no accents).
    assert invoice.public_id in text and "Nguyen Van A" in text and "Nguyễn" not in text
    document = ops.get(f"/api/v1/invoices/{invoice.id}/document").json()
    assert document["purchase_order_reference"] == "PO-778"
    assert "kango" not in json.dumps(document, ensure_ascii=False).lower()


def test_permissions_follow_invoicing(db, priced_world, api_for):  # noqa: F811
    _con, kids = priced_world
    _offer, draft = _accepted(db, kids[0])
    url = f"/api/v1/invoice-drafts/{draft.id}"
    manager = api_for(Role.READ_ONLY_MANAGER)
    assert manager.get(url).status_code == 200
    # RC-UAT-20 (owner, 2026-10-23; DEC-0229): Download, like Send, needs the saved revision's
    # GST/HST confirmed (422 tax_unconfirmed); a reader downloads once staff confirmed it.
    unconfirmed = manager.get(f"{url}/pdf", params={"revision": 1})
    assert unconfirmed.status_code == 422 and unconfirmed.json()["detail"]["code"] == (
        "tax_unconfirmed"
    )
    see_committed_changes(db)
    _confirm_tax(db, draft)
    assert manager.get(f"{url}/pdf", params={"revision": draft.revision}).status_code == 200
    assert manager.patch(url, json={"expected_revision": 1, "notes": "x"}).status_code == 403
    assert manager.post(f"{url}/send", json={"expected_revision": 1}).status_code == 403
    marketing = api_for(Role.MARKETING)
    assert marketing.get(url).status_code == 403
    assert marketing.get(f"{url}/pdf", params={"revision": 1}).status_code == 403


def test_the_english_customer_gets_the_english_email_and_a_customer_without_email_none(
    db,
    priced_world,  # noqa: F811
    captured_mail,
):
    _con, kids = priced_world
    english = db.get(Customer, kids[0].customer_id)
    english.preferred_language = "en"
    db.commit()
    _offer, draft = _accepted(db, kids[0])
    _confirm_tax(db, draft)
    drafts.send(db, draft, expected_revision=draft.revision, actor=None)
    db.commit()
    assert drafts.send_email(db, draft.id) == "sent"
    assert captured_mail.messages[-1]["template_key"] == "invoice.sent.en"

    silent = db.get(Customer, kids[1].customer_id)
    _offer, other = _accepted(db, kids[1])
    silent.email_normalized = None
    silent.email_entered = None
    db.commit()
    _confirm_tax(db, other)
    drafts.send(db, other, expected_revision=other.revision, actor=None)
    db.commit()
    assert drafts.send_email(db, other.id) == "no_email"


def test_a_second_acceptance_replaces_the_older_draft(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[1]
    first_offer, first = _accepted(db, shipment)
    _fee(db, shipment, quantity=1)
    _finalize(db, shipment)
    second_offer = _send(db, shipment)
    from app.models import CustomerIdentity

    identity = db.query(CustomerIdentity).filter_by(public_id=f"CA-T{shipment.customer_id:05d}")
    qos.accept(db, second_offer, identity.one())
    db.commit()
    db.refresh(first)
    assert first.status == "discarded" and "replaced" in first.discard_reason
    live = drafts.live_for_shipment(db, shipment.id)
    assert live.offer_id == second_offer.id and live.id != first.id
    assert first_offer.id != second_offer.id


def test_a_draft_behind_a_newer_version_needs_acknowledgement_or_is_withdrawn(
    db,
    priced_world,  # noqa: F811
    api_for,
):
    """Review M1: Send refuses (409 quote_superseded) once a newer version is finalised, unless
    the request acknowledges it; staff can instead withdraw the draft (audited) and issue
    from the latest version the normal way."""
    _con, kids = priced_world
    shipment = kids[1]
    _offer, draft = _accepted(db, shipment)
    _fee(db, shipment, quantity=1)
    newer = _finalize(db, shipment)
    assert newer.version == 2
    url = f"/api/v1/invoice-drafts/{draft.id}"
    ops = api_for(Role.OPERATIONS)
    read = ops.get(url).json()
    assert read["quote_version"] == 1 and read["superseded_by_version"] == 2

    refused = ops.post(f"{url}/send", json={"expected_revision": read["revision"]})
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail == {"code": "quote_superseded", "draft_version": 1, "latest_version": 2}
    assert "v1" in refused.json()["message"] and "v2" in refused.json()["message"]

    # Withdraw: financial write only, a reason required, audited.
    manager = api_for(Role.READ_ONLY_MANAGER)
    assert manager.post(f"{url}/withdraw", json={"reason": "x"}).status_code == 403
    ops = api_for(Role.OPERATIONS)
    assert ops.post(f"{url}/withdraw", json={"reason": "   "}).status_code == 422
    withdrawn = ops.post(f"{url}/withdraw", json={"reason": "re-priced as v2"})
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["status"] == "discarded"
    assert withdrawn.json()["superseded_by_version"] is None
    see_committed_changes(db)
    audit = _audits(db, "invoice.draft_discarded")[-1]
    assert audit.actor_label == "operations@demo.example.com"
    assert "re-priced as v2" in json.loads(audit.detail_json)["reason"]
    assert ops.post(f"{url}/withdraw", json={"reason": "again"}).status_code == 409

    # The normal way: the invoice from the latest version.
    invoice = fs.issue_invoice(db, shipment, actor=None)
    db.commit()
    assert invoice.quote_version_id == newer.id


def test_a_superseded_draft_is_sent_at_the_accepted_price_when_acknowledged(
    db,
    priced_world,  # noqa: F811
    api_for,
):
    _con, kids = priced_world
    shipment = kids[0]
    _offer, draft = _accepted(db, shipment)
    accepted_total = drafts.view(db, draft)["total_cad"]
    _fee(db, shipment, quantity=1)
    _finalize(db, shipment)
    with pytest.raises(ConflictError) as caught:
        drafts.send(db, draft, expected_revision=draft.revision, actor=None)
    assert caught.value.detail["code"] == "quote_superseded"
    db.rollback()
    _confirm_tax(db, draft)
    ops = api_for(Role.OPERATIONS)
    sent = ops.post(
        f"/api/v1/invoice-drafts/{draft.id}/send",
        json={"expected_revision": draft.revision, "acknowledge_superseded": True},
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["draft"]["total_cad"] == accepted_total
    see_committed_changes(db)
    audit = _audits(db, "invoice.draft_sent")[-1]
    assert json.loads(audit.detail_json)["sent_despite_newer_version"] == 2


def test_concurrent_unlock_is_a_conflict_not_a_server_error(db, priced_world, monkeypatch):  # noqa: F811
    """Two Admins at once: the second's insert hits the partial unique index -> 409."""
    con, _kids = priced_world
    _book(db, con)
    locks.unlock(db, con, reason="first", actor=None)
    db.commit()
    monkeypatch.setattr(locks, "open_unlock", lambda _db, _cid: None)  # both saw "locked"
    with pytest.raises(ConflictError, match="already unlocked"):
        locks.unlock(db, con, reason="second", actor=None)
    db.rollback()
    assert db.query(MasterEditUnlock).count() == 1


def test_long_notes_and_many_lines_continue_on_further_pages(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    _offer, draft = _accepted(db, kids[2])
    view = drafts.view(db, draft)
    document = pdfs.draft_document(db, draft)
    document["lines"] = [
        {"description": f"Line {n} " + "x" * 120, "amount_cad": "1.00"} for n in range(48)
    ]
    document["notes"] = "\n".join(f"Note line {n}" for n in range(80))
    document["bill_to_address"] = "UNBROKEN" * 40
    content = pdfs.render(document, draft=True, vendor_names=("kango",))
    reader = PdfReader(io.BytesIO(content))
    assert len(reader.pages) >= 3
    text = "".join(page.extract_text() for page in reader.pages)
    assert "Note line 79" in text and "Line 47" in text
    assert all("DRAFT" in page.extract_text() for page in reader.pages)
    assert view["status"] == "draft"


def test_a_void_invoice_pdf_is_watermarked_void(db, priced_world, api_for):  # noqa: F811
    _con, kids = priced_world
    _finalize(db, kids[1])
    invoice = fs.issue_invoice(db, kids[1], actor=None)
    db.commit()
    fs.void_invoice(db, invoice, reason="issued in error", actor=None)
    db.commit()
    ops = api_for(Role.OPERATIONS)
    pdf = ops.get(f"/api/v1/invoices/{invoice.id}/pdf")
    assert pdf.status_code == 200
    text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "VOID" in text and "DRAFT" not in text


def test_the_draft_pdf_renders_without_http(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    _offer, draft = _accepted(db, kids[2])
    content = pdfs.draft_pdf(db, draft)
    assert content.startswith(b"%PDF")
    text = PdfReader(io.BytesIO(content)).pages[0].extract_text()
    # DEC-0235: English for every customer (it read "HÓA ĐƠN" for a Vietnamese one).
    assert "DRAFT" in text and "INVOICE" in text and "HÓA ĐƠN" not in text


def test_quote_lines_of_an_expired_quote_are_untouched(db, priced_world):  # noqa: F811
    """The version itself keeps its status and figures: only the expiry row is new."""
    _con, kids = priced_world
    version = _finalize(db, kids[0])
    before = [(line.description, line.revenue_cad) for line in version.lines]
    _new_tariff(db)
    db.refresh(version)
    assert version.status == "finalized"
    assert [(line.description, line.revenue_cad) for line in version.lines] == before
    assert db.query(QuoteLine).count() > 0 and db.query(QuoteOffer).count() == 0


# === The migration =================================================================================

FIXPACK_REVISION = "d4f7a2c9e1b8"
PHASE_13H_REVISION = "c5e8a1f3d7b9"
NEW_TABLES = {"master_edit_unlocks", "quote_expiries", "invoice_drafts"}


def test_the_migration_only_adds_three_tables_and_round_trips(tmp_path):
    path = tmp_path / "m.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", PHASE_13H_REVISION).returncode == 0
    before = _tables(path)
    with sqlite3.connect(path) as c:
        schema_before = dict(c.execute("select name, sql from sqlite_master where sql is not null"))
    # RC-UAT-19's e6b1c4a8d2f3 revises this one, so upgrade to it by name.
    assert _alembic(url, "upgrade", FIXPACK_REVISION).returncode == 0
    assert FIXPACK_REVISION in _alembic(url, "current").stdout
    assert _tables(path) - before == NEW_TABLES
    with sqlite3.connect(path) as c:
        schema_after = dict(c.execute("select name, sql from sqlite_master where sql is not null"))
        fks = {r[3]: (r[2], r[6]) for r in c.execute("pragma foreign_key_list(invoice_drafts)")}
    for name, sql in schema_before.items():
        assert schema_after[name] == sql, name  # nothing existing altered
    assert fks["issued_invoice_id"] == ("customer_invoices", "SET NULL")
    assert fks["shipment_id"] == ("shipments", "RESTRICT")
    # `alembic check` runs at the head (test_owner_answers_2026_10_22.py): below the head the
    # models' newer table would read as drift.
    # An expired offer reads as withdrawn to the older code after a downgrade.
    with sqlite3.connect(path) as c:
        columns = c.execute("pragma table_info(quote_offers)").fetchall()
        values = {}
        for _cid, name, kind, notnull, default, _pk in columns:
            if name == "id" or not notnull or default is not None:
                continue
            kind = (kind or "").upper()
            values[name] = (
                1
                if "INT" in kind or "BOOL" in kind or "NUM" in kind
                else "2026-10-21 00:00:00"
                if "DATE" in kind
                else "x"
            )
        values["status"] = "expired"
        names = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        c.execute(f"insert into quote_offers ({names}) values ({marks})", list(values.values()))
    assert _alembic(url, "downgrade", PHASE_13H_REVISION).returncode == 0
    assert NEW_TABLES.isdisjoint(_tables(path))
    with sqlite3.connect(path) as c:
        status, withdrawn_at = c.execute("select status, withdrawn_at from quote_offers").fetchone()
    assert status == "withdrawn" and withdrawn_at is not None
    assert _alembic(url, "upgrade", "head").returncode == 0
