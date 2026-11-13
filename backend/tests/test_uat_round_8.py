"""UAT round 8: the owner's real-phone feedback and the staff-side gaps (2026-10-17).

1. Registration shows the shipping (pickup) address first and billing second (screen
   order only; see ``uatRound8.test.jsx``).
2. "Billing address is the same as shipping address": when ticked the server copies the
   shipping address into billing and refuses billing keys sent with it; when not ticked a
   filled shipping address needs a billing address.
3. The password is typed twice at registration and at reset, and the server refuses a
   missing or different confirmation.
4. A change request's approved values are not reported as drift once they are applied;
   a later change by someone else still is.
5. The ``customer.update`` row an approval writes names each field with its old and new
   value, instead of only ``contact``.
6. A customer's own marketing choice, and their other profile events, are audited with
   the actor ``customer_account:CA-...`` rather than ``system``.
"""

from __future__ import annotations

import json

from app.core.enums import Role
from app.models import (
    AuditEvent,
    Customer,
    CustomerDataProposal,
    CustomerDataProposalField,
    CustomerIdentity,
)
from app.services.customer_auth_service import (
    PASSWORD_CONFIRMATION_MISMATCH,
    PASSWORD_CONFIRMATION_MISSING,
)
from tests.account_fixtures import (
    ACCOUNT_PASSWORD,
    REGISTRATION_BODY,
    csrf_headers,
    registered_and_verified,
    registration,
    reset_token,
    sign_in,
)
from tests.approval_fixtures import acknowledged_preview, approve_create, pending_identity, staff
from tests.conftest import see_committed_changes

ACCOUNT = "/api/v1/account"
REGISTER = f"{ACCOUNT}/register"
FORGOT = f"{ACCOUNT}/password/forgot"
RESET = f"{ACCOUNT}/password/reset"
REVIEW = "/api/v1/customer-account"
APPLICANT = "hanh@demo.example.com"
NEW_PASSWORD = "BrandNewPhrase!2026"

SHIPPING = {
    "pickup_address.1.contact_name": "Tran Quoc Tuan",
    "pickup_address.1.address_line1": "4120 Dixie Road",
    "pickup_address.1.address_line2": "Unit 7",
    "pickup_address.1.city": "Mississauga",
    "pickup_address.1.province_state": "ON",
    "pickup_address.1.postal_code": "L4W 1V2",
    "pickup_address.1.country_code": "CA",
    "pickup_address.1.delivery_note": "Side door",
}


def _customer_fields(**changes) -> dict:
    """The fixture's customer map without any address, plus ``changes``."""
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


def _refused(response, field: str) -> str:
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["field"] == field, body
    return body["message"]


# --- 2. Billing address is the same as shipping address --------------------------------


def test_ticked_copies_the_shipping_address_into_billing(account_client, account_db):
    body = registration(customer=_customer_fields(**SHIPPING), billing_same_as_shipping=True)
    assert account_client.post(REGISTER, json=body).status_code == 200

    fields = _proposed(account_db)
    for part in ("address_line1", "address_line2", "city", "province_state", "postal_code"):
        assert fields[f"billing_address.{part}"] == fields[f"pickup_address.1.{part}"]
    assert fields["billing_address.country_code"] == "CA"
    # The pickup-only parts have no billing counterpart and are not invented.
    assert not any(key.startswith("billing_address.contact") for key in fields)
    assert "billing_address.delivery_note" not in fields


def test_ticked_with_billing_keys_as_well_is_refused(account_client, account_db):
    customer = _customer_fields(**SHIPPING, **{"billing_address.address_line1": "1 Other St"})
    body = registration(customer=customer, billing_same_as_shipping=True)
    _refused(account_client.post(REGISTER, json=body), "billing_same_as_shipping")
    assert account_db.query(CustomerIdentity).count() == 0


def test_ticked_without_a_shipping_address_is_refused(account_client, account_db):
    # Since UAT round 9 the address itself is required, so the refusal names its first
    # missing part rather than the box.
    body = registration(customer=_customer_fields(), billing_same_as_shipping=True)
    _refused(account_client.post(REGISTER, json=body), "pickup_address.1.country_code")
    assert account_db.query(CustomerIdentity).count() == 0


