"""RC-UAT-21 Phase B (DEC-0231): password change, self-service email change, reinstatement.

Driven through the real routes on the account test database: an applicant registers, staff
approve (which creates and links the customer), and the customer signs in. Each actor has its
own ``TestClient`` (its own cookie jar), so "every other session is revoked" is tested with
real, separate sessions.

1. Customer password change: current password required, policy, not the same, other sessions
   revoked and this one rotated, reset links die, notice in the customer's language, audited,
   rate-limited, CSRF and session required.
2. Staff password change: the same principles with the staff session model.
3. Email change -- since RC-UAT-25 item 2 (Ben, 2026-10-25) an Admin's alone: the customer's
   request is refused with one sentence for every address (no enumeration, nothing sent), an
   outstanding link changes nothing, a password change or reset still closes a pending
   request; the Admin's change keeps the single email rule and the unique index, ends every
   session and tells the old address. The superseded assertions are registered in
   docs/customer_account/SUPERSEDED_ASSERTIONS.md (AS-44 to AS-55).
4. Reinstating a deactivated account: Admin only, reason required, the prior usable status,
   old sessions stay revoked, notice, audited; privacy-request deactivations refused.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.account_enums import IdentityStatus, TokenPurpose
from app.core.config import settings
from app.core.enums import Role
from app.core.security import hash_token
from app.core.time_utils import utcnow
from app.main import app
from app.models import (
    AuditEvent,
    Customer,
    CustomerAccountReinstatement,
    CustomerAuthToken,
    CustomerEmailChangeRequest,
    CustomerIdentity,
    CustomerSession,
    User,
    UserSession,
)
from app.services import account_email_service as email
from tests.account_fixtures import ACCOUNT_PASSWORD
from tests.approval_fixtures import acknowledged_preview, approve_create, pending_identity, staff
from tests.conftest import TEST_PASSWORD, make_customer, see_committed_changes

ACCOUNT = "/api/v1/account"
REVIEW = "/api/v1/customer-account"
APPLICANT = "hanh@demo.example.com"
NEW_ADDRESS = "hanh.moi@demo.example.com"
NEW_PASSWORD = "SolarisCustomer!2027"


# --- Helpers ----------------------------------------------------------------------------------


class Account:
    """A signed-in customer on its own TestClient: its own cookie jar, its own session."""

    def __init__(self, email_address: str = APPLICANT, password: str = ACCOUNT_PASSWORD) -> None:
        self.client = TestClient(app)
        response = self.client.post(
            f"{ACCOUNT}/sign-in", json={"email": email_address, "password": password}
        )
        assert response.status_code == 200, response.text
        self.sign_in_response = response

    def csrf(self) -> dict[str, str]:
        token = self.client.cookies.get(settings.account_csrf_cookie_name)
        return {settings.account_csrf_header_name: token}

    def get(self, path: str):
        return self.client.get(f"{ACCOUNT}{path}")

    def post(self, path: str, body=None, *, csrf: bool = True):
        return self.client.post(f"{ACCOUNT}{path}", json=body, headers=self.csrf() if csrf else {})


def _sign_in(email_address: str, password: str):
    return TestClient(app).post(
        f"{ACCOUNT}/sign-in", json={"email": email_address, "password": password}
    )


def _activate(account_client, account_users, captured_mail, address: str = APPLICANT) -> str:
    reference = pending_identity(account_client, captured_mail, address)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    fingerprint = acknowledged_preview(api, reference, "create_new")
    assert approve_create(api, reference, fingerprint).status_code == 200
    account_client.cookies.clear()
    return reference


def _identity(db, address: str = APPLICANT) -> CustomerIdentity:
    see_committed_changes(db)
    return db.query(CustomerIdentity).filter_by(email_normalized=address).one()


def _audits(db, action: str) -> list[AuditEvent]:
    see_committed_changes(db)
    return db.query(AuditEvent).filter_by(action=action).order_by(AuditEvent.id).all()


def _messages(mail, template_key: str, to: str | None = None) -> list[dict]:
    return [
        m
        for m in mail.messages
        if m["template_key"] == template_key and (to is None or m["to_email"].lower() == to)
    ]


def _link_token(message: dict) -> str:
    return message["body"].split("token=")[1].split()[0]


def _change(account: Account, **overrides):
    body = {
        "current_password": ACCOUNT_PASSWORD,
        "new_password": NEW_PASSWORD,
        "new_password_confirmation": NEW_PASSWORD,
    }
    body.update(overrides)
    return account.post("/password/change", body)


def _live_sessions(db, identity_id: int) -> list[CustomerSession]:
    see_committed_changes(db)
    return (
        db.query(CustomerSession)
        .filter(CustomerSession.identity_id == identity_id, CustomerSession.revoked_at.is_(None))
        .all()
    )


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


# === 1. Customer password change ==================================================================


def test_password_change_revokes_other_sessions_rotates_this_one_and_notifies(active):
    db, mail = active["db"], active["mail"]
    other = Account()
    me = Account()
    old_cookie = me.client.cookies.get(settings.account_session_cookie_name)
    identity = _identity(db)
    assert len(_live_sessions(db, identity.id)) == 2
    mail.messages.clear()

    response = _change(me)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"message", "csrf_token"}
    assert NEW_PASSWORD not in json.dumps(body)

    # This browser carries on, on a new session; the other one and the old cookie are dead.
    assert me.get("/me").status_code == 200
    assert me.client.cookies.get(settings.account_session_cookie_name) != old_cookie
    assert other.get("/me").status_code == 401
    stale = TestClient(app)
    stale.cookies.set(settings.account_session_cookie_name, old_cookie)
    assert stale.get(f"{ACCOUNT}/me").status_code == 401
    live = _live_sessions(db, identity.id)
    assert len(live) == 1
    assert live[0].session_token_hash == hash_token(
        me.client.cookies.get(settings.account_session_cookie_name)
    )

    # New password signs in; the old one does not.
    assert _sign_in(APPLICANT, NEW_PASSWORD).status_code == 200
    assert _sign_in(APPLICANT, ACCOUNT_PASSWORD).status_code == 401

    # Notice, in the customer's language (the registration chose English), no password.
    notices = _messages(mail, email.TEMPLATE_PASSWORD_CHANGED_HERE, APPLICANT)
    assert len(notices) == 1
    assert notices[0]["language"] == "en"
    assert NEW_PASSWORD not in notices[0]["body"]

    rows = _audits(db, "customer_account.password_changed")
    assert len(rows) == 1
    detail = json.loads(rows[0].detail_json)
    assert detail["count"] == 1 and detail["identity_public_id"] == active["reference"]
    assert NEW_PASSWORD not in rows[0].detail_json and ACCOUNT_PASSWORD not in rows[0].detail_json
    assert rows[0].actor_label == f"customer_account:{active['reference']}"


def test_the_notice_is_vietnamese_for_a_vietnamese_customer(active):
    db, mail = active["db"], active["mail"]
    customer = db.query(Customer).filter_by(email_normalized=APPLICANT).one()
    customer.preferred_language = "vi"
    db.commit()
    mail.messages.clear()
    assert _change(Account()).status_code == 200
    notice = _messages(mail, email.TEMPLATE_PASSWORD_CHANGED_HERE, APPLICANT)[0]
    assert notice["language"] == "vi"
    assert "Mật khẩu" in notice["subject"]


def test_a_wrong_current_password_is_refused_audited_and_changes_nothing(active):
    db = active["db"]
    other = Account()
    me = Account()
    response = _change(me, current_password="NotTheRightOne!2026")
    assert response.status_code == 422, response.text
    assert response.json()["field"] == "current_password"
    assert other.get("/me").status_code == 200
    assert me.get("/me").status_code == 200
    assert _sign_in(APPLICANT, ACCOUNT_PASSWORD).status_code == 200
    rows = _audits(db, "customer_account.password_change_refused")
    assert [json.loads(r.detail_json)["reason_code"] for r in rows] == ["bad_current_password"]


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"new_password": "short!1", "new_password_confirmation": "short!1"}, "password"),
        (
            {
                "new_password": " LeadingSpace!2026",
                "new_password_confirmation": " LeadingSpace!2026",
            },
            "password",
        ),
        ({"new_password": "password1234", "new_password_confirmation": "password1234"}, "password"),
        ({"new_password_confirmation": "SomethingElse!2026"}, "password_confirmation"),
        ({"new_password_confirmation": None}, "password_confirmation"),
        (
            {"new_password": ACCOUNT_PASSWORD, "new_password_confirmation": ACCOUNT_PASSWORD},
            "password",
        ),
    ],
)
def test_the_new_password_follows_the_account_policy(active, overrides, field):
    response = _change(Account(), **overrides)
    assert response.status_code == 422, response.text
    assert response.json()["field"] == field
    assert _sign_in(APPLICANT, ACCOUNT_PASSWORD).status_code == 200


def test_password_change_needs_a_session_and_the_csrf_header(active):
    me = Account()
    assert me.post("/password/change", {}, csrf=False).status_code == 403
    assert TestClient(app).post(f"{ACCOUNT}/password/change", json={}).status_code == 401


def test_password_change_is_rate_limited_per_account(active):
    me = Account()
    for _ in range(5):
        assert _change(me, current_password="Wrong!Password2026").status_code == 422
    limited = _change(me)
    assert limited.status_code == 429
    assert limited.headers.get("Retry-After")


def test_a_password_change_kills_outstanding_reset_links(active):
    db, mail = active["db"], active["mail"]
    assert (
        TestClient(app).post(f"{ACCOUNT}/password/forgot", json={"email": APPLICANT}).status_code
        == 200
    )
    reset = _link_token(_messages(mail, email.TEMPLATE_PASSWORD_RESET, APPLICANT)[-1])
    assert _change(Account()).status_code == 200
    redeemed = TestClient(app).post(
        f"{ACCOUNT}/password/reset",
        json={
            "token": reset,
            "password": "Another!Password2028",
            "password_confirmation": "Another!Password2028",
        },
    )
    assert redeemed.status_code == 422
    assert _sign_in(APPLICANT, NEW_PASSWORD).status_code == 200
    see_committed_changes(db)


def test_a_pending_approval_account_may_change_its_password(
    account_client, account_db, captured_mail
):
    pending_identity(account_client, captured_mail, "cho@demo.example.com")
    me = Account("cho@demo.example.com")
    assert _change(me).status_code == 200
    assert _sign_in("cho@demo.example.com", NEW_PASSWORD).status_code == 200


# === 2. Staff password change =====================================================================


class StaffSession:
    def __init__(self, email_address: str, password: str = TEST_PASSWORD) -> None:
        self.client = TestClient(app)
        response = self.client.post(
            "/api/v1/auth/login", json={"email": email_address, "password": password}
        )
        assert response.status_code == 200, response.text
        self.headers = {settings.csrf_header_name: response.json()["csrf_token"]}

    def change(self, **overrides):
        body = {
            "current_password": TEST_PASSWORD,
            "new_password": "StaffNewPassword!2027",
            "new_password_confirmation": "StaffNewPassword!2027",
        }
        body.update(overrides)
        return self.client.post("/api/v1/auth/password/change", json=body, headers=self.headers)


def test_staff_password_change_keeps_this_session_and_ends_the_others(client, db, users):
    user = users[Role.OPERATIONS]
    user.must_change_password = True
    db.commit()
    other = StaffSession(user.email)
    me = StaffSession(user.email)
    response = me.change()
    assert response.status_code == 200, response.text
    assert "StaffNewPassword" not in response.text
    assert me.client.get("/api/v1/auth/me").status_code == 200
    assert other.client.get("/api/v1/auth/me").status_code == 401
    see_committed_changes(db)
    assert db.get(User, user.id).must_change_password is False
    live = (
        db.query(UserSession)
        .filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .count()
    )
    assert live == 1
    assert (
        TestClient(app)
        .post("/api/v1/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
        .status_code
        == 401
    )
    StaffSession(user.email, "StaffNewPassword!2027")
    rows = _audits(db, "auth.password_change")
    assert len(rows) == 1 and rows[0].actor_user_id == user.id
    assert json.loads(rows[0].detail_json) == {"sessions_revoked": 1}
    assert "StaffNewPassword" not in (rows[0].detail_json + rows[0].summary)


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"current_password": "Wrong!Password2026"}, "current_password"),
        ({"new_password": "short", "new_password_confirmation": "short"}, "password"),
        ({"new_password_confirmation": "Different!2027xx"}, "new_password_confirmation"),
        ({"new_password": TEST_PASSWORD, "new_password_confirmation": TEST_PASSWORD}, "password"),
    ],
)
def test_staff_password_change_refusals(client, db, users, overrides, field):
    me = StaffSession(users[Role.ADMIN].email)
    response = me.change(**overrides)
    assert response.status_code == 422, response.text
    assert response.json()["field"] == field
    StaffSession(users[Role.ADMIN].email)  # the old password still works


def test_staff_password_change_is_rate_limited_and_needs_csrf(client, db, users):
    me = StaffSession(users[Role.MARKETING].email)
    no_csrf = me.client.post("/api/v1/auth/password/change", json={})
    assert no_csrf.status_code == 403
    for _ in range(5):
        assert me.change(current_password="Wrong!Password2026").status_code == 422
    assert me.change().status_code == 429
    refused = _audits(db, "auth.password_change_refused")
    assert len(refused) == 5


# === 3. Email change ==============================================================================
#
# RC-UAT-25 item 2 (Ben, 2026-10-25): the customer can no longer change the sign-in email; an
# Admin does it on the staff account screen. The tests below that exercised the customer's
# own change were superseded and rewritten to the new rule; each is registered in
# docs/customer_account/SUPERSEDED_ASSERTIONS.md (AS-44 to AS-55). The Admin path is covered in
# full by tests/test_rc25_email_admin_only.py.

WITHDRAWN = (
    "Your sign-in email can only be changed by Solaris Express. Contact us and we will "
    "change it for you."
)


def legacy_link(db, identity: CustomerIdentity, address: str) -> str:
    """A change request and its link as RC-UAT-21 wrote them, before the customer path was
    withdrawn: the only way such a link can exist now. Returns the link's token."""
    from app.services import customer_identity_service

    issued = customer_identity_service.issue_token(
        db,
        identity,
        purpose=TokenPurpose.EMAIL_CHANGE,
        request_ip=None,
        invalidate_existing=False,
        issued_to_email_normalized=address,
    )
    db.add(
        CustomerEmailChangeRequest(
            identity_id=identity.id,
            token_id=issued.record.id,
            new_email_entered=address,
            new_email_normalized=address,
            status="pending",
            requested_at=utcnow(),
            expires_at=issued.record.expires_at,
        )
    )
    db.commit()
    return issued.plaintext


