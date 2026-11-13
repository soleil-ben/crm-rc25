"""Phase 13F milestone notifications (OD-72): queue, dedup, choices, suppressions, capture."""

from __future__ import annotations

import pytest

from app.core.enums import ConsentChannel, RouteGroup, ShipmentEventType
from app.models import NotificationOutbox
from app.services import account_email_service, consent_service, event_service
from app.services import notification_service as ns
from tests.conftest import booked_shipment, make_customer


def _publish(db, shipment, event_type, text="Update"):
    created = event_service.record_event(
        db,
        shipment,
        {"event_type": event_type, "is_public_update": True, "public_update_text": text},
    )
    db.commit()
    return created


@pytest.fixture
def shipment(db):
    customer = make_customer(db, email="notify.me@demo.example.com")
    return booked_shipment(db, customer, RouteGroup.VCA)


def _rows(db, shipment_id):
    return db.query(NotificationOutbox).filter_by(shipment_id=shipment_id).all()


def test_a_published_milestone_queues_one_email_and_capture_receives_it(
    db, shipment, captured_mail
):
    _publish(db, shipment, ShipmentEventType.RECEIVED_AT_SOLARIS)
    rows = _rows(db, shipment.id)
    assert [(r.milestone, r.status) for r in rows] == [("received", "queued")]
    assert ns.dispatch_pending(db) == 1
    db.commit()
    assert rows[0].status == "sent" and rows[0].transport == "capture"
    message = captured_mail.messages[-1]
    # Vietnamese first (OD-71): the customer's language is not English.
    assert message["template_key"] == "notify.received.vi"
    assert shipment.public_id in message["body"] and shipment.public_id in message["subject"]
    assert "notify.me@demo.example.com" not in str(rows[0].__dict__)


def test_unpublished_and_non_milestone_events_notify_nobody(db, shipment):
    event_service.record_event(db, shipment, {"event_type": ShipmentEventType.IN_TRANSIT})
    _publish(db, shipment, ShipmentEventType.CUSTOMS_PROCESSING)
    db.commit()
    assert _rows(db, shipment.id) == []


def test_each_milestone_notifies_once_whatever_repeats(db, shipment):
    _publish(db, shipment, ShipmentEventType.DEPARTED_ORIGIN)
    _publish(db, shipment, ShipmentEventType.IN_TRANSIT)
    _publish(db, shipment, ShipmentEventType.IN_TRANSIT, "Again")
    assert [r.milestone for r in _rows(db, shipment.id)] == ["in_transit"]
    _publish(db, shipment, ShipmentEventType.OUT_FOR_DELIVERY)
    _publish(db, shipment, ShipmentEventType.DELIVERED_TO_RECIPIENT)
    assert sorted(r.milestone for r in _rows(db, shipment.id)) == [
        "delivered",
        "in_transit",
        "out_for_delivery",
    ]


def test_an_opted_out_milestone_is_skipped_and_the_others_still_go(db, shipment):
    from app.models import Customer

    customer = db.get(Customer, shipment.customer_id)
    ns.set_preferences(db, customer, {"received": False}, via="account")
    db.commit()
    assert ns.preferences_for(db, customer.id) == {
        "received": False,
        "in_transit": True,
        "out_for_delivery": True,
        "delivered": True,
    }
    _publish(db, shipment, ShipmentEventType.RECEIVED_AT_SOLARIS)
    _publish(db, shipment, ShipmentEventType.IN_TRANSIT)
    ns.dispatch_pending(db)
    db.commit()
    outcome = {r.milestone: (r.status, r.skip_reason) for r in _rows(db, shipment.id)}
    assert outcome == {"received": ("skipped", "opted_out"), "in_transit": ("recorded", None)}


def test_a_suppressed_address_is_never_notified(db, shipment):
    consent_service.add_suppression(
        db,
        channel=ConsentChannel.EMAIL,
        address_value="notify.me@demo.example.com",
        reason="Customer asked",
        actor=None,
    )
    db.commit()
    _publish(db, shipment, ShipmentEventType.RECEIVED_AT_SOLARIS)
    ns.dispatch_pending(db)
    db.commit()
    assert [(r.status, r.skip_reason) for r in _rows(db, shipment.id)] == [
        ("skipped", "suppressed")
    ]


def test_english_customers_get_english_and_choices_are_validated(db):
    customer = make_customer(db, email="en.customer@demo.example.com", preferred_language="en")
    shipment = booked_shipment(db, customer, RouteGroup.VCA)
    _publish(db, shipment, ShipmentEventType.RECEIVED_AT_SOLARIS)
    assert _rows(db, shipment.id)[0].template_key == "notify.received.en"
    with pytest.raises(Exception, match="Choose among"):
        ns.set_preferences(db, customer, {"customs": False}, via="account")


