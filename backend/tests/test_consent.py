"""AC-15 (consent half): consent history, suppression, and marketing eligibility."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.core.enums import ConsentBasis, ConsentChannel, ConsentStatus, Role
from app.core.time_utils import utcnow
from app.models import ConsentEvent, ContactSuppression
from app.services import consent_service
from tests.conftest import make_customer


def test_consent_defaults_to_unknown_and_not_eligible(db):
    customer = make_customer(db)
    state = consent_service.current_state(db, customer, ConsentChannel.EMAIL)
    assert state.status == ConsentStatus.UNKNOWN
    assert state.is_marketing_eligible is False


def test_recording_consent_requires_a_basis(as_admin, db):
    customer = make_customer(db)
    response = as_admin.post(
        f"/api/v1/customers/{customer.id}/consent",
        json={"channel": "email", "status": "consented", "basis": "not_recorded"},
    )
    assert response.status_code == 422


def test_consent_history_is_append_only(as_admin, db):
    customer = make_customer(db)
    for status, basis in (
        ("consented", "express"),
        ("withdrawn", "not_recorded"),
        ("consented", "express"),
    ):
        response = as_admin.post(
            f"/api/v1/customers/{customer.id}/consent",
            json={
                "channel": "email",
                "status": status,
                "basis": basis,
                "evidence_reference": "FORM-9",
            },
        )
        assert response.status_code == 201, response.text

    events = db.scalars(select(ConsentEvent).where(ConsentEvent.customer_id == customer.id)).all()
    assert len(events) == 3
    body = response.json()
    email_state = next(state for state in body["states"] if state["channel"] == "email")
    assert email_state["status"] == "consented"
    assert email_state["is_marketing_eligible"] is True
    assert len(body["history"]) == 3


def test_withdrawn_consent_is_not_marketing_eligible(as_admin, db):
    customer = make_customer(db)
    as_admin.post(
        f"/api/v1/customers/{customer.id}/consent",
        json={
            "channel": "email",
            "status": "consented",
            "basis": "express",
            "evidence_reference": "F1",
        },
    )
    body = as_admin.post(
        f"/api/v1/customers/{customer.id}/consent",
        json={"channel": "email", "status": "withdrawn", "basis": "not_recorded"},
    ).json()
    email_state = next(state for state in body["states"] if state["channel"] == "email")
    assert email_state["is_marketing_eligible"] is False


def test_expired_consent_is_not_eligible(db):
    customer = make_customer(db)
    consent_service.record_consent_event(
        db,
        customer,
        channel=ConsentChannel.EMAIL,
        status=ConsentStatus.CONSENTED,
        basis=ConsentBasis.IMPLIED_BUSINESS_RELATIONSHIP,
        expires_at=utcnow() - timedelta(days=1),
        evidence_reference="OLD",
    )
    db.commit()
    assert consent_service.marketing_eligible(db, customer, ConsentChannel.EMAIL) is False


def test_suppression_blocks_a_new_consent_event(as_admin, db):
    customer = make_customer(db)
    response = as_admin.post(
        f"/api/v1/customers/{customer.id}/consent",
        json={
            "channel": "email",
            "status": "suppressed",
            "basis": "not_recorded",
            "note": "Complaint",
        },
    )
    assert response.status_code == 201

    blocked = as_admin.post(
        f"/api/v1/customers/{customer.id}/consent",
        json={
            "channel": "email",
            "status": "consented",
            "basis": "express",
            "evidence_reference": "F2",
        },
    )
    assert blocked.status_code == 409
    assert "suppressed" in blocked.json()["message"].lower()


def test_suppression_survives_a_merge(db, as_admin):
    """Suppression is keyed on channel + address, not on the customer row (AC-15)."""
    source = make_customer(db, full_name="Suppressed", email="stop@demo.example.com")
    target = make_customer(db, full_name="Target", email="target@demo.example.com")
    as_admin.post(
        f"/api/v1/customers/{source.id}/consent",
        json={
            "channel": "email",
            "status": "suppressed",
            "basis": "not_recorded",
            "note": "Complaint",
        },
    )
    as_admin.post(
        "/api/v1/customers/merge",
        json={
            "source_customer_id": source.id,
            "target_customer_id": target.id,
            "confirmation": source.public_id,
        },
    )
    db.expire_all()
    suppression = db.scalar(
        select(ContactSuppression).where(
            ContactSuppression.address_value == "stop@demo.example.com"
        )
    )
    assert suppression is not None
    assert suppression.released_at is None


def test_only_admin_can_release_a_suppression(api_for, as_admin, db):
    customer = make_customer(db, email="release@demo.example.com")
    as_admin.post(
        f"/api/v1/customers/{customer.id}/consent",
        json={
            "channel": "email",
            "status": "suppressed",
            "basis": "not_recorded",
            "note": "Complaint",
        },
    )

    ops_api = api_for(Role.OPERATIONS.value)
    denied = ops_api.post(
        "/api/v1/consent/suppressions/release",
        json={
            "channel": "email",
            "address_value": "release@demo.example.com",
            "reason": "Customer asked",
        },
    )
    assert denied.status_code == 403


def test_admin_release_is_audited(as_admin, db):
    customer = make_customer(db, email="release2@demo.example.com")
    as_admin.post(
        f"/api/v1/customers/{customer.id}/consent",
        json={
            "channel": "email",
            "status": "suppressed",
            "basis": "not_recorded",
            "note": "Complaint",
        },
    )
    released = as_admin.post(
        "/api/v1/consent/suppressions/release",
        json={
            "channel": "email",
            "address_value": "release2@demo.example.com",
            "reason": "Customer re-subscribed at the counter",
        },
    )
    assert released.status_code == 200

    audit = as_admin.get("/api/v1/audit?action=suppression.release").json()
    assert audit["total"] == 1


def test_do_not_contact_blocks_marketing_eligibility(db):
    customer = make_customer(db, do_not_contact=True)
    consent_service.record_consent_event(
        db,
        customer,
        channel=ConsentChannel.EMAIL,
        status=ConsentStatus.CONSENTED,
        basis=ConsentBasis.EXPRESS,
        evidence_reference="F3",
    )
    db.commit()
    assert consent_service.marketing_eligible(db, customer, ConsentChannel.EMAIL) is False


def test_consent_response_states_the_operational_separation(as_admin, db):
    customer = make_customer(db)
    body = as_admin.get(f"/api/v1/customers/{customer.id}/consent").json()
    assert "operational" in body["note"].lower()
