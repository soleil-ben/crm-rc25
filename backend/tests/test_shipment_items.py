"""Commodity line items and the payer (Phase 13B)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.enums import RouteGroup
from app.models import AuditEvent
from app.services import booking_service
from app.services import shipment_item_service as items
from app.services.errors import ConflictError, NotFoundError, ValidationError
from tests.conftest import booked_shipment, make_customer, make_draft, see_committed_changes


def test_items_are_numbered_in_order_and_removal_keeps_the_row(db):
    customer = make_customer(db)
    shipment = make_draft(db, customer, RouteGroup.VCA)
    first = items.add_item(
        db,
        shipment,
        {"description": "Sơn móng tay", "quantity": 3, "unit": "bottle", "weight_kg": "1.2"},
        actor=None,
    )
    second = items.add_item(
        db,
        shipment,
        {"description": "Quần áo", "quantity": 10, "unit": "piece", "weight_kg": "6"},
        actor=None,
    )
    db.commit()
    assert (first.sequence, second.sequence) == (1, 2)
    assert first.quantity == Decimal(3) and first.unit == "bottle"
    items.remove_item(db, shipment, first, actor=None)
    db.commit()
    assert [i.sequence for i in items.list_items(db, shipment.id)] == [2]
    assert [i.sequence for i in items.list_items(db, shipment.id, include_inactive=True)] == [1, 2]
    third = items.add_item(db, shipment, {"description": "Nước hoa"}, actor=None)
    assert third.sequence == 3  # numbers are never reused
    with pytest.raises(ConflictError, match="removed"):
        items.update_item(db, shipment, first, {"description": "x"}, actor=None)


def test_item_validation(db):
    customer = make_customer(db)
    shipment = make_draft(db, customer, RouteGroup.VCA)
    with pytest.raises(ValidationError, match="Describe"):
        items.add_item(db, shipment, {"description": "   "}, actor=None)
    with pytest.raises(ValidationError, match="Unit"):
        items.add_item(db, shipment, {"description": "x", "unit": "tonne"}, actor=None)
    with pytest.raises(ValidationError, match="greater than zero"):
        items.add_item(db, shipment, {"description": "x", "quantity": 0}, actor=None)
    with pytest.raises(NotFoundError, match="package"):
        items.add_item(db, shipment, {"description": "x", "package_id": 999999}, actor=None)
    other = make_draft(db, customer, RouteGroup.VCA)
    item = items.add_item(db, other, {"description": "elsewhere"}, actor=None)
    with pytest.raises(NotFoundError):
        items.update_item(db, shipment, item, {"description": "moved"}, actor=None)


def test_a_cancelled_booking_is_read_only(db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer, RouteGroup.VCA)
    item = items.add_item(db, shipment, {"description": "before"}, actor=None)
    db.commit()
    booking_service.cancel_shipment(db, shipment, reason="customer withdrew", actor=None)
    db.commit()
    with pytest.raises(ConflictError, match="read-only"):
        items.add_item(db, shipment, {"description": "after"}, actor=None)
    with pytest.raises(ConflictError, match="read-only"):
        items.update_item(db, shipment, item, {"description": "after"}, actor=None)


def test_items_over_http_and_on_the_shipment_detail(as_admin, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer, RouteGroup.VCA)
    created = as_admin.post(
        f"/api/v1/shipments/{shipment.id}/items",
        json={"description": "Sơn móng tay", "quantity": "3", "unit": "bottle", "weight_kg": "1.2"},
    )
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]
    updated = as_admin.patch(
        f"/api/v1/shipments/{shipment.id}/items/{item_id}", json={"quantity": "4"}
    )
    assert updated.status_code == 200 and updated.json()["quantity"] == "4.00"
    detail = as_admin.get(f"/api/v1/shipments/{shipment.id}").json()
    assert [i["description"] for i in detail["items"]] == ["Sơn móng tay"]
    removed = as_admin.post(f"/api/v1/shipments/{shipment.id}/items/{item_id}/remove")
    assert removed.status_code == 200 and removed.json()["is_active"] is False
    assert as_admin.get(f"/api/v1/shipments/{shipment.id}/items").json() == []
    assert as_admin.get(f"/api/v1/shipments/{shipment.id}/items/999/remove").status_code in (
        404,
        405,
    )
    see_committed_changes(db)
    actions = [a.action for a in db.query(AuditEvent).order_by(AuditEvent.id)]
    assert {"shipment.item_add", "shipment.item_update", "shipment.item_remove"} <= set(actions)


# --- Payer ------------------------------------------------------------------------------------------


def test_the_payer_is_a_distinct_customer_and_defaults_to_the_booking_customer(db):
    booking_customer = make_customer(db, email="booker@demo.example.com")
    payer = make_customer(db, email="payer@demo.example.com")
    shipment = make_draft(db, booking_customer, RouteGroup.VCA)
    assert booking_service.payer_customer_id(db, shipment.id) is None
    booking_service.update_shipment(db, shipment, {"payer_customer_id": payer.id})
    db.commit()
    assert booking_service.payer_customer_id(db, shipment.id) == payer.id
    # Naming the booking customer as payer stores nothing: the roles coincide.
    booking_service.update_shipment(db, shipment, {"payer_customer_id": booking_customer.id})
    assert booking_service.payer_customer_id(db, shipment.id) is None
    with pytest.raises(NotFoundError, match="paying customer"):
        booking_service.update_shipment(db, shipment, {"payer_customer_id": 999999})


def test_the_payer_can_be_set_at_creation_and_corrected_after_confirmation_over_http(as_admin, db):
    booking_customer = make_customer(db, email="booker@demo.example.com")
    payer = make_customer(db, email="payer@demo.example.com")
    created = as_admin.post(
        "/api/v1/shipments",
        json={
            "customer_id": booking_customer.id,
            "payer_customer_id": payer.id,
            "route_group": "VCA",
            "packages": [],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["payer"]["public_id"] == payer.public_id
    shipment_id = created.json()["id"]
    confirmed_shipment = booked_shipment(db, booking_customer, RouteGroup.VCA)
    patched = as_admin.patch(
        f"/api/v1/shipments/{confirmed_shipment.id}", json={"payer_customer_id": payer.id}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["payer"]["id"] == payer.id
    cleared = as_admin.patch(
        f"/api/v1/shipments/{shipment_id}", json={"payer_customer_id": booking_customer.id}
    )
    assert cleared.status_code == 200 and cleared.json()["payer"] is None


def test_a_customer_merge_moves_or_clears_the_payer_row(db, users):
    from app.core.enums import Role  # noqa: PLC0415
    from app.models import ShipmentPayer  # noqa: PLC0415
    from app.services import customer_service  # noqa: PLC0415

    admin = users[Role.ADMIN]
    booker = make_customer(db, email="booker@demo.example.com")
    payer_a = make_customer(db, email="payer-a@demo.example.com")
    payer_b = make_customer(db, email="payer-b@demo.example.com")
    paid_by_a = make_draft(db, booker, RouteGroup.VCA)
    paid_by_b = make_draft(db, booker, RouteGroup.VCA)
    booking_service.set_payer(db, paid_by_a, payer_a.id)
    booking_service.set_payer(db, paid_by_b, payer_b.id)
    db.commit()

    # Merging payer A into payer B re-points A's row to B.
    customer_service.merge_customers(db, source=payer_a, target=payer_b, actor=admin)
    db.commit()
    assert booking_service.payer_customer_id(db, paid_by_a.id) == payer_b.id
    # Merging payer B into the booking customer makes the payer the booking customer: the
    # rows are dropped, because no row means "the booking customer pays".
    customer_service.merge_customers(db, source=payer_b, target=booker, actor=admin)
    db.commit()
    assert booking_service.payer_customer_id(db, paid_by_a.id) is None
    assert booking_service.payer_customer_id(db, paid_by_b.id) is None
    assert db.query(ShipmentPayer).count() == 0