def test_unticked_with_a_shipping_address_needs_a_billing_address(account_client, account_db):
    body = registration(customer=_customer_fields(**SHIPPING), billing_same_as_shipping=False)
    message = _refused(account_client.post(REGISTER, json=body), "billing_address.country_code")
    assert "billing" in message
    assert account_db.query(CustomerIdentity).count() == 0


def test_unticked_keeps_a_different_billing_address(account_client, account_db):
    billing = {
        "billing_address.address_line1": "125 Đường Nguyễn Huệ",
        "billing_address.city": "Thành phố Hồ Chí Minh",
        "billing_address.province_state": "Hồ Chí Minh",
        "billing_address.postal_code": "700000",
        "billing_address.country_code": "VN",
    }
    body = registration(customer=_customer_fields(**SHIPPING, **billing))
    assert account_client.post(REGISTER, json=body).status_code == 200
    fields = _proposed(account_db)
    assert fields["billing_address.address_line1"] == "125 Đường Nguyễn Huệ"
    assert fields["pickup_address.1.address_line1"] == "4120 Dixie Road"
    assert fields["billing_address.postal_code"] == "700000"


def test_with_no_address_at_all_registration_is_refused(account_client, account_db):
    # Optional in round 8; required since UAT round 9.
    body = registration(customer=_customer_fields())
    _refused(account_client.post(REGISTER, json=body), "pickup_address.1.country_code")
    assert account_db.query(CustomerIdentity).count() == 0


# --- 3. Confirm password ---------------------------------------------------------------


def test_registration_refuses_a_missing_or_different_confirmation(account_client, account_db):
    missing = registration()
    del missing["password_confirmation"]
    assert (
        _refused(account_client.post(REGISTER, json=missing), "password_confirmation")
        == PASSWORD_CONFIRMATION_MISSING
    )
    different = registration(password_confirmation=ACCOUNT_PASSWORD + "x")
    assert (
        _refused(account_client.post(REGISTER, json=different), "password_confirmation")
        == PASSWORD_CONFIRMATION_MISMATCH
    )
    # Exact comparison: a confirmation that differs only by case is a different password.
    upper = registration(password_confirmation=ACCOUNT_PASSWORD.upper())
    _refused(account_client.post(REGISTER, json=upper), "password_confirmation")
    assert account_db.query(CustomerIdentity).count() == 0


def test_a_short_password_is_reported_as_short_before_any_mismatch(account_client):
    body = registration(password="short", password_confirmation="different")
    _refused(account_client.post(REGISTER, json=body), "password")


def test_reset_refuses_a_bad_confirmation_and_keeps_the_link_usable(account_client, captured_mail):
    registered_and_verified(account_client, captured_mail, APPLICANT)
    account_client.post(FORGOT, json={"email": APPLICANT})
    token = reset_token(captured_mail, APPLICANT)

    missing = account_client.post(RESET, json={"token": token, "password": NEW_PASSWORD})
    assert _refused(missing, "password_confirmation") == PASSWORD_CONFIRMATION_MISSING
    different = account_client.post(
        RESET,
        json={"token": token, "password": NEW_PASSWORD, "password_confirmation": "Other!2026xx"},
    )
    assert _refused(different, "password_confirmation") == PASSWORD_CONFIRMATION_MISMATCH

    # Refused before the token is touched, so the same link still works.
    done = account_client.post(
        RESET,
        json={"token": token, "password": NEW_PASSWORD, "password_confirmation": NEW_PASSWORD},
    )
    assert done.status_code == 200, done.text
    assert sign_in(account_client, APPLICANT, NEW_PASSWORD).status_code == 200


# --- 4 and 5. Approving a change request ---------------------------------------------


def _linked(account_client, account_users, captured_mail):
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    fingerprint = acknowledged_preview(api, reference, "create_new")
    assert approve_create(api, reference, fingerprint).status_code == 200
    account_client.cookies.clear()
    return reference


def _propose(account_client, fields: dict):
    account_client.cookies.clear()
    signed_in = sign_in(account_client, APPLICANT)
    response = account_client.post(
        f"{ACCOUNT}/profile/proposals", json={"fields": fields}, headers=csrf_headers(signed_in)
    )
    assert response.status_code in (200, 201), response.text
    account_client.cookies.clear()


