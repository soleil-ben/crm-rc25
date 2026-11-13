"""Phase 13F milestone notifications -- independent golden scenarios (OD-71, OD-72).

Written by the independent tester from the owner's requirements of 2026-10-20, not from the
implementation. Each test states the rule it checks. Test capture only: the transports are the
``null`` default and the ``captured_mail`` fixture; nothing reaches a real customer.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from app.core.enums import ConsentChannel, Role, RouteGroup, ShipmentEventType
from app.core.time_utils import utcnow
from app.models import Customer, CustomerIdentity, NotificationOutbox, ShipmentEvent
from app.services import account_email_service, consent_service, event_service, package_service
from app.services import consolidation_service as cs
from app.services import notification_service as ns
from tests.account_fixtures import csrf_headers, register, sign_in, verification_token, verify
from tests.approval_fixtures import acknowledged_preview, approve_create, staff
from tests.conftest import booked_shipment, make_customer, see_committed_changes

E = ShipmentEventType
ALL_ON = {"received": True, "in_transit": True, "out_for_delivery": True, "delivered": True}
INTERNAL_WORDS = ("opted_out", "suppressed", "no_email", "voided", "skip_reason", "notify.")


# --- helpers ------------------------------------------------------------------------------------


def _record(db, shipment, event_type, *, published=True, package=None, **extra):
    payload = {"event_type": event_type, "is_public_update": published}
    if published:
        payload["public_update_text"] = "Update"
    if package is not None:
        payload["package_id"] = package.id
    payload.update(extra)
    created = event_service.record_event(db, shipment, payload)
    db.commit()
    return created


def _rows(db, shipment_id):
    return (
        db.query(NotificationOutbox)
        .filter_by(shipment_id=shipment_id)
        .order_by(NotificationOutbox.id)
        .all()
    )


def _live(db, shipment_id):
    """Rows that will still go or went: not withdrawn."""
    return [r for r in _rows(db, shipment_id) if r.skip_reason != "voided"]


def _messages(mail, template_prefix):
    return [m for m in mail.messages if m["template_key"].startswith(template_prefix)]


@pytest.fixture
def customer(db):
    return make_customer(db, email="golden.customer@demo.example.com")


@pytest.fixture
def shipment(db, customer):
    return booked_shipment(db, customer, RouteGroup.VCA)


# --- Milestone mapping: which published events notify which milestone ---------------------------


@pytest.mark.parametrize(
    ("steps", "expected"),
    [
        ([E.RECEIVED_AT_SOLARIS], ["received"]),
        ([E.DEPARTED_ORIGIN], ["in_transit"]),
        ([E.IN_TRANSIT], ["in_transit"]),
        ([E.OUT_FOR_DELIVERY], ["out_for_delivery"]),
        ([E.DELIVERED_TO_RECIPIENT], ["delivered"]),
        ([E.CUSTOMS_PROCESSING], []),
        ([E.ARRIVED_DESTINATION], []),
        ([E.DELIVERED_TO_COLLECTION_POINT], []),
    ],
)
def test_each_published_event_maps_to_its_milestone(db, shipment, steps, expected):
    for step in steps:
        _record(db, shipment, step)
    assert [r.milestone for r in _rows(db, shipment.id)] == expected


def test_the_full_journey_notifies_four_milestones_once_each(db, shipment, captured_mail):
    for step in (
        E.RECEIVED_AT_SOLARIS,
        E.DEPARTED_ORIGIN,
        E.IN_TRANSIT,
        E.CUSTOMS_PROCESSING,
        E.ARRIVED_DESTINATION,
        E.OUT_FOR_DELIVERY,
        E.DELIVERED_TO_RECIPIENT,
    ):
        _record(db, shipment, step)
        ns.dispatch_pending(db)
        db.commit()
    rows = _rows(db, shipment.id)
    assert [r.milestone for r in rows] == [
        "received",
        "in_transit",
        "out_for_delivery",
        "delivered",
    ]
    assert all(r.status == "sent" for r in rows)
    assert [m["template_key"] for m in _messages(captured_mail, "notify.")] == [
        "notify.received.vi",
        "notify.in_transit.vi",
        "notify.out_for_delivery.vi",
        "notify.delivered.vi",
    ]
    assert all(m["to_email"] == "golden.customer@demo.example.com" for m in captured_mail.messages)


# --- Only published events ----------------------------------------------------------------------


def test_an_unpublished_milestone_notifies_nothing_and_a_later_published_one_does(db, shipment):
    _record(db, shipment, E.RECEIVED_AT_SOLARIS, published=False)
    assert _rows(db, shipment.id) == []
    _record(db, shipment, E.RECEIVED_AT_SOLARIS, published=True)
    assert [(r.milestone, r.status) for r in _rows(db, shipment.id)] == [("received", "queued")]


def test_unpublished_delivery_of_the_whole_shipment_notifies_nothing(db, shipment):
    _record(db, shipment, E.OUT_FOR_DELIVERY, published=False)
    _record(db, shipment, E.DELIVERED_TO_RECIPIENT, published=False)
    assert _rows(db, shipment.id) == []


# --- Dedup ---------------------------------------------------------------------------------------


def test_one_notification_per_shipment_and_milestone(db, shipment, captured_mail):
    for _ in range(3):
        _record(db, shipment, E.RECEIVED_AT_SOLARIS)
        ns.dispatch_pending(db)
        db.commit()
    _record(db, shipment, E.DEPARTED_ORIGIN)
    _record(db, shipment, E.IN_TRANSIT)
    _record(db, shipment, E.DEPARTED_ORIGIN)
    ns.dispatch_pending(db)
    db.commit()
    assert sorted(r.milestone for r in _rows(db, shipment.id)) == ["in_transit", "received"]
    assert len(_messages(captured_mail, "notify.received")) == 1
    assert len(_messages(captured_mail, "notify.in_transit")) == 1


def test_two_shipments_of_one_customer_each_notify(db, customer):
    first = booked_shipment(db, customer, RouteGroup.VCA)
    second = booked_shipment(db, customer, RouteGroup.VCA)
    _record(db, first, E.RECEIVED_AT_SOLARIS)
    _record(db, second, E.RECEIVED_AT_SOLARIS)
    assert len(_rows(db, first.id)) == 1 and len(_rows(db, second.id)) == 1


# --- Master milestone fan-out -------------------------------------------------------------------


@pytest.fixture
def master(db):
    customers = [make_customer(db, email=f"member{i}@demo.example.com") for i in range(3)]
    members = [booked_shipment(db, c, RouteGroup.VCA) for c in customers]
    con = cs.create_consolidation(
        db,
        {
            "solaris_service": "air_standard",
            "origin": "HCM",
            "vendor_reference": "GOLD1",
            "actual_weight_kg": "21",
            "length_cm": "60",
            "width_cm": "40",
            "height_cm": "40",
        },
        actor=None,
    )
    db.commit()
    for shipment in members:
        cs.add_member(db, con, shipment, actor=None)
    db.commit()
    return con, members


def test_a_master_milestone_notifies_each_member_once_and_only_its_own_customer(
    db, master, captured_mail
):
    con, members = master
    payload = {
        "event_type": E.DEPARTED_ORIGIN,
        "is_public_update": True,
        "public_update_text": "Departed",
    }
    result = cs.record_master_event(db, con, dict(payload), actor=None)
    db.commit()
    assert len(result["applied"]) == 3
    for shipment in members:
        rows = _rows(db, shipment.id)
        assert [(r.milestone, r.customer_id) for r in rows] == [
            ("in_transit", shipment.customer_id)
        ]
    # The same master milestone again, and an in-transit one: still one per member.
    cs.record_master_event(db, con, dict(payload), actor=None)
    cs.record_master_event(db, con, dict(payload, event_type=E.IN_TRANSIT), actor=None)
    db.commit()
    assert all(len(_rows(db, s.id)) == 1 for s in members)
    ns.dispatch_pending(db)
    db.commit()
    sent = _messages(captured_mail, "notify.in_transit")
    assert len(sent) == 3
    by_address = {m["to_email"]: m for m in sent}
    for i, shipment in enumerate(members):
        message = by_address[f"member{i}@demo.example.com"]
        assert shipment.public_id in message["body"]
        for other in members:
            if other is not shipment:
                assert other.public_id not in message["body"]
        assert con.public_id not in message["body"]


def test_an_unpublished_master_milestone_notifies_no_member(db, master):
    con, members = master
    cs.record_master_event(db, con, {"event_type": E.DEPARTED_ORIGIN}, actor=None)
    db.commit()
    assert all(_rows(db, s.id) == [] for s in members)


def test_a_master_milestone_over_http_dispatches_for_every_member(db, master, api_for):
    con, members = master
    ops = api_for(Role.OPERATIONS)
    response = ops.post(
        f"/api/v1/consolidations/{con.id}/events",
        json={
            "event_type": "departed_origin",
            "is_public_update": True,
            "public_update_text": "Departed",
        },
    )
    assert response.status_code == 201, response.text
    see_committed_changes(db)
    for shipment in members:
        # Null transport in this suite: noted, not sent to anybody.
        assert [(r.milestone, r.status) for r in _rows(db, shipment.id)] == [
            ("in_transit", "recorded")
        ]


# --- Delivery: whole shipment, not a package, not a collection point -----------------------------


def test_partial_delivery_by_package_waits_for_the_last_package(db, customer, captured_mail):
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=2)
    first, second = package_service.active_packages(db, shipment.id)
    _record(db, shipment, E.OUT_FOR_DELIVERY)
    _record(db, shipment, E.DELIVERED_TO_RECIPIENT, package=first)
    assert [r.milestone for r in _rows(db, shipment.id)] == ["out_for_delivery"]
    _record(db, shipment, E.DELIVERED_TO_RECIPIENT, package=second)
    ns.dispatch_pending(db)
    db.commit()
    assert [r.milestone for r in _rows(db, shipment.id)] == ["out_for_delivery", "delivered"]
    assert len(_messages(captured_mail, "notify.delivered")) == 1


def test_a_collection_point_handover_is_not_delivery(db, customer):
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=2)
    first, second = package_service.active_packages(db, shipment.id)
    _record(db, shipment, E.DELIVERED_TO_COLLECTION_POINT)
    _record(db, shipment, E.DELIVERED_TO_RECIPIENT, package=first)
    _record(db, shipment, E.DELIVERED_TO_COLLECTION_POINT, package=second)
    assert "delivered" not in [r.milestone for r in _rows(db, shipment.id)]


# --- Voided, then recorded again ----------------------------------------------------------------


def test_voiding_an_unsent_milestone_withdraws_it_and_the_corrected_one_goes(
    db, shipment, captured_mail
):
    wrong = _record(db, shipment, E.RECEIVED_AT_SOLARIS)
    event_service.void_event(db, wrong[0], reason="Wrong shipment")
    db.commit()
    assert [(r.status, r.skip_reason) for r in _rows(db, shipment.id)] == [("skipped", "voided")]
    ns.dispatch_pending(db)
    db.commit()
    assert _messages(captured_mail, "notify.") == []  # the withdrawn one never goes

    _record(db, shipment, E.RECEIVED_AT_SOLARIS)
    ns.dispatch_pending(db)
    db.commit()
    live = _live(db, shipment.id)
    assert [(r.milestone, r.status) for r in live] == [("received", "sent")]
    assert len(_messages(captured_mail, "notify.received")) == 1


def test_voiding_after_a_failed_try_also_withdraws_it(db, shipment, captured_mail):
    wrong = _record(db, shipment, E.OUT_FOR_DELIVERY)
    row = _rows(db, shipment.id)[0]
    row.status, row.attempts = "failed", 1
    db.commit()
    event_service.void_event(db, wrong[0], reason="Wrong shipment")
    db.commit()
    ns.dispatch_pending(db)
    db.commit()
    assert _messages(captured_mail, "notify.") == []
    _record(db, shipment, E.OUT_FOR_DELIVERY)
    assert [r.status for r in _live(db, shipment.id)] == ["queued"]


def test_voiding_a_sent_milestone_keeps_it_as_history_and_sends_no_second(
    db, shipment, captured_mail
):
    first = _record(db, shipment, E.RECEIVED_AT_SOLARIS)
    ns.dispatch_pending(db)
    db.commit()
    event_service.void_event(db, first[0], reason="Corrected time")
    db.commit()
    assert [r.status for r in _rows(db, shipment.id)] == ["sent"]
    _record(db, shipment, E.RECEIVED_AT_SOLARIS)
    ns.dispatch_pending(db)
    db.commit()
    assert len(_messages(captured_mail, "notify.received")) == 1


# --- Late and backdated steps -------------------------------------------------------------------


def test_a_step_behind_the_shipment_status_notifies_nothing(db, shipment):
    # Status follows the latest event in time, so the late step is entered backdated, as staff
    # would when catching up on paperwork after the shipment has moved on.
    _record(db, shipment, E.IN_TRANSIT, published=False)
    _record(db, shipment, E.RECEIVED_AT_SOLARIS, occurred_at=utcnow() - timedelta(days=1))
    assert shipment.operational_state == "in_transit"
    assert _rows(db, shipment.id) == []


def test_a_backdated_step_after_delivery_notifies_nothing(db, shipment):
    _record(db, shipment, E.DELIVERED_TO_RECIPIENT)
    _record(
        db,
        shipment,
        E.OUT_FOR_DELIVERY,
        occurred_at=utcnow() - timedelta(days=2),
    )
    _record(db, shipment, E.IN_TRANSIT, occurred_at=utcnow() - timedelta(days=4))
    assert [r.milestone for r in _rows(db, shipment.id)] == ["delivered"]


# --- Preferences: opt-out per milestone, default on ---------------------------------------------


def test_no_saved_choice_means_every_milestone_is_on(db, customer):
    assert ns.preferences_for(db, customer.id) == ALL_ON


@pytest.mark.parametrize("bad", [{"received": "yes"}, {"received": 1}, {}, {"customs": False}])
def test_choices_are_strictly_validated(db, customer, bad):
    with pytest.raises(Exception):  # noqa: B017 - the service's ValidationError
        ns.set_preferences(db, customer, bad, via="staff")


def test_a_customer_with_no_email_is_skipped_quietly(db):
    nobody = make_customer(db, email=None, phone="+1 416 555 0199")
    shipment = booked_shipment(db, nobody, RouteGroup.VCA)
    _record(db, shipment, E.RECEIVED_AT_SOLARIS)
    ns.dispatch_pending(db)
    db.commit()
    assert [(r.status, r.skip_reason) for r in _rows(db, shipment.id)] == [("skipped", "no_email")]


# --- Suppressions --------------------------------------------------------------------------------


def test_a_staff_suppression_blocks_milestones_and_a_release_lets_the_next_go(
    db, shipment, customer, captured_mail
):
    suppression = consent_service.suppress_address(
        db,
        customer,
        channel=ConsentChannel.EMAIL,
        evidence_reference="TICKET-1",
        reason="Customer asked us to stop",
    )
    db.commit()
    _record(db, shipment, E.RECEIVED_AT_SOLARIS)
    ns.dispatch_pending(db)
    db.commit()
    assert [(r.status, r.skip_reason) for r in _rows(db, shipment.id)] == [
        ("skipped", "suppressed")
    ]
    assert _messages(captured_mail, "notify.") == []
    suppression.released_at = utcnow()
    suppression.release_reason = "Customer asked again"
    db.commit()
    _record(db, shipment, E.IN_TRANSIT)
    ns.dispatch_pending(db)
    db.commit()
    assert [m["template_key"] for m in _messages(captured_mail, "notify.")] == [
        "notify.in_transit.vi"
    ]


def test_a_suppression_blocks_an_address_entered_in_mixed_case(db):
    # The block is on the normalized address; the entered spelling is the same address.
    customer = make_customer(db, email="Mixed.Case@Demo.Example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA)
    consent_service.suppress_address(
        db,
        customer,
        channel=ConsentChannel.EMAIL,
        evidence_reference="TICKET-2",
        reason="Bounced",
    )
    db.commit()
    _record(db, shipment, E.OUT_FOR_DELIVERY)
    ns.dispatch_pending(db)
    db.commit()
    assert _rows(db, shipment.id)[0].skip_reason == "suppressed"


# --- Language: account choice, else English customer, else Vietnamese ---------------------------


@pytest.mark.parametrize(
    ("customer_language", "expected"),
    [("en", "en"), ("vi", "vi"), ("unknown", "vi"), ("fr", "vi"), ("other", "vi")],
)
def test_without_an_account_the_customer_record_decides(
    db, customer_language, expected, captured_mail
):
    who = make_customer(
        db, email=f"lang.{customer_language}@demo.example.com", preferred_language=customer_language
    )
    shipment = booked_shipment(db, who, RouteGroup.VCA)
    _record(db, shipment, E.RECEIVED_AT_SOLARIS)
    ns.dispatch_pending(db)
    db.commit()
    row = _rows(db, shipment.id)[0]
    assert (row.language, row.template_key) == (expected, f"notify.received.{expected}")
    message = captured_mail.messages[-1]
    assert message["language"] == expected
    if expected == "vi":
        assert "Chúng tôi đã nhận lô hàng" in message["subject"]
        assert "Theo dõi tại đây" in message["body"]
    else:
        assert message["subject"].startswith("We have received your shipment")
    assert shipment.public_id in message["subject"]


# --- Customer Account: approved account helpers --------------------------------------------------

ACCOUNT = "/api/v1/account"
VI_APPLICANT = "lan.vi@demo.example.com"
EN_APPLICANT = "hanh@demo.example.com"


def _customer_body(language: str | None) -> dict:
    from tests.account_fixtures import REGISTRATION_BODY

    body = dict(REGISTRATION_BODY["customer"])
    if language is None:
        body.pop("preferred_language", None)
    else:
        body["preferred_language"] = language
    return body


def _approved_account(client, users, mail, address, language):
    """Register (in ``language``; ``None`` = not stated), verify, approve. Returns a signed-in
    account client wrapper: (get, post)."""
    response = register(client, email=address, customer=_customer_body(language))
    assert response.status_code == 200, response.text
    verify(client, verification_token(mail, address)).raise_for_status()
    signed = sign_in(client, address)
    assert signed.status_code == 200, signed.text
    reference = signed.json()["account_reference"]
    client.cookies.clear()
    api = staff(client, users[Role.OPERATIONS].email)
    fingerprint = acknowledged_preview(api, reference, "create_new")
    assert approve_create(api, reference, fingerprint).status_code == 200
    client.cookies.clear()
    return _Account(client, address)


class _Account:
    def __init__(self, client, address):
        self.client = client
        response = sign_in(client, address)
        assert response.status_code == 200, response.text
        self.headers = csrf_headers(response)

    def get(self, path):
        return self.client.get(f"{ACCOUNT}{path}")

    def post(self, path, body=None):
        return self.client.post(f"{ACCOUNT}{path}", json=body, headers=self.headers)


def _account_customer(db, address):
    see_committed_changes(db)
    return db.query(Customer).filter_by(email_normalized=address).one()


# --- OD-71: Vietnamese account emails for a Vietnamese registration ------------------------------


def test_a_registration_with_no_language_stated_is_vietnamese(
    account_client, account_db, captured_mail
):
    response = register(account_client, email=VI_APPLICANT, customer=_customer_body(None))
    assert response.status_code == 200, response.text
    see_committed_changes(account_db)
    identity = account_db.query(CustomerIdentity).filter_by(email_normalized=VI_APPLICANT).one()
    assert identity.preferred_language == "vi"


def test_a_vietnamese_registration_gets_its_verification_email_in_vietnamese(
    account_client, captured_mail
):
    response = register(account_client, email=VI_APPLICANT, customer=_customer_body("vi"))
    assert response.status_code == 200, response.text
    message = [m for m in captured_mail.messages if m["to_email"] == VI_APPLICANT][-1]
    assert message["template_key"] == account_email_service.TEMPLATE_VERIFY_EMAIL
    assert message["language"] == "vi", message["subject"]
    assert message["subject"] == "Xác nhận tài khoản Solaris Express của bạn"


def test_a_vietnamese_account_gets_approval_reset_and_milestones_in_vietnamese(
    account_client, account_db, account_users, captured_mail
):
    me = _approved_account(account_client, account_users, captured_mail, VI_APPLICANT, "vi")
    approved = [
        m
        for m in captured_mail.messages
        if m["template_key"] == account_email_service.TEMPLATE_ACCOUNT_APPROVED
    ][-1]
    assert approved["language"] == "vi"
    assert approved["subject"] == "Tài khoản Solaris Express của bạn đã sẵn sàng"

    assert me.get("/profile").json()["details"]["preferred_language"] == "vi"
    customer = _account_customer(account_db, VI_APPLICANT)
    shipment = booked_shipment(account_db, customer, RouteGroup.VCA)
    _record(account_db, shipment, E.RECEIVED_AT_SOLARIS)
    ns.dispatch_pending(account_db)
    account_db.commit()
    milestone = _messages(captured_mail, "notify.")[-1]
    assert milestone["template_key"] == "notify.received.vi"
    assert "Chúng tôi đã nhận lô hàng" in milestone["subject"]

    account_client.cookies.clear()
    forgot = account_client.post(f"{ACCOUNT}/password/forgot", json={"email": VI_APPLICANT})
    assert forgot.status_code == 200, forgot.text
    reset = [
        m
        for m in captured_mail.messages
        if m["template_key"] == account_email_service.TEMPLATE_PASSWORD_RESET
    ][-1]
    assert reset["language"] == "vi" and reset["subject"] == "Đặt mật khẩu Solaris Express mới"


@pytest.mark.parametrize(("registered", "chosen"), [("en", "vi"), ("vi", "en")])
def test_the_language_chosen_in_the_account_decides_the_milestone_email(
    account_client, account_db, account_users, captured_mail, registered, chosen
):
    """The account's chosen language is the one the account profile saves and shows."""
    address = VI_APPLICANT if registered == "vi" else EN_APPLICANT
    me = _approved_account(account_client, account_users, captured_mail, address, registered)
    changed = me.post("/profile/direct", {"preferred_language": chosen})
    assert changed.status_code == 200, changed.text
    assert me.get("/profile").json()["details"]["preferred_language"] == chosen
    customer = _account_customer(account_db, address)
    shipment = booked_shipment(account_db, customer, RouteGroup.VCA)
    _record(account_db, shipment, E.RECEIVED_AT_SOLARIS)
    row = _rows(account_db, shipment.id)[0]
    assert row.template_key == f"notify.received.{chosen}", (
        f"account chose {chosen}, notification queued as {row.template_key}"
    )


