"""UAT round 12: the owner's decisions of 2026-10-19 on the RC-UAT-15 questions.

Server half. The screen half is ``frontend/tests/uatRound12.test.jsx``.

1. The shipment detail carries the customer's own booking reference too (DEC-0163). Public
   Tracking still never does.
2. A cancelled package's reference still finds its shipment in the keyword search, among
   the customer's own shipments only (DEC-0164).
3. A typed postal code for Canada or the United States must have a lenient shape: Canada
   ``A1A 1A1`` with or without the space, any case; the United States five digits or
   ZIP+4. Blank is always allowed, and other countries are not checked (DEC-0165).
4. The API's ``billing_same_as_shipping`` defaults to true, as the form does (DEC-0166).
"""

from __future__ import annotations

import pytest

from app.api.account.routes import BILLING_SAME_WITH_BILLING
from app.core.account_fields import POSTAL_CODE_SHAPES, postal_code_format_message
from app.core.enums import BookingState
from app.models import CustomerDataProposal, CustomerDataProposalField, CustomerIdentity
from app.schemas.public_tracking import PublicTrackingResult
from tests.account_fixtures import REGISTRATION_BODY, registration
from tests.conftest import see_committed_changes
from tests.shipment_history_fixtures import (
    LIST_URL,
    detail_url,
    linked_and_signed_in,
    references,
    shipment,
)
from tests.shipment_history_fixtures import customer as make

REGISTER = "/api/v1/account/register"
MINE = "hanh@demo.example.com"

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


def _address(country: str, postal: str | None = None, prefix: str = "pickup_address.1.") -> dict:
    parts = dict(ADDRESSES[country])
    if postal is not None:
        parts["postal_code"] = postal
    return _prefixed(prefix, parts)


def _proposed(db) -> dict[str, str]:
    see_committed_changes(db)
    proposal = db.query(CustomerDataProposal).filter_by(kind="registration").one()
    rows = db.query(CustomerDataProposalField).filter_by(proposal_id=proposal.id).all()
    return {row.field_key: row.proposed_value for row in rows}


def _signed_in(account_client, account_users, captured_mail, owner):
    return linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=owner
    )


# --- 1. The booking reference on the detail ----------------------------------------


def test_the_detail_shows_the_booking_reference_or_null(
    account_client, account_db, account_users, captured_mail
):
    owner = make(account_db, full_name="Hanh Nguyen", email="hanh.c@demo.example.com")
    with_ref = shipment(account_db, owner, days_ago=3, booking_reference="  PO-4471  ")
    without = shipment(account_db, owner, days_ago=4)
    blank = shipment(account_db, owner, days_ago=5, booking_reference="   ")
    client = _signed_in(account_client, account_users, captured_mail, owner)

    assert client.get(detail_url(with_ref.public_id)).json()["booking_reference"] == "PO-4471"
    assert client.get(detail_url(without.public_id)).json()["booking_reference"] is None
    assert client.get(detail_url(blank.public_id)).json()["booking_reference"] is None


def test_a_cancelled_shipment_detail_still_shows_its_booking_reference(
    account_client, account_db, account_users, captured_mail
):
    """The reference identifies the booking; cancelling it does not make it a secret."""
    owner = make(account_db, full_name="Hanh Nguyen", email="hanh.c@demo.example.com")
    row = shipment(
        account_db,
        owner,
        days_ago=3,
        booking_state=BookingState.CANCELLED.value,
        booking_reference="PO-CANCELLED-9",
    )
    client = _signed_in(account_client, account_users, captured_mail, owner)

    body = client.get(detail_url(row.public_id)).json()
    assert body["cancelled_at"] is not None
    assert body["timeline"] == []
    assert body["booking_reference"] == "PO-CANCELLED-9"


def test_another_customers_detail_and_its_booking_reference_stay_hidden(
    account_client, account_db, account_users, captured_mail
):
    owner = make(account_db, full_name="Hanh Nguyen", email="hanh.c@demo.example.com")
    stranger = make(account_db, full_name="Stranger", email="stranger@demo.example.com")
    shipment(account_db, owner, days_ago=3, booking_reference="MINE-1")
    theirs = shipment(account_db, stranger, days_ago=3, booking_reference="THEIRS-DETAIL-1")
    client = _signed_in(account_client, account_users, captured_mail, owner)

    response = client.get(detail_url(theirs.public_id))
    assert response.status_code == 404, response.text
    assert "THEIRS-DETAIL-1" not in response.text
    assert "booking_reference" not in response.json()