def test_a_transport_fault_is_failed_retried_and_capped(db, shipment, monkeypatch):
    class Broken:
        name = "capture"

        def send(self, message):
            raise OSError("disk full")

    account_email_service.set_transport(Broken())
    try:
        _publish(db, shipment, ShipmentEventType.RECEIVED_AT_SOLARIS)
        for _ in range(ns.MAX_ATTEMPTS + 2):
            ns.dispatch_pending(db)
        db.commit()
        row = _rows(db, shipment.id)[0]
        assert (row.status, row.attempts, row.last_error) == ("failed", ns.MAX_ATTEMPTS, "OSError")
    finally:
        account_email_service.reset_transport()
    ns.retry(db, row, actor=None)
    db.commit()
    ns.dispatch_pending(db)
    db.refresh(row)
    assert row.status == "recorded"


def test_the_message_carries_only_the_reference_and_the_tracking_link():
    template = account_email_service.TEMPLATES["notify.delivered.en"]
    assert template.parameters == frozenset({"shipment_reference", "tracking_url"})
    for language in ("en", "vi"):
        for milestone in ns.MILESTONES:
            assert ns.template_key(milestone, language) in account_email_service.TEMPLATES


def test_staff_read_the_outbox_and_only_tracking_writers_retry(api_for, db, shipment):
    _publish(db, shipment, ShipmentEventType.RECEIVED_AT_SOLARIS)
    row = _rows(db, shipment.id)[0]
    row.status, row.attempts = "failed", 1
    db.commit()
    marketing = api_for("marketing")
    listed = marketing.get("/api/v1/notifications")
    assert listed.status_code == 200 and listed.json()["total"] == 1
    body = listed.text.lower()
    assert "notify.me@demo.example.com" not in body and "track it here" not in body
    assert marketing.post(f"/api/v1/notifications/{row.id}/retry").status_code == 403
    ops = api_for("operations")
    retried = ops.post(f"/api/v1/notifications/{row.id}/retry")
    assert retried.status_code == 200 and retried.json()["status"] == "recorded"
    changed = ops.patch(
        f"/api/v1/customers/{shipment.customer_id}/notification-preferences",
        json={"preferences": {"delivered": False}},
    )
    assert changed.status_code == 200 and changed.json()["preferences"]["delivered"] is False


def test_recording_a_milestone_over_http_dispatches_it(api_for, db, shipment):
    ops = api_for("operations")
    response = ops.post(
        f"/api/v1/shipments/{shipment.id}/events",
        json={
            "event_type": "received_at_solaris",
            "is_public_update": True,
            "public_update_text": "Received",
        },
    )
    assert response.status_code == 201, response.text
    db.expire_all()
    db.rollback()
    assert [r.status for r in _rows(db, shipment.id)] == ["recorded"]


# --- Customer Account ---------------------------------------------------------------------------