# --- Customer Account: opt-out route, history states, privacy -----------------------------------


def test_opting_out_through_the_account_skips_that_milestone_only(
    account_client, account_db, account_users, captured_mail
):
    me = _approved_account(account_client, account_users, captured_mail, VI_APPLICANT, "vi")
    first = me.get("/notifications")
    assert first.status_code == 200, first.text
    assert first.json()["preferences"] == ALL_ON and first.json()["history"] == []

    changed = me.post("/notifications/preferences", {"preferences": {"in_transit": False}})
    assert changed.status_code == 200, changed.text
    assert changed.json()["preferences"] == dict(ALL_ON, in_transit=False)

    for bad in (
        {"preferences": {"in_transit": "off"}},
        {"preferences": {}},
        {"preferences": {"in_transit": False}, "extra": 1},
        {"in_transit": False},
    ):
        refused = me.post("/notifications/preferences", bad)
        assert refused.status_code in (400, 422), (bad, refused.text)
    assert me.get("/notifications").json()["preferences"] == dict(ALL_ON, in_transit=False)

    customer = _account_customer(account_db, VI_APPLICANT)
    shipment = booked_shipment(account_db, customer, RouteGroup.VCA)
    _record(account_db, shipment, E.RECEIVED_AT_SOLARIS)
    _record(account_db, shipment, E.DEPARTED_ORIGIN)
    ns.dispatch_pending(account_db)
    account_db.commit()
    assert [m["template_key"] for m in _messages(captured_mail, "notify.")] == [
        "notify.received.vi"
    ]
    history = me.get("/notifications").json()["history"]
    assert sorted((h["milestone"], h["state"]) for h in history) == [
        ("in_transit", "not_sent"),
        ("received", "sent"),
    ]

    # Staff see the same saved choice, and turning it back on lets the next milestone go.
    see_committed_changes(account_db)
    assert ns.preferences_for(account_db, customer.id)["in_transit"] is False
    me.post("/notifications/preferences", {"preferences": {"in_transit": True}})
    see_committed_changes(account_db)
    _record(account_db, shipment, E.OUT_FOR_DELIVERY)
    ns.dispatch_pending(account_db)
    account_db.commit()
    assert _messages(captured_mail, "notify.")[-1]["template_key"] == "notify.out_for_delivery.vi"


