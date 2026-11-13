"""UAT round 11: the owner's decisions of 2026-10-18 on the RC-UAT-13 and RC-UAT-14 questions.

Server half. The screen half is ``frontend/tests/uatRound11.test.jsx``.

1. The sign-in lockout fix (DEC-0155) stays as it is: ``test_uat_round_9.py`` still covers it.
2. The billing box starts ticked (DEC-0158). Since UAT round 12 the API's
   ``billing_same_as_shipping`` defaults to true as well (DEC-0166).
3. The country list still starts on Canada: screen only.
4. The postal code is optional for the address and for billing, in every country. A blank
   one is never refused; a typed one is kept as typed, held to the field's 30-character
   bound (DEC-0159) and, since UAT round 12, for Canada and the United States to a lenient
   shape (DEC-0165, ``test_uat_round_12.py``).
5. The shipment list row carries the customer's own booking reference (DEC-0160), and since
   UAT round 12 so does the detail (DEC-0163).
6. The keyword search stays accent-insensitive: ``test_account_shipment_search.py``.
7. A package reference finds its shipment, own shipments only (DEC-0161):
   ``test_account_shipment_search.py``.
"""

from __future__ import annotations

import pytest

from app.api.account.routes import REQUIRED_ADDRESS_PARTS, address_part_missing_message
from app.models import CustomerDataProposal, CustomerDataProposalField, CustomerIdentity
from app.schemas.account import RegistrationRequest
from tests.account_fixtures import REGISTRATION_BODY, registration
from tests.conftest import see_committed_changes
from tests.shipment_history_fixtures import (
    LIST_URL,
    detail_url,
    linked_and_signed_in,
    shipment,
)
from tests.shipment_history_fixtures import customer as make

REGISTER = "/api/v1/account/register"
MINE = "hanh@demo.example.com"

#: One address per country the form offers, none with a postal code.
ADDRESSES = {
    "CA": {
        "country_code": "CA",
        "address_line1": "4120 Dixie Road",
        "city": "Mississauga",
        "province_state": "ON",
    },
    "VN": {
        "country_code": "VN",
        "address_line1": "125 Đường Nguyễn Huệ",
        "city": "Thành phố Hồ Chí Minh",
        "province_state": "Hồ Chí Minh",
    },
    "US": {
        "country_code": "US",
        "address_line1": "1 Pike Street",
        "city": "Seattle",
        "province_state": "WA",
    },
}


def _prefixed(prefix: str, parts: dict) -> dict:
    return {f"{prefix}{part}": value for part, value in parts.items()}


def _customer(**changes) -> dict:
    base = {
        key: value
        for key, value in REGISTRATION_BODY["customer"].items()
        if not key.startswith(("billing_address.", "pickup_address."))
    }
    return {**base, **changes}


def _proposed(db) -> dict[str, str]:
    see_committed_changes(db)
    proposal = db.query(CustomerDataProposal).filter_by(kind="registration").one()
    rows = db.query(CustomerDataProposalField).filter_by(proposal_id=proposal.id).all()
    return {row.field_key: row.proposed_value for row in rows}


# --- 4. The postal code is optional ----------------------------------------------------


def test_the_required_parts_are_country_line_1_city_and_province():
    assert REQUIRED_ADDRESS_PARTS == ("country_code", "address_line1", "city", "province_state")
    with pytest.raises(ValueError):
        address_part_missing_message("postal_code", billing=False)


@pytest.mark.parametrize("country", sorted(ADDRESSES))
@pytest.mark.parametrize("blank", [False, True], ids=["absent", "blank"])
def test_an_address_without_a_postal_code_is_accepted(account_client, account_db, country, blank):
    address = _prefixed("pickup_address.1.", ADDRESSES[country])
    if blank:
        address["pickup_address.1.postal_code"] = "   "
    body = registration(customer=_customer(**address), billing_same_as_shipping=True)
    response = account_client.post(REGISTER, json=body)
    assert response.status_code == 200, response.text
    fields = _proposed(account_db)
    assert fields["pickup_address.1.city"] == ADDRESSES[country]["city"]
    # Nothing is invented for the empty part, on either address.
    assert "pickup_address.1.postal_code" not in fields
    assert "billing_address.postal_code" not in fields
    assert fields["billing_address.city"] == ADDRESSES[country]["city"]


@pytest.mark.parametrize("country", sorted(ADDRESSES))
def test_an_unticked_billing_address_without_a_postal_code_is_accepted(
    account_client, account_db, country
):
    body = registration(
        customer=_customer(
            **_prefixed("pickup_address.1.", ADDRESSES["CA"]),
            **_prefixed("billing_address.", ADDRESSES[country]),
        ),
        billing_same_as_shipping=False,
    )
    response = account_client.post(REGISTER, json=body)
    assert response.status_code == 200, response.text
    fields = _proposed(account_db)
    assert fields["billing_address.country_code"] == country
    assert "billing_address.postal_code" not in fields