def _request(account: Account, new_email: str = NEW_ADDRESS, password: str = ACCOUNT_PASSWORD):
    return account.post("/email/change", {"current_password": password, "new_email": new_email})


def _confirm(token: str):
    return TestClient(app).post(f"{ACCOUNT}/email/change/confirm", json={"token": token})


def _admin_change(active, new_email: str = NEW_ADDRESS, **extra):
    admin = staff(active["client"], active["users"][Role.ADMIN].email)
    return admin.post(
        f"{REVIEW}/identities/{active['reference']}/sign-in-email",
        json={"new_email": new_email, "reason_code": "customer_request", **extra},
    )


def test_the_customer_cannot_ask_to_change_the_sign_in_email(active):
    """Superseded: see SUPERSEDED_ASSERTIONS.md AS-44 (was: a confirmed change switches the
    address and tells the old one)."""
    db, mail = active["db"], active["mail"]
    me = Account()
    mail.messages.clear()
    response = _request(me, "Hanh.Moi@Demo.Example.com")
    assert response.status_code == 403, response.text
    assert response.json()["message"] == WITHDRAWN
    assert mail.messages == []
    assert me.get("/security").json() == {
        "email": APPLICANT,
        "pending_email_change": None,
        "min_password_length": settings.account_min_password_length,
        "message": None,
    }
    assert _sign_in(NEW_ADDRESS, ACCOUNT_PASSWORD).status_code == 401
    assert _sign_in(APPLICANT, ACCOUNT_PASSWORD).status_code == 200
    see_committed_changes(db)
    assert db.query(CustomerEmailChangeRequest).count() == 0
    assert _audits(db, "customer_account.email_change_requested") == []