def test_a_customer_reads_and_changes_their_choices_and_sees_history(
    account_client, account_db, account_users, captured_mail
):
    from tests.test_account_profile import _customer, _setup

    _reference, customer_session = _setup(account_client, account_users, captured_mail)
    customer = _customer(account_db)
    shipment = booked_shipment(account_db, customer, RouteGroup.VCA)
    _publish(account_db, shipment, ShipmentEventType.RECEIVED_AT_SOLARIS)
    ns.dispatch_pending(account_db)
    account_db.commit()

    read = customer_session.get("/notifications")
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["channel"] == "email"
    assert body["preferences"] == {
        "received": True,
        "in_transit": True,
        "out_for_delivery": True,
        "delivered": True,
    }
    assert [(h["milestone"], h["state"]) for h in body["history"]] == [("received", "sent")]
    assert body["history"][0]["shipment_reference"] == shipment.public_id
    for forbidden in ("skip_reason", "template_key", "transport", "attempts", "@"):
        assert forbidden not in read.text

    changed = customer_session.post(
        "/notifications/preferences", {"preferences": {"delivered": False}}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["preferences"]["delivered"] is False
    refused = customer_session.post("/notifications/preferences", {"preferences": {"x": True}})
    assert refused.status_code in (400, 422)


# --- Independent review, 2026-10-20 -------------------------------------------------------------


def _package_events(db, shipment, event_type, package):
    created = event_service.record_event(
        db,
        shipment,
        {
            "event_type": event_type,
            "package_id": package.id,
            "is_public_update": True,
            "public_update_text": "Update",
        },
    )
    db.commit()
    return created


def test_delivered_waits_for_the_whole_shipment_and_a_collection_point_is_not_delivery(db):
    from app.services import package_service

    customer = make_customer(db, email="multi@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=3)
    packages = package_service.active_packages(db, shipment.id)
    _publish(db, shipment, ShipmentEventType.DELIVERED_TO_COLLECTION_POINT)
    assert _rows(db, shipment.id) == []
    _package_events(db, shipment, ShipmentEventType.DELIVERED_TO_RECIPIENT, packages[0])
    assert [r.milestone for r in _rows(db, shipment.id)] == []  # one of three
    for package in packages[1:]:
        _package_events(db, shipment, ShipmentEventType.DELIVERED_TO_RECIPIENT, package)
    assert [r.milestone for r in _rows(db, shipment.id)] == ["delivered"]


def test_voiding_withdraws_an_unsent_notification_and_the_real_one_still_goes(db, shipment):
    created = _publish(db, shipment, ShipmentEventType.OUT_FOR_DELIVERY)
    event_service.void_event(db, created[0], reason="Recorded on the wrong shipment")
    db.commit()
    first = _rows(db, shipment.id)[0]
    assert (first.status, first.skip_reason) == ("skipped", "voided")
    _publish(db, shipment, ShipmentEventType.OUT_FOR_DELIVERY, "Corrected")
    live = [r for r in _rows(db, shipment.id) if r.status == "queued"]
    assert [r.milestone for r in live] == ["out_for_delivery"]


def test_a_late_step_behind_the_shipment_notifies_nothing(db, shipment):
    from datetime import timedelta

    from app.core.time_utils import utcnow

    _publish(db, shipment, ShipmentEventType.OUT_FOR_DELIVERY)
    event_service.record_event(
        db,
        shipment,
        {
            "event_type": ShipmentEventType.RECEIVED_AT_SOLARIS,
            "is_public_update": True,
            "public_update_text": "Backdated",
            "occurred_at": utcnow() - timedelta(days=3),
        },
    )
    db.commit()
    assert [r.milestone for r in _rows(db, shipment.id)] == ["out_for_delivery"]


def test_one_bad_row_does_not_block_the_rest(db, shipment, monkeypatch):
    other = booked_shipment(db, make_customer(db, email="other@demo.example.com"), RouteGroup.VCA)
    _publish(db, shipment, ShipmentEventType.RECEIVED_AT_SOLARIS)
    _publish(db, other, ShipmentEventType.RECEIVED_AT_SOLARIS)
    real = ns._tracking_url

    def flaky(db_, s):
        if s.id == shipment.id:
            raise RuntimeError("boom")
        return real(db_, s)

    monkeypatch.setattr(ns, "_tracking_url", flaky)
    ns.dispatch_pending(db)
    db.rollback()
    assert _rows(db, shipment.id)[0].status == "failed"
    assert _rows(db, other.id)[0].status == "recorded"


def test_the_account_language_wins_and_a_null_transport_is_not_called_sent(
    account_client, account_db, account_users, captured_mail
):
    from app.models import CustomerIdentity
    from tests.test_account_profile import _customer, _setup

    _reference, session = _setup(account_client, account_users, captured_mail)
    customer = _customer(account_db)
    identity = account_db.query(CustomerIdentity).one()
    identity.preferred_language = "en"
    account_db.commit()
    shipment = booked_shipment(account_db, customer, RouteGroup.VCA)
    _publish(account_db, shipment, ShipmentEventType.RECEIVED_AT_SOLARIS)
    assert _rows(account_db, shipment.id)[0].template_key == "notify.received.en"
    account_email_service.set_transport(account_email_service.NullEmailTransport())
    try:
        ns.dispatch_pending(account_db)
    finally:
        account_email_service.reset_transport()
    history = session.get("/notifications").json()["history"]
    assert [(h["milestone"], h["state"]) for h in history] == [("received", "not_sent")]


def test_a_withdrawn_milestone_is_not_in_the_customers_history(db, shipment):
    created = _publish(db, shipment, ShipmentEventType.OUT_FOR_DELIVERY)
    event_service.void_event(db, created[0], reason="Wrong shipment")
    db.commit()
    assert ns.history_for_customer(db, shipment.customer_id) == []


def test_voiding_one_packages_event_keeps_the_shipments_notification(db):
    """Review 2026-10-20: a milestone recorded on every package is one notification; voiding the
    event that queued it moves it to another package's standing event instead of losing it."""
    from app.services import package_service

    customer = make_customer(db, email="twopack@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=2)
    first, second = package_service.active_packages(db, shipment.id)
    a = _package_events(db, shipment, ShipmentEventType.OUT_FOR_DELIVERY, first)
    b = _package_events(db, shipment, ShipmentEventType.OUT_FOR_DELIVERY, second)
    (row,) = _rows(db, shipment.id)
    assert row.event_id == a[0].id
    event_service.void_event(db, a[0], reason="Wrong package")
    db.commit()
    (row,) = _rows(db, shipment.id)
    assert (row.status, row.event_id) == ("queued", b[0].id)
    ns.dispatch_pending(db)
    db.rollback()
    assert _rows(db, shipment.id)[0].status == "recorded"


def test_a_failed_outcome_write_does_not_stop_the_batch(db, shipment, monkeypatch):
    other = booked_shipment(db, make_customer(db, email="other2@demo.example.com"), RouteGroup.VCA)
    _publish(db, shipment, ShipmentEventType.RECEIVED_AT_SOLARIS)
    _publish(db, other, ShipmentEventType.RECEIVED_AT_SOLARIS)
    real = ns._record
    target = _rows(db, shipment.id)[0].id

    def broken(db_, outbox_id, now, **fields):
        if outbox_id == target:
            raise RuntimeError("database is locked")
        return real(db_, outbox_id, now, **fields)

    monkeypatch.setattr(ns, "_record", broken)
    assert ns.dispatch_pending(db) == 2
    db.rollback()
    assert _rows(db, shipment.id)[0].status == "sending"  # reclaimed after CLAIM_TIMEOUT
    assert _rows(db, other.id)[0].status == "recorded"