@pytest.mark.parametrize(
    ("country", "postal"),
    [
        ("CA", "l4w1v2"),
        ("CA", "L4W 1V2"),
        ("VN", "700000"),
        ("VN", "Not a real code"),
        ("US", "98101-1234"),
    ],
)
def test_a_typed_postal_code_is_kept_as_typed(account_client, account_db, country, postal):
    """Registered in `SUPERSEDED_ASSERTIONS.md` (AS-17): any format used to be kept.

    Since UAT round 12 a Canadian or United States code must have its lenient shape
    (DEC-0165); one that has it, and any Vietnamese code, is still kept exactly as typed.
    """
    address = {
        **_prefixed("pickup_address.1.", ADDRESSES[country]),
        "pickup_address.1.postal_code": postal,
    }
    body = registration(customer=_customer(**address), billing_same_as_shipping=True)
    response = account_client.post(REGISTER, json=body)
    assert response.status_code == 200, response.text
    fields = _proposed(account_db)
    assert fields["pickup_address.1.postal_code"] == postal
    assert fields["billing_address.postal_code"] == postal


def test_the_postal_code_length_bound_still_applies(account_client, account_db):
    address = {
        **_prefixed("pickup_address.1.", ADDRESSES["CA"]),
        "pickup_address.1.postal_code": "9" * 31,
    }
    body = registration(customer=_customer(**address), billing_same_as_shipping=True)
    response = account_client.post(REGISTER, json=body)
    assert response.status_code in (400, 422), response.text
    assert response.json()["field"] == "pickup_address.1.postal_code"
    assert account_db.query(CustomerIdentity).count() == 0


@pytest.mark.parametrize("part", REQUIRED_ADDRESS_PARTS)
def test_the_four_parts_are_still_required_without_a_postal_code(account_client, part):
    address = _prefixed("pickup_address.1.", ADDRESSES["VN"])
    del address[f"pickup_address.1.{part}"]
    body = registration(customer=_customer(**address), billing_same_as_shipping=True)
    response = account_client.post(REGISTER, json=body)
    assert response.status_code == 422, response.text
    assert response.json()["field"] == f"pickup_address.1.{part}"


# --- 2. The billing box: the API default matches the form since round 12 -------------


def test_the_api_defaults_the_billing_box_to_ticked(account_client, account_db):
    """Registered in `SUPERSEDED_ASSERTIONS.md` (AS-18): the API used to default to false.

    A client that omits the flag now gets what the untouched form sends (DEC-0166): the
    address is copied into billing, and no billing address is asked for.
    """
    assert RegistrationRequest.model_fields["billing_same_as_shipping"].default is True
    body = registration(customer=_customer(**_prefixed("pickup_address.1.", ADDRESSES["CA"])))
    body.pop("billing_same_as_shipping", None)
    response = account_client.post(REGISTER, json=body)
    assert response.status_code == 200, response.text
    fields = _proposed(account_db)
    assert fields["billing_address.city"] == ADDRESSES["CA"]["city"]
    assert fields["billing_address.country_code"] == "CA"


# --- 5. The booking reference on the list row ---------------------------------------


def _signed_in(account_client, account_db, account_users, captured_mail, owner):
    return linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=owner
    )


def test_each_row_carries_its_own_booking_reference(
    account_client, account_db, account_users, captured_mail
):
    owner = make(account_db, full_name="Hanh Nguyen", email="hanh.c@demo.example.com")
    with_ref = shipment(account_db, owner, days_ago=3, booking_reference="  PO-4471  ")
    without = shipment(account_db, owner, days_ago=4)
    blank = shipment(account_db, owner, days_ago=5, booking_reference="   ")
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    items = {item["shipment_reference"]: item for item in client.get(LIST_URL).json()["items"]}
    assert items[with_ref.public_id]["booking_reference"] == "PO-4471"
    assert items[without.public_id]["booking_reference"] is None
    assert items[blank.public_id]["booking_reference"] is None


def test_the_detail_carries_the_same_booking_reference_as_the_row(
    account_client, account_db, account_users, captured_mail
):
    """Registered in `SUPERSEDED_ASSERTIONS.md` (AS-19): the detail used to carry none.

    Since UAT round 12 the detail shows the booking reference too (DEC-0163), the same
    trimmed value the list row shows.
    """
    owner = make(account_db, full_name="Hanh Nguyen", email="hanh.c@demo.example.com")
    row = shipment(account_db, owner, days_ago=3, booking_reference=" PO-DETAIL-1 ")
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    detail = client.get(detail_url(row.public_id))
    assert detail.status_code == 200, detail.text
    assert detail.json()["booking_reference"] == "PO-DETAIL-1"
    [item] = client.get(LIST_URL).json()["items"]
    assert item["booking_reference"] == detail.json()["booking_reference"]


def test_another_customers_booking_reference_is_never_listed(
    account_client, account_db, account_users, captured_mail
):
    owner = make(account_db, full_name="Hanh Nguyen", email="hanh.c@demo.example.com")
    stranger = make(account_db, full_name="Stranger", email="stranger@demo.example.com")
    shipment(account_db, owner, days_ago=3, booking_reference="MINE-1")
    shipment(account_db, stranger, days_ago=3, booking_reference="THEIRS-1")
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    response = client.get(LIST_URL)
    assert [item["booking_reference"] for item in response.json()["items"]] == ["MINE-1"]
    assert "THEIRS-1" not in response.text