def test_an_outstanding_link_no_longer_works(active):
    """Superseded: see SUPERSEDED_ASSERTIONS.md AS-45 (was: the link works once)."""
    db = active["db"]
    token = legacy_link(db, _identity(db), NEW_ADDRESS)
    first = _confirm(token)
    assert first.status_code == 422
    assert first.json()["message"] == "That link is no longer valid. Request a new one."
    assert _confirm(token).status_code == 422
    assert _identity(db).email_normalized == APPLICANT


def test_an_expired_link_is_refused_and_changes_nothing(active):
    db = active["db"]
    token = legacy_link(db, _identity(db), NEW_ADDRESS)
    stored = db.query(CustomerAuthToken).filter_by(purpose=TokenPurpose.EMAIL_CHANGE.value).one()
    stored.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert _confirm(token).status_code == 422
    assert _identity(db).email_normalized == APPLICANT


def test_a_pending_request_is_closed_and_cancel_still_answers(active):
    """Superseded: see SUPERSEDED_ASSERTIONS.md AS-46 (was: a new request supersedes the old
    link and cancel kills it)."""
    db = active["db"]
    me = Account()
    token = legacy_link(db, _identity(db), "first@demo.example.com")
    cancelled = me.post("/email/change/cancel", {})
    assert cancelled.status_code == 200 and cancelled.json()["pending_email_change"] is None
    assert _confirm(token).status_code == 422
    assert _identity(db).email_normalized == APPLICANT
    see_committed_changes(db)
    assert [r.status for r in db.query(CustomerEmailChangeRequest)] == ["cancelled"]


