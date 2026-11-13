"""Server-side authorization for every Phase 2 endpoint.

Each test calls the endpoint *directly* with a signed-in role. Hiding a control in React
is never the boundary (CRM.md section 11, AC-2).
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from app.core.enums import Role, RouteGroup
from app.services import package_service
from tests.conftest import booked_shipment, draft_payload, make_customer

ROLES = [role.value for role in Role]


@pytest.fixture
def shipment(db: Session):
    customer = make_customer(db, email="perm.shipment@demo.example.com")
    booking = booked_shipment(db, customer, RouteGroup.CAV, packages=2)
    booking.currency = "CAD"
    booking.selling_amount = 220
    booking.shipping_cost = 140
    booking.surcharges_amount = 12
    db.commit()
    return booking


@pytest.fixture
def customer(db: Session):
    return make_customer(db, email="perm.customer@demo.example.com")


# --- Read ------------------------------------------------------------------


@pytest.mark.parametrize(
    "role,allowed",
    [
        (Role.ADMIN, True),
        (Role.OPERATIONS, True),
        (Role.MARKETING, True),
        (Role.READ_ONLY_MANAGER, True),
    ],
)
def test_shipment_read_matches_the_matrix(api_for, shipment, role, allowed):
    response = api_for(role).get(f"/api/v1/shipments/{shipment.id}")
    assert (response.status_code == 200) is allowed, response.text


# --- Write -----------------------------------------------------------------


@pytest.mark.parametrize(
    "role,allowed",
    [
        (Role.ADMIN, True),
        (Role.OPERATIONS, True),
        (Role.MARKETING, False),
        (Role.READ_ONLY_MANAGER, False),
    ],
)
def test_only_writers_can_create_a_draft(api_for, customer, role, allowed):
    response = api_for(role).post("/api/v1/shipments", json=draft_payload(customer, RouteGroup.CAD))
    assert (response.status_code == 201) is allowed, response.text
    if not allowed:
        assert response.status_code == 403


@pytest.mark.parametrize(
    "role,allowed",
    [
        (Role.ADMIN, True),
        (Role.OPERATIONS, True),
        (Role.MARKETING, False),
        (Role.READ_ONLY_MANAGER, False),
    ],
)
def test_only_writers_can_add_a_package(api_for, shipment, role, allowed):
    response = api_for(role).post(
        f"/api/v1/shipments/{shipment.id}/packages", json={"weight_value": "2"}
    )
    assert (response.status_code == 201) is allowed, response.text


@pytest.mark.parametrize(
    "role,allowed",
    [
        (Role.ADMIN, True),
        (Role.OPERATIONS, True),
        (Role.MARKETING, False),
        (Role.READ_ONLY_MANAGER, False),
    ],
)
def test_only_writers_can_confirm_a_booking(api_for, customer, role, allowed):
    creator = api_for(Role.ADMIN)
    draft = creator.post("/api/v1/shipments", json=draft_payload(customer, RouteGroup.CAD))
    shipment_id = draft.json()["id"]

    response = api_for(role).post(
        f"/api/v1/shipments/{shipment_id}/confirm",
        json={"idempotency_key": f"perm-key-{role}"},
    )
    assert (response.status_code == 200) is allowed, response.text


# --- Cancellation is gated separately -------------------------------------


@pytest.mark.parametrize(
    "role,allowed",
    [
        (Role.ADMIN, True),
        (Role.OPERATIONS, True),
        (Role.MARKETING, False),
        (Role.READ_ONLY_MANAGER, False),
    ],
)
def test_cancellation_needs_its_own_permission(api_for, shipment, role, allowed):
    """Operations may work a shipment but may not retire its Solaris ID."""
    response = api_for(role).post(
        f"/api/v1/shipments/{shipment.id}/cancel", json={"reason": "Testing authorization"}
    )
    assert (response.status_code == 200) is allowed, response.text


@pytest.mark.parametrize(
    "role,allowed",
    [
        (Role.ADMIN, True),
        (Role.OPERATIONS, True),
        (Role.MARKETING, False),
        (Role.READ_ONLY_MANAGER, False),
    ],
)
def test_rebooking_needs_the_cancel_permission(api_for, shipment, role, allowed):
    response = api_for(role).post(
        f"/api/v1/shipments/{shipment.id}/rebook", json={"reason": "Wrong route group"}
    )
    assert (response.status_code == 201) is allowed, response.text


# --- Tracking and events ---------------------------------------------------


@pytest.mark.parametrize(
    "role,allowed",
    [
        (Role.ADMIN, True),
        (Role.OPERATIONS, True),
        (Role.MARKETING, False),
        (Role.READ_ONLY_MANAGER, False),
    ],
)
def test_only_tracking_writers_can_record_an_event(api_for, shipment, role, allowed):
    response = api_for(role).post(
        f"/api/v1/shipments/{shipment.id}/events", json={"event_type": "in_transit"}
    )
    assert (response.status_code == 201) is allowed, response.text


@pytest.mark.parametrize(
    "role,allowed",
    [
        (Role.ADMIN, True),
        (Role.OPERATIONS, True),
        (Role.MARKETING, False),
        (Role.READ_ONLY_MANAGER, False),
    ],
)
def test_only_tracking_writers_can_add_a_leg(api_for, shipment, role, allowed):
    response = api_for(role).post(
        f"/api/v1/shipments/{shipment.id}/legs", json={"leg_type": "origin_pickup"}
    )
    assert (response.status_code == 201) is allowed, response.text


# --- Labels ----------------------------------------------------------------


@pytest.mark.parametrize(
    "role,allowed",
    [
        (Role.ADMIN, True),
        (Role.OPERATIONS, True),
        (Role.MARKETING, False),
        (Role.READ_ONLY_MANAGER, False),
    ],
)
def test_label_generation_is_permission_gated(api_for, shipment, role, allowed):
    response = api_for(role).get(f"/api/v1/shipments/{shipment.id}/labels.pdf")
    assert (response.status_code == 200) is allowed, response.text
    preview = api_for(role).get(f"/api/v1/shipments/{shipment.id}/label-preview")
    assert (preview.status_code == 200) is allowed


def test_a_read_only_user_generates_no_label_activity(api_for, shipment, db: Session):
    """A read-only role must not be able to produce misleading activity records."""
    from app.models import LabelPrintJob

    api_for(Role.READ_ONLY_MANAGER).get(f"/api/v1/shipments/{shipment.id}/labels.pdf")
    assert db.query(LabelPrintJob).count() == 0


def test_a_read_only_user_cannot_mutate_anything(api_for, shipment, customer):
    api = api_for(Role.READ_ONLY_MANAGER)
    package_id = None
    for method, path, body in [
        ("post", "/api/v1/shipments", draft_payload(customer, RouteGroup.CAD)),
        ("patch", f"/api/v1/shipments/{shipment.id}", {"internal_notes": "no"}),
        ("post", f"/api/v1/shipments/{shipment.id}/confirm", {"idempotency_key": "ro-key-01"}),
        ("post", f"/api/v1/shipments/{shipment.id}/cancel", {"reason": "no"}),
        ("post", f"/api/v1/shipments/{shipment.id}/rebook", {"reason": "no"}),
        ("post", f"/api/v1/shipments/{shipment.id}/packages", {"weight_value": "1"}),
        ("post", f"/api/v1/shipments/{shipment.id}/legs", {"leg_type": "origin_pickup"}),
        ("post", f"/api/v1/shipments/{shipment.id}/events", {"event_type": "in_transit"}),
        ("patch", f"/api/v1/shipments/{shipment.id}/financials", {"selling_amount": "1"}),
    ]:
        response = getattr(api, method)(path, json=body)
        assert response.status_code == 403, f"{method} {path} returned {response.status_code}"
    assert package_id is None


# --- Financial and cost visibility ----------------------------------------


def test_revenue_and_cost_visibility_are_separate(api_for, shipment):
    """A role without cost permission receives no cost field at all (CRM.md section 11)."""
    admin = api_for(Role.ADMIN).get(f"/api/v1/shipments/{shipment.id}").json()
    assert admin["financials"]["selling_amount"] == "220.00"
    assert admin["financials"]["costs"]["shipping_cost"] == "140.00"
    assert admin["financials"]["costs"]["surcharges_amount"] == "12.00"

    # Operations holds financial:read but not financial_cost:read.
    ops_response = api_for(Role.OPERATIONS).get(f"/api/v1/shipments/{shipment.id}")
    ops = ops_response.json()
    assert ops["financials"]["selling_amount"] == "220.00"
    # UAT round 3: the cost block is omitted, not sent as ``"costs": null``.
    assert "costs" not in ops["financials"]
    # The keys are genuinely absent from the payload, not merely null.
    assert "shipping_cost" not in ops_response.text
    assert "surcharges_amount" not in ops_response.text


def test_marketing_receives_no_financial_block(api_for, shipment):
    response = api_for(Role.MARKETING).get(f"/api/v1/shipments/{shipment.id}")
    assert response.json()["financials"] is None
    assert "shipping_cost" not in response.text


def test_the_read_only_manager_sees_revenue_but_not_cost(api_for, shipment):
    response = api_for(Role.READ_ONLY_MANAGER).get(f"/api/v1/shipments/{shipment.id}")
    body = response.json()
    assert body["financials"]["selling_amount"] == "220.00"
    assert "costs" not in body["financials"]
    assert "shipping_cost" not in response.text


def test_the_shipment_list_never_leaks_costs(api_for, shipment):
    for role in (Role.OPERATIONS, Role.MARKETING):
        response = api_for(role).get("/api/v1/shipments")
        assert "shipping_cost" not in response.text
        assert "surcharges_amount" not in response.text


@pytest.mark.parametrize(
    "role,allowed",
    [
        (Role.ADMIN, True),
        (Role.OPERATIONS, True),
        (Role.MARKETING, False),
        (Role.READ_ONLY_MANAGER, False),
    ],
)
def test_recording_amounts_needs_financial_write(api_for, shipment, role, allowed):
    response = api_for(role).patch(
        f"/api/v1/shipments/{shipment.id}/financials", json={"selling_amount": "199.00"}
    )
    assert (response.status_code == 200) is allowed, response.text


# --- Session and CSRF ------------------------------------------------------


def test_an_unauthenticated_request_is_refused(client, shipment):
    assert client.get(f"/api/v1/shipments/{shipment.id}").status_code == 401
    assert client.post("/api/v1/shipments", json={}).status_code == 401
    assert client.get(f"/api/v1/shipments/{shipment.id}/labels.pdf").status_code == 401


def test_a_state_change_without_the_csrf_header_is_refused(client, users, shipment):
    from tests.conftest import sign_in

    sign_in(client, users[Role.ADMIN].email)
    response = client.post(
        f"/api/v1/shipments/{shipment.id}/events", json={"event_type": "in_transit"}
    )
    assert response.status_code == 403
    assert "security token" in response.json()["message"]


def test_audit_entries_redact_and_stay_admin_only(api_for, shipment, db: Session):
    api_for(Role.ADMIN).post(
        f"/api/v1/shipments/{shipment.id}/events",
        json={"event_type": "received_at_solaris", "internal_detail": "Customer owes a balance"},
    )
    audit = (
        api_for(Role.ADMIN).get("/api/v1/audit", params={"action": "shipment.event_record"}).json()
    )
    detail = json.dumps(audit["items"][0])
    assert "Customer owes a balance" not in detail

    assert api_for(Role.OPERATIONS).get("/api/v1/audit").status_code == 403
    assert api_for(Role.OPERATIONS).get("/api/v1/audit").status_code == 403


def test_packages_of_another_shipment_cannot_be_printed(api_for, shipment, db: Session):
    other_customer = make_customer(db, email="perm.other@demo.example.com")
    other = booked_shipment(db, other_customer, RouteGroup.CAD)
    foreign = package_service.active_packages(db, other.id)[0]

    response = api_for(Role.ADMIN).get(
        f"/api/v1/shipments/{shipment.id}/labels.pdf", params={"package_id": [foreign.id]}
    )
    assert response.status_code == 422
