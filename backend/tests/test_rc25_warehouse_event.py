"""RC-UAT-25 item 5, Ben 2026-10-25: "Received at Solaris" is shown as "Received at warehouse".

The stored code ``received_at_solaris`` is unchanged (no data change): the event type, the
operational state, the milestone mapping and every existing row keep it. What changes is the
label in every language file and the standard update sentence. The catalogue's wording is
immutable per key, so the new sentence is a new key (``received_at_solaris.v2``, "We have
received your shipment at our warehouse.") and the old one is **retired**: still rendered for
the events that carry it, never offered again.
"""

from __future__ import annotations

import pathlib

import pytest

from app.core.enums import (
    EVENT_TYPE_TO_OPERATIONAL_STATE,
    OperationalState,
    RouteGroup,
    ShipmentEventType,
    value_label,
)
from app.services import event_service
from app.services import notification_service as ns
from app.services import public_update_templates as templates
from app.services.public_update_templates import CatalogueError, check_catalogue
from tests.conftest import booked_shipment, make_customer

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"
LABEL_FILES = {
    "staff en": (FRONTEND / "i18n" / "en.js", "Received at warehouse"),
    "staff vi": (FRONTEND / "i18n" / "vi.js", "Đã nhận hàng tại kho"),
    "account en": (FRONTEND / "account" / "i18n" / "en.js", "Received at warehouse"),
    "account vi": (FRONTEND / "account" / "i18n" / "vi.js", "Đã nhận hàng tại kho"),
    "public en": (FRONTEND / "public" / "locales" / "en.js", "Received at warehouse"),
    "public vi": (FRONTEND / "public" / "locales" / "vi.js", "Đã nhận hàng tại kho"),
}
NEW_EN = "We have received your shipment at our warehouse."
NEW_VI = "Chúng tôi đã nhận lô hàng của bạn tại kho."


def test_the_stored_code_is_unchanged():
    assert ShipmentEventType.RECEIVED_AT_SOLARIS.value == "received_at_solaris"
    assert OperationalState.RECEIVED_AT_SOLARIS.value == "received_at_solaris"
    assert EVENT_TYPE_TO_OPERATIONAL_STATE[ShipmentEventType.RECEIVED_AT_SOLARIS] == (
        "received_at_solaris"
    )
    assert ns.EVENT_MILESTONE[ShipmentEventType.RECEIVED_AT_SOLARIS] == "received"


def test_the_english_label_is_received_at_warehouse():
    assert value_label("received_at_solaris") == "Received at warehouse"


@pytest.mark.parametrize("name", sorted(LABEL_FILES))
def test_every_language_file_says_warehouse(name):
    path, expected = LABEL_FILES[name]
    text = path.read_text(encoding="utf-8")
    assert f"received_at_solaris': '{expected}'" in text or (
        f"received_at_solaris: '{expected}'" in text
    ), name
    assert "Received at Solaris" not in text, name
    assert "nhận tại Solaris" not in text and "tại kho Solaris" not in text, name


def test_the_standard_update_is_the_warehouse_sentence_and_the_old_one_is_retired():
    assert templates.keys_for_event_type("received_at_solaris") == ["received_at_solaris.v2"]
    assert templates.render("received_at_solaris.v2", "en") == NEW_EN
    assert templates.render("received_at_solaris.v2", "vi") == NEW_VI
    # History still renders what the customer was told; it is just never offered again.
    assert templates.render("received_at_solaris.v1", "en") == (
        "We have received your shipment at our facility."
    )
    assert not templates.is_valid_for("received_at_solaris.v1", "received_at_solaris")
    assert "received_at_solaris.v1" in templates.catalogue()["retired"]


def test_a_retired_key_must_exist_and_must_not_be_offered():
    base = {
        "templates": {
            "a.v1": {"text": {"en": "A", "vi": "A-vi"}},
            "a.v2": {"text": {"en": "B", "vi": "B-vi"}},
        },
        "event_types": {"in_transit": {"default_public": True, "templates": ["a.v2"]}},
    }
    check_catalogue({**base, "retired": ["a.v1"]})  # fine
    with pytest.raises(CatalogueError, match="belong to no event type"):
        check_catalogue(base)
    with pytest.raises(CatalogueError, match="not in the catalogue"):
        check_catalogue({**base, "retired": ["a.v1", "ghost.v1"]})
    with pytest.raises(CatalogueError, match="still offered"):
        check_catalogue({**base, "retired": ["a.v1", "a.v2"]})


def test_the_staff_timeline_and_the_reference_list_show_the_new_label(api_for, db):
    shipment = booked_shipment(db, make_customer(db, email="wh@demo.example.com"), RouteGroup.VCA)
    event_service.record_event(
        db,
        shipment,
        {
            "event_type": "received_at_solaris",
            "is_public_update": True,
            "public_update_template_key": "received_at_solaris.v2",
        },
    )
    db.commit()
    ops = api_for("operations")
    [event] = ops.get(f"/api/v1/shipments/{shipment.id}/events").json()
    assert event["event_type"] == "received_at_solaris"
    assert event["event_type_label"] == "Received at warehouse"
    assert event["public_update_template_text"] == NEW_EN
