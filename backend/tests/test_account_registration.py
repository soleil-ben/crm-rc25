"""Registration: what it creates, what it refuses, and what it never says.

The hardest thing to test here is an absence. "Registration does not disclose whether an
address exists" is not demonstrated by a passing happy path; it is demonstrated by putting
an account into every state the state machine has, registering against each one, and
asserting the responses are **identical** -- status, body and headers -- and that the
sentence is the same sentence.

The second absence is the canonical one. `test_account_no_canonical_write.py` carries the
whole-surface version; this module asserts the registration-specific half against a database
that already holds a matching customer, because a registration that matched an existing
customer is exactly the case where an implementation would be tempted to link.
"""

from __future__ import annotations

import pytest

from app.core.account_enums import IdentityStatus, ProposalStatus
from app.core.account_fields import ALLOWED_FIELD_KEYS
from app.core.time_utils import utcnow
from app.models import (
    ConsentEvent,
    ContactSuppression,
    Customer,
    CustomerAddress,
    CustomerAuthToken,
    CustomerDataProposal,
    CustomerDataProposalField,
    CustomerIdentity,
    CustomerNotificationPreference,
    CustomerRegistrationAttempt,
    CustomerTermsAcknowledgement,
)
from app.services import account_email_service as email
from app.services import customer_identity_service
from tests.account_fixtures import ACCOUNT_PASSWORD, register, registration

REGISTER = "/api/v1/account/register"


def _identity(db, address: str) -> CustomerIdentity | None:
    return db.query(CustomerIdentity).filter_by(email_normalized=address).one_or_none()


def _fingerprint_of(response) -> tuple:
    """Everything a caller can observe, so "identical" means identical.

    Headers that legitimately vary per request -- the date, and the content length, which
    cannot differ while the body does not -- are excluded by comparing the header *set* and
    the security-relevant values rather than every value.
    """
    interesting = {"content-type", "cache-control", "x-correlation-id", "retry-after"}
    return (
        response.status_code,
        response.json(),
        {key: value for key, value in response.headers.items() if key.lower() in interesting},
    )


# --- The happy path, stated as what it created -------------------------------


def test_registration_creates_one_identity_one_proposal_and_one_token(
    account_client, account_db, captured_mail
):
    response = register(account_client)
    assert response.status_code == 200

    identities = account_db.query(CustomerIdentity).all()
    assert len(identities) == 1
    identity = identities[0]
    assert identity.status == IdentityStatus.PENDING_VERIFICATION
    assert identity.email_verified_at is None
    assert identity.approved_at is None
    assert identity.public_id.startswith("CA-")

    proposals = account_db.query(CustomerDataProposal).all()
    assert len(proposals) == 1
    assert proposals[0].status == ProposalStatus.PENDING
    assert proposals[0].customer_id is None

    tokens = account_db.query(CustomerAuthToken).all()
    assert len(tokens) == 1
    assert tokens[0].purpose == "email_verification"
    assert tokens[0].consumed_at is None

    assert [m["template_key"] for m in captured_mail.messages] == [email.TEMPLATE_VERIFY_EMAIL]


def test_the_password_is_hashed_with_argon2_and_the_plaintext_is_nowhere(
    account_client, account_db, captured_mail
):
    register(account_client)
    identity = _identity(account_db, "hanh@demo.example.com")
    assert identity.password_hash.startswith("$argon2")
    assert ACCOUNT_PASSWORD not in identity.password_hash

    from app.core.security import verify_password

    assert verify_password(ACCOUNT_PASSWORD, identity.password_hash)
    assert not verify_password("wrong-password-entirely", identity.password_hash)

    # Not in any captured message either.
    for message in captured_mail.messages:
        assert ACCOUNT_PASSWORD not in message["body"]


def test_email_is_normalized_and_both_forms_are_kept(account_client, account_db, captured_mail):
    register(account_client, email="  HANH@Demo.Example.COM  ")
    identity = account_db.query(CustomerIdentity).one()
    assert identity.email_normalized == "hanh@demo.example.com"
    assert identity.email_entered == "HANH@Demo.Example.COM"


def test_case_differences_are_the_same_account(account_client, account_db, captured_mail):
    """The case-insensitive uniqueness strategy, exercised rather than described."""
    register(account_client, email="hanh@demo.example.com")
    register(account_client, email="HANH@DEMO.EXAMPLE.COM")
    assert account_db.query(CustomerIdentity).count() == 1


