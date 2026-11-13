# ruff: noqa: F811 - `priced_world` is an imported fixture used as a parameter
"""Phase 15 workflow hardening -- independent golden scenarios (DEC-0216).

Written by the independent tester from ``docs/b2c_merge/18_PHASE_15_RECORD.md``. Black-box
where the product has a route (staff HTTP via ``api_for``, the Customer Account via its own
sign-in); the service seam is used only to stage a condition no route produces on demand (a
milestone row still queued when a return lands). Air only, demo addresses, capture transport.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from app.core.enums import RouteGroup, ShipmentEventType
from app.core.time_utils import utcnow
from app.models import AuditEvent, Customer, NotificationOutbox, QuoteOffer
from app.services import account_email_service, event_service
from app.services import consolidation_service as cs
from app.services import notification_service as ns
from app.services import quote_offer_service as qos
from tests.conftest import booked_shipment, make_customer, see_committed_changes
from tests.shipment_history_fixtures import add_event, walk
from tests.shipment_history_fixtures import shipment as history_shipment
from tests.test_quote_offers import _account_world, _fee, _finalize, _identity_for, _send
from tests.test_quotes import priced_world  # noqa: F401 - fixture

E = ShipmentEventType
ADDRESS = "p15.golden@demo.example.com"


class Broken:
    name = "capture"

    def send(self, message):
        raise OSError("disk full")


# --- helpers ------------------------------------------------------------------------------------


def _post_event(api, shipment_id, event_type, *, text="Update", days_ago=None):
    body = {"event_type": event_type, "is_public_update": True, "public_update_text": text}
    if days_ago is not None:
        body["occurred_at"] = (utcnow() - timedelta(days=days_ago)).isoformat()
    response = api.post(f"/api/v1/shipments/{shipment_id}/events", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _queue_only(db, shipment, event_type):
    """Record a published milestone without dispatching (a row left queued, as when the
    request's after-commit dispatch was deferred to the worker)."""
    created = event_service.record_event(
        db,
        shipment,
        {"event_type": event_type, "is_public_update": True, "public_update_text": "x"},
    )
    db.commit()
    return created


def _notify(mail, address=ADDRESS):
    return [
        m["template_key"].split(".")[1]
        for m in mail.messages
        if m["template_key"].startswith("notify.") and m["to_email"] == address
    ]


def _rows(db, shipment_id):
    see_committed_changes(db)
    return (
        db.query(NotificationOutbox)
        .filter_by(shipment_id=shipment_id)
        .order_by(NotificationOutbox.id)
        .all()
    )


@pytest.fixture
def parcel(db):
    return booked_shipment(db, make_customer(db, email=ADDRESS), RouteGroup.VCA)


@pytest.fixture
def ops(api_for):
    return api_for("operations")


# --- Milestone emails across journeys -----------------------------------------------------------


def test_a_normal_journey_sends_exactly_four(parcel, ops, captured_mail):
    for step in (E.RECEIVED_AT_SOLARIS, E.IN_TRANSIT, E.OUT_FOR_DELIVERY, E.DELIVERED_TO_RECIPIENT):
        _post_event(ops, parcel.id, step)
    assert _notify(captured_mail) == ["received", "in_transit", "out_for_delivery", "delivered"]


def test_a_backdated_received_after_in_transit_sends_nothing(db, parcel, ops, captured_mail):
    _post_event(ops, parcel.id, E.IN_TRANSIT)
    _post_event(ops, parcel.id, E.RECEIVED_AT_SOLARIS, text="Backdated", days_ago=4)
    assert _notify(captured_mail) == ["in_transit"]
    assert [r.milestone for r in _rows(db, parcel.id)] == ["in_transit"]


def test_an_exception_then_in_transit_resumes_without_resending(parcel, ops, captured_mail):
    _post_event(ops, parcel.id, E.RECEIVED_AT_SOLARIS)
    _post_event(ops, parcel.id, E.IN_TRANSIT)
    _post_event(ops, parcel.id, E.EXCEPTION, text="On hold at customs")
    _post_event(ops, parcel.id, E.RECEIVED_AT_SOLARIS, text="Late scan", days_ago=3)
    _post_event(ops, parcel.id, E.IN_TRANSIT, text="Released, moving again")
    assert _notify(captured_mail) == ["received", "in_transit"]
    _post_event(ops, parcel.id, E.OUT_FOR_DELIVERY)
    _post_event(ops, parcel.id, E.DELIVERED_TO_RECIPIENT)
    assert _notify(captured_mail) == ["received", "in_transit", "out_for_delivery", "delivered"]


def test_a_returned_shipment_gets_nothing_further_and_its_queued_row_is_closed(
    db, parcel, ops, captured_mail
):
    _post_event(ops, parcel.id, E.RECEIVED_AT_SOLARIS)
    _queue_only(db, parcel, E.OUT_FOR_DELIVERY)
    _post_event(ops, parcel.id, E.RETURNED, text="Refused by the recipient")
    _post_event(ops, parcel.id, E.IN_TRANSIT, text="Late", days_ago=2)
    _post_event(ops, parcel.id, E.DELIVERED_TO_RECIPIENT, text="After the return")
    see_committed_changes(db)  # read what the requests committed
    ns.dispatch_pending(db)
    db.commit()
    # Review fix 1+3 (2026-10-21): "closed" is read from the shipment's state only. The late
    # in-transit leaves the state returned (nothing sent); the delivery "after the return" puts
    # the state back on the ladder (sent out again), so it notifies normally.
    assert _notify(captured_mail) == ["received", "delivered"]
    rows = _rows(db, parcel.id)
    assert [(r.milestone, r.status, r.skip_reason) for r in rows] == [
        ("received", "sent", None),
        ("out_for_delivery", "skipped", "closed"),
        ("delivered", "sent", None),
    ]


def test_a_cancelled_shipment_gets_nothing_further_and_its_queued_row_is_closed(
    db, parcel, ops, captured_mail
):
    _queue_only(db, parcel, E.RECEIVED_AT_SOLARIS)
    cancelled = ops.post(f"/api/v1/shipments/{parcel.id}/cancel", json={"reason": "Changed mind"})
    assert cancelled.status_code == 200, cancelled.text
    see_committed_changes(db)  # read what the requests committed
    ns.dispatch_pending(db)
    db.commit()
    # Whatever staff then try to record, nothing reaches the customer.
    ops.post(
        f"/api/v1/shipments/{parcel.id}/events",
        json={"event_type": "in_transit", "is_public_update": True, "public_update_text": "x"},
    )
    see_committed_changes(db)  # read what the requests committed
    ns.dispatch_pending(db)
    db.commit()
    assert _notify(captured_mail) == []
    assert [(r.status, r.skip_reason) for r in _rows(db, parcel.id)] == [("skipped", "closed")]


def test_voiding_a_queued_wrong_out_for_delivery_then_the_real_one_sends_once(
    db, parcel, ops, captured_mail
):
    _post_event(ops, parcel.id, E.IN_TRANSIT)
    wrong = _queue_only(db, parcel, E.OUT_FOR_DELIVERY)
    voided = ops.post(f"/api/v1/events/{wrong[0].id}/void", json={"reason": "Wrong shipment"})
    assert voided.status_code == 200, voided.text
    _post_event(ops, parcel.id, E.OUT_FOR_DELIVERY, text="The real one")
    assert _notify(captured_mail) == ["in_transit", "out_for_delivery"]


def test_voiding_a_sent_wrong_out_for_delivery_then_the_real_one_sends_no_second(
    parcel, ops, captured_mail
):
    _post_event(ops, parcel.id, E.IN_TRANSIT)
    wrong = _post_event(ops, parcel.id, E.OUT_FOR_DELIVERY)
    assert ops.post(f"/api/v1/events/{wrong[0]['id']}/void", json={"reason": "Typo"}).status_code
    _post_event(ops, parcel.id, E.OUT_FOR_DELIVERY, text="The real one")
    assert _notify(captured_mail).count("out_for_delivery") == 1


def test_a_master_milestone_sends_one_email_per_member_customer(db, ops, captured_mail):
    addresses = [f"p15.member{i}@demo.example.com" for i in range(3)]
    members = [booked_shipment(db, make_customer(db, email=a), RouteGroup.VCA) for a in addresses]
    con = cs.create_consolidation(
        db,
        {"solaris_service": "air_standard", "origin": "HCM", "vendor_reference": "P15GD"},
        actor=None,
    )
    for member in members:
        cs.add_member(db, con, member, actor=None)
    db.commit()
    body = {"event_type": "in_transit", "is_public_update": True, "public_update_text": "Flying"}
    for _ in range(2):  # pressed twice
        response = ops.post(f"/api/v1/consolidations/{con.id}/events", json=body)
        assert response.status_code == 201, response.text
    for address, member in zip(addresses, members, strict=True):
        sent = [m for m in captured_mail.messages if m["to_email"] == address]
        assert [m["template_key"] for m in sent] == ["notify.in_transit.vi"]
        assert member.public_id in sent[0]["body"]


def test_the_customers_history_never_shows_closed_or_withdrawn_rows_as_sent(
    account_client, account_db, account_users, captured_mail
):
    from tests.test_account_profile import _customer, _setup

    _reference, me = _setup(account_client, account_users, captured_mail)
    shipment = booked_shipment(account_db, _customer(account_db), RouteGroup.VCA)
    _queue_only(account_db, shipment, E.RECEIVED_AT_SOLARIS)
    ns.dispatch_pending(account_db)
    account_db.commit()
    wrong = _queue_only(account_db, shipment, E.IN_TRANSIT)
    event_service.void_event(account_db, wrong[0], reason="Wrong shipment")
    account_db.commit()
    _queue_only(account_db, shipment, E.OUT_FOR_DELIVERY)
    _queue_only(account_db, shipment, E.RETURNED)
    ns.dispatch_pending(account_db)
    account_db.commit()

    read = me.get("/notifications")
    assert read.status_code == 200, read.text
    history = sorted((h["milestone"], h["state"]) for h in read.json()["history"])
    assert history == [("out_for_delivery", "not_sent"), ("received", "sent")]
    for word in ("closed", "voided", "withdrawn", "skip_reason"):
        assert word not in read.text


# --- Customer timeline --------------------------------------------------------------------------

NOTE = "P15G-INTERNAL-NOTE-7Q"
HIDDEN = "P15G-UNPUBLISHED-7Q"


def test_the_timeline_names_each_published_step_and_hides_internal_notes(
    account_client, account_db, account_users, captured_mail
):
    """Registered in `SUPERSEDED_ASSERTIONS.md` (AS-32): the public contract was twenty-four
    fields until RC-UAT-19 added ``carrier_links`` (2026-10-22)."""
    from app.schemas.public_tracking import PublicTimelineEntry, PublicTrackingResult
    from tests.test_account_profile import _customer, _setup

    _reference, me = _setup(account_client, account_users, captured_mail)
    row = history_shipment(account_db, _customer(account_db), route_group=RouteGroup.VCA)
    add_event(account_db, row, days_ago=5, text="We have your parcel.", state="received_at_solaris")
    add_event(
        account_db, row, days_ago=4, text=None, template_key="in_transit.v1", state="in_transit"
    )
    handover = add_event(
        account_db,
        row,
        days_ago=2,
        text="Collect it at the District 1 office.",
        internal_detail=NOTE,
        state="out_for_delivery",
    )
    handover.event_type = "delivered_to_collection_point"
    add_event(account_db, row, public=False, internal_detail=HIDDEN, days_ago=1, state="returned")
    account_db.commit()

    # The shared applicant fixture registers in English; an unstated language is Vietnamese
    # (covered by test_notifications_golden). The wording is chosen client-side by language.
    assert me.get("/me").json()["preferred_language"] == "en"
    detail = me.get(f"/shipments/{row.public_id}")
    assert detail.status_code == 200, detail.text
    timeline = detail.json()["timeline"]
    assert [(e["event_type"], e["message"]) for e in timeline] == [
        ("delivered_to_collection_point", "Collect it at the District 1 office."),
        ("in_transit", timeline[1]["message"]),
        ("received_at_solaris", "We have your parcel."),
    ]
    assert timeline[1]["message_template_key"] == "in_transit.v1" and timeline[1]["message"]
    for path, key, value in walk(detail.json()):
        assert NOTE not in str(key) + str(value), path
        assert HIDDEN not in str(key) + str(value), path
        assert key not in ("internal_detail", "is_public_update"), path
    assert "returned" not in [e["event_type"] for e in timeline]

    # Switched to Vietnamese: the same entries, the same staff text, nothing extra exposed.
    switched = me.post("/profile/direct", {"preferred_language": "vi"})
    assert switched.status_code == 200, switched.text
    assert me.get("/me").json()["preferred_language"] == "vi"
    again = me.get(f"/shipments/{row.public_id}").json()["timeline"]
    assert [e["event_type"] for e in again] == [e["event_type"] for e in timeline]

    public = account_client.get(f"/api/v1/public/track/{row.public_id}")
    assert public.status_code == 200, public.text
    body = public.json()
    assert set(body) <= set(PublicTrackingResult.model_fields)
    assert (
        len(PublicTrackingResult.model_fields) == 25
    )  # 24 until RC-UAT-19 added carrier_links (2026-10-22)
    for entry in body["timeline"]:
        assert set(entry) <= set(PublicTimelineEntry.model_fields)
        assert "event_type" not in entry
    assert NOTE not in public.text and HIDDEN not in public.text


# --- Quote email resend -------------------------------------------------------------------------


def _resend(offer_id):
    return f"/api/v1/quote-offers/{offer_id}/resend-email"


def _failed(db, shipment):
    _finalize(db, shipment)
    offer = _send(db, shipment)
    account_email_service.set_transport(Broken())
    try:
        assert qos.send_email(db, offer.id) == "failed"
    finally:
        account_email_service.reset_transport()
    return offer.id


def test_a_failed_quote_email_resends_once_to_the_current_address(
    api_for, db, priced_world, captured_mail
):
    _con, kids = priced_world
    offer_id = _failed(db, kids[0])
    account_email_service.set_transport(captured_mail)
    see_committed_changes(db)
    admin = api_for("admin")
    changed = admin.patch(
        f"/api/v1/customers/{kids[0].customer_id}", json={"email": "p15.new.addr@demo.example.com"}
    )
    assert changed.status_code == 200, changed.text

    ops = api_for("operations")
    before = len(captured_mail.messages)
    first = ops.post(_resend(offer_id))
    second = ops.post(_resend(offer_id))
    assert first.status_code == 200, first.text
    assert first.json()["email_status"] == "sent"
    assert second.status_code == 409
    sent = captured_mail.messages[before:]
    assert [m["to_email"] for m in sent] == ["p15.new.addr@demo.example.com"]
    see_committed_changes(db)
    audits = db.query(AuditEvent).filter_by(action="quote.email_resent").all()
    assert len(audits) == 1 and str(audits[0].entity_id) == str(offer_id)
    assert json.loads(audits[0].detail_json)["previous_email_status"] == "failed"


def test_a_resend_pressed_while_another_is_in_flight_sends_nothing(
    api_for, db, priced_world, captured_mail
):
    _con, kids = priced_world
    offer_id = _failed(db, kids[0])
    account_email_service.set_transport(captured_mail)
    qos.prepare_resend(db, db.get(QuoteOffer, offer_id), actor=None)  # the first press's claim
    db.commit()
    before = len(captured_mail.messages)
    assert api_for("operations").post(_resend(offer_id)).status_code == 409
    assert len(captured_mail.messages) == before


def test_marketing_and_read_only_cannot_resend(api_for, db, priced_world, captured_mail):
    _con, kids = priced_world
    offer_id = _failed(db, kids[0])
    account_email_service.set_transport(captured_mail)
    for role in ("marketing", "read_only_manager"):
        assert api_for(role).post(_resend(offer_id)).status_code == 403
    see_committed_changes(db)
    assert db.get(QuoteOffer, offer_id).email_status == "failed"
    assert captured_mail.messages == []
    assert db.query(AuditEvent).filter_by(action="quote.email_resent").count() == 0


def test_a_customer_account_session_cannot_resend(
    account_client, account_db, account_users, captured_mail
):
    from tests.test_account_profile import _customer, _setup

    _reference, me = _setup(account_client, account_users, captured_mail)
    kids = _account_world(account_db, _customer(account_db))
    offer_id = _failed(account_db, kids[2])
    account_email_service.set_transport(captured_mail)
    before = len(captured_mail.messages)
    refused = me.client.post(_resend(offer_id), headers=me.headers)
    assert refused.status_code in (401, 403), refused.text
    see_committed_changes(account_db)
    assert account_db.get(QuoteOffer, offer_id).email_status == "failed"
    assert len(captured_mail.messages) == before


# --- Accepted, not invoiced ---------------------------------------------------------------------

LIST = "/api/v1/finance/accepted-not-invoiced"


def _listed(api):
    response = api.get(LIST)
    assert response.status_code == 200, response.text
    return [
        (i["offer_id"], i["version"], i["superseded_by_version"]) for i in response.json()["items"]
    ]


def test_accepted_is_listed_until_invoiced_and_back_after_a_void(api_for, db, priced_world):
    _con, kids = priced_world
    accepted, declined, withdrawn = kids[2], kids[0], kids[1]
    _fee(db, accepted, quantity=1)
    for shipment in kids:
        _finalize(db, shipment)
    offers = {s.id: _send(db, s) for s in kids}
    identity = {s.id: _identity_for(db, db.get(Customer, s.customer_id)) for s in kids}
    qos.accept(db, offers[accepted.id], identity[accepted.id])
    qos.decline(db, offers[declined.id], identity[declined.id], reason="Too dear")
    qos.withdraw(db, offers[withdrawn.id], reason="Wrong weight", actor=None)
    db.commit()
    accepted_id = offers[accepted.id].id

    ops = api_for("operations")
    assert _listed(ops) == [(accepted_id, 1, None)]
    # Owner decision 9a: acceptance prepared a draft; sending it issues the invoice.
    draft = ops.get(f"/api/v1/shipments/{accepted.id}/invoice-draft").json()
    # RC-UAT-19: staff confirm the draft's GST/HST before Send.
    confirm = {"expected_revision": 1, "tax_confirmed": True}
    assert ops.patch(f"/api/v1/invoice-drafts/{draft['id']}", json=confirm).status_code == 200
    sent = ops.post(f"/api/v1/invoice-drafts/{draft['id']}/send", json={"expected_revision": 1})
    assert sent.status_code == 200, sent.text
    issued = ops.get(f"/api/v1/invoices/{sent.json()['invoice_id']}")
    assert _listed(ops) == []
    admin = api_for("admin")
    voided = admin.post(f"/api/v1/invoices/{issued.json()['id']}/void", json={"reason": "Tax"})
    assert voided.status_code == 200, voided.text
    assert _listed(admin) == [(accepted_id, 1, None)]


def test_a_superseded_acceptance_stays_listed_and_flagged_then_the_new_one_replaces_it(
    api_for, db, priced_world
):
    _con, kids = priced_world
    shipment = kids[2]
    identity = _identity_for(db, db.get(Customer, shipment.customer_id))
    _finalize(db, shipment)
    first = _send(db, shipment)
    qos.accept(db, first, identity)
    db.commit()
    _fee(db, shipment, quantity=1)
    _finalize(db, shipment)  # a newer price after the customer said yes
    ops = api_for("operations")
    assert _listed(ops) == [(first.id, 1, 2)]  # flagged: agree the price first

    second = _send(db, shipment)
    qos.accept(db, second, identity)
    db.commit()
    assert _listed(ops) == [(second.id, 2, None)]  # one row per shipment, the latest


def test_a_cancelled_booking_is_not_listed(api_for, db, priced_world):
    _con, kids = priced_world
    shipment = kids[2]
    _finalize(db, shipment)
    offer = _send(db, shipment)
    qos.accept(db, offer, _identity_for(db, db.get(Customer, shipment.customer_id)))
    db.commit()
    ops = api_for("operations")
    assert [o for o, _v, _s in _listed(ops)] == [offer.id]
    cancelled = ops.post(f"/api/v1/shipments/{shipment.id}/cancel", json={"reason": "Gone"})
    assert cancelled.status_code == 200, cancelled.text
    assert _listed(ops) == []


# --- Tariff approver pending count --------------------------------------------------------------

COUNT = "/api/v1/tariffs/intake/pending-count"


@pytest.fixture
def intake_folder(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "tariff_intake_dir", str(tmp_path / "intake"))


def _counts(api):
    response = api.get(COUNT)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == body["drafts_awaiting"] + body["held_senders"]
    return body["viewer_is_approver"], body["drafts_awaiting"], body["held_senders"]


def test_the_approver_sees_drafts_and_held_intakes_counted(
    db, intake_folder, admin_is_tariff_approver, as_admin
):
    from tests.test_tariff_intake import WORKBOOK, build_eml, ingest
    from tests.test_tariff_intake_review import manual_draft

    assert _counts(as_admin) == (True, 0, 0)
    held = ingest(db, build_eml([("rates.xlsx", WORKBOOK.read_bytes())])).intake
    see_committed_changes(db)
    assert _counts(as_admin) == (True, 0, 1)

    # Released, the held email becomes one draft awaiting a decision (and is no longer held).
    released = as_admin.post(f"/api/v1/tariffs/intake/{held.id}/release")
    assert released.status_code == 200, released.text
    draft_id = released.json()["tariff_version_id"]
    assert _counts(as_admin) == (True, 1, 0)

    # The same workbook uploaded by hand is a duplicate, not a second draft to review.
    try:
        manual_draft(db, WORKBOOK.read_bytes())
    except Exception:  # noqa: BLE001 - refused is as good as deduplicated here
        db.rollback()
    see_committed_changes(db)
    assert _counts(as_admin)[1] == 1

    assert as_admin.post(f"/api/v1/tariffs/versions/{draft_id}/approve").status_code == 200
    assert _counts(as_admin) == (True, 0, 0)


def test_a_non_approver_admin_and_operations_are_not_the_approver(
    db, intake_folder, users, api_for
):
    from app.services import tariff_intake_service as svc
    from tests.test_tariff_intake import WORKBOOK, build_eml, ingest

    svc.update_settings(db, approver_emails=["owner@demo.example.com"], actor=None)
    db.commit()
    ingest(db, build_eml([("rates.xlsx", WORKBOOK.read_bytes())]))
    see_committed_changes(db)
    for role in ("admin", "operations"):
        viewer_is_approver, _drafts, _held = _counts(api_for(role))
        assert viewer_is_approver is False, role
    for role in ("marketing", "read_only_manager"):
        assert api_for(role).get(COUNT).status_code == 403