def test_every_customer_request_gets_the_same_refusal_and_no_message(active, account_client):
    """Superseded: see SUPERSEDED_ASSERTIONS.md AS-47 (was: an address in use gets the same
    answer as success). Still no enumeration: free, taken and known addresses are answered
    identically, and nothing is sent to any of them."""
    db, mail = active["db"], active["mail"]
    pending_identity(account_client, mail, "taken@demo.example.com")
    make_customer(db, email="record@demo.example.com")
    db.commit()
    me = Account()
    answers = {}
    for address in ("free@demo.example.com", "taken@demo.example.com", "record@demo.example.com"):
        mail.messages.clear()
        response = _request(me, address)
        assert response.status_code == 403, response.text
        answers[address] = (response.json(), dict(response.headers).get("content-type"))
        assert mail.messages == [], address
    assert len({json.dumps(a, sort_keys=True) for a in answers.values()}) == 1
    assert _audits(db, "customer_account.email_change_requested") == []


def test_the_admin_change_refuses_an_address_held_by_another_account(active, account_client):
    """Superseded: see SUPERSEDED_ASSERTIONS.md AS-48 (was: the single email rule is checked
    again when the link is used)."""
    db, mail = active["db"], active["mail"]
    pending_identity(account_client, mail, NEW_ADDRESS)
    refused = _admin_change(active)
    assert refused.status_code == 409
    assert refused.json()["message"] == (
        "That address is already the sign-in email of another Customer Account."
    )
    assert _identity(db).email_entered == APPLICANT