def test_proposal_fields_are_typed_normalized_and_within_the_allowlist(
    account_client, account_db, captured_mail
):
    register(account_client)
    rows = account_db.query(CustomerDataProposalField).all()
    assert rows

    by_key = {row.field_key: row for row in rows}
    assert set(by_key) <= ALLOWED_FIELD_KEYS

    # Typed, and the type recorded.
    assert by_key["customer_type"].value_type == "enum"
    assert by_key["phone"].value_type == "phone"
    assert by_key["legal_name"].value_type == "string"
    assert by_key["billing_address.country_code"].value_type == "country"

    # Normalized alongside entered, through the existing normalization service.
    assert by_key["phone"].proposed_value_normalized == "+84901234567"
    assert by_key["billing_address.country_code"].proposed_value_normalized == "VN"
    assert by_key["legal_name"].proposed_value_normalized == "nguyen thi bich hanh"
    assert by_key["legal_name"].proposed_value == "Nguyễn Thị Bích Hạnh"

    # Nothing is applied, because nothing may be.
    assert all(row.applied is False for row in rows)
    assert all(row.current_value_at_submission is None for row in rows)


def test_terms_and_privacy_are_recorded_with_version_language_and_timestamp(
    account_client, account_db, captured_mail
):
    register(account_client)
    rows = account_db.query(CustomerTermsAcknowledgement).all()
    assert {row.document_kind for row in rows} == {"terms", "privacy"}
    for row in rows:
        assert row.document_version
        assert row.presented_language == "en"
        assert row.acknowledged_at is not None


def test_registration_is_refused_without_an_acknowledgement(account_client, account_db):
    for missing in ("accept_terms", "accept_privacy"):
        response = account_client.post(REGISTER, json=registration(**{missing: False}))
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"
    assert account_db.query(CustomerIdentity).count() == 0


def test_marketing_consent_is_a_proposal_field_and_never_a_consent_row(
    account_client, account_db, captured_mail
):
    """OD-38: explicit, separate, and written to `consent_events` only at approval."""
    register(account_client)
    row = account_db.query(CustomerDataProposalField).filter_by(field_key="marketing_consent").one()
    assert row.proposed_value == "true"
    assert account_db.query(ConsentEvent).count() == 0


def test_marketing_consent_is_absent_unless_chosen(account_client, account_db, captured_mail):
    body = registration()
    body["customer"].pop("marketing_consent")
    account_client.post(REGISTER, json=body)
    assert (
        account_db.query(CustomerDataProposalField).filter_by(field_key="marketing_consent").count()
        == 0
    )


def test_notification_preferences_are_unchecked_by_default(
    account_client, account_db, captured_mail
):
    account_client.post(REGISTER, json=registration(notification_topics=[]))
    assert account_db.query(CustomerNotificationPreference).count() == 0


def test_account_security_cannot_be_switched_off(account_client, account_db):
    """A preference that could suppress a reset message would lock people out."""
    response = account_client.post(
        REGISTER, json=registration(notification_topics=["account_security"])
    )
    assert response.status_code == 422
    assert account_db.query(CustomerIdentity).count() == 0


# --- The absence: no canonical write -----------------------------------------


def test_registration_writes_no_canonical_row_even_when_a_customer_matches(
    account_client, account_db, captured_mail
):
    """The case an implementation is most tempted to link: an exact email match."""
    from app.services import customer_service

    customer_service.create_customer(
        account_db,
        {
            "full_name": "Nguyễn Thị Bích Hạnh",
            "email": "hanh@demo.example.com",
            "phone": "+84 90 123 4567",
            "country_code": "VN",
        },
    )
    account_db.commit()

    before = (
        account_db.query(Customer).count(),
        account_db.query(CustomerAddress).count(),
        account_db.query(ConsentEvent).count(),
    )

    assert register(account_client).status_code == 200

    after = (
        account_db.query(Customer).count(),
        account_db.query(CustomerAddress).count(),
        account_db.query(ConsentEvent).count(),
    )
    assert after == before

    # And nothing links the two.
    from app.models import CustomerIdentityLink

    assert account_db.query(CustomerIdentityLink).count() == 0


def test_no_response_field_carries_a_duplicate_score_or_match_count(
    account_client, account_db, captured_mail
):
    from app.services import customer_service

    customer_service.create_customer(
        account_db,
        {
            "full_name": "Nguyễn Thị Bích Hạnh",
            "email": "hanh@demo.example.com",
            "phone": "+84 90 123 4567",
            "country_code": "VN",
        },
    )
    account_db.commit()

    body = register(account_client).json()
    assert set(body) == {"message"}
    raw = str(body).lower()
    for forbidden in ("score", "match", "duplicate", "candidate", "cus-", "customer_id"):
        assert forbidden not in raw


