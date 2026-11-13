"""The preview, the acknowledgement, and the eight ways the world moves under a reviewer.

The preview exists so that a person decides using figures the server computed. The
fingerprint exists so that the decision cannot be applied to a different set of facts than
the one they read. Between the two there is a window -- a reviewer reads a page, thinks
about it, and presses approve -- and everything in the second half of this module happens
inside that window.

Each drift test does the same thing: take a preview, acknowledge it, change one fact, then
approve. The approval must refuse with ``409``, and the acknowledgement must not be
reusable. The eight facts are the eight the instruction names, and they are tested
separately rather than as a set because a fingerprint that covered seven of them would
pass a test that only checked one.
"""

from __future__ import annotations

from app.core.enums import BookingState, Role
from app.models import Customer, CustomerIdentity, CustomerIdentityLink
from tests.approval_fixtures import (
    BASE,
    acknowledge,
    acknowledged_preview,
    add_shipment,
    approve_create,
    approve_link,
    make_customer,
    pending_identity,
    preview,
    reject,
    staff,
)

APPLICANT = "hanh@demo.example.com"


def _operations(account_client, account_users):
    return staff(account_client, account_users[Role.OPERATIONS].email)


# --- What the preview says ----------------------------------------------------


def test_a_create_new_preview_discloses_nothing_and_says_so(
    account_client, account_users, captured_mail
):
    """A customer that does not exist yet has no history. The zero is still shown.

    OD-29 requires the acknowledgement "even if the count is zero" -- a reviewer who never
    sees a zero has not learned to read the number.
    """
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)

    body = preview(api, reference, "create_new").json()
    assert body["action"] == "create_new"
    assert body["current"] is None
    assert body["differences"] == []
    assert body["target_customer_public_id"] is None
    assert body["disclosure"]["shipment_count"] == 0
    assert body["disclosure"]["oldest_booked_at"] is None
    assert body["disclosure"]["includes_cancelled"] is False
    assert body["fingerprint"]


def test_a_create_new_preview_shows_what_would_be_written(
    account_client, account_users, captured_mail
):
    """``proposed`` is the mapped canonical snapshot, not a second opinion about it.

    It is produced by running the proposal through the same mapping the approval uses, so
    a reviewer reading it is reading what the approval would actually set.
    """
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)

    proposed = preview(api, reference, "create_new").json()["proposed"]
    assert proposed["full_name"] == "Nguyễn Thị Bích Hạnh"
    assert proposed["display_name"] == "Hạnh"
    assert proposed["legal_name"] == "Nguyễn Thị Bích Hạnh"
    assert proposed["email_entered"] == APPLICANT
    assert proposed["category"] == "individual"
    assert proposed["country_code"] == "VN"


def test_a_link_preview_carries_the_disclosure_and_the_differences(
    account_client, account_db, account_users, captured_mail
):
    customer = make_customer(
        account_db, full_name="Hanh Nguyen", email="hanh@demo.example.com", city="Toronto"
    )
    add_shipment(account_db, customer, days_ago=30)
    add_shipment(account_db, customer, days_ago=2, booking_state=BookingState.CANCELLED)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)

    body = preview(api, reference, "link_existing", customer.public_id).json()
    assert body["target_customer_public_id"] == customer.public_id
    assert body["disclosure"]["shipment_count"] == 2
    assert body["disclosure"]["includes_cancelled"] is True
    assert body["current"]["full_name"] == "Hanh Nguyen"
    differing = {row["field"] for row in body["differences"]}
    assert "full_name" in differing
    assert "city" in differing


def test_the_preview_carries_no_shipment_detail_at_all(
    account_client, account_db, account_users, captured_mail
):
    """Counts and two dates. No reference, no package, no event, no recipient, no money."""
    customer = make_customer(account_db, full_name="Hanh Nguyen", email=APPLICANT)
    shipment = add_shipment(account_db, customer, days_ago=9)
    shipment.recipient_name = "PLANTED-RECIPIENT"
    shipment.selling_amount = 1234.56
    shipment.internal_notes = "PLANTED-INTERNAL"
    account_db.commit()

    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    raw = preview(api, reference, "link_existing", customer.public_id).text

    for planted in (shipment.public_id, "PLANTED-RECIPIENT", "PLANTED-INTERNAL", "1234.56"):
        assert planted not in raw, planted