def test_public_tracking_still_has_no_booking_reference():
    """DEC-0163 widens the authenticated detail only; OD-31 keeps the public contract narrow.

    Registered in `SUPERSEDED_ASSERTIONS.md` (AS-37): the public count was 24 until RC-UAT-19
    added ``carrier_links`` (DEC-0224, OD-91, OD-92); the booking reference is still absent.
    """
    assert "booking_reference" not in PublicTrackingResult.model_fields
    assert len(PublicTrackingResult.model_fields) == 25
    assert "carrier_links" in PublicTrackingResult.model_fields


# --- 2. A cancelled package's reference, own shipments only -------------------------


def test_a_cancelled_package_reference_finds_only_the_callers_own_shipment(
    account_client, account_db, account_users, captured_mail
):
    owner = make(account_db, full_name="Hanh Nguyen", email="hanh.c@demo.example.com")
    stranger = make(account_db, full_name="Stranger", email="stranger@demo.example.com")
    mine = shipment(account_db, owner, days_ago=3, packages=1, cancelled_packages=1)
    theirs = shipment(account_db, stranger, days_ago=3, packages=1, cancelled_packages=1)
    client = _signed_in(account_client, account_users, captured_mail, owner)

    # The second package is the cancelled one.
    found = client.get(LIST_URL, params={"q": f"{mine.public_id}-02"}).json()
    assert references(found) == [mine.public_id]
    assert found["total"] == 1

    foreign = client.get(LIST_URL, params={"q": f"{theirs.public_id}-02"})
    nothing = client.get(LIST_URL, params={"q": "SX-NO-SUCH-PACKAGE-02"})
    assert foreign.json()["items"] == [] and foreign.json()["total"] == 0
    assert foreign.text == nothing.text
    assert theirs.public_id not in foreign.text


# --- 3. The postal code's lenient shape ---------------------------------------------


@pytest.mark.parametrize(
    ("country", "postal"),
    [
        ("CA", "L4W 1V2"),
        ("CA", "L4W1V2"),
        ("CA", "l4w 1v2"),
        ("CA", "  k1a0b1  "),
        ("US", "98101"),
        ("US", "98101-1234"),
        ("US", " 98101 "),
    ],
)
def test_a_canadian_or_united_states_code_of_the_right_shape_is_accepted(
    account_client, account_db, country, postal
):
    body = registration(
        customer=_customer(**_address(country, postal)), billing_same_as_shipping=True
    )
    response = account_client.post(REGISTER, json=body)
    assert response.status_code == 200, response.text
    # Kept as typed: whitespace is collapsed as for every field, and nothing else changes.
    assert _proposed(account_db)["pickup_address.1.postal_code"] == postal.strip()


@pytest.mark.parametrize(
    ("country", "postal"),
    [
        ("CA", "L4W 1V"),
        ("CA", "L4W-1V2"),
        ("CA", "4LW 1V2"),
        ("CA", "98101"),
        ("CA", "Not a real code"),
        ("US", "9810"),
        ("US", "981011"),
        ("US", "98101-123"),
        ("US", "981011234"),
        ("US", "L4W 1V2"),
    ],
)
def test_a_canadian_or_united_states_code_of_the_wrong_shape_is_refused_by_name(
    account_client, account_db, country, postal
):
    body = registration(
        customer=_customer(**_address(country, postal)), billing_same_as_shipping=True
    )
    response = account_client.post(REGISTER, json=body)
    assert response.status_code == 422, response.text
    assert response.json()["field"] == "pickup_address.1.postal_code"
    assert response.json()["message"] == postal_code_format_message(country, billing=False)
    assert account_db.query(CustomerIdentity).count() == 0


def test_the_sentences_name_the_shape_and_say_blank_is_fine():
    assert postal_code_format_message("CA", billing=False) == (
        "Enter the postal code as A1A 1A1, or leave it blank."
    )
    assert postal_code_format_message("US", billing=True) == (
        "Enter the billing ZIP code as 12345 or 12345-6789, or leave it blank."
    )
    assert sorted(POSTAL_CODE_SHAPES) == ["CA", "US"]