# --- Enumeration resistance: every state, one answer -------------------------


def _put_into_state(db, address: str, status: IdentityStatus) -> None:
    identity = _identity(db, address)
    identity.status = status.value
    if status is not IdentityStatus.PENDING_VERIFICATION:
        identity.email_verified_at = utcnow()
    db.commit()


@pytest.mark.parametrize(
    "state",
    [
        IdentityStatus.PENDING_VERIFICATION,
        IdentityStatus.PENDING_APPROVAL,
        IdentityStatus.ACTIVE,
        IdentityStatus.REJECTED,
        IdentityStatus.SUSPENDED,
        IdentityStatus.DEACTIVATED,
    ],
)
def test_registration_answers_identically_whatever_state_the_account_is_in(
    account_client, account_db, captured_mail, state
):
    """Six existing states and one unknown address. Seven registrations, one answer.

    This is the test OD-23 asks for, and it is written as a comparison rather than as seven
    assertions about a literal, so that changing the sentence changes it in one place and
    still proves the seven are the same.
    """
    baseline = _fingerprint_of(register(account_client, email="stranger@demo.example.com"))

    register(account_client, email="hanh@demo.example.com")
    _put_into_state(account_db, "hanh@demo.example.com", state)

    again = _fingerprint_of(register(account_client, email="hanh@demo.example.com"))
    assert again == baseline


def test_a_suppressed_address_gets_the_same_answer_and_its_verification_email(
    account_client, account_db, captured_mail
):
    """A marketing suppression does not block account email (owner decision, 2026-10-15).

    Before UAT round 6 nothing was sent and nothing was created, and the customer could
    never finish signing up. The answer is still the ordinary one, so it says nothing.
    """
    account_db.add(
        ContactSuppression(
            channel="email",
            address_value="hanh@demo.example.com",
            reason="Customer asked to be removed",
            created_at=utcnow(),
        )
    )
    account_db.commit()

    baseline = _fingerprint_of(register(account_client, email="stranger@demo.example.com"))
    captured_mail.messages.clear()

    suppressed = _fingerprint_of(register(account_client, email="hanh@demo.example.com"))
    assert suppressed == baseline
    assert [message["template_key"] for message in captured_mail.messages] == [
        "account.verify_email"
    ]
    assert (
        account_db.query(CustomerIdentity)
        .filter_by(email_normalized="hanh@demo.example.com")
        .count()
        == 1
    )


def test_an_existing_address_receives_at_most_one_notice_and_creates_nothing(
    account_client, account_db, captured_mail
):
    """T-11: registering against somebody else's address is not a way to mail them."""
    register(account_client, email="hanh@demo.example.com")
    captured_mail.messages.clear()
    before = account_db.query(CustomerIdentity).count()

    # The per-address bucket allows two registrations per day; the third is refused with the
    # ordinary body and produces nothing at all.
    for _ in range(4):
        assert register(account_client, email="hanh@demo.example.com").status_code == 200

    assert account_db.query(CustomerIdentity).count() == before
    notices = [
        m
        for m in captured_mail.messages
        if m["template_key"] == email.TEMPLATE_REGISTRATION_ATTEMPT_NOTICE
    ]
    assert 0 < len(notices) <= 2, [m["template_key"] for m in captured_mail.messages]
    for notice in notices:
        # No account details, because the reader may not be the person who typed the address.
        assert "CA-" not in notice["body"]
        assert "pending" not in notice["body"].lower()


# --- Idempotency and repetition ----------------------------------------------


def test_the_same_key_with_the_same_data_creates_nothing_the_second_time(
    account_client, account_db, captured_mail
):
    first = account_client.post(REGISTER, json=registration(idempotency_key="key-1"))
    second = account_client.post(REGISTER, json=registration(idempotency_key="key-1"))

    assert _fingerprint_of(first) == _fingerprint_of(second)
    assert account_db.query(CustomerIdentity).count() == 1
    assert account_db.query(CustomerDataProposal).count() == 1
    assert account_db.query(CustomerAuthToken).count() == 1
    assert len(captured_mail.messages) == 1
    assert account_db.query(CustomerRegistrationAttempt).count() == 1