CHANGE = {
    "legal_name": "Trần Thị Bích Hạnh",
    "display_name": "Chị Hạnh",
    "phone_country_code": "CA",
    "phone": "416 555 0199",
    "pickup_address.1.address_line1": "88 Queen Street East",
    "pickup_address.1.city": "Toronto",
    "pickup_address.1.country_code": "CA",
}


def _approve_all(api, reference):
    review = api.get(f"{REVIEW}/identities/{reference}/profile-proposal").json()
    response = api.post(
        f"{REVIEW}/identities/{reference}/profile-proposal/decide",
        json={"decisions": dict.fromkeys(review["groups"], "approve")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_approved_values_are_not_reported_as_drift(
    account_client, account_db, account_users, captured_mail
):
    reference = _linked(account_client, account_users, captured_mail)
    _propose(account_client, CHANGE)
    api = staff(account_client, account_users[Role.OPERATIONS].email)

    decided = _approve_all(api, reference)
    assert decided["status"] == "approved"
    assert all(row["applied"] for row in decided["fields"])
    assert [row["field_key"] for row in decided["fields"] if row["drifted"]] == []

    reread = api.get(f"{REVIEW}/identities/{reference}/profile-proposal").json()
    assert [row["field_key"] for row in reread["fields"] if row["drifted"]] == []


def test_a_change_by_someone_else_after_approval_is_still_drift(
    account_client, account_db, account_users, captured_mail
):
    reference = _linked(account_client, account_users, captured_mail)
    _propose(account_client, CHANGE)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    _approve_all(api, reference)

    see_committed_changes(account_db)
    customer = account_db.query(Customer).filter_by(email_normalized=APPLICANT).one()
    customer.display_name = "Edited by staff afterwards"
    account_db.commit()

    reread = api.get(f"{REVIEW}/identities/{reference}/profile-proposal").json()
    assert [row["field_key"] for row in reread["fields"] if row["drifted"]] == ["display_name"]


def test_a_declined_group_does_not_become_drift(
    account_client, account_db, account_users, captured_mail
):
    reference = _linked(account_client, account_users, captured_mail)
    _propose(account_client, {"display_name": "Chị Hạnh", "legal_name": "Trần Thị Bích Hạnh"})
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    response = api.post(
        f"{REVIEW}/identities/{reference}/profile-proposal/decide",
        json={
            "decisions": {"display_name": "approve", "legal_name": "decline"},
            "reason_code": "could_not_verify",
        },
    )
    assert response.status_code == 200, response.text
    rows = {row["field_key"]: row for row in response.json()["fields"]}
    assert rows["display_name"]["drifted"] is False
    assert rows["legal_name"]["drifted"] is False
    assert rows["legal_name"]["applied"] is False


def _update_rows(db) -> list[dict]:
    see_committed_changes(db)
    rows = db.query(AuditEvent).filter_by(action="customer.update").order_by(AuditEvent.id).all()
    return [json.loads(row.detail_json) | {"_summary": row.summary} for row in rows]


def test_the_approval_audit_names_each_field_with_old_and_new_values(
    account_client, account_db, account_users, captured_mail
):
    reference = _linked(account_client, account_users, captured_mail)
    see_committed_changes(account_db)
    customer = account_db.query(Customer).filter_by(email_normalized=APPLICANT).one()
    old_legal, old_display, old_phone = (
        customer.legal_name or customer.full_name,
        customer.display_name,
        customer.phone_entered,
    )
    updates_before = len(_update_rows(account_db))

    _propose(account_client, CHANGE)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    _approve_all(api, reference)

    rows = _update_rows(account_db)
    assert len(rows) == updates_before + 1
    detail = rows[-1]
    assert "contact" not in detail["changed_fields"]
    assert detail["source"] == "customer_account_profile_proposal"
    assert "approved change request" in detail["_summary"]
    changes = {item["field"]: (item["old"], item["new"]) for item in detail["changes"]}
    assert changes["legal_name"] == (old_legal, "Trần Thị Bích Hạnh")
    assert changes["display_name"] == (old_display, "Chị Hạnh")
    assert changes["phone"] == (old_phone, "416 555 0199")
    assert changes["pickup_address.1.address_line1"][1] == "88 Queen Street East"
    assert set(changes) <= set(detail["changed_fields"])

    # The audit screen shows the same values to a role that reads the audit.
    admin = staff(account_client, account_users[Role.ADMIN].email)
    item = admin.get("/api/v1/audit", params={"action": "customer.update"}).json()["items"][0]
    shown = {entry["field"]: (entry["old"], entry["new"]) for entry in item["changes"]}
    assert shown["display_name"] == (old_display, "Chị Hạnh")
    assert "phone" in item["changed_fields"]


def test_an_address_only_approval_still_writes_the_customer_update(
    account_client, account_db, account_users, captured_mail
):
    reference = _linked(account_client, account_users, captured_mail)
    updates_before = len(_update_rows(account_db))
    _propose(
        account_client,
        {key: value for key, value in CHANGE.items() if key.startswith("pickup_address.")},
    )
    _approve_all(staff(account_client, account_users[Role.ADMIN].email), reference)

    rows = _update_rows(account_db)
    assert len(rows) == updates_before + 1
    # The registration's pickup address was already in Canada, so the country is not a
    # change and is not listed as one.
    assert {item["field"] for item in rows[-1]["changes"]} == {
        "pickup_address.1.address_line1",
        "pickup_address.1.city",
    }


def test_a_plain_staff_edit_still_writes_names_only(account_client, account_db, account_users):
    from tests.conftest import make_customer

    customer = make_customer(account_db)
    account_db.commit()
    admin = staff(account_client, account_users[Role.ADMIN].email)
    response = admin.client.patch(
        f"/api/v1/customers/{customer.id}", json={"city": "Hà Nội"}, headers=admin.headers
    )
    assert response.status_code == 200, response.text
    detail = _update_rows(account_db)[-1]
    assert detail["changed_fields"] == ["city"]
    assert "changes" not in detail
    assert "Hà Nội" not in json.dumps(detail, ensure_ascii=False)


# --- 6. The customer is the actor --------------------------------------------------------


def test_a_customer_withdrawal_is_audited_with_the_customer_account_as_actor(
    account_client, account_db, account_users, captured_mail
):
    reference = _linked(account_client, account_users, captured_mail)
    account_client.cookies.clear()
    signed_in = sign_in(account_client, APPLICANT)
    headers = csrf_headers(signed_in)
    for granted in (True, False):
        response = account_client.post(
            f"{ACCOUNT}/consent/marketing", json={"granted": granted}, headers=headers
        )
        assert response.status_code == 200, response.text
    direct = account_client.post(
        f"{ACCOUNT}/profile/direct", json={"preferred_language": "vi"}, headers=headers
    )
    assert direct.status_code == 200, direct.text
    account_client.cookies.clear()

    see_committed_changes(account_db)
    expected = f"customer_account:{reference}"
    choices = (
        account_db.query(AuditEvent)
        .filter_by(action="customer_account.marketing_choice")
        .order_by(AuditEvent.id)
        .all()
    )
    assert [json.loads(row.detail_json)["status"] for row in choices] == ["granted", "withdrawn"]
    assert {row.actor_label for row in choices} == {expected}
    assert {row.actor_user_id for row in choices} == {None}
    language = (
        account_db.query(AuditEvent)
        .filter_by(action="customer_account.profile_direct_update")
        .one()
    )
    assert language.actor_label == expected

    # The staff consent history names the account too, not "system".
    customer = account_db.query(Customer).filter_by(email_normalized=APPLICANT).one()
    admin = staff(account_client, account_users[Role.ADMIN].email)
    history = admin.get(f"/api/v1/customers/{customer.id}/consent").json()["history"]
    mine = [event for event in history if event["source"] == "customer_account"]
    assert len(mine) == 2
    assert {event["recorded_by_account"] for event in mine} == {expected}
    assert {event["recorded_by"] for event in mine} == {None}


def test_a_staff_consent_row_has_no_account_actor(account_client, account_db, account_users):
    from tests.conftest import make_customer

    customer = make_customer(account_db, email="staffrecorded@demo.example.com")
    account_db.commit()
    admin = staff(account_client, account_users[Role.ADMIN].email)
    recorded = admin.post(
        f"/api/v1/customers/{customer.id}/consent",
        json={
            "channel": "email",
            "status": "withdrawn",
            "basis": "not_recorded",
            "evidence_reference": "customer_account:CA-000001",
            "source": "phone_call",
        },
    )
    assert recorded.status_code == 201, recorded.text
    history = recorded.json()["history"]
    assert history[0]["recorded_by_account"] is None
    assert history[0]["recorded_by"] is not None
