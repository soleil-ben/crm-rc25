"""The two allowlists, asserted by name, and the independence that keeps them still.

A field count alone would pass if somebody swapped one field for another, so every
assertion here is against a **frozen list written out in this file**. Changing the surface
means editing this test, which means a reviewer sees the diff -- which is the entire
mechanism. `SHIPMENT_ALLOWLISTS.md` §7 and AC-CA-6 ask for exactly this.

The independence assertions are the other half. A schema that *inherits* the public one
would pass a field-count test today and start publishing whatever the public one gained
tomorrow, so subclassing is asserted absent in every direction rather than assumed.
"""

from __future__ import annotations

import inspect

import pydantic
import pytest

from app.schemas import account_shipments as account
from app.schemas import public_tracking as public
from app.schemas import shipment as staff_shipment

# --- The frozen field lists ----------------------------------------------------

LIST_FIELDS = [
    "shipment_reference",
    "booking_reference",
    "booked_at",
    "route_group",
    "route_label",
    "origin_city",
    "origin_country_code",
    "destination_city",
    "destination_country_code",
    "status",
    "status_label",
    "package_count_active",
    "package_count_cancelled",
    "delivered_at",
    "cancelled_at",
    "last_public_update_at",
    "is_cancelled",
    "is_rebooked",
]

DETAIL_FIELDS = [
    "shipment_reference",
    "booking_reference",
    "matched_reference_type",
    "selected_package_reference",
    "route_group",
    "route_label",
    "origin",
    "destination",
    "status",
    "status_label",
    "package_count_active",
    "package_count_cancelled",
    "package_count_delivered",
    "progress_summary",
    "packages",
    "estimated_delivery_at",
    "delivered_at",
    "cancelled_at",
    "timeline",
    "tracking_state",
    "last_public_update_at",
    "carrier_link",
    "carrier_links",  # one per generic tracking name (2026-10-22)
    "data_mode",
    "help_url",
    "timezone",
]


def test_the_list_item_has_exactly_the_eighteen_approved_fields():
    """Registered in `SUPERSEDED_ASSERTIONS.md` (AS-12, AS-20): seventeen until UAT round 11.

    Until UAT round 12 this also asserted the booking reference was not in the detail.
    """
    assert sorted(account.AccountShipmentListItem.model_fields) == sorted(LIST_FIELDS)
    assert len(LIST_FIELDS) == 18
    # The one field the list and the detail add over Public Tracking (DEC-0160, DEC-0163).
    assert "booking_reference" in DETAIL_FIELDS
    assert "booking_reference" not in public.PublicTrackingResult.model_fields


def test_the_detail_has_exactly_the_twenty_six_approved_fields():
    """Registered in `SUPERSEDED_ASSERTIONS.md` (AS-21, AS-27): twenty-four until UAT round 12;
    twenty-five until RC-UAT-19 added ``carrier_links`` (one link per generic tracking name,
    owner answers of 2026-10-22)."""
    assert sorted(account.AccountShipmentDetail.model_fields) == sorted(DETAIL_FIELDS)
    assert len(DETAIL_FIELDS) == 26


def test_public_tracking_is_exactly_twenty_five_fields():
    """OD-31's other half: the public contract does not expand because this one exists.

    ``test_public_contract_unchanged.py`` asserts the same thing by name and is deliberately
    untouched by Phase 11. This is the assertion restated from the Customer Account's side,
    so a change that widened the public model would fail in the suite that caused it as well
    as in the one that guards it.

    Registered in `SUPERSEDED_ASSERTIONS.md` (AS-28): twenty-four until RC-UAT-19 added
    ``carrier_links`` (2026-10-22).
    """
    # Twenty-four until RC-UAT-19 added ``carrier_links`` (2026-10-22; SUPERSEDED_ASSERTIONS.md AS-27 to AS-35).
    assert len(public.PublicTrackingResult.model_fields) == 25


def test_the_detail_is_the_public_names_plus_the_booking_reference_and_not_the_same_class():
    """Registered in `SUPERSEDED_ASSERTIONS.md` (AS-22): the names matched exactly until UAT
    round 12.

    Release 1 started the authenticated view at the public view's contents; DEC-0163 adds
    the customer's own booking reference to the authenticated side only. The *classes* are
    unrelated, so either can move without the other, and nothing else differs.
    """
    assert sorted(account.AccountShipmentDetail.model_fields) == sorted(
        [*public.PublicTrackingResult.model_fields, "booking_reference"]
    )
    assert account.AccountShipmentDetail is not public.PublicTrackingResult


# --- Independence ---------------------------------------------------------------


def _account_models() -> list[type[pydantic.BaseModel]]:
    return [
        value
        for _, value in inspect.getmembers(account, inspect.isclass)
        if issubclass(value, pydantic.BaseModel) and value.__module__ == account.__name__
    ]


def _public_models() -> list[type[pydantic.BaseModel]]:
    return [
        value
        for _, value in inspect.getmembers(public, inspect.isclass)
        if issubclass(value, pydantic.BaseModel) and value.__module__ == public.__name__
    ]


def _staff_models() -> list[type[pydantic.BaseModel]]:
    return [
        value
        for _, value in inspect.getmembers(staff_shipment, inspect.isclass)
        if issubclass(value, pydantic.BaseModel) and value.__module__ == staff_shipment.__name__
    ]


def test_no_account_shipment_model_subclasses_a_public_or_staff_model():
    foreign = _public_models() + _staff_models()
    for model in _account_models():
        for other in foreign:
            assert not issubclass(model, other), f"{model.__name__} subclasses {other.__name__}"


def test_no_public_or_staff_model_subclasses_an_account_shipment_model():
    """The mirror. Independence is not a direction; it is a property of the pair."""
    mine = _account_models()
    for other in _public_models() + _staff_models():
        for model in mine:
            assert not issubclass(other, model), f"{other.__name__} subclasses {model.__name__}"


def test_the_account_module_does_not_re_export_a_public_model_under_its_own_name():
    """An alias is inheritance with the paperwork hidden, and would defeat every test above."""
    for _, value in inspect.getmembers(account, inspect.isclass):
        if issubclass(value, pydantic.BaseModel):
            assert value.__module__ in {account.__name__, "pydantic.main"}, (
                f"{value.__name__} is defined in {value.__module__}, not in this module"
            )


def test_no_account_shipment_model_sets_from_attributes():
    """``from_attributes`` is what would let a ``Shipment`` ORM row be handed to a model."""
    for model in _account_models():
        assert model.model_config.get("from_attributes") is False, model.__name__


def test_every_account_shipment_model_forbids_extra_fields():
    for model in _account_models():
        assert model.model_config.get("extra") == "forbid", model.__name__


def test_an_orm_object_cannot_be_validated_into_the_detail():
    """The property ``from_attributes=False`` buys, exercised rather than asserted."""

    class Pretend:
        shipment_reference = "SX-CAV-000001"

    with pytest.raises(pydantic.ValidationError):
        account.AccountShipmentDetail.model_validate(Pretend())


def test_the_tracking_vocabularies_are_separate_enums():
    """Re-declared, so widening one is not widening the other.

    They carry the same members today -- parity again -- and they are different types, which
    is what stops a value added to the public vocabulary from appearing here.
    """
    assert account.AccountTrackingState is not public.TrackingState
    assert {m.value for m in account.AccountTrackingState} == {
        m.value for m in public.TrackingState
    }
    assert "connected_api" not in {m.value for m in account.AccountTrackingState}