@pytest.mark.parametrize("postal", ["Not a real code", "700000", "A1A 1A1", "12345"])
def test_a_vietnamese_code_is_not_checked(account_client, account_db, postal):
    body = registration(customer=_customer(**_address("VN", postal)), billing_same_as_shipping=True)
    response = account_client.post(REGISTER, json=body)
    assert response.status_code == 200, response.text
    assert _proposed(account_db)["pickup_address.1.postal_code"] == postal


@pytest.mark.parametrize("country", sorted(ADDRESSES))
@pytest.mark.parametrize("postal", [None, "", "   "], ids=["absent", "empty", "spaces"])
def test_a_blank_postal_code_is_always_allowed(account_client, account_db, country, postal):
    body = registration(
        customer=_customer(**_address(country, postal)), billing_same_as_shipping=True
    )
    response = account_client.post(REGISTER, json=body)
    assert response.status_code == 200, response.text
    assert "pickup_address.1.postal_code" not in _proposed(account_db)


def test_an_unticked_billing_code_is_checked_against_the_billing_country(
    account_client, account_db
):
    body = registration(
        customer=_customer(
            **_address("CA", "L4W 1V2"),
            **_address("US", "L4W 1V2", prefix="billing_address."),
        ),
        billing_same_as_shipping=False,
    )
    response = account_client.post(REGISTER, json=body)
    assert response.status_code == 422, response.text
    assert response.json()["field"] == "billing_address.postal_code"
    assert response.json()["message"] == (
        "Enter the billing ZIP code as 12345 or 12345-6789, or leave it blank."
    )
    assert account_db.query(CustomerIdentity).count() == 0


def test_an_unticked_billing_code_of_the_right_shape_is_accepted(account_client, account_db):
    body = registration(
        customer=_customer(
            **_address("CA", "L4W 1V2"),
            **_address("US", "98101-1234", prefix="billing_address."),
        ),
        billing_same_as_shipping=False,
    )
    response = account_client.post(REGISTER, json=body)
    assert response.status_code == 200, response.text
    assert _proposed(account_db)["billing_address.postal_code"] == "98101-1234"


def test_a_ticked_box_refuses_the_address_code_not_the_copy(account_client, account_db):
    """The copy is the same value, but the person typed it in the address block."""
    body = registration(customer=_customer(**_address("CA", "123")), billing_same_as_shipping=True)
    response = account_client.post(REGISTER, json=body)
    assert response.status_code == 422, response.text
    assert response.json()["field"] == "pickup_address.1.postal_code"


def test_a_missing_required_part_is_reported_before_the_postal_shape(account_client):
    address = _address("CA", "123")
    del address["pickup_address.1.city"]
    body = registration(customer=_customer(**address), billing_same_as_shipping=True)
    response = account_client.post(REGISTER, json=body)
    assert response.status_code == 422, response.text
    assert response.json()["field"] == "pickup_address.1.city"


# --- 4. The API's billing default ---------------------------------------------------


def test_a_client_that_omits_the_flag_and_sends_billing_is_told_to_choose(
    account_client, account_db
):
    """Default true means a billing address needs an explicit false, as the form sends."""
    body = registration(
        customer=_customer(
            **_address("CA", "L4W 1V2"), **_address("VN", "700000", prefix="billing_address.")
        )
    )
    body.pop("billing_same_as_shipping", None)
    response = account_client.post(REGISTER, json=body)
    assert response.status_code == 422, response.text
    assert response.json()["field"] == "billing_same_as_shipping"
    assert response.json()["message"] == BILLING_SAME_WITH_BILLING
    assert account_db.query(CustomerIdentity).count() == 0


def test_an_explicit_false_still_takes_a_separate_billing_address(account_client, account_db):
    body = registration(
        customer=_customer(
            **_address("CA", "L4W 1V2"), **_address("VN", "700000", prefix="billing_address.")
        ),
        billing_same_as_shipping=False,
    )
    response = account_client.post(REGISTER, json=body)
    assert response.status_code == 200, response.text
    fields = _proposed(account_db)
    assert fields["billing_address.country_code"] == "VN"
    assert fields["pickup_address.1.country_code"] == "CA"
