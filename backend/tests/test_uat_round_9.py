"""UAT round 9: the owner's decisions of 2026-10-18.

1. The first registration address is "Address", not "Shipping address", and the billing
   box reads "Billing address is the same as the address above" (wording only; see
   ``uatRound9.test.jsx``). The server's sentence for a conflicting submission says the
   same.
2. That address needs a country, line 1, city and province or state. The server refuses
   the first one missing, by field, with the form's sentence. (The postal code was a fifth
   required part until UAT round 11 made it optional; see ``test_uat_round_11.py``.)
3. The driver note's new label is screen wording only (``uatRound9.test.jsx``).
4. With the billing box unticked, the billing address needs the same parts.
5. A customer's own sign-in and sign-out are audited with the actor
   ``customer_account:CA-...`` rather than ``system``; a refused sign-in is not.
6. A refused sign-in is committed: its audit row, the failure count and the lockout
   survive the request (they were rolled back before).
"""

from __future__ import annotations

import pytest

from app.api.account.routes import (
    BILLING_SAME_WITH_BILLING,
    REQUIRED_ADDRESS_PARTS,
    address_part_missing_message,
)
from app.core.enums import Role
from app.models import AuditEvent, CustomerDataProposal, CustomerDataProposalField, CustomerIdentity
from tests.account_fixtures import (
    ACCOUNT_PASSWORD,
    REGISTRATION_BODY,
    REQUIRED_ADDRESS,
    csrf_headers,
    registered_and_verified,
    registration,
    sign_in,
)
from tests.approval_fixtures import staff
from tests.conftest import see_committed_changes

ACCOUNT = "/api/v1/account"
REGISTER = f"{ACCOUNT}/register"
APPLICANT = "hanh@demo.example.com"

ADDRESS = {
    **REQUIRED_ADDRESS,
    "pickup_address.1.address_line2": "Unit 7",
    "pickup_address.1.delivery_note": "Buzz 204, ask the concierge",
}
BILLING = {
    "billing_address.country_code": "VN",
    "billing_address.address_line1": "125 Đường Nguyễn Huệ",
    "billing_address.city": "Thành phố Hồ Chí Minh",
    "billing_address.province_state": "Hồ Chí Minh",
    "billing_address.postal_code": "700000",
}


def _customer_fields(**changes) -> dict:
    """The fixture's customer map without any address, plus ``changes``."""
    base = {
        key: value
        for key, value in REGISTRATION_BODY["customer"].items()
        if not key.startswith(("billing_address.", "pickup_address."))
    }
    return {**base, **changes}


def _refused(response, field: str) -> str:
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["field"] == field, body
    return body["message"]


def _without(fields: dict, key: str, blank: bool) -> dict:
    if blank:
        return {**fields, key: "   "}
    return {name: value for name, value in fields.items() if name != key}


# --- 1. Wording ----------------------------------------------------------------------


def test_the_conflict_sentence_names_the_new_checkbox_wording(account_client):
    body = registration(
        customer=_customer_fields(**ADDRESS, **{"billing_address.address_line1": "1 Other St"}),
        billing_same_as_shipping=True,
    )
    message = _refused(account_client.post(REGISTER, json=body), "billing_same_as_shipping")
    assert message == BILLING_SAME_WITH_BILLING
    assert "the same as the address above" in message
    assert "shipping" not in message


# --- 2. The address is required ------------------------------------------------------


@pytest.mark.parametrize("blank", [False, True], ids=["absent", "blank"])
@pytest.mark.parametrize("part", REQUIRED_ADDRESS_PARTS)
def test_each_required_address_part_is_refused_by_name(account_client, account_db, part, blank):
    key = f"pickup_address.1.{part}"
    body = registration(
        customer=_customer_fields(**_without(ADDRESS, key, blank)), billing_same_as_shipping=True
    )
    message = _refused(account_client.post(REGISTER, json=body), key)
    assert message == address_part_missing_message(part, billing=False)
    assert "billing" not in message
    assert account_db.query(CustomerIdentity).count() == 0


def test_the_first_missing_part_in_screen_order_is_the_one_reported(account_client):
    body = registration(customer=_customer_fields(), billing_same_as_shipping=True)
    assert (
        _refused(account_client.post(REGISTER, json=body), "pickup_address.1.country_code")
        == "Choose the country."
    )
    only_country = _customer_fields(**{"pickup_address.1.country_code": "CA"})
    body = registration(customer=only_country, billing_same_as_shipping=True)
    assert (
        _refused(account_client.post(REGISTER, json=body), "pickup_address.1.address_line1")
        == "Enter the street address (address line 1)."
    )


def test_a_united_states_address_without_a_zip_code_is_accepted(account_client, account_db):
    """Registered in `SUPERSEDED_ASSERTIONS.md` (AS-09): this was the ZIP code refusal."""
    address = _without(
        {**ADDRESS, "pickup_address.1.country_code": "US"}, "pickup_address.1.postal_code", False
    )
    body = registration(customer=_customer_fields(**address), billing_same_as_shipping=True)
    response = account_client.post(REGISTER, json=body)
    assert response.status_code == 200, response.text
    see_committed_changes(account_db)
    assert account_db.query(CustomerIdentity).count() == 1