def test_linking_without_naming_a_customer_is_refused(account_client, account_users, captured_mail):
    """There is no closest match. OD-28 forbids an implicit selection."""
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    response = api.get(f"{BASE}/{reference}/preview", params={"action": "link_existing"})
    assert response.status_code == 422
    assert "customer_public_id" in response.text


def test_a_merged_customer_is_named_but_never_silently_retargeted(
    account_client, account_db, account_users, captured_mail
):
    """The alias chain is read to *tell* the reviewer, not to choose for them."""
    from app.services import customer_service

    source = make_customer(account_db, full_name="Old Record", email="old@demo.example.com")
    target = make_customer(account_db, full_name="New Record", email="new@demo.example.com")
    old_reference = source.public_id
    customer_service.merge_customers(account_db, source=source, target=target)
    account_db.commit()

    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    response = preview(api, reference, "link_existing", old_reference)
    assert response.status_code == 409
    assert target.public_id in response.text


def test_an_archived_customer_cannot_be_linked(
    account_client, account_db, account_users, captured_mail
):
    customer = make_customer(account_db, full_name="Archived", email="arch@demo.example.com")
    customer.is_archived = True
    account_db.commit()

    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    assert preview(api, reference, "link_existing", customer.public_id).status_code == 409


# --- Acknowledgement ----------------------------------------------------------


def test_approval_without_an_acknowledgement_is_refused(
    account_client, account_users, captured_mail
):
    """AC-CA-4.2. The fingerprint is right; nobody has agreed to it."""
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)

    fingerprint = preview(api, reference, "create_new").json()["fingerprint"]
    response = approve_create(api, reference, fingerprint)
    assert response.status_code == 409
    assert "acknowledge" in response.text.lower()


def test_acknowledging_a_stale_fingerprint_is_refused(
    account_client, account_db, account_users, captured_mail
):
    """Acknowledging a preview that has already gone stale is not a pre-authorization."""
    customer = make_customer(account_db, full_name="Target", email="target@demo.example.com")
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)

    stale = preview(api, reference, "link_existing", customer.public_id).json()["fingerprint"]
    add_shipment(account_db, customer, days_ago=1)

    response = acknowledge(
        api,
        reference,
        {
            "action": "link_existing",
            "customer_public_id": customer.public_id,
            "fingerprint": stale,
        },
    )
    assert response.status_code == 409


def test_an_acknowledgement_of_one_action_does_not_authorize_the_other(
    account_client, account_db, account_users, captured_mail
):
    """The action is in the fingerprint, so a create acknowledgement matches no link."""
    customer = make_customer(account_db, full_name="Target", email="target@demo.example.com")
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)

    create_fingerprint = acknowledged_preview(api, reference, "create_new")
    response = approve_link(api, reference, customer.public_id, create_fingerprint)
    assert response.status_code == 409


# --- The eight drifts ---------------------------------------------------------


def _linkable(account_db, email="target@demo.example.com"):
    return make_customer(account_db, full_name="Target Customer", email=email)


def test_drift_a_customer_edit(account_client, account_db, account_users, captured_mail):
    customer = _linkable(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)

    customer.city = "Somewhere Else"
    account_db.commit()

    response = approve_link(api, reference, customer.public_id, fingerprint)
    assert response.status_code == 409
    assert account_db.get(CustomerIdentity, 1).status == "pending_approval"


def test_drift_a_customer_merge(account_client, account_db, account_users, captured_mail):
    from app.services import customer_service

    customer = _linkable(account_db)
    survivor = make_customer(account_db, full_name="Survivor", email="surv@demo.example.com")
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)

    customer_service.merge_customers(account_db, source=customer, target=survivor)
    account_db.commit()

    response = approve_link(api, reference, customer.public_id, fingerprint)
    assert response.status_code == 409


def test_drift_a_new_shipment(account_client, account_db, account_users, captured_mail):
    """The disclosure grew after the reviewer agreed to its size. That is the whole point."""
    customer = _linkable(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)

    add_shipment(account_db, customer, days_ago=0)

    response = approve_link(api, reference, customer.public_id, fingerprint)
    assert response.status_code == 409
    assert account_db.query(CustomerIdentityLink).count() == 0


def test_drift_a_cancellation(account_client, account_db, account_users, captured_mail):
    """``includes_cancelled`` flipped, so the sentence the reviewer read is now wrong."""
    customer = _linkable(account_db)
    shipment = add_shipment(account_db, customer, days_ago=5)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)

    shipment.booking_state = BookingState.CANCELLED
    account_db.commit()

    assert approve_link(api, reference, customer.public_id, fingerprint).status_code == 409