def test_account_responses_never_show_reasons_keys_addresses_or_other_customers(
    account_client, account_db, account_users, captured_mail
):
    me = _approved_account(account_client, account_users, captured_mail, VI_APPLICANT, "vi")
    customer = _account_customer(account_db, VI_APPLICANT)
    mine = booked_shipment(account_db, customer, RouteGroup.VCA)
    other_customer = make_customer(account_db, email="stranger@demo.example.com")
    theirs = booked_shipment(account_db, other_customer, RouteGroup.VCA)

    me.post("/notifications/preferences", {"preferences": {"received": False}})
    see_committed_changes(account_db)
    _record(account_db, mine, E.RECEIVED_AT_SOLARIS)  # opted out
    _record(account_db, theirs, E.RECEIVED_AT_SOLARIS)
    consent_service.suppress_address(
        account_db,
        customer,
        channel=ConsentChannel.EMAIL,
        evidence_reference="T-9",
        reason="Asked",
    )
    account_db.commit()
    _record(account_db, mine, E.IN_TRANSIT)  # suppressed
    voided = _record(account_db, mine, E.OUT_FOR_DELIVERY)
    event_service.void_event(account_db, voided[0], reason="Wrong")  # withdrawn
    account_db.commit()
    ns.dispatch_pending(account_db)
    account_db.commit()

    response = me.get("/notifications")
    assert response.status_code == 200
    text = response.text
    body = response.json()
    assert set(body) == {"channel", "preferences", "history"}
    for item in body["history"]:
        assert set(item) == {"milestone", "shipment_reference", "created_at", "state"}
        assert item["state"] in ("pending", "sent", "not_sent")
        assert item["shipment_reference"] == mine.public_id
    assert theirs.public_id not in text
    for word in INTERNAL_WORDS + ("@", "capture", "template", "attempt", "transport"):
        assert word not in text, word