def test_line_2_and_the_driver_fields_stay_optional(account_client, account_db):
    body = registration(
        customer=_customer_fields(**REQUIRED_ADDRESS), billing_same_as_shipping=True
    )
    assert account_client.post(REGISTER, json=body).status_code == 200, body
    see_committed_changes(account_db)
    proposal = account_db.query(CustomerDataProposal).filter_by(kind="registration").one()
    keys = {
        row.field_key
        for row in account_db.query(CustomerDataProposalField).filter_by(proposal_id=proposal.id)
    }
    for part in REQUIRED_ADDRESS_PARTS:
        assert f"pickup_address.1.{part}" in keys
        assert f"billing_address.{part}" in keys
    assert "pickup_address.1.address_line2" not in keys
    assert "pickup_address.1.delivery_note" not in keys


# --- 4. Billing is required when the box is unticked ---------------------------------


@pytest.mark.parametrize("blank", [False, True], ids=["absent", "blank"])
@pytest.mark.parametrize("part", REQUIRED_ADDRESS_PARTS)
def test_each_billing_part_is_required_when_unticked(account_client, account_db, part, blank):
    key = f"billing_address.{part}"
    body = registration(
        customer=_customer_fields(**ADDRESS, **_without(BILLING, key, blank)),
        billing_same_as_shipping=False,
    )
    message = _refused(account_client.post(REGISTER, json=body), key)
    assert message == address_part_missing_message(part, billing=True)
    assert "billing" in message
    assert account_db.query(CustomerIdentity).count() == 0


def test_the_address_is_checked_before_the_billing_address(account_client):
    address = _without(ADDRESS, "pickup_address.1.city", False)
    body = registration(customer=_customer_fields(**address), billing_same_as_shipping=False)
    _refused(account_client.post(REGISTER, json=body), "pickup_address.1.city")


def test_unticked_with_both_complete_addresses_is_accepted(account_client, account_db):
    body = registration(
        customer=_customer_fields(**ADDRESS, **BILLING), billing_same_as_shipping=False
    )
    assert account_client.post(REGISTER, json=body).status_code == 200
    see_committed_changes(account_db)
    assert account_db.query(CustomerIdentity).count() == 1


def test_ticked_needs_no_billing_parts(account_client, account_db):
    body = registration(customer=_customer_fields(**ADDRESS), billing_same_as_shipping=True)
    assert account_client.post(REGISTER, json=body).status_code == 200
    see_committed_changes(account_db)
    assert account_db.query(CustomerIdentity).count() == 1


# --- 5. Sign-in and sign-out name the customer account ------------------------------


def _rows(db, action: str) -> list[AuditEvent]:
    see_committed_changes(db)
    return db.query(AuditEvent).filter_by(action=action).order_by(AuditEvent.id).all()


def test_sign_in_and_sign_out_are_audited_with_the_customer_account_as_actor(
    account_client, account_db, account_users, captured_mail
):
    registered_and_verified(account_client, captured_mail, APPLICANT)
    signed_in = sign_in(account_client, APPLICANT)
    assert signed_in.status_code == 200, signed_in.text
    reference = signed_in.json()["account_reference"]
    out = account_client.post(f"{ACCOUNT}/sign-out", headers=csrf_headers(signed_in))
    assert out.status_code == 200, out.text
    account_client.cookies.clear()

    expected = f"customer_account:{reference}"
    for action in ("customer_account.sign_in", "customer_account.sign_out"):
        rows = _rows(account_db, action)
        assert rows, action
        assert {row.actor_label for row in rows} == {expected}
        assert {row.actor_user_id for row in rows} == {None}

    # Audit access shows the same actor to staff.
    admin = staff(account_client, account_users[Role.ADMIN].email)
    page = admin.get("/api/v1/audit", params={"action": "customer_account.sign_in"}).json()
    assert {item["actor_label"] for item in page["items"]} == {expected}
    page = admin.get("/api/v1/audit", params={"action": "customer_account.sign_out"}).json()
    assert {item["actor_label"] for item in page["items"]} == {expected}


def test_a_refused_sign_in_keeps_the_system_actor(account_client, account_db, captured_mail):
    registered_and_verified(account_client, captured_mail, APPLICANT)
    refused = sign_in(account_client, APPLICANT, ACCOUNT_PASSWORD + "x")
    assert refused.status_code != 200
    rows = _rows(account_db, "customer_account.sign_in_failed")
    assert rows
    assert {row.actor_label for row in rows} == {"system"}


def test_the_lockout_engages_over_http(account_client, account_db, captured_mail, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "account_lockout_threshold", 3)
    registered_and_verified(account_client, captured_mail, APPLICANT)
    for _ in range(3):
        assert sign_in(account_client, APPLICANT, ACCOUNT_PASSWORD + "x").status_code == 401
    see_committed_changes(account_db)
    identity = account_db.query(CustomerIdentity).filter_by(email_normalized=APPLICANT).one()
    assert identity.locked_until is not None
    assert _rows(account_db, "customer_account.locked")
    # Locked: even the right password is refused, with the same sentence.
    refused = sign_in(account_client, APPLICANT)
    assert refused.status_code == 401
    assert refused.json()["message"] == "Email or password is incorrect."
