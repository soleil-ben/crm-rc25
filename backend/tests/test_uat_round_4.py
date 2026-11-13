"""UAT round 4 fix pack (RC-UAT-7 findings, 2026-10-15).

1. CA-APR-05: an Admin approval is marked as an Admin override in the audit row, and the
   audit screen's derived fields carry the marker (DEC-0129).
2. An import whose every held row was decided "skip" can be committed (DEC-0132).
3. A staff action suppresses a customer's address with an evidence reference and a reason,
   for Marketing and Admin, audited (DEC-0130).
4. Saving a shipment's internal notes writes its own audit row.
5. Admin-only deactivation (DEC-0126, DEC-0131), and the password-reset per-connection 429
   carries the ordinary recovery sentence.
"""

from __future__ import annotations

import json

from sqlalchemy import func, select

from app.core.config import settings
from app.core.enums import ConsentStatus, Role
from app.models import (
    AuditEvent,
    ConsentEvent,
    ContactSuppression,
    Customer,
    CustomerIdentity,
    ImportBatch,
)
from app.services import consent_service, customer_identity_service
from tests.account_fixtures import sign_in as customer_sign_in
from tests.approval_fixtures import (
    acknowledged_preview,
    approve_create,
    pending_identity,
    reject,
    staff,
)
from tests.conftest import booked_shipment, make_customer, see_committed_changes

APPLICANT = "hanh@demo.example.com"
IDENTITIES = "/api/v1/customer-account/identities"


def _approve_as(account_client, account_users, captured_mail, role):
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[role].email)
    fingerprint = acknowledged_preview(api, reference, "create_new")
    response = approve_create(api, reference, fingerprint)
    assert response.status_code == 200, response.text
    return reference, api


def _approval_row(db) -> AuditEvent:
    see_committed_changes(db)
    return db.query(AuditEvent).filter_by(action="customer_account.approve").one()


# --- 1. CA-APR-05: the Admin override is explicit ---------------------------------------


def test_an_admin_approval_is_recorded_as_an_admin_override(
    account_client, account_db, account_users, captured_mail
):
    _reference, api = _approve_as(account_client, account_users, captured_mail, Role.ADMIN)

    row = _approval_row(account_db)
    detail = json.loads(row.detail_json)
    assert row.actor_user_id == account_users[Role.ADMIN].id
    assert detail["admin_override"] is True
    assert detail["reason_code"]
    assert "(Admin override)" in row.summary

    # The audit screen reads the marker from the API, not from the raw detail.
    page = api.get("/api/v1/audit", params={"action": "customer_account.approve"}).json()
    assert page["items"][0]["admin_override"] is True


def test_an_operations_approval_is_not_an_override(
    account_client, account_db, account_users, captured_mail
):
    _approve_as(account_client, account_users, captured_mail, Role.OPERATIONS)

    row = _approval_row(account_db)
    assert json.loads(row.detail_json)["admin_override"] is False
    assert "override" not in row.summary.lower()


def test_an_admin_rejection_is_marked_too(account_client, account_db, account_users, captured_mail):
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.ADMIN].email)
    response = reject(api, reference, key="reject-admin-override-key")
    assert response.status_code == 200, response.text

    see_committed_changes(account_db)
    row = account_db.query(AuditEvent).filter_by(action="customer_account.reject").one()
    assert json.loads(row.detail_json)["admin_override"] is True


def test_the_marker_only_counts_a_literal_true():
    from app.services.audit_service import audit_display_fields

    assert audit_display_fields('{"admin_override": true}')["admin_override"] is True
    for value in ('"true"', "1", '"yes"', "null"):
        assert audit_display_fields(f'{{"admin_override": {value}}}')["admin_override"] is False


# --- 2. An all-skip import can be finished ----------------------------------------------

IMPORT_HEADER = "full_name,email,phone,country_code,city,preferred_language\r\n"