def test_failed_tries_read_pending_until_the_cap_then_not_sent(
    account_client, account_db, account_users, captured_mail
):
    me = _approved_account(account_client, account_users, captured_mail, VI_APPLICANT, "vi")
    customer = _account_customer(account_db, VI_APPLICANT)
    shipment = booked_shipment(account_db, customer, RouteGroup.VCA)

    class Broken:
        name = "capture"

        def send(self, message):
            raise OSError("relay down")

    account_email_service.set_transport(Broken())
    try:
        _record(account_db, shipment, E.RECEIVED_AT_SOLARIS)
        ns.dispatch_pending(account_db)
        account_db.commit()
        assert [h["state"] for h in me.get("/notifications").json()["history"]] == ["pending"]
        for _ in range(ns.MAX_ATTEMPTS + 3):
            ns.dispatch_pending(account_db)
            account_db.commit()
    finally:
        account_email_service.set_transport(captured_mail)
    row = _rows(account_db, shipment.id)[0]
    assert (row.status, row.attempts) == ("failed", ns.MAX_ATTEMPTS)
    assert [h["state"] for h in me.get("/notifications").json()["history"]] == ["not_sent"]
    assert "OSError" not in me.get("/notifications").text


# --- Staff routes: permissions, retry, privacy --------------------------------------------------


