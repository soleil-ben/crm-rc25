"""RC-UAT-25 item 2, Ben 2026-10-25: the sign-in email is changed by an Admin only.

1. The customer cannot change it: the request route refuses (403, one sentence) before
   reading the body, sends nothing and writes nothing; a link sent before the change no
   longer works (the account is untouched, the request is closed, the link cannot be retried,
   no session ends); a request still pending is closed when the customer opens "Sign-in and
   security". The password change stays.
2. An Admin changes it on the staff account screen: Admin only (the deactivation permission),
   a bounded reason and an optional note, the address normalized, the single email rule
   (another account, another customer record), the unique index on a true race, the linked
   customer's email follows, every session ends, every outstanding link dies, the old address
   is told and the new one is told how to sign in, audited with keyed digests only, and the
   history kept on ``customer_account_email_changes``.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.core.account_enums import IdentityStatus
from app.core.enums import Role
from app.main import app
from app.models import (
    Customer,
    CustomerAccountEmailChange,
    CustomerAuthToken,
    CustomerEmailChangeRequest,
    CustomerIdentity,
)
from app.services import account_email_service as email
from app.services import customer_account_security_service as security
from tests.account_fixtures import ACCOUNT_PASSWORD
from tests.approval_fixtures import pending_identity, staff
from tests.conftest import make_customer, see_committed_changes
from tests.test_rc21_account_security import (
    ACCOUNT,
    APPLICANT,
    REVIEW,
    Account,
    _activate,
    _audits,
    _identity,
    _link_token,
    _live_sessions,
    _messages,
    _sign_in,
    legacy_link,
)

NEW_ADDRESS = "hanh.moi@demo.example.com"
WITHDRAWN = (
    "Your sign-in email can only be changed by Solaris Express. Contact us and we will "
    "change it for you."
)
TOKEN_FAILURE = "That link is no longer valid. Request a new one."


def _change(api, reference: str, **body):
    payload = {"new_email": NEW_ADDRESS, "reason_code": "customer_request", **body}
    return api.post(f"{REVIEW}/identities/{reference}/sign-in-email", json=payload)


@pytest.fixture
def active(account_client, account_db, account_users, captured_mail):
    reference = _activate(account_client, account_users, captured_mail)
    return {
        "reference": reference,
        "db": account_db,
        "mail": captured_mail,
        "users": account_users,
        "client": account_client,
    }


# === 1. The customer cannot change it ============================================================


def test_the_customer_request_is_refused_with_one_sentence_and_nothing_happens(active):
    db, mail = active["db"], active["mail"]
    me = Account()
    mail.messages.clear()
    answers = set()
    for body in (
        {"current_password": ACCOUNT_PASSWORD, "new_email": NEW_ADDRESS},
        {"current_password": "wrong", "new_email": "not-an-address"},
        {},
    ):
        response = me.post("/email/change", body)
        assert response.status_code == 403, response.text
        answers.add(json.dumps(response.json(), sort_keys=True))
    assert len(answers) == 1
    assert json.loads(answers.pop())["message"] == WITHDRAWN
    assert mail.messages == []
    see_committed_changes(db)
    assert db.query(CustomerEmailChangeRequest).count() == 0
    assert db.query(CustomerAuthToken).filter_by(purpose="email_change").count() == 0
    assert _identity(db).email_normalized == APPLICANT
    # The session and the CSRF check still come first.
    assert me.post("/email/change", {}, csrf=False).status_code == 403
    assert TestClient(app).post(f"{ACCOUNT}/email/change", json={}).status_code == 401


def test_a_link_sent_before_the_change_no_longer_works(active):
    db = active["db"]
    me = Account()
    token = legacy_link(db, _identity(db), NEW_ADDRESS)
    refused = me.client.post(f"{ACCOUNT}/email/change/confirm", json={"token": token})
    assert refused.status_code == 422
    assert refused.json()["message"] == TOKEN_FAILURE
    identity = _identity(db)
    assert identity.email_normalized == APPLICANT
    assert db.query(Customer).filter_by(email_normalized=APPLICANT).count() == 1
    row = db.query(CustomerEmailChangeRequest).one()
    assert (row.status, row.refused_reason_code) == ("refused", "self_service_withdrawn")
    # Consumed: it cannot be tried again; and no session ended.
    assert db.query(CustomerAuthToken).filter_by(purpose="email_change").one().consumed_at
    again = TestClient(app).post(f"{ACCOUNT}/email/change/confirm", json={"token": token})
    assert again.status_code == 422
    assert me.get("/me").status_code == 200
    reasons = [
        json.loads(r.detail_json)["reason_code"]
        for r in _audits(db, "customer_account.email_change_refused")
    ]
    assert reasons == ["self_service_withdrawn"]


def test_opening_the_security_page_closes_a_pending_request(active):
    db = active["db"]
    me = Account()
    token = legacy_link(db, _identity(db), NEW_ADDRESS)
    page = me.get("/security")
    assert page.status_code == 200
    assert page.json()["email"] == APPLICANT and page.json()["pending_email_change"] is None
    see_committed_changes(db)
    assert db.query(CustomerEmailChangeRequest).one().status == "cancelled"
    reasons = [
        json.loads(r.detail_json)["reason_code"]
        for r in _audits(db, "customer_account.email_change_cancelled")
    ]
    assert reasons == ["self_service_withdrawn"]
    assert (
        TestClient(app).post(f"{ACCOUNT}/email/change/confirm", json={"token": token}).status_code
        == 422
    )
    # A second read finds nothing to close and records nothing.
    assert me.get("/security").status_code == 200
    assert len(_audits(db, "customer_account.email_change_cancelled")) == 1


def test_the_password_change_stays(active):
    me = Account()
    response = me.post(
        "/password/change",
        {
            "current_password": ACCOUNT_PASSWORD,
            "new_password": "SolarisCustomer!2028",
            "new_password_confirmation": "SolarisCustomer!2028",
        },
    )
    assert response.status_code == 200, response.text
    assert _sign_in(APPLICANT, "SolarisCustomer!2028").status_code == 200


# === 2. An Admin changes it ======================================================================


def test_admin_changes_the_sign_in_email_and_everything_follows(active):
    db, mail, users, reference = active["db"], active["mail"], active["users"], active["reference"]
    customer = db.query(Customer).filter_by(email_normalized=APPLICANT).one()
    customer.preferred_language = "vi"
    db.commit()
    first, second = Account(), Account()
    assert TestClient(app).post(f"{ACCOUNT}/password/forgot", json={"email": APPLICANT})
    reset = _link_token(_messages(mail, email.TEMPLATE_PASSWORD_RESET, APPLICANT)[-1])
    stale = legacy_link(db, _identity(db), "elsewhere@demo.example.com")
    mail.messages.clear()

    admin = staff(active["client"], users[Role.ADMIN].email)
    shown = admin.get(f"{REVIEW}/identities/{reference}").json()
    assert shown["can_change_sign_in_email"] is True
    response = _change(
        admin,
        reference,
        new_email="Hanh.Moi@Demo.Example.com",
        reason_code="mailbox_lost",
        note="Phoned in; old mailbox closed.",
    )
    assert response.status_code == 200, response.text
    assert response.json()["account_email_entered"] == "Hanh.Moi@Demo.Example.com"

    identity = _identity(db, NEW_ADDRESS)
    assert identity.email_entered == "Hanh.Moi@Demo.Example.com"
    see_committed_changes(db)
    followed = db.get(Customer, customer.id)
    assert followed.email_normalized == NEW_ADDRESS
    assert followed.email_entered == "Hanh.Moi@Demo.Example.com"

    # Every session ended; the new address signs in with the unchanged password.
    assert first.get("/me").status_code == 401 and second.get("/me").status_code == 401
    assert _live_sessions(db, identity.id) == []
    assert _sign_in(APPLICANT, ACCOUNT_PASSWORD).status_code == 401
    assert _sign_in(NEW_ADDRESS, ACCOUNT_PASSWORD).status_code == 200

    # Every outstanding link died.
    redeemed = TestClient(app).post(
        f"{ACCOUNT}/password/reset",
        json={
            "token": reset,
            "password": "Another!Password2029",
            "password_confirmation": "Another!Password2029",
        },
    )
    assert redeemed.status_code == 422
    assert (
        TestClient(app).post(f"{ACCOUNT}/email/change/confirm", json={"token": stale}).status_code
        == 422
    )
    see_committed_changes(db)
    assert {r.status for r in db.query(CustomerEmailChangeRequest)} == {"cancelled"}

    # Notices: the old address (no address, no token), the new one (how to sign in), in vi.
    old = _messages(mail, email.TEMPLATE_EMAIL_CHANGED_NOTICE, APPLICANT)
    new = _messages(mail, email.TEMPLATE_SIGN_IN_EMAIL_SET_BY_STAFF, NEW_ADDRESS)
    assert len(old) == 1 and len(new) == 1
    assert old[0]["language"] == "vi" and new[0]["language"] == "vi"
    assert NEW_ADDRESS not in old[0]["body"].lower() and "token" not in old[0]["body"]
    assert "/sign-in" in new[0]["body"] and "token" not in new[0]["body"]
    assert _messages(mail, email.TEMPLATE_EMAIL_CHANGE_CONFIRM) == []

    # History row with the note; audit with keyed digests, the reason and the actor only.
    record = db.query(CustomerAccountEmailChange).one()
    assert record.previous_email_entered == APPLICANT
    assert record.new_email_entered == "Hanh.Moi@Demo.Example.com"
    assert record.reason_code == "mailbox_lost" and record.note == "Phoned in; old mailbox closed."
    assert record.customer_id == customer.id and record.sessions_revoked == 2
    assert record.changed_by_user_id == users[Role.ADMIN].id
    rows = _audits(db, "customer_account.sign_in_email_changed_by_staff")
    assert len(rows) == 1 and rows[0].actor_user_id == users[Role.ADMIN].id
    detail = json.loads(rows[0].detail_json)
    assert detail["reason_code"] == "mailbox_lost" and detail["count"] == 2
    assert detail["customer_public_id"] == customer.public_id
    assert detail["address_key"] and detail["previous_address_key"]
    raw = rows[0].detail_json.lower() + rows[0].summary.lower()
    assert NEW_ADDRESS not in raw and APPLICANT not in raw and "mailbox closed" not in raw


def test_only_admin_may_change_it(active):
    db, users, reference, client = (
        active["db"],
        active["users"],
        active["reference"],
        active["client"],
    )
    for role in (Role.OPERATIONS, Role.MARKETING, Role.READ_ONLY_MANAGER):
        refused = _change(staff(client, users[role].email), reference)
        assert refused.status_code == 403, role
    assert _identity(db).email_normalized == APPLICANT
    assert db.query(CustomerAccountEmailChange).count() == 0


@pytest.mark.parametrize(
    ("body", "status", "field"),
    [
        ({"reason_code": "because"}, 422, "reason_code"),
        ({"new_email": "not-an-address"}, 422, "new_email"),
        ({"new_email": APPLICANT.upper()}, 422, "new_email"),
        ({"note": "x" * 501}, 422, None),
    ],
)
def test_admin_change_refusals_about_the_input(active, body, status, field):
    admin = staff(active["client"], active["users"][Role.ADMIN].email)
    response = _change(admin, active["reference"], **body)
    assert response.status_code == status, response.text
    if field:
        assert response.json()["field"] == field
    assert _identity(active["db"]).email_normalized == APPLICANT


def test_the_single_email_rule_refuses_an_address_already_held(active):
    db, mail, client = active["db"], active["mail"], active["client"]
    pending_identity(client, mail, "taken@demo.example.com")
    make_customer(db, email="record@demo.example.com")
    db.commit()
    admin = staff(client, active["users"][Role.ADMIN].email)
    held_by_account = _change(admin, active["reference"], new_email="Taken@demo.example.com")
    assert held_by_account.status_code == 409
    assert held_by_account.json()["message"] == security.ADDRESS_HELD_BY_ACCOUNT
    held_by_record = _change(admin, active["reference"], new_email="record@demo.example.com")
    assert held_by_record.status_code == 409
    assert held_by_record.json()["message"] == security.ADDRESS_HELD_BY_CUSTOMER
    assert _identity(db).email_normalized == APPLICANT
    assert db.query(CustomerAccountEmailChange).count() == 0


def test_the_unique_index_decides_a_true_race(active, monkeypatch):
    db = active["db"]
    db.add(
        CustomerIdentity(
            public_id="CA-999998",
            email_entered=NEW_ADDRESS,
            email_normalized=NEW_ADDRESS,
            password_hash="x",
            status=IdentityStatus.PENDING_VERIFICATION.value,
        )
    )
    db.commit()
    monkeypatch.setattr(security, "address_refusal", lambda *_args: None)
    admin = staff(active["client"], active["users"][Role.ADMIN].email)
    assert _change(admin, active["reference"]).status_code == 409
    assert _identity(db).email_normalized == APPLICANT
    assert db.query(CustomerAccountEmailChange).count() == 0


def test_a_deactivated_account_must_be_reinstated_first(active):
    admin = staff(active["client"], active["users"][Role.ADMIN].email)
    reference = active["reference"]
    assert (
        admin.post(
            f"{REVIEW}/identities/{reference}/deactivate", json={"reason_code": "customer_request"}
        ).status_code
        == 200
    )
    assert admin.get(f"{REVIEW}/identities/{reference}").json()["can_change_sign_in_email"] is False
    refused = _change(admin, reference)
    assert refused.status_code == 409
    assert "deactivated" in refused.json()["message"]


def test_an_account_waiting_for_review_can_be_corrected(
    account_client, account_db, account_users, captured_mail
):
    reference = pending_identity(account_client, captured_mail, "cho@demo.example.com")
    admin = staff(account_client, account_users[Role.ADMIN].email)
    response = _change(admin, reference, new_email="cho.dung@demo.example.com")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending_approval"
    record = account_db.query(CustomerAccountEmailChange).one()
    assert record.customer_id is None and record.reason_code == "customer_request"
    assert _sign_in("cho.dung@demo.example.com", ACCOUNT_PASSWORD).status_code == 200
