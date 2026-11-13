"""RC-UAT-22 (B-13, DEC-0234 draft): staff re-link or close of an orphaned Customer Account.

Driven through the real routes on the account test database. The orphan is made the way
production makes one: an applicant registers, Operations approve (creating and linking the
customer), an Admin deactivates the account, the customer is merged away (or archived), and
an Admin reinstates it -- which ends the link and leaves it ``pending_approval`` with no
proposal (RC-UAT-21, review HIGH 2).

1. Eligibility is a state, not a history: approved, pending_approval, no live link, no
   pending proposal. A fresh application, an active account and an account with a pending
   proposal are not orphans.
2. The list: Admin only, audited, the last link and why it ended, the merge survivor as the
   suggestion.
3. Re-link: preview (history figures, email change, fingerprint) then link -- status active,
   exactly one link, the single email rule, audit, a row, a notice.
4. Re-link refusals: no acknowledgement, a stale preview, a merged or archived or linked
   target, an unknown one, an account that is not orphaned, a role that is not Admin.
5. Close: deactivated ``orphan_closed``, sessions end, row and audit, no email; reversible by
   the ordinary reinstatement, which brings it back to the list.
6. The approval path is untouched.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.core.account_enums import ProposalKind, ProposalStatus
from app.core.config import settings
from app.core.enums import Role
from app.core.time_utils import utcnow
from app.main import app
from app.models import (
    AuditEvent,
    Customer,
    CustomerAccountRelink,
    CustomerDataProposal,
    CustomerIdentity,
    CustomerIdentityLink,
)
from app.services import account_email_service as email
from app.services import customer_account_relink_service as relink_service
from app.services import customer_service
from tests.account_fixtures import ACCOUNT_PASSWORD
from tests.approval_fixtures import (
    acknowledged_preview,
    approve_create,
    approve_link,
    pending_identity,
    staff,
)
from tests.conftest import make_customer, see_committed_changes

ACCOUNT = "/api/v1/account"
REVIEW = "/api/v1/customer-account"
ORPHANS = f"{REVIEW}/identities-orphaned"
APPLICANT = "hanh@demo.example.com"
SURVIVOR_EMAIL = "survivor.record@demo.example.com"


# --- Helpers ----------------------------------------------------------------------------------


def _sign_in(address: str = APPLICANT) -> TestClient:
    client = TestClient(app)
    response = client.post(
        f"{ACCOUNT}/sign-in", json={"email": address, "password": ACCOUNT_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return client


def _identity(db, address: str = APPLICANT) -> CustomerIdentity:
    see_committed_changes(db)
    return db.query(CustomerIdentity).filter_by(email_normalized=address).one()


def _audits(db, action: str) -> list[AuditEvent]:
    see_committed_changes(db)
    return db.query(AuditEvent).filter_by(action=action).order_by(AuditEvent.id).all()


def _live_links(db, identity_id: int) -> list[CustomerIdentityLink]:
    see_committed_changes(db)
    return db.query(CustomerIdentityLink).filter_by(identity_id=identity_id, status="active").all()


def _activate(client, users, mail, address: str = APPLICANT) -> str:
    reference = pending_identity(client, mail, address)
    ops = staff(client, users[Role.OPERATIONS].email)
    fingerprint = acknowledged_preview(ops, reference, "create_new")
    assert approve_create(ops, reference, fingerprint).status_code == 200
    client.cookies.clear()
    return reference


def _orphan(client, db, users, mail, *, how: str = "merged", address: str = APPLICANT):
    """Approve, deactivate, merge (or archive) the customer, reinstate: an orphan."""
    reference = _activate(client, users, mail, address)
    admin = staff(client, users[Role.ADMIN].email)
    assert (
        admin.post(
            f"{REVIEW}/identities/{reference}/deactivate", json={"reason_code": "customer_request"}
        ).status_code
        == 200
    )
    see_committed_changes(db)
    owner = db.query(Customer).filter_by(email_normalized=address).one()
    survivor = None
    if how == "merged":
        survivor = make_customer(db, full_name="Survivor Record", email=SURVIVOR_EMAIL)
        customer_service.merge_customers(db, source=owner, target=survivor)
    else:
        owner.is_archived = True
    db.commit()
    response = admin.post(
        f"{REVIEW}/identities/{reference}/reactivate", json={"reason_code": "customer_request"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending_approval"
    return {"reference": reference, "owner": owner, "survivor": survivor, "admin": admin}


def _preview(admin, reference: str, customer: str):
    return admin.get(
        f"{REVIEW}/identities/{reference}/relink-preview", params={"customer_public_id": customer}
    )


def _relink(admin, reference: str, customer: str, fingerprint: str, **overrides):
    body = {
        "customer_public_id": customer,
        "reason_code": "merge_survivor",
        "note": "Merged into the survivor on 2026-10-24.",
        "history_acknowledged": True,
        "preview_fingerprint": fingerprint,
    }
    body.update(overrides)
    return admin.post(f"{REVIEW}/identities/{reference}/relink", json=body)


def _close(admin, reference: str, **overrides):
    body = {"reason_code": "no_customer", "note": "No record to link."}
    body.update(overrides)
    return admin.post(f"{REVIEW}/identities/{reference}/close-orphan", json=body)


def _sweep(db) -> None:
    """The activation invariant: active has exactly one live link; pending has none."""
    see_committed_changes(db)
    for identity in db.query(CustomerIdentity).all():
        live = len(_live_links(db, identity.id))
        if identity.status == "active":
            assert live == 1, identity.public_id
        elif identity.status in {"pending_approval", "pending_verification", "rejected"}:
            assert live == 0, identity.public_id


@pytest.fixture
def orphan(account_client, account_db, account_users, captured_mail):
    made = _orphan(account_client, account_db, account_users, captured_mail)
    made.update(db=account_db, users=account_users, mail=captured_mail, client=account_client)
    return made


# === 1. Eligibility =============================================================================


def test_an_orphan_is_defined_by_state(orphan):
    db, client, users, mail = orphan["db"], orphan["client"], orphan["users"], orphan["mail"]
    identity = _identity(db)
    assert relink_service.is_orphaned(db, identity)

    # A fresh application (never approved) and an active account are not orphans.
    pending_identity(client, mail, "fresh@demo.example.com")
    _activate(client, users, mail, "active@demo.example.com")
    see_committed_changes(db)
    assert not relink_service.is_orphaned(db, _identity(db, "fresh@demo.example.com"))
    assert not relink_service.is_orphaned(db, _identity(db, "active@demo.example.com"))

    # A pending proposal makes it the approval queue's to decide, whatever its history.
    proposal = CustomerDataProposal(
        identity_id=identity.id,
        customer_id=None,
        kind=ProposalKind.REGISTRATION.value,
        status=ProposalStatus.PENDING.value,
        submitted_at=utcnow(),
    )
    db.add(proposal)
    db.commit()
    assert not relink_service.is_orphaned(db, _identity(db))
    db.delete(proposal)
    db.commit()
    assert relink_service.is_orphaned(db, _identity(db))


def test_an_archived_customer_also_leaves_an_orphan(
    account_client, account_db, account_users, captured_mail
):
    made = _orphan(account_client, account_db, account_users, captured_mail, how="archived")
    items = made["admin"].get(ORPHANS).json()["items"]
    assert [i["account_reference"] for i in items] == [made["reference"]]
    assert items[0]["last_link_end_reason"] == "archived_since_deactivation"
    # An archived customer suggests nothing: there is no record to send the Admin to.
    assert items[0]["suggested_customer_public_id"] is None


# === 2. The list ================================================================================


def test_the_list_names_the_last_link_and_suggests_the_survivor(orphan):
    db, admin, users, client = orphan["db"], orphan["admin"], orphan["users"], orphan["client"]
    response = admin.get(ORPHANS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["relink_reason_codes"] == ["merge_survivor", "correct_customer", "other"]
    assert body["close_reason_codes"] == ["no_customer", "duplicate", "other"]
    [row] = body["items"]
    assert row["account_reference"] == orphan["reference"]
    assert row["account_email_entered"] == APPLICANT
    assert row["approved_at"] is not None
    assert row["last_customer_public_id"] == orphan["owner"].public_id
    assert row["last_link_end_reason"] == "merged_since_deactivation"
    assert row["last_customer_merged"] is True and row["last_link_ended_at"] is not None
    assert row["suggested_customer_public_id"] == orphan["survivor"].public_id
    assert len(_audits(db, "customer_account.orphaned_list_read")) == 1

    for role in (Role.OPERATIONS, Role.MARKETING, Role.READ_ONLY_MANAGER):
        assert staff(client, users[role].email).get(ORPHANS).status_code == 403, role


# === 3. Re-link =================================================================================


def test_relink_to_the_survivor_activates_with_one_link_and_the_single_email(orphan):
    db, mail, reference = orphan["db"], orphan["mail"], orphan["reference"]
    survivor = orphan["survivor"]
    admin = staff(orphan["client"], orphan["users"][Role.ADMIN].email)
    before = _sign_in()
    assert before.get(f"{ACCOUNT}/shipments").status_code == 403

    preview = _preview(admin, reference, survivor.public_id)
    assert preview.status_code == 200, preview.text
    shown = preview.json()
    assert shown["target_customer_public_id"] == survivor.public_id
    assert shown["email_change"] == {"current": SURVIVOR_EMAIL, "new": APPLICANT}
    assert set(shown["disclosure"]) == {
        "shipment_count",
        "oldest_booked_at",
        "newest_booked_at",
        "includes_cancelled",
        "includes_rebooked",
        "definition_version",
    }
    assert len(_audits(db, "customer_account.relink_previewed")) == 1
    mail.messages.clear()

    response = _relink(admin, reference, survivor.public_id, shown["fingerprint"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "active"
    assert body["linked_customer_public_id"] == survivor.public_id

    identity = _identity(db)
    [link] = _live_links(db, identity.id)
    assert link.customer_id == survivor.id
    assert identity.status_reason_code == "merge_survivor" and identity.approved_at is not None
    db.refresh(survivor)
    assert survivor.email_normalized == APPLICANT  # the single email rule

    row = db.query(CustomerAccountRelink).one()
    assert (row.action, row.reason_code) == ("relink", "merge_survivor")
    assert row.previous_customer_id == orphan["owner"].id
    assert row.previous_link_end_reason == "merged_since_deactivation"
    assert row.target_customer_id == survivor.id and row.note.startswith("Merged into")
    assert row.preview_fingerprint == shown["fingerprint"]
    assert row.disclosed_shipment_count == shown["disclosure"]["shipment_count"]
    assert row.acted_by_user_id == orphan["users"][Role.ADMIN].id

    [event] = _audits(db, "customer_account.relink")
    detail = json.loads(event.detail_json)
    assert detail["customer_public_id"] == survivor.public_id
    assert detail["previous_customer_public_id"] == orphan["owner"].public_id
    assert detail["reason_code"] == "merge_survivor" and detail["status"] == "active"
    assert "Merged into" not in event.detail_json  # the note stays on the row
    assert event.actor_user_id == orphan["users"][Role.ADMIN].id
    assert _audits(db, "customer_account.sign_in_email_applied")
    assert json.loads(_audits(db, "customer_account.link")[-1].detail_json)[
        "customer_public_id"
    ] == (survivor.public_id)

    notices = [m for m in mail.messages if m["template_key"] == email.TEMPLATE_ACCOUNT_APPROVED]
    assert len(notices) == 1 and notices[0]["to_email"] == APPLICANT
    # The account now reaches its (new) customer's shipments, and is off the list.
    assert _sign_in().get(f"{ACCOUNT}/shipments").status_code == 200
    assert admin.get(ORPHANS).json()["items"] == []
    _sweep(db)


def test_relink_to_the_same_customer_after_an_incoming_merge(
    account_client, account_db, account_users, captured_mail
):
    """The other merge direction: the customer absorbed another record. It is suggested
    as it stands, and its own email already agrees, so nothing about the email moves."""
    reference = _activate(account_client, account_users, captured_mail)
    admin = staff(account_client, account_users[Role.ADMIN].email)
    admin.post(f"{REVIEW}/identities/{reference}/deactivate", json={"reason_code": "abuse_or_test"})
    see_committed_changes(account_db)
    owner = account_db.query(Customer).filter_by(email_normalized=APPLICANT).one()
    other = make_customer(account_db, email="absorbed@demo.example.com")
    customer_service.merge_customers(account_db, source=other, target=owner)
    account_db.commit()
    admin.post(
        f"{REVIEW}/identities/{reference}/reactivate", json={"reason_code": "review_complete"}
    )

    [row] = admin.get(ORPHANS).json()["items"]
    assert row["suggested_customer_public_id"] == owner.public_id
    shown = _preview(admin, reference, owner.public_id).json()
    assert shown["email_change"] is None
    response = _relink(
        admin, reference, owner.public_id, shown["fingerprint"], reason_code="correct_customer"
    )
    assert response.status_code == 200 and response.json()["status"] == "active"
    assert not _audits(account_db, "customer_account.sign_in_email_applied")
    _sweep(account_db)


# === 4. Re-link refusals =========================================================================


def _unchanged(db, reference: str) -> None:
    identity = _identity(db)
    assert identity.public_id == reference and identity.status == "pending_approval"
    assert _live_links(db, identity.id) == []
    assert db.query(CustomerAccountRelink).count() == 0
    assert not _audits(db, "customer_account.relink")


def test_relink_needs_the_acknowledgement_a_listed_reason_and_a_current_preview(orphan):
    db, admin, reference = orphan["db"], orphan["admin"], orphan["reference"]
    survivor = orphan["survivor"].public_id
    fingerprint = _preview(admin, reference, survivor).json()["fingerprint"]

    refused = _relink(admin, reference, survivor, fingerprint, history_acknowledged=False)
    assert refused.status_code == 422
    refused = _relink(admin, reference, survivor, fingerprint, reason_code="because")
    assert refused.status_code == 422
    refused = _relink(admin, reference, survivor, fingerprint, note="x" * 501)
    assert refused.status_code == 422
    refused = _relink(admin, reference, survivor, "0" * 64)
    assert refused.status_code == 409 and "preview" in refused.text

    # The world moves under the preview: the survivor is edited, so the fingerprint is stale.
    see_committed_changes(db)
    record = db.query(Customer).filter_by(public_id=survivor).one()
    customer_service.update_customer(db, record, {"city": "Toronto"})
    db.commit()
    stale = _relink(admin, reference, survivor, fingerprint)
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "preview_stale"
    _unchanged(db, reference)


def test_relink_refuses_a_merged_archived_linked_or_unknown_target(orphan):
    db, admin, reference = orphan["db"], orphan["admin"], orphan["reference"]
    client, users, mail = orphan["client"], orphan["users"], orphan["mail"]

    # The merged tombstone: refused, and the survivor is named instead.
    merged = _preview(admin, reference, orphan["owner"].public_id)
    assert merged.status_code == 409 and orphan["survivor"].public_id in merged.text
    assert _relink(admin, reference, orphan["owner"].public_id, "0" * 64).status_code == 409

    archived = make_customer(db, full_name="Archived Record", email="archived@demo.example.com")
    archived.is_archived = True
    db.commit()
    assert _preview(admin, reference, archived.public_id).status_code == 409

    # A customer another live account holds.
    _activate(client, users, mail, "holder@demo.example.com")
    see_committed_changes(db)
    held = db.query(Customer).filter_by(email_normalized="holder@demo.example.com").one()
    admin = staff(client, users[Role.ADMIN].email)
    assert _preview(admin, reference, held.public_id).status_code == 409
    assert _relink(admin, reference, held.public_id, "0" * 64).status_code == 409

    assert _preview(admin, reference, "C-DOESNOTEXIST").status_code == 404
    _unchanged(db, reference)


def test_relink_and_close_refuse_an_account_that_is_not_orphaned(
    account_client, account_db, account_users, captured_mail
):
    active = _activate(account_client, account_users, captured_mail)
    waiting = pending_identity(account_client, captured_mail, "waiting@demo.example.com")
    target = make_customer(account_db, email="free@demo.example.com")
    admin = staff(account_client, account_users[Role.ADMIN].email)
    for reference in (active, waiting):
        assert _preview(admin, reference, target.public_id).status_code == 409
        assert _relink(admin, reference, target.public_id, "0" * 64).status_code == 409
        assert _close(admin, reference).status_code == 409
    see_committed_changes(account_db)
    assert account_db.query(CustomerAccountRelink).count() == 0
    assert _identity(account_db).status == "active"


def test_only_admin_may_relink_or_close(orphan):
    db, client, users, reference = (
        orphan["db"],
        orphan["client"],
        orphan["users"],
        orphan["reference"],
    )
    survivor = orphan["survivor"].public_id
    for role in (Role.OPERATIONS, Role.MARKETING, Role.READ_ONLY_MANAGER):
        caller = staff(client, users[role].email)
        assert _preview(caller, reference, survivor).status_code == 403, role
        assert _relink(caller, reference, survivor, "0" * 64).status_code == 403, role
        assert _close(caller, reference).status_code == 403, role
    _unchanged(db, reference)
    assert _identity(db).deactivated_at is None


# === 5. Close ====================================================================================


def test_close_deactivates_records_and_sends_nothing(orphan):
    db, mail, reference = orphan["db"], orphan["mail"], orphan["reference"]
    admin = staff(orphan["client"], orphan["users"][Role.ADMIN].email)
    session = _sign_in()
    mail.messages.clear()

    assert _close(admin, reference, reason_code="nonsense").status_code == 422
    response = _close(admin, reference, reason_code="duplicate")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "deactivated" and body["status_reason_code"] == "orphan_closed"
    assert body["can_reactivate"] is True

    assert session.get(f"{ACCOUNT}/me").status_code == 401  # sessions ended
    assert mail.messages == []  # no email to the customer (stand-in B-19)
    see_committed_changes(db)
    row = db.query(CustomerAccountRelink).one()
    assert (row.action, row.reason_code, row.target_customer_id) == ("close", "duplicate", None)
    assert row.previous_customer_id == orphan["owner"].id
    [event] = _audits(db, "customer_account.orphan_closed")
    assert json.loads(event.detail_json)["reason_code"] == "duplicate"
    assert "No record" not in event.detail_json
    deactivations = _audits(db, "customer_account.deactivate")
    assert json.loads(deactivations[-1].detail_json)["reason_code"] == "orphan_closed"
    assert admin.get(ORPHANS).json()["items"] == []

    # Reversible (stand-in B-20): reinstatement brings it back to the list, still linkless.
    again = admin.post(
        f"{REVIEW}/identities/{reference}/reactivate", json={"reason_code": "deactivated_in_error"}
    )
    assert again.status_code == 200 and again.json()["status"] == "pending_approval"
    assert [i["account_reference"] for i in admin.get(ORPHANS).json()["items"]] == [reference]
    _sweep(db)


# === 6. The approval path is untouched ===========================================================


def test_the_approval_queue_still_approves_and_ignores_orphans(orphan):
    db, client, users, mail = orphan["db"], orphan["client"], orphan["users"], orphan["mail"]
    applicant = pending_identity(client, mail, "newcomer@demo.example.com")
    target = make_customer(db, email="newcomer.record@demo.example.com")
    ops = staff(client, users[Role.OPERATIONS].email)

    queue = ops.get(f"{REVIEW}/registrations").json()["items"]
    assert [row["account_reference"] for row in queue] == [applicant]  # the orphan is not there
    fingerprint = acknowledged_preview(ops, applicant, "link_existing", target.public_id)
    approved = approve_link(ops, applicant, target.public_id, fingerprint)
    assert approved.status_code == 200 and approved.json()["status"] == "active"
    # The orphan's registration route still says what it always said.
    assert ops.get(f"{REVIEW}/registrations/{orphan['reference']}").status_code == 409
    see_committed_changes(db)
    assert db.query(CustomerAccountRelink).count() == 0
    _sweep(db)


def test_the_csrf_header_is_required(orphan):
    admin = orphan["admin"]
    bare = admin.client.post(
        f"{REVIEW}/identities/{orphan['reference']}/close-orphan",
        json={"reason_code": "no_customer"},
    )
    assert bare.status_code == 403
    assert settings.csrf_header_name  # the header the staff client sends