def _failed_row(db, shipment):
    _record(db, shipment, E.RECEIVED_AT_SOLARIS)
    row = _rows(db, shipment.id)[0]
    row.status, row.attempts, row.last_error = "failed", ns.MAX_ATTEMPTS, "OSError"
    db.commit()
    return row


def test_the_attempt_cap_stops_automatic_retries(db, shipment):
    row = _failed_row(db, shipment)
    assert ns.dispatch_pending(db) == 0
    db.refresh(row)
    assert (row.status, row.attempts) == ("failed", ns.MAX_ATTEMPTS)


def test_reading_needs_shipment_and_customer_read(api_for, db, shipment, monkeypatch):
    from app.core import permissions

    _record(db, shipment, E.RECEIVED_AT_SOLARIS)
    for role in (Role.ADMIN, Role.OPERATIONS, Role.MARKETING, Role.READ_ONLY_MANAGER):
        assert api_for(role).get("/api/v1/notifications").status_code == 200, role
    for missing in (permissions.Permission.CUSTOMER_READ, permissions.Permission.SHIPMENT_READ):
        monkeypatch.setitem(
            permissions.ROLE_PERMISSIONS,
            Role.MARKETING,
            permissions.ROLE_PERMISSIONS[Role.MARKETING] - {missing},
        )
        api = api_for(Role.MARKETING)
        assert api.get("/api/v1/notifications").status_code == 403, missing
        assert (
            api.get(
                f"/api/v1/customers/{shipment.customer_id}/notification-preferences"
            ).status_code
            == 403
        )
        monkeypatch.undo()