def test_the_admin_change_refuses_an_address_held_by_another_customer_record(active):
    """Superseded: see SUPERSEDED_ASSERTIONS.md AS-49 (was: a customer record taking the
    address meanwhile refuses the link)."""
    db = active["db"]
    make_customer(db, email=NEW_ADDRESS)
    db.commit()
    assert _admin_change(active).status_code == 409
    assert _identity(db).email_normalized == APPLICANT


def test_the_unique_index_decides_a_true_race_on_an_admin_change(active, monkeypatch):
    """Superseded: see SUPERSEDED_ASSERTIONS.md AS-50 (was: the unique index decides a race
    on the customer's confirmation)."""
    from app.services import customer_account_security_service as security

    db = active["db"]
    clash = CustomerIdentity(
        public_id="CA-999999",
        email_entered=NEW_ADDRESS,
        email_normalized=NEW_ADDRESS,
        password_hash="x",
        status=IdentityStatus.PENDING_VERIFICATION.value,
    )
    db.add(clash)
    db.commit()
    monkeypatch.setattr(security, "address_refusal", lambda *_args: None)
    assert _admin_change(active).status_code == 409
    assert _identity(db).email_normalized == APPLICANT


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"reason_code": "because"}, "reason_code"),
        ({"new_email": "not-an-address"}, "new_email"),
        ({"new_email": APPLICANT.upper()}, "new_email"),
    ],
)
def test_admin_change_refusals_about_the_input(active, body, field):
    """Superseded: see SUPERSEDED_ASSERTIONS.md AS-51 (was: the customer's own refusals --
    wrong password, malformed address, own address)."""
    payload = {"new_email": NEW_ADDRESS, **body}
    response = _admin_change(active, **payload)
    assert response.status_code == 422, response.text
    assert response.json()["field"] == field


def test_the_customer_route_refuses_every_time_and_sends_nothing(active):
    """Superseded: see SUPERSEDED_ASSERTIONS.md AS-52 (was: three requests an hour, then 429).
    Nothing is sent any more, so there is nothing to rate-limit: every call is the refusal."""
    mail = active["mail"]
    me = Account()
    mail.messages.clear()
    for index in range(5):
        assert _request(me, f"n{index}@demo.example.com").status_code == 403
    assert mail.messages == []


