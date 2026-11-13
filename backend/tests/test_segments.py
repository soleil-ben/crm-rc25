"""AC-15 (segment half): segments are dynamic, validated, and consent-aware."""

from __future__ import annotations

import pytest

from app.core.enums import ConsentBasis, ConsentChannel, ConsentStatus, RouteGroup
from app.services import consent_service, segment_service
from app.services.activity_service import LifecycleThresholds
from app.services.errors import ValidationError
from tests.conftest import add_shipment, make_customer

THRESHOLDS = LifecycleThresholds()


def _definition(field, operator, value):
    return {"match": "all", "conditions": [{"field": field, "operator": operator, "value": value}]}


def test_segment_updates_after_a_new_shipment(db):
    customer = make_customer(db, full_name="Segment Member")
    definition = segment_service.validate_definition(
        _definition("observed_route_group", "in", ["VCA"])
    )
    assert segment_service.count_members(db, definition, THRESHOLDS) == 0

    add_shipment(db, customer, days_ago=5, route_group=RouteGroup.VCA)
    assert segment_service.count_members(db, definition, THRESHOLDS) == 1


def test_lifecycle_segment_tracks_the_derived_status(db):
    recent = make_customer(db, full_name="Recent", email="recent@demo.example.com")
    lapsed = make_customer(db, full_name="Lapsed", email="lapsed@demo.example.com")
    add_shipment(db, recent, days_ago=5)
    add_shipment(db, lapsed, days_ago=75)
    add_shipment(db, lapsed, days_ago=100)

    at_risk = segment_service.validate_definition(
        _definition("lifecycle_status", "in", ["at_risk"])
    )
    members = segment_service.list_members(db, at_risk, THRESHOLDS)
    assert [member.full_name for member in members] == ["Lapsed"]


def test_and_or_groups_compile_correctly(db):
    vietnamese = make_customer(
        db, full_name="VN Customer", email="vn@demo.example.com", preferred_language="vi"
    )
    english = make_customer(
        db, full_name="EN Customer", email="en@demo.example.com", preferred_language="en"
    )
    add_shipment(db, vietnamese, days_ago=80, route_group=RouteGroup.CAV)
    add_shipment(db, english, days_ago=80, route_group=RouteGroup.CAV)

    definition = segment_service.validate_definition(
        {
            "match": "all",
            "conditions": [
                {"field": "observed_route_group", "operator": "in", "value": ["CAV"]},
                {"field": "preferred_language", "operator": "in", "value": ["vi"]},
                {"field": "last_shipment_at", "operator": "more_than_days_ago", "value": 60},
            ],
        }
    )
    members = segment_service.list_members(db, definition, THRESHOLDS)
    assert [member.full_name for member in members] == ["VN Customer"]

    any_group = segment_service.validate_definition(
        {
            "match": "any",
            "conditions": [
                {"field": "preferred_language", "operator": "in", "value": ["vi"]},
                {"field": "preferred_language", "operator": "in", "value": ["en"]},
            ],
        }
    )
    assert segment_service.count_members(db, any_group, THRESHOLDS) == 2


def test_nested_groups_are_supported(db):
    a = make_customer(db, full_name="A", email="a@demo.example.com", city="Toronto")
    make_customer(db, full_name="B", email="b@demo.example.com", city="Calgary")
    add_shipment(db, a, days_ago=5)

    definition = segment_service.validate_definition(
        {
            "match": "all",
            "conditions": [
                {"field": "is_archived", "operator": "is", "value": False},
                {
                    "match": "any",
                    "conditions": [
                        {"field": "city", "operator": "equals", "value": "Calgary"},
                        {"field": "total_qualifying_shipments", "operator": "gte", "value": 1},
                    ],
                },
            ],
        }
    )
    assert segment_service.count_members(db, definition, THRESHOLDS) == 2


@pytest.mark.parametrize(
    "definition",
    [
        {
            "match": "all",
            "conditions": [{"field": "password_hash", "operator": "equals", "value": "x"}],
        },
        {"match": "all", "conditions": [{"field": "city", "operator": "drop_table", "value": "x"}]},
        {
            "match": "all",
            "conditions": [{"field": "preferred_language", "operator": "in", "value": ["klingon"]}],
        },
        {"match": "maybe", "conditions": [{"field": "city", "operator": "equals", "value": "x"}]},
        {"match": "all", "conditions": []},
    ],
)
def test_invalid_definitions_are_rejected(definition):
    with pytest.raises(ValidationError):
        segment_service.validate_definition(definition)


def test_plain_language_description_is_readable(db):
    definition = segment_service.validate_definition(
        {
            "match": "all",
            "conditions": [
                {"field": "observed_route_group", "operator": "in", "value": ["CAV"]},
                {"field": "preferred_language", "operator": "in", "value": ["vi"]},
            ],
        }
    )
    text = segment_service.describe(definition)
    assert "Canada to Vietnam" in text
    assert "Vietnamese" in text
    assert " and " in text


def test_marketing_eligible_count_is_separate_from_member_count(db):
    consented = make_customer(db, full_name="Consented", email="yes@demo.example.com")
    unknown = make_customer(db, full_name="Unknown", email="no@demo.example.com")
    for customer in (consented, unknown):
        add_shipment(db, customer, days_ago=10, route_group=RouteGroup.CAV)
    consent_service.record_consent_event(
        db,
        consented,
        channel=ConsentChannel.EMAIL,
        status=ConsentStatus.CONSENTED,
        basis=ConsentBasis.EXPRESS,
        evidence_reference="FORM-1",
    )
    db.commit()

    definition = segment_service.validate_definition(
        _definition("observed_route_group", "in", ["CAV"])
    )
    assert segment_service.count_members(db, definition, THRESHOLDS) == 2
    assert segment_service.marketing_eligible_count(db, definition, THRESHOLDS) == 1


def test_marketing_eligibility_is_not_a_filter_field():
    """Design.md section 8 keeps consent as a separate export filter, not a segment condition."""
    keys = set(segment_service.FIELDS)
    assert not any("consent" in key or "eligible" in key for key in keys)


def test_segment_api_round_trip(as_admin, db):
    customer = make_customer(db, full_name="Api Member")
    add_shipment(db, customer, days_ago=5, route_group=RouteGroup.VCA)

    created = as_admin.post(
        "/api/v1/segments",
        json={
            "name": "VCA shippers",
            "description": "Shipped Vietnam to Canada",
            "definition": _definition("observed_route_group", "in", ["VCA"]),
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["member_count"] == 1
    assert body["slug"] == "vca-shippers"
    assert "eligible" in body["eligibility_note"].lower()

    members = as_admin.get(f"/api/v1/segments/{body['id']}/members")
    assert members.status_code == 200
    assert members.json()["items"][0]["full_name"] == "Api Member"


def test_segment_preview_does_not_persist(as_admin, db):
    make_customer(db)
    response = as_admin.post(
        "/api/v1/segments/preview",
        json={"definition": _definition("is_archived", "is", False), "limit": 5},
    )
    assert response.status_code == 200
    assert response.json()["member_count"] == 1
    assert as_admin.get("/api/v1/segments").json() == []


def test_segment_field_catalog_is_exposed(as_admin):
    response = as_admin.get("/api/v1/segments/fields")
    assert response.status_code == 200
    keys = {field["key"] for field in response.json()["fields"]}
    assert {"lifecycle_status", "observed_route_group", "has_overdue_task", "tag"} <= keys