def test_drift_a_rebooking(account_client, account_db, account_users, captured_mail):
    customer = _linkable(account_db)
    original = add_shipment(account_db, customer, days_ago=6)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)

    replacement = add_shipment(account_db, customer, days_ago=5, rebooked_from=original.id)
    original.rebooked_to_shipment_id = replacement.id
    account_db.commit()

    assert approve_link(api, reference, customer.public_id, fingerprint).status_code == 409


def test_drift_a_replacement_proposal(account_client, account_db, account_users, captured_mail):
    """The submission the reviewer read has been superseded by a newer one.

    Driven through ``create_registration_proposal`` rather than through a second
    registration, because **no route in this phase can produce one**: a registration for
    an address that already has an identity creates nothing at all (OD-23), which is the
    behaviour that makes the surface enumeration-safe. A replacement therefore arrives
    only from the Phase 12 profile-proposal path or from a re-registration after
    reinstatement, neither of which is built.

    The drift is still tested now, at the service that will produce it, because the
    fingerprint has to cover the proposal *today* -- discovering in Phase 12 that it did
    not would mean an approval applying a submission nobody reviewed.
    """
    from app.core.account_fields import normalize_field
    from app.services import customer_identity_service

    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "create_new")

    identity = account_db.query(CustomerIdentity).filter_by(public_id=reference).one()
    replacement = [
        normalize_field("legal_name", "Somebody Else Entirely", context={}),
        normalize_field("customer_type", "individual", context={}),
    ]
    customer_identity_service.create_registration_proposal(
        account_db, identity, fields=replacement, request_ip=None
    )
    account_db.commit()

    assert approve_create(api, reference, fingerprint).status_code == 409


def test_drift_another_staff_member_decided_first(account_client, account_users, captured_mail):
    """Approve and reject cannot both win, and the loser is told rather than ignored."""
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "create_new")

    admin = staff(account_client, account_users[Role.ADMIN].email)
    assert reject(admin, reference).status_code == 200

    operations = _operations(account_client, account_users)
    response = approve_create(operations, reference, fingerprint)
    assert response.status_code == 409


def test_drift_another_identity_was_linked_to_the_customer(
    account_client, account_db, account_users, captured_mail
):
    """One active identity per customer (OD-25), and the second reviewer is told."""
    customer = _linkable(account_db)
    first = pending_identity(account_client, captured_mail, "first@demo.example.com")
    second = pending_identity(account_client, captured_mail, "second@demo.example.com")
    api = _operations(account_client, account_users)

    second_fingerprint = acknowledged_preview(api, second, "link_existing", customer.public_id)

    first_fingerprint = acknowledged_preview(api, first, "link_existing", customer.public_id)
    assert approve_link(api, first, customer.public_id, first_fingerprint).status_code == 200

    response = approve_link(api, second, customer.public_id, second_fingerprint)
    assert response.status_code == 409
    assert account_db.query(CustomerIdentityLink).filter_by(status="active").count() == 1


def test_a_refused_stale_approval_leaves_everything_alone(
    account_client, account_db, account_users, captured_mail
):
    """A conflict is not a partial write. Nothing moved, in any table."""
    customer = _linkable(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)

    customers_before = account_db.query(Customer).count()
    add_shipment(account_db, customer, days_ago=0)

    assert approve_link(api, reference, customer.public_id, fingerprint).status_code == 409

    account_db.expire_all()
    assert account_db.query(Customer).count() == customers_before
    assert account_db.query(CustomerIdentityLink).count() == 0
    identity = account_db.query(CustomerIdentity).one()
    assert identity.status == "pending_approval"
    assert identity.approved_at is None


def test_a_fresh_preview_after_drift_can_be_approved(
    account_client, account_db, account_users, captured_mail
):
    """The refusal is a redirection, not a dead end: read it again, agree again, approve."""
    customer = _linkable(account_db)
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = _operations(account_client, account_users)
    stale = acknowledged_preview(api, reference, "link_existing", customer.public_id)

    add_shipment(account_db, customer, days_ago=0)
    assert approve_link(api, reference, customer.public_id, stale).status_code == 409

    fresh = acknowledged_preview(api, reference, "link_existing", customer.public_id)
    assert fresh != stale
    assert approve_link(api, reference, customer.public_id, fresh).status_code == 200
