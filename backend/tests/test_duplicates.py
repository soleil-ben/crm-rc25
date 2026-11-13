"""AC-16: duplicates are reviewed, never blindly merged; merges preserve everything."""

from __future__ import annotations

from sqlalchemy import select

from app.core.enums import ConsentBasis, ConsentChannel, ConsentStatus
from app.models import ConsentEvent, Customer, CustomerIdAlias, FollowUpTask, Referral, Shipment
from app.services import consent_service, customer_service
from tests.conftest import add_shipment, make_customer


def test_shared_phone_creates_a_candidate_not_a_merge(as_admin, db):
    first = as_admin.post(
        "/api/v1/customers",
        json={"full_name": "Nguyễn Văn A", "phone": "+1 416 555 0142", "country_code": "CA"},
    ).json()
    check = as_admin.post(
        "/api/v1/customers/duplicate-check",
        json={"full_name": "Nguyễn Văn B", "phone": "+1 416 555 0142", "country_code": "CA"},
    )
    assert check.status_code == 200
    body = check.json()
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["customer"]["public_id"] == first["public_id"]
    assert body["candidates"][0]["matched_on"] == ["phone"]
    assert body["candidates"][0]["requires_review"] is True

    # Creating the second record anyway is allowed: families share phone numbers.
    second = as_admin.post(
        "/api/v1/customers",
        json={"full_name": "Nguyễn Văn B", "phone": "+1 416 555 0142", "country_code": "CA"},
    )
    assert second.status_code == 201
    assert second.json()["public_id"] != first["public_id"]
    assert (
        db.scalar(select(Customer).where(Customer.public_id == second.json()["public_id"]))
        is not None
    )


def test_email_and_name_match_scores_higher(as_admin):
    as_admin.post(
        "/api/v1/customers",
        json={
            "full_name": "Priya Raghunathan",
            "email": "priya@demo.example.com",
            "phone": "+1 647 555 0119",
        },
    )
    both = as_admin.post(
        "/api/v1/customers/duplicate-check",
        json={"full_name": "Priya Raghunathan", "email": "priya@demo.example.com"},
    ).json()["candidates"][0]
    name_only = as_admin.post(
        "/api/v1/customers/duplicate-check", json={"full_name": "Priya Raghunathan"}
    ).json()["candidates"][0]
    assert both["confidence"] > name_only["confidence"]
    assert set(both["matched_on"]) == {"email", "name"}


def test_merge_preserves_shipments_tasks_referrals_and_consent(db, as_admin, users):
    source = make_customer(db, full_name="Source Record", email="source@demo.example.com")
    target = make_customer(db, full_name="Target Record", email="target@demo.example.com")
    other = make_customer(db, full_name="Referred Record", email="referred@demo.example.com")

    add_shipment(db, source, days_ago=30)
    db.add(
        FollowUpTask(
            customer_id=source.id,
            subject="Open task on source",
            status="scheduled",
            due_at=None,
        )
    )
    consent_service.record_consent_event(
        db,
        source,
        channel=ConsentChannel.EMAIL,
        status=ConsentStatus.CONSENTED,
        basis=ConsentBasis.EXPRESS,
        obtained_at=None,
        evidence_reference="FORM-1",
    )
    customer_service.add_referral(db, referrer=source, referred=other, note=None)
    db.commit()

    source_public_id = source.public_id
    response = as_admin.post(
        "/api/v1/customers/merge",
        json={
            "source_customer_id": source.id,
            "target_customer_id": target.id,
            "confirmation": source_public_id,
        },
    )
    assert response.status_code == 200, response.text

    db.expire_all()
    assert db.scalar(select(Shipment).where(Shipment.customer_id == target.id)) is not None
    assert db.scalar(select(FollowUpTask).where(FollowUpTask.customer_id == target.id)) is not None
    assert db.scalar(select(ConsentEvent).where(ConsentEvent.customer_id == target.id)) is not None
    assert db.scalar(select(Referral).where(Referral.referrer_customer_id == target.id)) is not None

    alias = db.scalar(
        select(CustomerIdAlias).where(CustomerIdAlias.alias_public_id == source_public_id)
    )
    assert alias is not None and alias.customer_id == target.id

    # The former ID still resolves to the surviving record.
    found = customer_service.get_customer_by_public_id(db, source_public_id)
    assert found.id == target.id


def test_merge_requires_typed_confirmation(as_admin, db):
    source = make_customer(db, full_name="A", email="a@demo.example.com")
    target = make_customer(db, full_name="B", email="b@demo.example.com")
    response = as_admin.post(
        "/api/v1/customers/merge",
        json={
            "source_customer_id": source.id,
            "target_customer_id": target.id,
            "confirmation": "WRONG",
        },
    )
    assert response.status_code == 422


def test_merge_keeps_do_not_contact_from_either_record(db, as_admin):
    source = make_customer(
        db, full_name="Restricted", email="r@demo.example.com", do_not_contact=True
    )
    target = make_customer(db, full_name="Open", email="o@demo.example.com")
    as_admin.post(
        "/api/v1/customers/merge",
        json={
            "source_customer_id": source.id,
            "target_customer_id": target.id,
            "confirmation": source.public_id,
        },
    )
    db.expire_all()
    assert db.get(Customer, target.id).do_not_contact is True


def test_merged_record_is_read_only(db, as_admin):
    source = make_customer(db, full_name="A", email="a@demo.example.com")
    target = make_customer(db, full_name="B", email="b@demo.example.com")
    as_admin.post(
        "/api/v1/customers/merge",
        json={
            "source_customer_id": source.id,
            "target_customer_id": target.id,
            "confirmation": source.public_id,
        },
    )
    response = as_admin.patch(f"/api/v1/customers/{source.id}", json={"city": "Toronto"})
    assert response.status_code == 409


def test_self_referral_is_rejected(as_admin, db):
    customer = make_customer(db)
    response = as_admin.post(
        f"/api/v1/customers/{customer.id}/referrals",
        json={"referred_customer_id": customer.id},
    )
    assert response.status_code == 422
    assert "themselves" in response.json()["message"]


def test_qualified_referral_count_requires_a_qualifying_shipment(db, as_admin):
    referrer = make_customer(db, full_name="Referrer", email="ref@demo.example.com")
    referred = make_customer(db, full_name="Referred", email="rd@demo.example.com")
    customer_service.add_referral(db, referrer=referrer, referred=referred, note=None)
    db.commit()

    detail = as_admin.get(f"/api/v1/customers/{referrer.id}").json()
    assert detail["activity"]["referral_count"] == 1
    assert detail["activity"]["qualified_referral_count"] == 0

    add_shipment(db, referred, days_ago=5)
    detail = as_admin.get(f"/api/v1/customers/{referrer.id}").json()
    assert detail["activity"]["qualified_referral_count"] == 1
