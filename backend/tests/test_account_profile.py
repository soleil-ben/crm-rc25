"""The Customer Account profile, end to end (fix pack 2; CA-PRF-01 … CA-PRF-04).

Each test drives the real routes: an applicant registers, a staff member approves them
(which creates and links the customer), the customer signs in and uses the profile, and
where a case needs it a staff member reviews the result. Nothing is set up by writing
identity or proposal rows directly.
"""

from __future__ import annotations

import json

from app.core.account_fields import postal_code_format_message
from app.core.config import settings
from app.core.enums import Role
from app.core.time_utils import utcnow
from app.models import (
    AuditEvent,
    ConsentEvent,
    ContactSuppression,
    Customer,
    CustomerAddress,
    CustomerDataProposal,
    Interaction,
    Tag,
)
from app.services import consent_service, customer_service
from tests.account_fixtures import csrf_headers, sign_in
from tests.approval_fixtures import acknowledged_preview, approve_create, pending_identity, staff
from tests.conftest import see_committed_changes

ACCOUNT = "/api/v1/account"
REVIEW = "/api/v1/customer-account"
APPLICANT = "hanh@demo.example.com"


# --- Helpers -------------------------------------------------------------------------


def _activate(account_client, account_users, captured_mail) -> str:
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    fingerprint = acknowledged_preview(api, reference, "create_new")
    assert approve_create(api, reference, fingerprint).status_code == 200
    account_client.cookies.clear()
    return reference


class Customer_:
    """A signed-in customer: the client plus the CSRF header the page would send."""

    def __init__(self, client) -> None:
        client.cookies.clear()
        response = sign_in(client, APPLICANT)
        assert response.status_code == 200, response.text
        self.client = client
        self.headers = csrf_headers(response)

    def get(self, path: str):
        return self.client.get(f"{ACCOUNT}{path}")

    def post(self, path: str, body=None):
        return self.client.post(f"{ACCOUNT}{path}", json=body, headers=self.headers)


def _customer(db) -> Customer:
    see_committed_changes(db)
    return db.query(Customer).filter_by(email_normalized=APPLICANT).one()


def _setup(account_client, account_users, captured_mail):
    reference = _activate(account_client, account_users, captured_mail)
    return reference, Customer_(account_client)


# --- Reading (CA-PRF-03) ---------------------------------------------------------------


def test_the_profile_shows_what_is_on_file_and_nothing_internal(
    account_client, account_db, account_users, captured_mail
):
    """Every FIELD_MATRIX §3.4 "Never" field populated, then asserted absent by name."""
    _reference, me = _setup(account_client, account_users, captured_mail)

    customer = _customer(account_db)
    tag = Tag(slug="vip-internal", name="SENTINEL-TAG")
    account_db.add(tag)
    account_db.flush()
    customer_service.set_customer_tags(account_db, customer, [tag.id])
    customer.notes = "SENTINEL-NOTE"
    customer.service_restriction_note = "SENTINEL-RESTRICTION"
    customer.owner_user_id = account_users[Role.OPERATIONS].id
    account_db.add(
        Interaction(
            customer_id=customer.id,
            occurred_at=utcnow(),
            channel="phone",
            direction="inbound",
            subject="SENTINEL-INTERACTION",
            body="SENTINEL-INTERACTION-BODY",
            author_user_id=account_users[Role.OPERATIONS].id,
        )
    )
    account_db.commit()

    response = me.get("/profile")
    assert response.status_code == 200, response.text
    body = response.json()
    raw = json.dumps(body)

    assert body["details"]["customer_reference"] == customer.public_id
    assert body["details"]["legal_name"] == "Nguyễn Thị Bích Hạnh"
    assert body["details"]["pickup_address"]["city"] == "Mississauga"
    assert body["marketing"]["status"] in {"granted", "not_given"}
    assert body["timezone"]

    for sentinel in (
        "SENTINEL-TAG",
        "SENTINEL-NOTE",
        "SENTINEL-RESTRICTION",
        "SENTINEL-INTERACTION",
        account_users[Role.OPERATIONS].email,
        account_users[Role.OPERATIONS].full_name,
    ):
        assert sentinel not in raw, sentinel
    for key in (
        "tags",
        "notes",
        "lifecycle_status",
        "owner",
        "owner_user_id",
        "is_archived",
        "merged_into_customer_id",
        "is_demo_record",
        "name_match_key",
        "phone_match_key",
        "email_normalized",
        "do_not_contact",
        "selling_amount",
        "shipping_cost",
        "suppress",
        '"id"',
        "customer_id",
    ):
        assert key not in raw, key
    # The account's own privacy header set, as on the shipment routes.
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate, private"
    assert response.headers["x-robots-tag"] == "noindex, nofollow, noarchive"


