"""Recording an approved template, and what a customer then reads.

The unit-level catalogue lives in ``test_public_update_templates``. This file is about the
two ends: what ``record_event`` accepts, and what comes out of the public tracking API.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.enums import RouteGroup, ShipmentEventType
from app.core.security import rate_limiter
from app.core.time_utils import utcnow
from app.services import event_service
from app.services.errors import ValidationError
from tests.conftest import booked_shipment, make_customer

TRACK = "/api/v1/public/track"


def record(db, shipment, event_type=ShipmentEventType.IN_TRANSIT, **extra):
    events = event_service.record_event(
        db,
        shipment,
        {"event_type": event_type, "occurred_at": utcnow() - timedelta(minutes=1), **extra},
    )
    db.commit()
    return events


# --- What the service accepts ----------------------------------------------


def test_a_template_key_is_stored_instead_of_a_sentence(db: Session):
    """The whole point: the row holds the key, so the sentence is chosen at read time by
    the reader's language rather than frozen at write time by the staff member's."""
    customer = make_customer(db, email="tplstore@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)

    event = record(
        db,
        shipment,
        is_public_update=True,
        public_update_template_key="in_transit.v1",
    )[0]

    assert event.public_update_template_key == "in_transit.v1"
    assert event.public_update_text is None


def test_a_template_and_free_text_together_are_refused(db: Session):
    """Merging them would let the customer's language decide which of two different
    messages they read."""
    customer = make_customer(db, email="tplboth@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)

    with pytest.raises(ValidationError) as excinfo:
        record(
            db,
            shipment,
            is_public_update=True,
            public_update_template_key="in_transit.v1",
            public_update_text="Something else entirely.",
        )

    assert excinfo.value.field == "public_update_template_key"


def test_a_template_from_another_event_type_is_refused(db: Session):
    """A customs sentence on a delivery event would be worse than no sentence."""
    customer = make_customer(db, email="tplwrong@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)

    with pytest.raises(ValidationError) as excinfo:
        record(
            db,
            shipment,
            ShipmentEventType.DELIVERED_TO_RECIPIENT,
            is_public_update=True,
            public_update_template_key="customs_processing.held.v1",
        )

    assert excinfo.value.field == "public_update_template_key"


def test_an_unknown_template_key_is_refused(db: Session):
    customer = make_customer(db, email="tplghost@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)

    with pytest.raises(ValidationError) as excinfo:
        record(db, shipment, is_public_update=True, public_update_template_key="ghost.v1")

    assert excinfo.value.field == "public_update_template_key"


def test_a_template_without_the_publish_flag_is_refused(db: Session):
    """Same rule free text already had: nothing becomes customer-visible by accident."""
    customer = make_customer(db, email="tplunflagged@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)

    with pytest.raises(ValidationError) as excinfo:
        record(db, shipment, public_update_template_key="in_transit.v1")

    assert excinfo.value.field == "is_public_update"


def test_the_flag_still_needs_wording_of_some_kind(db: Session):
    customer = make_customer(db, email="tplnone@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)

    with pytest.raises(ValidationError) as excinfo:
        record(db, shipment, is_public_update=True)

    assert excinfo.value.field == "public_update_text"


def test_free_text_still_works_exactly_as_before(db: Session):
    """Templates are a convenience, never a cage. Anything a template does not cover is
    still sayable."""
    customer = make_customer(db, email="tplfree@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)

    event = record(
        db,
        shipment,
        is_public_update=True,
        public_update_text="Held at the depot pending an address correction.",
    )[0]

    assert event.public_update_template_key is None
    assert event.public_update_text == "Held at the depot pending an address correction."


# --- The audit trail --------------------------------------------------------


def test_the_audit_records_the_key_and_not_the_sentence(db: Session):
    """The catalogue says what the key meant. Storing the rendered sentence too would
    create a second copy that could disagree with it."""
    from app.models import AuditEvent

    customer = make_customer(db, email="tplaudit@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)
    record(db, shipment, is_public_update=True, public_update_template_key="in_transit.v1")

    details = [row.detail_json for row in db.query(AuditEvent).all() if row.detail_json]
    relevant = [d for d in details if "public_update_template_key" in d]

    assert relevant, "the template choice was not audited"
    assert any("in_transit.v1" in d for d in relevant)
    assert not any("Your shipment is on its way" in d for d in details)


# --- What the customer reads ------------------------------------------------


def test_the_public_timeline_carries_the_key_and_a_rendered_fallback(client, db: Session):
    rate_limiter.reset()
    customer = make_customer(db, email="tplpublic@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)
    record(db, shipment, is_public_update=True, public_update_template_key="in_transit.v1")

    body = client.get(f"{TRACK}/{shipment.public_id}").json()
    entry = body["timeline"][0]

    assert entry["message_template_key"] == "in_transit.v1"
    # ``message`` stays readable for any consumer that cannot localize.
    assert entry["message"] == "Your shipment is on its way."


def test_a_free_text_milestone_reports_no_template_key(client, db: Session):
    rate_limiter.reset()
    customer = make_customer(db, email="tplpublicfree@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)
    record(db, shipment, is_public_update=True, public_update_text="A specific thing happened.")

    body = client.get(f"{TRACK}/{shipment.public_id}").json()
    entry = body["timeline"][0]

    assert entry["message_template_key"] is None
    assert entry["message"] == "A specific thing happened."


def test_a_template_milestone_still_leaks_no_internal_detail(client, db: Session):
    """The new field must not become a side door."""
    rate_limiter.reset()
    customer = make_customer(db, email="tplleak@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)
    record(
        db,
        shipment,
        is_public_update=True,
        public_update_template_key="in_transit.v1",
        internal_detail="UNIQUE-SENTINEL-49182 customer owes a balance",
    )

    text = client.get(f"{TRACK}/{shipment.public_id}").text

    assert "UNIQUE-SENTINEL-49182" not in text
    assert "owes a balance" not in text


def test_an_event_flagged_public_with_no_wording_never_reaches_the_timeline(client, db: Session):
    """Belt and braces. The service refuses to create one; if a row ever existed anyway --
    a direct database edit, a downgraded column -- it must not render as a blank milestone."""
    from app.models import ShipmentEvent

    rate_limiter.reset()
    customer = make_customer(db, email="tplblank@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV)
    record(db, shipment, is_public_update=True, public_update_template_key="in_transit.v1")

    event = db.query(ShipmentEvent).filter_by(shipment_id=shipment.id).first()
    event.public_update_template_key = None
    event.public_update_text = None
    db.commit()

    body = client.get(f"{TRACK}/{shipment.public_id}").json()

    assert body["timeline"] == []
