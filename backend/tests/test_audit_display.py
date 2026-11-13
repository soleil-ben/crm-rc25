"""The audit screen's detail columns: a reason code and changed field *names*, never values.

UAT round 3 found the audit access screen showed only a one-line summary. The API now
derives two display fields from the stored detail. These tests hold the line that matters:
whatever the detail contains, those two fields can only ever carry short snake_case
tokens, so the screen cannot become a way to read a customer value.
"""

from __future__ import annotations

import json

from app.core.enums import Role
from app.services import audit_service
from tests.conftest import make_customer

SECRET_NOTE = "Gate code 4417, leave with Mrs Nguyễn Thị Lan"
SECRET_CITY = "Biên Hòa"


def _only_names(item: dict) -> str:
    """The derived part of a row, serialised, for a substring search."""
    return json.dumps(
        {"reason_code": item["reason_code"], "changed_fields": item["changed_fields"]},
        ensure_ascii=False,
    )


def test_a_customer_update_lists_the_changed_field_names(as_admin, db):
    customer = make_customer(db)
    response = as_admin.patch(
        f"/api/v1/customers/{customer.id}",
        json={"notes": SECRET_NOTE, "city": SECRET_CITY},
    )
    assert response.status_code == 200

    page = as_admin.get("/api/v1/audit", params={"action": "customer.update"}).json()
    item = page["items"][0]
    assert item["changed_fields"] == ["city", "notes"]
    assert item["reason_code"] is None

    derived = _only_names(item)
    assert SECRET_NOTE not in derived
    assert SECRET_CITY not in derived
    assert "Gate code" not in derived


def test_values_smuggled_into_a_field_list_or_reason_code_are_dropped(as_admin, db):
    audit_service.record_audit(
        db,
        action="test.hostile_detail",
        entity_type="customer",
        entity_id="STCA-000001",
        summary="Hostile detail",
        detail={
            "fields": ["city", "Nguyễn Văn A", "123 Main St", "phone", 42, None],
            "changed_fields": ["email_entered", "a@b.example.com"],
            "reason_code": "Customer said: call me at 416-555-0142",
            "reason": "free text that may name a person",
            "before": {"city": "Toronto"},
            "after": {"city": "Hanoi"},
        },
    )
    db.commit()

    page = as_admin.get("/api/v1/audit", params={"action": "test.hostile_detail"}).json()
    item = page["items"][0]
    assert item["changed_fields"] == ["city", "email_entered", "phone"]
    assert item["reason_code"] is None

    derived = _only_names(item)
    for value in (
        "Nguyễn Văn A",
        "123 Main St",
        "a@b.example.com",
        "416-555-0142",
        "free text",
        "Toronto",
        "Hanoi",
    ):
        assert value not in derived


def test_a_reason_code_is_shown_when_it_is_a_code(as_admin, db):
    audit_service.record_audit(
        db,
        action="test.reason_code",
        entity_type="customer_account",
        summary="Refused",
        detail={"override_reason_code": "duplicate_reviewed", "field_keys": ["display_name"]},
    )
    db.commit()

    item = as_admin.get("/api/v1/audit", params={"action": "test.reason_code"}).json()["items"][0]
    assert item["reason_code"] == "duplicate_reviewed"
    assert item["changed_fields"] == ["display_name"]


def test_the_audit_list_stays_closed_to_roles_without_audit_read(api_for):
    assert api_for(Role.OPERATIONS).get("/api/v1/audit").status_code == 403
    assert api_for(Role.MARKETING).get("/api/v1/audit").status_code == 403


def test_display_fields_tolerate_missing_or_malformed_detail():
    empty = {
        "reason_code": None,
        "changed_fields": [],
        "admin_override": False,
        "evidence_reference": None,
        "changes": [],
    }
    assert audit_service.audit_display_fields(None) == empty
    assert audit_service.audit_display_fields("") == empty
    assert audit_service.audit_display_fields("not json") == empty
    assert audit_service.audit_display_fields('["a", "b"]') == empty
    assert audit_service.audit_display_fields('{"fields": "city"}') == empty