def test_an_import_whose_every_held_row_is_skipped_commits_and_creates_nobody(as_admin, db):
    make_customer(db, full_name="Nguyễn Thị Bích Hạnh", email="hanh@example.com", country_code="CA")
    content = (IMPORT_HEADER + "Nguyễn Thị Bích Hạnh,hanh@example.com,,CA,Toronto,vi\r\n").encode()
    before = db.scalar(select(func.count(Customer.id)))

    previewed = as_admin.post(
        "/api/v1/imports/customers/preview",
        files={"file": ("customers.csv", content, "text/csv")},
    ).json()
    assert previewed["counts"]["new"] == 0
    held = [row for row in previewed["rows"] if row["classification"] == "duplicate_review"]
    assert len(held) == 1

    response = as_admin.post(
        "/api/v1/imports/customers/commit",
        files={"file": ("customers.csv", content, "text/csv")},
        data={
            "content_sha256": previewed["content_sha256"],
            "confirm": "true",
            "decisions_json": json.dumps({str(held[0]["row_number"]): "skip"}),
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["created"] == 0
    assert result["skipped"] == 1

    see_committed_changes(db)
    assert db.scalar(select(func.count(Customer.id))) == before
    assert db.scalar(select(func.count(ImportBatch.id))) == 1


# --- 3. Staff suppression ---------------------------------------------------------------

SUPPRESS = "/api/v1/customers/{id}/consent/suppressions"
EVIDENCE = "TICKET-4417"
REASON = "Customer asked by phone to stop all marketing email"


def _suppress(api, customer_id, **overrides):
    body = {"channel": "email", "evidence_reference": EVIDENCE, "reason": REASON, **overrides}
    return api.post(SUPPRESS.format(id=customer_id), json=body)


def test_marketing_suppresses_an_address_with_evidence_and_a_reason(api_for, db, users):
    customer = make_customer(db, email="lan@example.com")
    api = api_for(Role.MARKETING)

    response = _suppress(api, customer.id)

    assert response.status_code == 201, response.text
    email_state = next(s for s in response.json()["states"] if s["channel"] == "email")
    assert email_state["is_suppressed"] is True
    assert email_state["is_marketing_eligible"] is False

    see_committed_changes(db)
    suppression = db.query(ContactSuppression).one()
    assert suppression.address_value == "lan@example.com"
    assert suppression.reason == REASON
    assert suppression.created_by_user_id == users[Role.MARKETING].id

    event = db.query(ConsentEvent).one()
    assert event.status == ConsentStatus.SUPPRESSED
    assert event.evidence_reference == EVIDENCE
    assert event.note == REASON

    row = db.query(AuditEvent).filter_by(action="suppression.add").one()
    assert row.actor_user_id == users[Role.MARKETING].id
    assert row.entity_id == customer.public_id
    # The audit detail names the channel, the customer and (since UAT round 5) the evidence
    # reference, never the address or the reason prose.
    assert "lan@example.com" not in (row.detail_json or "")
    assert REASON not in (row.detail_json or "")
    assert json.loads(row.detail_json)["evidence_reference"] == EVIDENCE


def test_admin_may_suppress_and_operations_and_the_manager_may_not(api_for, db):
    customer = make_customer(db, email="minh@example.com")
    assert _suppress(api_for(Role.OPERATIONS), customer.id).status_code == 403
    assert _suppress(api_for(Role.READ_ONLY_MANAGER), customer.id).status_code == 403
    assert _suppress(api_for(Role.ADMIN), customer.id).status_code == 201


def test_evidence_and_reason_are_required(api_for, db):
    customer = make_customer(db, email="tuan@example.com")
    api = api_for(Role.MARKETING)
    assert _suppress(api, customer.id, evidence_reference="").status_code == 422
    assert _suppress(api, customer.id, reason="").status_code == 422
    see_committed_changes(db)
    assert db.query(ContactSuppression).count() == 0


def test_a_second_suppression_is_refused_and_writes_nothing(api_for, db):
    customer = make_customer(db, email="thu@example.com")
    api = api_for(Role.MARKETING)
    assert _suppress(api, customer.id).status_code == 201
    assert _suppress(api, customer.id).status_code == 409
    see_committed_changes(db)
    assert db.query(ConsentEvent).count() == 1
    assert db.query(AuditEvent).filter_by(action="suppression.add").count() == 1


def test_a_customer_without_the_channel_has_nothing_to_suppress(api_for, db):
    customer = make_customer(db, email="only-email@example.com", phone=None)
    assert _suppress(api_for(Role.MARKETING), customer.id, channel="sms").status_code == 422


def test_a_staff_suppression_makes_an_opted_in_address_ineligible(api_for, db, users):
    """The DEC-0127 note depends on this: a grant does not survive the suppression."""
    customer = make_customer(db, email="hoa@example.com")
    consent_service.record_consent_event(
        db,
        customer,
        channel="email",
        status=ConsentStatus.CONSENTED,
        basis="express",
        evidence_reference="FORM-1",
        actor=users[Role.ADMIN],
    )
    db.commit()
    assert consent_service.marketing_eligible(db, customer, "email") is True

    assert _suppress(api_for(Role.MARKETING), customer.id).status_code == 201
    see_committed_changes(db)
    assert consent_service.marketing_eligible(db, customer, "email") is False


# --- 4. Internal notes are audited ------------------------------------------------------


def test_saving_internal_notes_writes_a_named_audit_row(as_admin, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    note = "Gate code 4417, leave with the neighbour"

    response = as_admin.patch(f"/api/v1/shipments/{shipment.id}", json={"internal_notes": note})

    assert response.status_code == 200, response.text
    assert response.json()["internal_notes"] == note
    see_committed_changes(db)
    row = db.query(AuditEvent).filter_by(action="shipment.internal_notes_update").one()
    assert row.entity_id == str(shipment.id)
    assert row.summary.startswith("Internal notes updated on ")
    assert note not in (row.detail_json or "")
    assert json.loads(row.detail_json)["fields"] == ["internal_notes"]


def test_any_other_edit_keeps_the_generic_action(as_admin, db):
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    response = as_admin.patch(
        f"/api/v1/shipments/{shipment.id}",
        json={"internal_notes": "x", "booking_reference": "REF-1"},
    )
    assert response.status_code == 200, response.text
    see_committed_changes(db)
    assert db.query(AuditEvent).filter_by(action="shipment.update").count() >= 1
    assert db.query(AuditEvent).filter_by(action="shipment.internal_notes_update").count() == 0


# --- 5a. Admin-only deactivation --------------------------------------------------------


def _identity(db) -> CustomerIdentity:
    see_committed_changes(db)
    return db.query(CustomerIdentity).filter_by(email_normalized=APPLICANT).one()


def test_admin_deactivates_an_account_and_it_can_no_longer_sign_in(
    account_client, account_db, account_users, captured_mail
):
    reference, _ = _approve_as(account_client, account_users, captured_mail, Role.OPERATIONS)
    account_client.cookies.clear()
    assert customer_sign_in(account_client, APPLICANT).status_code == 200
    customer_cookie = account_client.cookies[settings.account_session_cookie_name]
    account_client.cookies.clear()

    api = staff(account_client, account_users[Role.ADMIN].email)
    before = api.get(f"{IDENTITIES}/{reference}").json()
    assert before["can_deactivate"] is True

    response = api.post(
        f"{IDENTITIES}/{reference}/deactivate", json={"reason_code": "customer_request"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "deactivated"
    assert body["deactivated_at"] is not None
    assert body["can_deactivate"] is False
    assert body["can_suspend"] is False
    identity = _identity(account_db)
    assert identity.deactivated_by_user_id == account_users[Role.ADMIN].id
    assert identity.status_reason_code == "customer_request"

    # The live session is dead and sign-in is refused like a wrong password.
    account_client.cookies.clear()
    account_client.cookies.set(settings.account_session_cookie_name, customer_cookie)
    assert account_client.get("/api/v1/account/me").status_code == 401
    account_client.cookies.clear()
    refused = customer_sign_in(account_client, APPLICANT)
    wrong = customer_sign_in(account_client, APPLICANT, password="not-the-password-2026")
    assert refused.status_code == wrong.status_code == 401
    assert refused.json() == wrong.json()

    see_committed_changes(account_db)
    row = account_db.query(AuditEvent).filter_by(action="customer_account.deactivate").one()
    assert row.actor_user_id == account_users[Role.ADMIN].id
    assert json.loads(row.detail_json)["reason_code"] == "customer_request"


def test_operations_cannot_deactivate(account_client, account_db, account_users, captured_mail):
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    response = api.post(
        f"{IDENTITIES}/{reference}/deactivate", json={"reason_code": "customer_request"}
    )
    assert response.status_code == 403
    assert _identity(account_db).status == "pending_approval"


def test_deactivation_needs_a_listed_reason_and_happens_once(
    account_client, account_db, account_users, captured_mail
):
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.ADMIN].email)

    assert (
        api.post(
            f"{IDENTITIES}/{reference}/deactivate", json={"reason_code": "because"}
        ).status_code
        == 422
    )
    assert _identity(account_db).status == "pending_approval"

    first = api.post(f"{IDENTITIES}/{reference}/deactivate", json={"reason_code": "abuse_or_test"})
    assert first.status_code == 200, first.text
    second = api.post(f"{IDENTITIES}/{reference}/deactivate", json={"reason_code": "abuse_or_test"})
    assert second.status_code == 409
    see_committed_changes(account_db)
    assert account_db.query(AuditEvent).filter_by(action="customer_account.deactivate").count() == 1


# --- 5b. The reset limit does not say "too many" ----------------------------------------


def test_the_reset_per_connection_429_carries_the_recovery_sentence(account_client, captured_mail):
    limit = settings.account_reset_ip_attempts
    for index in range(limit):
        response = account_client.post(
            "/api/v1/account/password/forgot", json={"email": f"p{index}@demo.example.com"}
        )
        assert response.status_code == 200, index

    refused = account_client.post(
        "/api/v1/account/password/forgot", json={"email": "one-more@demo.example.com"}
    )

    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) > 0
    assert set(refused.json()) == {"code", "message", "field"}
    assert refused.json()["message"] == customer_identity_service.GENERIC_RECOVERY_MESSAGE
    assert "too many" not in refused.text.lower()
