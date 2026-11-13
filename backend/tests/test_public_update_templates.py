"""Approved public wording: the catalogue, the exclusivity rule, and the language payoff.

The feature exists because a customer reading the tracking page in Vietnamese was being
handed whatever language the staff member happened to be working in. These tests hold the
two halves of the fix in place: an event stores a *key*, and the key renders per reader.
"""

from __future__ import annotations

import pytest

from app.core.enums import ShipmentEventType
from app.services import public_update_templates as templates
from app.services.public_update_templates import CatalogueError, check_catalogue

# --- The catalogue itself ---------------------------------------------------


def test_every_template_carries_both_languages():
    """Half a translation is exactly the bug this feature was built to remove."""
    data = templates.catalogue()["templates"]
    assert data, "catalogue is empty"

    for key, entry in data.items():
        for language in templates.REQUIRED_LANGUAGES:
            text = entry["text"].get(language)
            assert isinstance(text, str) and text.strip(), f"{key} is missing {language}"


def test_english_and_vietnamese_are_actually_different_strings():
    """A copy-pasted English string sitting in the `vi` slot would pass a presence check
    and still show a Vietnamese reader English."""
    for key, entry in templates.catalogue()["templates"].items():
        assert entry["text"]["en"] != entry["text"]["vi"], key


def test_every_event_type_offering_templates_is_a_real_event_type():
    known = {member.value for member in ShipmentEventType}
    for event_type in templates.catalogue()["event_types"]:
        assert event_type in known, event_type


def test_no_template_promises_a_date_or_claims_a_carrier_reported_something():
    """No provider integration exists (DEC-0075), and no template may imply one does."""
    forbidden = ("carrier", "tracking number", "scanned", "shipstation", "estimated delivery")
    for key, entry in templates.catalogue()["templates"].items():
        english = entry["text"]["en"].lower()
        for phrase in forbidden:
            assert phrase not in english, f"{key} says '{phrase}'"


def test_exception_states_do_not_publish_by_default():
    """A canned sentence about a problem nobody has diagnosed is worse than silence
    (DEC-0083)."""
    for event_type in ("exception", "delivery_attempted", "return_in_progress", "awaiting_parcel"):
        assert templates.publishes_by_default(event_type) is False, event_type


def test_ordinary_milestones_publish_by_default():
    for event_type in (
        "received_at_solaris",
        "in_transit",
        "out_for_delivery",
        "delivered_to_recipient",
    ):
        assert templates.publishes_by_default(event_type) is True, event_type


def test_a_system_written_event_type_does_not_publish():
    """``booked`` is written by the booking service, not chosen by a person."""
    assert templates.publishes_by_default("booked") is False


def test_an_unknown_key_renders_as_none_rather_than_raising():
    """A retired template must not take the tracking page down for historical events."""
    assert templates.render("no.such.key.v1") is None


def test_render_falls_back_to_english_for_an_unknown_language():
    assert templates.render("in_transit.v1", "fr") == templates.render("in_transit.v1", "en")


def test_a_template_is_only_valid_for_its_own_event_type():
    assert templates.is_valid_for("in_transit.v1", "in_transit") is True
    assert templates.is_valid_for("in_transit.v1", "delivered_to_recipient") is False


# --- The catalogue guard ----------------------------------------------------


def test_a_template_missing_vietnamese_is_rejected_at_load():
    with pytest.raises(CatalogueError, match="missing vi"):
        check_catalogue(
            {
                "templates": {"a.v1": {"text": {"en": "Hello"}}},
                "event_types": {"in_transit": {"default_public": True, "templates": ["a.v1"]}},
            }
        )


def test_an_event_type_pointing_at_a_missing_template_is_rejected():
    with pytest.raises(CatalogueError, match="unknown template"):
        check_catalogue(
            {
                "templates": {},
                "event_types": {"in_transit": {"default_public": True, "templates": ["ghost.v1"]}},
            }
        )


def test_a_template_no_event_type_offers_is_rejected():
    """Unreachable wording is a mistake, not a spare: it can never be chosen, so it would
    sit in the file looking approved forever."""
    with pytest.raises(CatalogueError, match="belong to no event type"):
        check_catalogue(
            {
                "templates": {
                    "a.v1": {"text": {"en": "A", "vi": "A-vi"}},
                    "orphan.v1": {"text": {"en": "B", "vi": "B-vi"}},
                },
                "event_types": {"in_transit": {"default_public": True, "templates": ["a.v1"]}},
            }
        )


def test_an_unknown_event_type_is_rejected():
    with pytest.raises(CatalogueError, match="not a ShipmentEventType"):
        check_catalogue(
            {
                "templates": {"a.v1": {"text": {"en": "A", "vi": "A-vi"}}},
                "event_types": {"teleported": {"default_public": True, "templates": ["a.v1"]}},
            }
        )