def test_staff_retry_is_for_failed_rows_and_tracking_writers_only(api_for, db, shipment):
    row = _failed_row(db, shipment)
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        assert api_for(role).post(f"/api/v1/notifications/{row.id}/retry").status_code == 403
    ops = api_for(Role.OPERATIONS)
    assert ops.post("/api/v1/notifications/999999/retry").status_code == 404
    retried = ops.post(f"/api/v1/notifications/{row.id}/retry")
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "recorded"  # null transport: noted, nobody mailed
    again = ops.post(f"/api/v1/notifications/{row.id}/retry")
    assert again.status_code == 409, again.text

    skipped_shipment = booked_shipment(
        db, make_customer(db, email=None, phone="+14165550111"), RouteGroup.VCA
    )
    _record(db, skipped_shipment, E.RECEIVED_AT_SOLARIS)
    ns.dispatch_pending(db)
    db.commit()
    skipped = _rows(db, skipped_shipment.id)[0]
    assert skipped.status == "skipped"
    assert ops.post(f"/api/v1/notifications/{skipped.id}/retry").status_code == 409
    queued_shipment = booked_shipment(
        db, make_customer(db, email="q@demo.example.com"), RouteGroup.VCA
    )
    _record(db, queued_shipment, E.RECEIVED_AT_SOLARIS)
    queued = _rows(db, queued_shipment.id)[0]
    assert ops.post(f"/api/v1/notifications/{queued.id}/retry").status_code == 409