def test_a_pending_account_has_no_profile(account_client, account_db, captured_mail):
    pending_identity(account_client, captured_mail, APPLICANT)
    account_client.cookies.clear()
    me = Customer_(account_client)

    assert me.get("/profile").status_code == 403
    assert me.post("/consent/marketing", {"granted": True}).status_code == 403
    assert me.post("/profile/direct", {"preferred_language": "vi"}).status_code == 403


def test_a_signed_out_caller_gets_nothing(account_client):
    assert account_client.get(f"{ACCOUNT}/profile").status_code == 401


# --- Direct edit (CA-PRF-01) -------------------------------------------------------------


def test_preferred_language_applies_at_once_and_is_audited(
    account_client, account_db, account_users, captured_mail
):
    _reference, me = _setup(account_client, account_users, captured_mail)

    response = me.post("/profile/direct", {"preferred_language": "vi"})

    assert response.status_code == 200, response.text
    assert response.json()["details"]["preferred_language"] == "vi"
    assert _customer(account_db).preferred_language == "vi"
    assert account_db.query(CustomerDataProposal).filter_by(kind="profile_update").count() == 0
    row = (
        account_db.query(AuditEvent)
        .filter_by(action="customer_account.profile_direct_update")
        .one()
    )
    assert json.loads(row.detail_json)["field_keys"] == ["preferred_language"]
    assert "vi" not in row.detail_json  # keys, never values


def test_me_and_the_profile_report_the_same_language_after_a_change(
    account_client, account_db, account_users, captured_mail
):
    """UAT round 3: ``/me`` read the identity and ``/profile`` the customer; now one field."""
    _reference, me = _setup(account_client, account_users, captured_mail)

    def both() -> tuple[str, str]:
        return (
            me.get("/me").json()["preferred_language"],
            me.get("/profile").json()["details"]["preferred_language"],
        )

    first_me, first_profile = both()
    assert first_me == first_profile

    for language in ("vi", "fr", "en"):
        assert me.post("/profile/direct", {"preferred_language": language}).status_code == 200
        assert both() == (language, language)
    assert _customer(account_db).preferred_language == "en"


def test_a_customer_language_staff_left_unknown_falls_back_on_both_endpoints(
    account_client, account_db, account_users, captured_mail
):
    _reference, me = _setup(account_client, account_users, captured_mail)
    customer = _customer(account_db)
    customer.preferred_language = "unknown"
    account_db.commit()

    reported_me = me.get("/me").json()["preferred_language"]
    reported_profile = me.get("/profile").json()["details"]["preferred_language"]
    assert reported_me == reported_profile
    assert reported_me != "unknown"


def test_a_direct_edit_naming_a_proposal_or_never_field_is_refused(
    account_client, account_db, account_users, captured_mail
):
    _reference, me = _setup(account_client, account_users, captured_mail)
    before = _customer(account_db).full_name

    for key, value in (("legal_name", "Somebody Else"), ("notes", "x"), ("email", "a@b.example")):
        response = me.post("/profile/direct", {key: value})
        assert response.status_code == 422, (key, response.text)
        assert response.json()["field"] == key

    assert me.post("/profile/direct", {"preferred_language": "klingon"}).status_code == 422
    assert _customer(account_db).full_name == before


# --- Proposals (CA-PRF-02) -------------------------------------------------------------


def _propose(me, **fields):
    return me.post("/profile/proposals", {"fields": fields})


