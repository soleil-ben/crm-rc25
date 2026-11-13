"""RC-UAT-25 item 6, Ben 2026-10-25: edit an operational timeline event, published or not.

* Admin and Operations (``tracking:write``, who record and void today) may edit; Marketing and
  the read-only manager may not.
* Event type, occurred-at, location, packages, leg and the standard update can be corrected;
  every edit writes a ``shipment_event_revisions`` row and a ``shipment.event_edit`` audit row
  with before and after; the derived status is recomputed.
* No silent rewrite: publishing does not change in an edit; a published event's wording
  changes only to a standard update offered for its (new) type; own wording can be kept but
  not rewritten; a retired standard update can be kept only while the type is unchanged.
* No milestone email: an edit never queues, sends or withdraws one.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from app.core.enums import RouteGroup
from app.core.time_utils import utcnow
from app.models import (
    AuditEvent,
    NotificationOutbox,
    ShipmentEvent,
    ShipmentEventRevision,
)
from app.services import event_service, package_service
from app.services import notification_service as ns
from app.services.errors import ConflictError, NotFoundError, ValidationError
from tests.conftest import booked_shipment, make_customer, see_committed_changes

RECEIVED = "received_at_solaris"


@pytest.fixture
def shipment(db):
    customer = make_customer(db, email="edit.me@demo.example.com")
    return booked_shipment(db, customer, RouteGroup.VCA, packages=2)


def _record(db, shipment, **payload):
    body = {
        "event_type": RECEIVED,
        "is_public_update": True,
        "public_update_template_key": "received_at_solaris.v2",
        "location_label": "Ho Chi Minh City",
        **payload,
    }
    created = event_service.record_event(db, shipment, body)
    db.commit()
    return created


def _edit(db, shipment, rows, **changes):
    first = rows[0]
    payload = {
        "event_ids": [row.id for row in rows],
        "event_type": first.event_type,
        "package_ids": [row.package_id for row in rows if row.package_id],
        "leg_id": first.leg_id,
        "location_label": first.location_label,
        "location_country_code": first.location_country_code,
        "internal_detail": first.internal_detail,
        "public_update_template_key": first.public_update_template_key,
        "public_update_text": first.public_update_text,
        "reason": "Wrong warehouse entered.",
        **changes,
    }
    result = event_service.edit_event(db, shipment, payload)
    db.commit()
    return result


def _outbox(db, shipment):
    return db.query(NotificationOutbox).filter_by(shipment_id=shipment.id).all()


def _edit_body(rows, **changes):
    first = rows[0]
    return {
        "event_ids": [row["id"] for row in rows],
        "event_type": first["event_type"],
        "package_ids": [row["package_id"] for row in rows if row["package_id"]],
        "location_label": first["location_label"],
        "public_update_template_key": first["public_update_template_key"],
        "reason": "Corrected after a phone call.",
        **changes,
    }


# --- Who may edit, and what is recorded --------------------------------------------------------


def test_operations_edits_a_published_event_with_before_and_after(api_for, db, shipment):
    ops = api_for("operations")
    recorded = ops.post(
        f"/api/v1/shipments/{shipment.id}/events",
        json={
            "event_type": RECEIVED,
            "is_public_update": True,
            "public_update_template_key": "received_at_solaris.v2",
            "location_label": "Ho Chi Minh City",
        },
    )
    assert recorded.status_code == 201, recorded.text
    rows = recorded.json()
    assert len(rows) == 2  # one per package
    earlier = (utcnow() - timedelta(hours=5)).replace(microsecond=0)
    response = ops.post(
        f"/api/v1/shipments/{shipment.id}/events/edit",
        json=_edit_body(
            rows,
            event_type="in_transit",
            public_update_template_key="in_transit.v1",
            location_label="Hanoi",
            occurred_at=earlier.isoformat() + "Z",
        ),
    )
    assert response.status_code == 200, response.text
    edited = response.json()
    assert {row["event_type"] for row in edited} == {"in_transit"}
    assert {row["location_label"] for row in edited} == {"Hanoi"}
    assert all(row["is_public_update"] for row in edited)
    assert {row["id"] for row in edited} == {row["id"] for row in rows}

    see_committed_changes(db)
    assert shipment.operational_state == "in_transit"
    revision = db.query(ShipmentEventRevision).one()
    before, after = json.loads(revision.before_json), json.loads(revision.after_json)
    assert before["event_type"] == RECEIVED and after["event_type"] == "in_transit"
    assert before["location_label"] == "Ho Chi Minh City" and after["location_label"] == "Hanoi"
    assert before["public_update_template_key"] == "received_at_solaris.v2"
    assert after["public_update_template_key"] == "in_transit.v1"
    assert revision.was_published and revision.public_wording_changed
    assert revision.reason == "Corrected after a phone call."
    audit = db.query(AuditEvent).filter_by(action="shipment.event_edit").one()
    detail = json.loads(audit.detail_json)
    assert detail["revision_id"] == revision.id and detail["was_published"] is True
    assert set(detail["changed_fields"]) >= {"event_type", "location_label", "occurred_at"}
    assert detail["before"]["event_type"] == RECEIVED
    assert detail["after"]["event_type"] == "in_transit"
    assert audit.actor_user_id is not None

    history = ops.get(f"/api/v1/shipments/{shipment.id}/event-revisions")
    assert history.status_code == 200
    [item] = history.json()
    assert item["before"]["event_type"] == RECEIVED and item["after"]["event_type"] == "in_transit"
    assert item["edited_by"]["full_name"]


def test_admin_may_edit_and_marketing_and_read_only_may_not(api_for, db, shipment):
    rows = [
        {"id": row.id, **{k: getattr(row, k) for k in _FIELDS}} for row in _record(db, shipment)
    ]
    body = _edit_body(rows, location_label="Da Nang")
    for role in ("marketing", "read_only_manager"):
        refused = api_for(role).post(f"/api/v1/shipments/{shipment.id}/events/edit", json=body)
        assert refused.status_code == 403, role
    see_committed_changes(db)
    assert db.query(ShipmentEventRevision).count() == 0
    admin = api_for("admin")
    assert admin.post(f"/api/v1/shipments/{shipment.id}/events/edit", json=body).status_code == 200


_FIELDS = ("event_type", "package_id", "location_label", "public_update_template_key")


# --- No silent rewrite ------------------------------------------------------------------------


def test_own_wording_can_be_kept_but_not_rewritten(db, shipment):
    rows = _record(
        db, shipment, public_update_template_key=None, public_update_text="Your parcel is here."
    )
    with pytest.raises(ValidationError) as refused:
        _edit(db, shipment, rows, public_update_text="Something quite different.")
    assert refused.value.field == "public_update_text"
    db.rollback()
    kept = _edit(db, shipment, rows, location_label="Da Nang")
    assert {row.public_update_text for row in kept.events} == {"Your parcel is here."}
    assert kept.revision.public_wording_changed is False
    switched = _edit(
        db,
        shipment,
        kept.events,
        public_update_text=None,
        public_update_template_key="received_at_solaris.v2",
    )
    assert switched.revision.public_wording_changed is True
    assert {row.public_update_text for row in switched.events} == {None}


def test_the_standard_update_must_be_offered_for_the_new_type(db, shipment):
    rows = _record(db, shipment)
    with pytest.raises(ValidationError) as refused:
        _edit(db, shipment, rows, event_type="in_transit")  # keeps the received template
    assert refused.value.field == "public_update_template_key"
    db.rollback()
    with pytest.raises(ValidationError):
        _edit(db, shipment, rows, public_update_template_key=None)  # a published event keeps one


def test_editing_never_publishes_or_unpublishes(db, shipment):
    rows = _record(db, shipment, is_public_update=False, public_update_template_key=None)
    with pytest.raises(ValidationError) as refused:
        _edit(db, shipment, rows, public_update_template_key="received_at_solaris.v2")
    assert refused.value.field == "is_public_update"
    db.rollback()
    result = _edit(db, shipment, rows, location_label="Can Tho")
    assert {row.is_public_update for row in result.events} == {False}
    assert result.revision.was_published is False


def test_a_retired_standard_update_is_kept_only_while_the_type_is_unchanged(db, shipment):
    rows = _record(db, shipment)
    for row in rows:  # an event recorded before the wording was retired
        row.public_update_template_key = "received_at_solaris.v1"
    db.commit()
    kept = _edit(db, shipment, rows, location_label="Hai Phong")
    assert {row.public_update_template_key for row in kept.events} == {"received_at_solaris.v1"}
    with pytest.raises(ValidationError):
        _edit(db, shipment, kept.events, event_type="processing")


# --- No milestone email ------------------------------------------------------------------------


def test_an_edit_sends_no_milestone_email(db, shipment, captured_mail):
    rows = _record(db, shipment)
    assert [r.milestone for r in _outbox(db, shipment)] == ["received"]
    assert ns.dispatch_pending(db) == 1
    db.commit()
    sent = len(captured_mail.messages)

    moved = _edit(
        db, shipment, rows, event_type="in_transit", public_update_template_key=("in_transit.v1")
    )
    _edit(
        db,
        shipment,
        moved.events,
        occurred_at=utcnow() - timedelta(hours=1),
        location_label="Somewhere else",
    )
    assert [r.milestone for r in _outbox(db, shipment)] == ["received"]
    assert ns.dispatch_pending(db) == 0
    db.commit()
    assert len(captured_mail.messages) == sent


# --- Packages, legs, refusals -----------------------------------------------------------------


def test_a_removed_package_is_voided_and_an_added_one_gets_a_row(db, shipment):
    first, second = package_service.active_packages(db, shipment.id)
    rows = _record(db, shipment, package_id=first.id)
    assert len(rows) == 1
    result = _edit(db, shipment, rows, package_ids=[second.id])
    db.refresh(rows[0])
    assert rows[0].is_voided and rows[0].voided_reason.startswith("Removed from this event")
    [added] = result.events
    assert added.package_id == second.id and added.recorded_at == rows[0].recorded_at
    assert added.is_public_update and added.public_update_template_key == "received_at_solaris.v2"
    revision = result.revision
    assert json.loads(revision.event_ids_before) == [rows[0].id]
    assert json.loads(revision.event_ids_after) == [added.id]
    assert json.loads(revision.after_json)["package_ids"] == [second.id]
    # Back to every active package: the second row stays, the first package gets a new row.
    both = _edit(db, shipment, result.events, package_ids=[])
    assert sorted(row.package_id for row in both.events) == sorted([first.id, second.id])


def test_refusals_change_nothing(db, shipment):
    rows = _record(db, shipment)
    other = booked_shipment(db, make_customer(db, email="other@demo.example.com"), RouteGroup.VCA)
    with pytest.raises(ValidationError):
        _edit(db, shipment, rows, reason="  ")
    with pytest.raises(ValidationError):
        _edit(db, shipment, rows, occurred_at=utcnow() + timedelta(days=1))
    with pytest.raises(ValidationError):
        _edit(db, shipment, rows)  # nothing changed
    with pytest.raises(NotFoundError):
        _edit(db, other, rows, location_label="x")
    with pytest.raises(NotFoundError):
        _edit(db, shipment, rows, leg_id=999999, location_label="x")
    db.rollback()
    event_service.void_event(db, rows[0], reason="Mistake")
    db.commit()
    with pytest.raises(ConflictError):
        _edit(db, shipment, rows, location_label="x")
    db.rollback()
    assert db.query(ShipmentEventRevision).count() == 0
    assert db.query(ShipmentEvent).filter_by(location_label="x").count() == 0