def test_a_suspended_account_cannot_complete_an_email_change(active):
    db = active["db"]
    token = legacy_link(db, _identity(db), NEW_ADDRESS)
    identity = _identity(db)
    identity.status = IdentityStatus.SUSPENDED.value
    db.commit()
    assert _confirm(token).status_code == 422
    assert _identity(db).email_normalized == APPLICANT


# === 4. Reinstating a deactivated account =========================================================


def _deactivate(account_client, users, reference: str, reason: str = "customer_request"):
    admin = staff(account_client, users[Role.ADMIN].email)
    response = admin.post(
        f"{REVIEW}/identities/{reference}/deactivate", json={"reason_code": reason}
    )
    assert response.status_code == 200, response.text
    return admin


def test_admin_reinstates_a_deactivated_account_to_active(active, account_client):
    db, mail, users, reference = active["db"], active["mail"], active["users"], active["reference"]
    before = Account()
    admin = _deactivate(account_client, users, reference)
    assert before.get("/me").status_code == 401
    assert admin.get(f"{REVIEW}/identities/{reference}").json()["can_reactivate"] is True
    mail.messages.clear()

    response = admin.post(
        f"{REVIEW}/identities/{reference}/reactivate",
        json={
            "reason_code": "deactivated_in_error",
            "note": "Deactivated by mistake on the phone.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "active" and body["deactivated_at"] is None
    assert body["can_reactivate"] is False and body["can_deactivate"] is True

    # Old sessions stay revoked: the customer signs in again.
    assert before.get("/me").status_code == 401
    assert Account().get("/shipments").status_code == 200
    notice = _messages(mail, email.TEMPLATE_ACCOUNT_REINSTATED, APPLICANT)
    assert len(notice) == 1 and "/sign-in" in notice[0]["body"]

    see_committed_changes(db)
    row = db.query(CustomerAccountReinstatement).one()
    assert row.restored_status == "active" and row.deactivation_reason_code == "customer_request"
    assert row.reinstated_by_user_id == users[Role.ADMIN].id and row.deactivated_at is not None
    events = _audits(db, "customer_account.reactivate")
    assert len(events) == 1 and events[0].actor_user_id == users[Role.ADMIN].id
    detail = json.loads(events[0].detail_json)
    assert detail["reason_code"] == "deactivated_in_error"
    assert "mistake" not in events[0].detail_json


def test_reinstatement_is_admin_only_and_needs_a_listed_reason(active, account_client):
    users, reference = active["users"], active["reference"]
    admin = _deactivate(account_client, users, reference)
    for role in (Role.OPERATIONS, Role.MARKETING, Role.READ_ONLY_MANAGER):
        caller = staff(account_client, users[role].email)
        refused = caller.post(
            f"{REVIEW}/identities/{reference}/reactivate", json={"reason_code": "customer_request"}
        )
        assert refused.status_code == 403, role
    admin = staff(account_client, users[Role.ADMIN].email)
    for payload in ({}, {"reason_code": "because"}, {"reason_code": ""}):
        assert (
            admin.post(f"{REVIEW}/identities/{reference}/reactivate", json=payload).status_code
            == 422
        )
    assert admin.get(f"{REVIEW}/identities/{reference}").json()["status"] == "deactivated"


def test_a_privacy_request_deactivation_is_not_reversed(active, account_client):
    users, reference = active["users"], active["reference"]
    admin = _deactivate(account_client, users, reference, "privacy_request")
    assert admin.get(f"{REVIEW}/identities/{reference}").json()["can_reactivate"] is False
    refused = admin.post(
        f"{REVIEW}/identities/{reference}/reactivate", json={"reason_code": "customer_request"}
    )
    assert refused.status_code == 409


def test_only_a_deactivated_account_is_reinstated(active, account_client):
    users, reference = active["users"], active["reference"]
    admin = staff(account_client, users[Role.ADMIN].email)
    refused = admin.post(
        f"{REVIEW}/identities/{reference}/reactivate", json={"reason_code": "customer_request"}
    )
    assert refused.status_code == 409


def test_a_suspended_then_deactivated_account_returns_suspended(active, account_client):
    db, users, reference = active["db"], active["users"], active["reference"]
    ops = staff(account_client, users[Role.OPERATIONS].email)
    assert (
        ops.post(
            f"{REVIEW}/identities/{reference}/suspend", json={"reason_code": "staff_review"}
        ).status_code
        == 200
    )
    admin = _deactivate(account_client, users, reference)
    response = admin.post(
        f"{REVIEW}/identities/{reference}/reactivate", json={"reason_code": "review_complete"}
    )
    assert response.status_code == 200 and response.json()["status"] == "suspended"
    assert _sign_in(APPLICANT, ACCOUNT_PASSWORD).status_code == 401
    see_committed_changes(db)


def test_a_pending_account_returns_to_pending_approval(
    account_client, account_db, account_users, captured_mail
):
    reference = pending_identity(account_client, captured_mail, "cho@demo.example.com")
    admin = _deactivate(account_client, account_users, reference)
    response = admin.post(
        f"{REVIEW}/identities/{reference}/reactivate", json={"reason_code": "customer_request"}
    )
    assert response.status_code == 200 and response.json()["status"] == "pending_approval"


def test_the_deactivated_list_is_admin_only_and_audited(active, account_client):
    db, users, reference = active["db"], active["users"], active["reference"]
    admin = _deactivate(account_client, users, reference)
    listed = admin.get(f"{REVIEW}/identities-deactivated")
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert [i["account_reference"] for i in items] == [reference]
    assert items[0]["can_reactivate"] is True and items[0]["linked_customer_public_id"]
    ops = staff(account_client, users[Role.OPERATIONS].email)
    assert ops.get(f"{REVIEW}/identities-deactivated").status_code == 403
    assert len(_audits(db, "customer_account.deactivated_list_read")) == 1


# === 5. Review fixes (independent review, 2026-10-24) =============================================


def test_the_old_address_is_told_when_an_admin_changes_it(active):
    """Superseded: see SUPERSEDED_ASSERTIONS.md AS-53 (was: the current address is told when
    the customer asks for a change, HIGH 1). The old address is told after the Admin's change,
    in the customer's language, with no token and no new address."""
    db, mail = active["db"], active["mail"]
    customer = db.query(Customer).filter_by(email_normalized=APPLICANT).one()
    customer.preferred_language = "vi"
    db.commit()
    mail.messages.clear()
    assert _admin_change(active).status_code == 200
    notices = _messages(mail, email.TEMPLATE_EMAIL_CHANGED_NOTICE, APPLICANT)
    assert len(notices) == 1 and notices[0]["language"] == "vi"
    assert "token" not in notices[0]["body"] and NEW_ADDRESS not in notices[0]["body"]
    assert "http" not in notices[0]["body"]
    assert _messages(mail, email.TEMPLATE_EMAIL_CHANGE_REQUESTED) == []


def test_a_password_change_cancels_a_pending_email_change(active):
    """HIGH 1: a hijacker's pending change dies when the owner changes the password."""
    db = active["db"]
    token = legacy_link(db, _identity(db), "thief@demo.example.com")
    assert _change(Account()).status_code == 200
    assert _confirm(token).status_code == 422
    assert _identity(db).email_normalized == APPLICANT
    assert db.query(CustomerEmailChangeRequest).one().status == "cancelled"
    reasons = [
        json.loads(r.detail_json)["reason_code"]
        for r in _audits(db, "customer_account.email_change_cancelled")
    ]
    assert reasons == ["password_changed"]


def test_a_password_reset_cancels_a_pending_email_change(active):
    db, mail = active["db"], active["mail"]
    token = legacy_link(db, _identity(db), "thief@demo.example.com")
    assert (
        TestClient(app).post(f"{ACCOUNT}/password/forgot", json={"email": APPLICANT}).status_code
        == 200
    )
    reset = _link_token(_messages(mail, email.TEMPLATE_PASSWORD_RESET, APPLICANT)[-1])
    done = TestClient(app).post(
        f"{ACCOUNT}/password/reset",
        json={"token": reset, "password": NEW_PASSWORD, "password_confirmation": NEW_PASSWORD},
    )
    assert done.status_code == 200, done.text
    assert _confirm(token).status_code == 422
    assert _identity(db).email_normalized == APPLICANT
    reasons = [
        json.loads(r.detail_json)["reason_code"]
        for r in _audits(db, "customer_account.email_change_cancelled")
    ]
    assert reasons == ["password_reset"]


def test_an_admin_email_change_ends_every_session(active):
    """Superseded: see SUPERSEDED_ASSERTIONS.md AS-54 (was: confirming a change ends every
    other session, LOW 12). The Admin's change ends them all: no session is the one that
    asked."""
    other = Account()
    me = Account()
    assert _admin_change(active).status_code == 200
    assert me.get("/me").status_code == 401
    assert other.get("/me").status_code == 401
    assert _sign_in(NEW_ADDRESS, ACCOUNT_PASSWORD).status_code == 200


def test_a_withdrawn_link_ends_no_session(active):
    """Superseded: see SUPERSEDED_ASSERTIONS.md AS-55 (was: a link opened elsewhere ends every
    session). The link changes nothing now, so nothing is ended."""
    db = active["db"]
    me = Account()
    token = legacy_link(db, _identity(db), NEW_ADDRESS)
    assert _confirm(token).status_code == 422
    assert me.get("/me").status_code == 200


def test_staff_password_change_rotates_this_session(client, db, users):
    """LOW 12: the cookie held before the change no longer works; the browser carries on."""
    user = users[Role.OPERATIONS]
    me = StaffSession(user.email)
    old_cookie = me.client.cookies.get(settings.session_cookie_name)
    assert me.change().status_code == 200
    assert me.client.cookies.get(settings.session_cookie_name) != old_cookie
    assert me.client.get("/api/v1/auth/me").status_code == 200
    stale = TestClient(app)
    stale.cookies.set(settings.session_cookie_name, old_cookie)
    assert stale.get("/api/v1/auth/me").status_code == 401


def _sweep(db) -> None:
    """The activation invariant: active has exactly one live link; pending has none."""
    from app.models import CustomerIdentityLink

    see_committed_changes(db)
    for identity in db.query(CustomerIdentity).all():
        live = (
            db.query(CustomerIdentityLink)
            .filter_by(identity_id=identity.id, status="active")
            .count()
        )
        if identity.status == "active":
            assert live == 1, identity.public_id
        elif identity.status in {"pending_approval", "pending_verification", "rejected"}:
            assert live == 0, identity.public_id


def _owner(db) -> Customer:
    see_committed_changes(db)
    return db.query(Customer).filter_by(email_normalized=APPLICANT).one()


@pytest.mark.parametrize("direction", ["linked_merged_away", "other_merged_into_linked"])
def test_reinstatement_after_a_merge_returns_to_review_not_active(
    active, account_client, direction
):
    """HIGH 2, both directions: never back onto a merged history."""
    from app.models import CustomerIdentityLink
    from app.services import customer_service

    db, users, reference, mail = active["db"], active["users"], active["reference"], active["mail"]
    admin = _deactivate(account_client, users, reference)
    owner = _owner(db)
    other = make_customer(db, email="other.record@demo.example.com")
    db.commit()
    if direction == "linked_merged_away":
        customer_service.merge_customers(db, source=owner, target=other)
    else:
        customer_service.merge_customers(db, source=other, target=owner)
    db.commit()
    mail.messages.clear()

    response = admin.post(
        f"{REVIEW}/identities/{reference}/reactivate", json={"reason_code": "customer_request"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "pending_approval" and body["linked_customer_public_id"] is None
    see_committed_changes(db)
    link = db.query(CustomerIdentityLink).filter_by(customer_id=owner.id).one()
    assert (link.status, link.revoke_reason_code) == ("revoked", "merged_since_deactivation")
    unlink = _audits(db, "customer_account.unlink")
    assert json.loads(unlink[-1].detail_json)["reason_code"] == "merged_since_deactivation"
    row = db.query(CustomerAccountReinstatement).one()
    assert row.restored_status == "pending_approval"
    # The customer can sign in to a pending account, and reaches no shipment.
    me = Account()
    assert me.get("/shipments").status_code == 403
    _sweep(db)


def test_reinstatement_onto_an_archived_customer_returns_to_review(active, account_client):
    db, users, reference = active["db"], active["users"], active["reference"]
    admin = _deactivate(account_client, users, reference)
    owner = _owner(db)
    owner.is_archived = True
    db.commit()
    response = admin.post(
        f"{REVIEW}/identities/{reference}/reactivate", json={"reason_code": "customer_request"}
    )
    assert response.status_code == 200 and response.json()["status"] == "pending_approval"
    _sweep(db)


def test_an_unmerged_customer_still_returns_to_active(active, account_client):
    db, users, reference = active["db"], active["users"], active["reference"]
    admin = _deactivate(account_client, users, reference)
    response = admin.post(
        f"{REVIEW}/identities/{reference}/reactivate", json={"reason_code": "customer_request"}
    )
    assert response.status_code == 200 and response.json()["status"] == "active"
    _sweep(db)