def test_staff_list_filters_and_carries_no_address_or_body(api_for, db, shipment, customer):
    _record(db, shipment, E.RECEIVED_AT_SOLARIS)
    ns.dispatch_pending(db)
    db.commit()
    other = booked_shipment(db, make_customer(db, email="other.g@demo.example.com"), RouteGroup.VCA)
    _record(db, other, E.RECEIVED_AT_SOLARIS)
    api = api_for(Role.READ_ONLY_MANAGER)
    listed = api.get("/api/v1/notifications")
    assert listed.status_code == 200 and listed.json()["total"] == 2
    by_shipment = api.get("/api/v1/notifications", params={"shipment_id": shipment.id}).json()
    assert [i["shipment_reference"] for i in by_shipment["items"]] == [shipment.public_id]
    queued = api.get("/api/v1/notifications", params={"status": "queued"}).json()
    assert [i["shipment_id"] for i in queued["items"]] == [other.id]
    text = listed.text
    assert "@" not in text
    assert "Chúng tôi" not in text and "We have received" not in text
    assert "Theo dõi" not in text and "Track it here" not in text


def test_the_outbox_table_has_no_address_or_body_column():
    columns = {c.name for c in NotificationOutbox.__table__.columns}
    for forbidden in ("email", "to_email", "address", "body", "subject", "rendered", "message"):
        assert not any(forbidden in c for c in columns), (forbidden, columns)


