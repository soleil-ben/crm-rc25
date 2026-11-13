"""AC-1 and AC-19: customer persistence, validation, and accented names."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.services import customer_service
from tests.conftest import make_customer

VIETNAMESE_NAME = "Nguyễn Thị Bích Hạnh"
LONG_VIETNAMESE_NAME = "Nguyễn Hoàng Thị Phương Uyên Trần Đặng Minh Khôi"


def test_create_customer_persists_and_returns_public_id(as_admin):
    response = as_admin.post(
        "/api/v1/customers",
        json={"full_name": "Aisha Bello", "email": "aisha@demo.example.com", "country_code": "CA"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["public_id"] == "STCA-000001"
    assert body["lifecycle_status"] == "prospect"
    assert body["total_qualifying_shipments"] == 0

    # Reading it back through a fresh request proves it persisted, not just echoed.
    again = as_admin.get(f"/api/v1/customers/{body['id']}")
    assert again.status_code == 200
    assert again.json()["full_name"] == "Aisha Bello"


def test_customer_ids_increment_without_gaps(as_admin):
    ids = []
    for index in range(3):
        response = as_admin.post(
            "/api/v1/customers",
            json={"full_name": f"Person {index}", "phone": f"+1 416 555 01{index:02d}"},
        )
        assert response.status_code == 201, response.text
        ids.append(response.json()["public_id"])
    assert ids == ["STCA-000001", "STCA-000002", "STCA-000003"]


@pytest.mark.parametrize("name", [VIETNAMESE_NAME, LONG_VIETNAMESE_NAME, "Marie-Claude Deschênes"])
def test_accented_names_survive_round_trip(as_admin, name):
    response = as_admin.post(
        "/api/v1/customers",
        json={"full_name": name, "phone": "+1 416 555 0123", "country_code": "CA"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["full_name"] == name

    # The accent-folded key exists only for duplicate matching; it never replaces the name.
    detail = as_admin.get(f"/api/v1/customers/{response.json()['id']}").json()
    assert detail["full_name"] == name


def test_customer_requires_phone_or_email(as_admin):
    response = as_admin.post("/api/v1/customers", json={"full_name": "No Contact"})
    assert response.status_code == 422
    assert "phone" in response.json()["message"].lower()


def test_invalid_email_is_rejected(as_admin):
    response = as_admin.post(
        "/api/v1/customers", json={"full_name": "Bad Email", "email": "not-an-email"}
    )
    assert response.status_code in (400, 422)


def test_negative_estimated_monthly_shipments_rejected(as_admin):
    response = as_admin.post(
        "/api/v1/customers",
        json={
            "full_name": "Negative Estimate",
            "phone": "+1 416 555 0177",
            "estimated_monthly_shipments": -3,
        },
    )
    assert response.status_code == 422


def test_phone_is_stored_as_entered_and_normalized(db):
    customer = make_customer(db, phone="(416) 555-0100", country_code="CA")
    assert customer.phone_entered == "(416) 555-0100"
    assert customer.phone_e164 == "+14165550100"
    assert customer.phone_match_key == "+14165550100"


def test_unparseable_international_phone_is_still_accepted(db):
    customer = make_customer(db, phone="0084 90 1234 567", email=None, country_code=None)
    assert customer.phone_entered == "0084 90 1234 567"
    assert customer.phone_match_key is not None


def test_business_only_fields_cleared_for_individual(db):
    customer = make_customer(
        db, category="business", business_name="Acme", business_type="retailer"
    )
    assert customer.business_name == "Acme"
    customer_service.update_customer(db, customer, {"category": "individual"})
    db.commit()
    assert customer.business_name is None
    assert customer.business_type is None


def test_archive_does_not_delete_shipment_history(db, as_admin):
    from tests.conftest import add_shipment

    customer = make_customer(db, full_name="Archive Me", email="archive@demo.example.com")
    add_shipment(db, customer, days_ago=5)

    response = as_admin.post(
        f"/api/v1/customers/{customer.id}/archive", json={"reason": "Duplicate"}
    )
    assert response.status_code == 200
    assert response.json()["lifecycle_status"] == "archived"
    assert response.json()["activity"]["total_qualifying_shipments"] == 1

    from app.models import Shipment

    assert db.scalar(select(Shipment).where(Shipment.customer_id == customer.id)) is not None


def test_customer_search_matches_public_id_and_accent_folded_name(db, as_admin):
    make_customer(db, full_name=VIETNAMESE_NAME, email="bich@demo.example.com")
    by_id = as_admin.get("/api/v1/search?q=STCA-000001")
    assert by_id.status_code == 200
    assert by_id.json()["items"][0]["public_id"] == "STCA-000001"

    folded = as_admin.get("/api/v1/search?q=nguyen thi")
    assert folded.status_code == 200
    assert any(item["full_name"] == VIETNAMESE_NAME for item in folded.json()["items"])


def test_service_restriction_is_independent_of_lifecycle(db, as_admin):
    from tests.conftest import add_shipment

    customer = make_customer(db, full_name="Restricted", email="restricted@demo.example.com")
    add_shipment(db, customer, days_ago=5)
    response = as_admin.patch(
        f"/api/v1/customers/{customer.id}",
        json={"do_not_contact": True, "service_restriction_note": "Unpaid balance"},
    )
    assert response.status_code == 200
    body = response.json()
    # Do-not-contact is stored separately and does not change the derived lifecycle state.
    assert body["do_not_contact"] is True
    assert body["lifecycle_status"] == "new"
