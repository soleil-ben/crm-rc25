"""RC-UAT-25 item 3, Ben 2026-10-25: the booking's declared value currency is a list.

The booking screen offers CAD and VND (and blank, because it is optional) instead of free
text. The server holds the same list and refuses anything else, so a bypassed screen, an
API call or a spreadsheet import cannot store another code:

* ``/shipments/meta`` publishes the list the screen renders;
* creating or editing a draft with CAD or VND (any case) is accepted and stored upper-case;
  blank stays blank;
* any other code -- including well-formed ones such as USD -- is refused with 422 and
  the field named;
* a code stored before the list existed is not a trap: re-sending it unchanged is accepted,
  and a rebook copies it forward;
* the shipment import refuses the row in its preview rather than failing at commit.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.core.enums import RouteGroup
from app.services import booking_service
from app.services.errors import ValidationError
from tests.conftest import draft_payload, make_customer, make_draft


def test_the_meta_endpoint_publishes_the_list(as_admin):
    response = as_admin.get("/api/v1/shipments/meta")
    assert response.status_code == 200, response.text
    assert response.json()["declared_value_currencies"] == ["CAD", "VND"]


@pytest.mark.parametrize(("sent", "stored"), [("CAD", "CAD"), ("vnd", "VND"), (" cad ", "CAD")])
def test_cad_and_vnd_are_accepted(as_admin, db: Session, sent, stored):
    customer = make_customer(db, email=f"rc25.ok.{stored.lower()}@demo.example.com")
    payload = draft_payload(
        customer, RouteGroup.CAV, declared_value="120", declared_value_currency=sent
    )
    response = as_admin.post("/api/v1/shipments", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["financials"]["declared_value_currency"] == stored


def test_blank_stays_blank(as_admin, db: Session):
    customer = make_customer(db, email="rc25.blank@demo.example.com")
    payload = draft_payload(customer, RouteGroup.CAV, declared_value_currency="")
    response = as_admin.post("/api/v1/shipments", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["financials"]["declared_value_currency"] is None


@pytest.mark.parametrize("code", ["USD", "EUR", "XXX", "CA", "12A"])
def test_any_other_code_is_refused_over_the_api(as_admin, db: Session, code):
    customer = make_customer(db, email=f"rc25.bad.{code.lower()}@demo.example.com")
    payload = draft_payload(customer, RouteGroup.CAV, declared_value_currency=code)
    response = as_admin.post("/api/v1/shipments", json=payload)
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["field"] == "declared_value_currency"
    assert "CAD or VND" in body["message"]


def test_an_over_long_code_is_refused_by_the_schema(as_admin, db: Session):
    customer = make_customer(db, email="rc25.long@demo.example.com")
    payload = draft_payload(customer, RouteGroup.CAV, declared_value_currency="CADX")
    response = as_admin.post("/api/v1/shipments", json=payload)
    assert response.status_code == 422, response.text


def test_an_edit_to_another_code_is_refused(as_admin, db: Session):
    customer = make_customer(db, email="rc25.edit@demo.example.com")
    shipment = make_draft(db, customer, RouteGroup.CAV, declared_value_currency="CAD")
    response = as_admin.patch(
        f"/api/v1/shipments/{shipment.id}", json={"declared_value_currency": "USD"}
    )
    assert response.status_code == 422, response.text
    assert response.json()["field"] == "declared_value_currency"

    changed = as_admin.patch(
        f"/api/v1/shipments/{shipment.id}", json={"declared_value_currency": "VND"}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["financials"]["declared_value_currency"] == "VND"


def test_a_code_stored_before_the_list_survives_an_unchanged_edit_and_a_rebook(db: Session):
    customer = make_customer(db, email="rc25.legacy@demo.example.com")
    shipment = make_draft(db, customer, RouteGroup.CAV)
    # As a row written before RC-UAT-25 could hold it.
    shipment.declared_value_currency = "USD"
    db.commit()

    booking_service.update_shipment(
        db, shipment, {"declared_value_currency": "USD", "booking_reference": "RC25-LEGACY"}
    )
    db.commit()
    assert shipment.declared_value_currency == "USD"
    assert shipment.booking_reference == "RC25-LEGACY"

    with pytest.raises(ValidationError):
        booking_service.update_shipment(db, shipment, {"declared_value_currency": "EUR"})
    db.rollback()

    replacement = booking_service.rebook_shipment(db, shipment, reason="RC-UAT-25 legacy check")
    db.commit()
    assert replacement.declared_value_currency == "USD"


def test_the_service_refuses_directly_too(db: Session):
    customer = make_customer(db, email="rc25.service@demo.example.com")
    with pytest.raises(ValidationError) as caught:
        booking_service.create_draft(
            db, draft_payload(customer, RouteGroup.VCA, declared_value_currency="JPY")
        )
    assert caught.value.field == "declared_value_currency"
    assert caught.value.detail == {"allowed": ["CAD", "VND"]}


# --- The shipment import ---------------------------------------------------------------

VALID_IMPORT = (Path(__file__).parent / "fixtures" / "rc21_shipments_valid.csv").read_bytes()


def _import_dry_run(api, content: bytes) -> dict:
    response = api.post(
        "/api/v1/imports/shipments/dry-run",
        files={"file": ("shipments.csv", io.BytesIO(content), "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _row_one(data: dict) -> dict:
    return next(item for item in data["rows"] if item["reference"] == "TEST-SHP-0001")


def test_the_import_accepts_cad_and_refuses_another_code_per_row(as_admin, db: Session):
    make_customer(db, full_name="Nguyễn Văn Thử", email="rc25.import1@example.com")
    make_customer(db, full_name="Công ty Thử", email="rc25.import2@example.com")

    assert _row_one(_import_dry_run(as_admin, VALID_IMPORT))["classification"] == "ready"

    usd = VALID_IMPORT.replace(b",110,CAD,", b",110,USD,")
    assert usd != VALID_IMPORT
    row = _row_one(_import_dry_run(as_admin, usd))
    assert row["classification"] == "rejected"
    assert {issue["code"] for issue in row["issues"]} == {"invalid_currency"}

    lower = VALID_IMPORT.replace(b",110,CAD,", b",110,vnd,")
    assert _row_one(_import_dry_run(as_admin, lower))["classification"] == "ready"