def test_a_name_and_address_change_becomes_a_proposal_and_nothing_canonical_moves(
    account_client, account_db, account_users, captured_mail
):
    _reference, me = _setup(account_client, account_users, captured_mail)
    customer = _customer(account_db)
    before_name, before_addresses = customer.full_name, account_db.query(CustomerAddress).count()

    response = _propose(
        me,
        legal_name="Nguyễn Thị Bích Hạnh Trần",
        **{
            "pickup_address.1.address_line1": "88 Queen Street East",
            "pickup_address.1.city": "Toronto",
            "pickup_address.1.country_code": "CA",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["proposal"]["status"] == "pending"
    customer = _customer(account_db)
    assert customer.full_name == before_name
    assert customer.legal_name != "Nguyễn Thị Bích Hạnh Trần"
    assert account_db.query(CustomerAddress).count() == before_addresses

    proposal = account_db.query(CustomerDataProposal).filter_by(kind="profile_update").one()
    assert proposal.customer_id == customer.id
    by_key = {row.field_key: row for row in proposal.fields}
    assert by_key["legal_name"].current_value_at_submission == "Nguyễn Thị Bích Hạnh"
    assert by_key["pickup_address.1.city"].current_value_at_submission == "Mississauga"

    # The customer sees their own request and its state.
    profile = me.get("/profile").json()
    assert profile["proposals"][0]["status"] == "pending"


def test_proposals_refuse_email_never_fields_and_half_addresses(
    account_client, account_db, account_users, captured_mail
):
    _reference, me = _setup(account_client, account_users, captured_mail)
    for fields, field in (
        ({"email": "new@demo.example.com"}, "email"),
        ({"notes": "x"}, "notes"),
        ({"preferred_language": "vi"}, "preferred_language"),
        ({"pickup_address.1.address_line1": "1 Main St"}, "pickup_address.1.city"),
        ({}, None),
    ):
        response = _propose(me, **fields)
        assert response.status_code == 422, (fields, response.text)
        assert response.json()["field"] == field
    assert account_db.query(CustomerDataProposal).filter_by(kind="profile_update").count() == 0


def test_a_proposed_postal_code_has_the_same_lenient_shape_as_at_registration(
    account_client, account_db, account_users, captured_mail
):
    """The profile's address proposal goes through the same field check (DEC-0165)."""
    _reference, me = _setup(account_client, account_users, captured_mail)
    address = {
        "pickup_address.1.address_line1": "88 Queen Street East",
        "pickup_address.1.city": "Toronto",
        "pickup_address.1.province_state": "ON",
        "pickup_address.1.country_code": "CA",
    }
    refused = _propose(me, **address, **{"pickup_address.1.postal_code": "12345"})
    assert refused.status_code == 422, refused.text
    assert refused.json()["field"] == "pickup_address.1.postal_code"
    assert refused.json()["message"] == postal_code_format_message("CA", billing=False)
    assert account_db.query(CustomerDataProposal).filter_by(kind="profile_update").count() == 0

    accepted = _propose(me, **address, **{"pickup_address.1.postal_code": "m5c1a1"})
    assert accepted.status_code == 200, accepted.text


def test_a_newer_request_supersedes_and_carries_forward(
    account_client, account_db, account_users, captured_mail
):
    _reference, me = _setup(account_client, account_users, captured_mail)
    assert _propose(me, display_name="Hạnh N.").status_code == 200
    assert _propose(me, legal_name="Hạnh Nguyễn").status_code == 200

    see_committed_changes(account_db)
    rows = account_db.query(CustomerDataProposal).filter_by(kind="profile_update").all()
    statuses = sorted(row.status for row in rows)
    assert statuses == ["pending", "superseded"]
    pending = next(row for row in rows if row.status == "pending")
    assert {row.field_key for row in pending.fields} == {"display_name", "legal_name"}


def test_the_customer_can_withdraw_the_pending_request(
    account_client, account_db, account_users, captured_mail
):
    _reference, me = _setup(account_client, account_users, captured_mail)
    _propose(me, display_name="Hạnh N.")

    response = me.post("/profile/proposals/withdraw")
    assert response.status_code == 200
    assert response.json()["proposals"][0]["status"] == "withdrawn"
    assert me.post("/profile/proposals/withdraw").status_code == 404


# --- Staff review (CA-PRF-02 steps 3-4; FIELD_MATRIX §5) ------------------------------


def test_staff_approve_one_field_and_decline_the_other(
    account_client, account_db, account_users, captured_mail
):
    reference, me = _setup(account_client, account_users, captured_mail)
    _propose(
        me,
        legal_name="Hạnh Nguyễn Trần",
        **{
            "pickup_address.1.address_line1": "88 Queen Street East",
            "pickup_address.1.city": "Toronto",
            "pickup_address.1.country_code": "CA",
        },
    )
    addresses_before = account_db.query(CustomerAddress).count()

    api = staff(account_client, account_users[Role.OPERATIONS].email)
    queue = api.get(f"{REVIEW}/profile-proposals").json()
    assert [row["account_reference"] for row in queue["items"]] == [reference]
    assert queue["items"][0]["groups"] == ["legal_name", "pickup_address"]

    detail = api.get(f"{REVIEW}/identities/{reference}/profile-proposal").json()
    legal = next(row for row in detail["fields"] if row["field_key"] == "legal_name")
    assert legal["proposed_value"] == "Hạnh Nguyễn Trần"
    assert legal["current_value_now"] == "Nguyễn Thị Bích Hạnh"
    assert legal["proposed_value_normalized"]
    assert legal["drifted"] is False

    response = api.post(
        f"{REVIEW}/identities/{reference}/profile-proposal/decide",
        json={
            "decisions": {"legal_name": "approve", "pickup_address": "decline"},
            "reason_code": "could_not_verify",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"

    customer = _customer(account_db)
    assert customer.legal_name == "Hạnh Nguyễn Trần"
    assert customer.full_name == "Hạnh Nguyễn Trần"
    assert account_db.query(CustomerAddress).count() == addresses_before
    proposal = account_db.query(CustomerDataProposal).filter_by(kind="profile_update").one()
    applied = {row.field_key: row.applied for row in proposal.fields}
    assert applied["legal_name"] is True
    assert applied["pickup_address.1.city"] is False

    # Deciding again changes nothing and writes no second decision (FIELD_MATRIX §7.5).
    again = api.post(
        f"{REVIEW}/identities/{reference}/profile-proposal/decide",
        json={"decisions": {"legal_name": "approve", "pickup_address": "approve"}},
    )
    assert again.status_code == 409
    see_committed_changes(account_db)
    assert account_db.query(CustomerAddress).count() == addresses_before
    assert (
        account_db.query(AuditEvent).filter_by(action="customer_data_proposal.decide").count() == 1
    )

    # And the customer sees each field's outcome.
    me = Customer_(account_client)
    fields = me.get("/profile").json()["proposals"][0]["fields"]
    assert {row["field_key"]: row["applied"] for row in fields}["legal_name"] is True


def test_an_approved_address_lands_as_the_default_pickup(
    account_client, account_db, account_users, captured_mail
):
    reference, me = _setup(account_client, account_users, captured_mail)
    _propose(
        me,
        **{
            "pickup_address.1.contact_name": "Hạnh",
            "pickup_address.1.address_line1": "88 Queen Street East",
            "pickup_address.1.city": "Toronto",
            "pickup_address.1.country_code": "CA",
        },
    )
    api = staff(account_client, account_users[Role.ADMIN].email)
    response = api.post(
        f"{REVIEW}/identities/{reference}/profile-proposal/decide",
        json={"decisions": {"pickup_address": "approve"}},
    )
    assert response.status_code == 200, response.text

    see_committed_changes(account_db)
    customer = _customer(account_db)
    default = (
        account_db.query(CustomerAddress)
        .filter_by(customer_id=customer.id, is_default_sender=True, is_archived=False)
        .all()
    )
    assert len(default) == 1
    assert default[0].city == "Toronto"
    assert default[0].role == "sender"


def test_a_drifted_field_is_refused_not_merged(
    account_client, account_db, account_users, captured_mail
):
    reference, me = _setup(account_client, account_users, captured_mail)
    _propose(me, display_name="Hạnh N.")

    customer = _customer(account_db)
    customer.display_name = "Changed by staff meanwhile"
    account_db.commit()

    api = staff(account_client, account_users[Role.OPERATIONS].email)
    detail = api.get(f"{REVIEW}/identities/{reference}/profile-proposal").json()
    assert detail["fields"][0]["drifted"] is True
    response = api.post(
        f"{REVIEW}/identities/{reference}/profile-proposal/decide",
        json={"decisions": {"display_name": "approve"}},
    )
    assert response.status_code == 409
    assert _customer(account_db).display_name == "Changed by staff meanwhile"


def test_a_partial_or_unreasoned_decision_is_refused(
    account_client, account_db, account_users, captured_mail
):
    reference, me = _setup(account_client, account_users, captured_mail)
    _propose(me, display_name="Hạnh N.", legal_name="Hạnh Nguyễn")
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    url = f"{REVIEW}/identities/{reference}/profile-proposal/decide"

    assert api.post(url, json={"decisions": {"display_name": "approve"}}).status_code == 422
    declined = api.post(
        url, json={"decisions": {"display_name": "approve", "legal_name": "decline"}}
    )
    assert declined.status_code == 422
    assert declined.json()["field"] == "reason_code"


def test_marketing_and_the_manager_cannot_review_profile_changes(
    account_client, account_db, account_users, captured_mail
):
    reference, me = _setup(account_client, account_users, captured_mail)
    _propose(me, display_name="Hạnh N.")
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        api = staff(account_client, account_users[role].email)
        assert api.get(f"{REVIEW}/profile-proposals").status_code == 403
        assert api.get(f"{REVIEW}/identities/{reference}/profile-proposal").status_code == 403
        assert (
            api.post(
                f"{REVIEW}/identities/{reference}/profile-proposal/decide",
                json={"decisions": {"display_name": "approve"}},
            ).status_code
            == 403
        )


# --- Marketing consent (FIELD_MATRIX §4; CA-PRF-04) -------------------------------------


def test_marketing_consent_is_granted_and_withdrawn_append_only_with_audit(
    account_client, account_db, account_users, captured_mail
):
    _reference, me = _setup(account_client, account_users, captured_mail)
    before = account_db.query(ConsentEvent).count()

    granted = me.post("/consent/marketing", {"granted": True})
    assert granted.status_code == 200, granted.text
    assert granted.json()["marketing"]["status"] == "granted"
    withdrawn = me.post("/consent/marketing", {"granted": False})
    assert withdrawn.json()["marketing"]["status"] == "withdrawn"

    see_committed_changes(account_db)
    assert account_db.query(ConsentEvent).count() == before + 2
    audits = (
        account_db.query(AuditEvent).filter_by(action="customer_account.marketing_choice").all()
    )
    assert [json.loads(row.detail_json)["status"] for row in audits] == ["granted", "withdrawn"]
    history = me.get("/profile").json()["marketing_history"]
    assert [item["status"] for item in history][:2] == ["withdrawn", "granted"]


def test_a_customer_grant_does_not_lift_a_suppression_and_names_nothing_about_it(
    account_client, account_db, account_users, captured_mail
):
    _reference, me = _setup(account_client, account_users, captured_mail)
    customer = _customer(account_db)
    consent_service.add_suppression(
        account_db,
        channel="email",
        address_value=customer.email_normalized,
        reason="Bounced",
        actor=account_users[Role.OPERATIONS],
    )
    account_db.commit()

    response = me.post("/consent/marketing", {"granted": True})

    assert response.status_code == 200
    # One boolean says the opt-in cannot be delivered (UAT round 3). Nothing names the
    # suppression, its reason or who recorded it.
    assert response.json() == {
        "marketing": {
            "status": "granted",
            "changed_at": response.json()["marketing"]["changed_at"],
            "delivery_blocked": True,
        }
    }
    profile = me.get("/profile")
    assert profile.json()["marketing"]["delivery_blocked"] is True
    for text in (response.text, profile.text):
        assert "suppress" not in text.lower()
        assert "bounced" not in text.lower()
        assert account_users[Role.OPERATIONS].email not in text

    see_committed_changes(account_db)
    customer = _customer(account_db)
    suppression = account_db.query(ContactSuppression).one()
    assert suppression.released_at is None
    assert consent_service.marketing_eligible(account_db, customer, "email") is False
    audit = account_db.query(AuditEvent).filter_by(action="customer_account.marketing_choice").one()
    assert json.loads(audit.detail_json)["address_suppressed"] is True


def test_delivery_blocked_is_false_without_a_suppression_and_without_an_opt_in(
    account_client, account_db, account_users, captured_mail
):
    _reference, me = _setup(account_client, account_users, captured_mail)

    granted = me.post("/consent/marketing", {"granted": True})
    assert granted.json()["marketing"]["delivery_blocked"] is False
    assert me.get("/profile").json()["marketing"]["delivery_blocked"] is False

    customer = _customer(account_db)
    consent_service.add_suppression(
        account_db,
        channel="email",
        address_value=customer.email_normalized,
        reason="Complaint",
        actor=account_users[Role.OPERATIONS],
    )
    account_db.commit()
    assert me.get("/profile").json()["marketing"]["delivery_blocked"] is True

    # A withdrawn customer learns nothing about the address: the bit is only ever set on
    # an opt-in, so withdrawing reads exactly as it does for an unsuppressed address.
    withdrawn = me.post("/consent/marketing", {"granted": False})
    assert withdrawn.json()["marketing"]["delivery_blocked"] is False
    assert me.get("/profile").json()["marketing"]["delivery_blocked"] is False


def test_a_malformed_marketing_body_is_refused(
    account_client, account_db, account_users, captured_mail
):
    _reference, me = _setup(account_client, account_users, captured_mail)
    for body in ({"granted": "yes"}, {"granted": True, "extra": 1}, {}):
        assert me.post("/consent/marketing", body).status_code in {400, 422}


def test_every_profile_write_needs_the_account_csrf_token(
    account_client, account_db, account_users, captured_mail
):
    _reference, me = _setup(account_client, account_users, captured_mail)
    for path, body in (
        ("/profile/direct", {"preferred_language": "vi"}),
        ("/profile/proposals", {"fields": {"display_name": "x"}}),
        ("/profile/proposals/withdraw", None),
        ("/consent/marketing", {"granted": True}),
    ):
        response = account_client.post(f"{ACCOUNT}{path}", json=body)
        assert response.status_code == 403, path
    assert settings.account_csrf_header_name