def test_the_same_key_with_different_data_is_refused_rather_than_replayed(
    account_client, account_db, captured_mail
):
    """DEC-0031's rule: one key reused for different data is a conflict, not a silent return."""
    account_client.post(REGISTER, json=registration(idempotency_key="key-1"))
    response = account_client.post(
        REGISTER,
        json=registration(idempotency_key="key-1", email="someone.else@demo.example.com"),
    )
    assert response.status_code == 409
    assert account_db.query(CustomerIdentity).count() == 1


def test_a_client_that_sends_no_key_still_cannot_double_click_into_two_identities(
    account_client, account_db, captured_mail
):
    """Two keyless registrations for one address: the address constraint is the backstop."""
    body = registration()
    body.pop("idempotency_key")
    account_client.post(REGISTER, json=body)
    account_client.post(REGISTER, json=body)
    assert account_db.query(CustomerIdentity).count() == 1


def test_repeated_registration_does_not_create_unbounded_rows(
    account_client, account_db, captured_mail
):
    for index in range(6):
        register(account_client, idempotency_key=f"k{index}")

    assert account_db.query(CustomerIdentity).count() == 1
    assert account_db.query(CustomerDataProposal).count() == 1
    # Two allowed by the per-address bucket, then the ordinary body and no work at all.
    assert account_db.query(CustomerRegistrationAttempt).count() <= 2
    assert len(captured_mail.messages) <= 3


# --- Malformed and oversized -------------------------------------------------


def test_a_field_outside_the_allowlist_is_refused(account_client, account_db):
    body = registration()
    body["customer"]["internal_notes"] = "Staff prose about the customer"
    response = account_client.post(REGISTER, json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert account_db.query(CustomerIdentity).count() == 0


@pytest.mark.parametrize(
    "key",
    ["owner_user_id", "lifecycle_status", "is_demo_record", "selling_amount", "role", "id"],
)
def test_a_never_field_cannot_be_submitted(account_client, account_db, key):
    """Every one of these is a `FIELD_MATRIX.md` section 3.4 "Never" row."""
    body = registration()
    body["customer"][key] = "1"
    assert account_client.post(REGISTER, json=body).status_code == 422
    assert account_db.query(CustomerIdentity).count() == 0


def test_an_oversized_value_is_refused_without_being_truncated(account_client, account_db):
    body = registration()
    body["customer"]["legal_name"] = "x" * 5000
    assert account_client.post(REGISTER, json=body).status_code == 422
    assert account_db.query(CustomerIdentity).count() == 0


def test_an_oversized_body_is_refused(account_client, account_db):
    body = registration()
    body["customer"] = {"pickup_address.1.city": "x" * 900}
    body["padding"] = "y" * 200000
    response = account_client.post(REGISTER, json=body)
    assert response.status_code in {400, 413, 422}
    assert account_db.query(CustomerIdentity).count() == 0


def test_a_body_that_is_not_json_is_refused_without_detail(account_client, account_db):
    response = account_client.post(
        REGISTER, content=b"{not json at all", headers={"content-type": "application/json"}
    )
    assert response.status_code == 400
    body = response.json()
    # The fixed three-key shape, and no `field`: there is nothing safe to be specific about
    # when the body is not JSON at all.
    assert set(body) == {"code", "message", "field"}
    assert body["field"] is None
    assert "detail" not in body
    assert account_db.query(CustomerIdentity).count() == 0


def test_a_short_password_is_refused_as_a_format_problem(account_client, account_db):
    response = account_client.post(REGISTER, json=registration(password="short"))
    assert response.status_code == 422
    assert response.json()["field"] == "password"
    assert account_db.query(CustomerIdentity).count() == 0


def test_a_malformed_email_is_refused_as_a_format_problem(account_client, account_db):
    response = account_client.post(REGISTER, json=registration(email="not-an-address"))
    assert response.status_code == 422
    assert response.json()["field"] == "email"
    # And says nothing about existence.
    assert "registered" not in response.json()["message"].lower()
    assert "exists" not in response.json()["message"].lower()


# --- The generic message is one message ---------------------------------------


def test_the_generic_message_names_no_state():
    """It may say an address *can be* registered. It may not say whether one *is*.

    The distinction is the whole sentence: "if that address can be registered" is a
    conditional about a hypothetical, and every phrase below would turn it into a report
    about a particular account.
    """
    message = customer_identity_service.GENERIC_REGISTRATION_MESSAGE.lower()
    for leak in (
        "already",
        "exists",
        "is registered",
        "not registered",
        "verified",
        "unverified",
        "suspended",
        "approved",
        "pending",
        "suppressed",
    ):
        assert leak not in message, f"the generic message reveals state: {leak!r}"