def test_staff_preferences_read_default_on_and_patch_needs_tracking_write(api_for, db, customer):
    reader = api_for(Role.MARKETING)
    url = f"/api/v1/customers/{customer.id}/notification-preferences"
    read = reader.get(url)
    assert read.status_code == 200 and read.json()["preferences"] == ALL_ON
    assert reader.patch(url, json={"preferences": {"received": False}}).status_code == 403
    ops = api_for(Role.OPERATIONS)
    assert ops.patch(url, json={"preferences": {"received": "no"}}).status_code == 422
    assert ops.patch(url, json={"preferences": {"customs": False}}).status_code in (400, 422)
    changed = ops.patch(url, json={"preferences": {"received": False}})
    assert changed.status_code == 200 and changed.json()["preferences"] == dict(
        ALL_ON, received=False
    )
    assert ops.get("/api/v1/customers/999999/notification-preferences").status_code == 404


def test_a_staff_milestone_over_http_with_the_capture_transport_mails_once(
    api_for, db, shipment, captured_mail
):
    ops = api_for(Role.OPERATIONS)
    for _ in range(2):
        response = ops.post(
            f"/api/v1/shipments/{shipment.id}/events",
            json={
                "event_type": "received_at_solaris",
                "is_public_update": True,
                "public_update_text": "Received",
            },
        )
        assert response.status_code == 201, response.text
    assert len(_messages(captured_mail, "notify.received")) == 1
    assert json.dumps(captured_mail.messages[-1]).count(shipment.public_id) >= 2


def test_the_voided_event_row_is_linked_to_its_event(db, shipment):
    created = _record(db, shipment, E.RECEIVED_AT_SOLARIS)
    row = _rows(db, shipment.id)[0]
    assert row.event_id == created[0].id
    assert db.get(ShipmentEvent, row.event_id).is_public_update is True
