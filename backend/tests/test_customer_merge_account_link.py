"""OD-40: a customer merge is refused while either side holds a Customer Account link.

Three groups of assertion, and they are different claims.

**The gate.** A linked source, a linked target, or both, refuse the whole merge with a
stable conflict code. An unlinked pair merges exactly as it always did -- which is the
assertion that keeps this from being a change that quietly broke merging.

**Completeness of the refusal.** Every table a merge touches is counted and compared
before and after. "Refused" has to mean nothing happened, not that the visible part of it
did not happen, and the only way to say that is to look at all of them.

**The definition of an effective link**, case by case, from
`app.services.customer_account_link_policy`. Each of the six states the owner asked about
is built directly and asserted, because the interesting ones -- suspended, deactivated,
revoked -- are states no route in this phase can reach.

Every link row here is built by hand rather than through an approval, except where the
approval is what is being tested. That is deliberate: a suspended identity with a retained
link is not a state Phase 10 has a route to, and a test that could only build the states
the happy path produces would not be testing the definition.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.account_enums import IdentityStatus, LinkRole, LinkStatus
from app.core.time_utils import utcnow
from app.models import (
    AuditEvent,
    ConsentEvent,
    Customer,
    CustomerAddress,
    CustomerIdAlias,
    CustomerIdentity,
    CustomerIdentityLink,
    CustomerRouteInterest,
    CustomerTag,
    FollowUpTask,
    Interaction,
    Referral,
    ServiceIssue,
    Shipment,
)
from app.services import customer_account_link_policy as link_policy
from app.services import customer_service
from app.services.errors import ConflictError
from tests.conftest import add_shipment, make_customer

#: Every table a merge writes, plus the ones it must be shown not to write. Counted whole
#: rather than sampled, because "the merge was refused" is a claim about all of them.
AFFECTED_MODELS = (
    Customer,
    Shipment,
    FollowUpTask,
    Interaction,
    ConsentEvent,
    ServiceIssue,
    CustomerAddress,
    Referral,
    CustomerTag,
    CustomerRouteInterest,
    CustomerIdAlias,
    CustomerIdentity,
    CustomerIdentityLink,
)


def _identity(db, email: str, *, status: str = IdentityStatus.ACTIVE.value) -> CustomerIdentity:
    """An identity row, built directly. No route in Phase 10 reaches most of these states."""
    identity = CustomerIdentity(
        public_id=f"CA-{abs(hash(email)) % 1000000:06d}",
        email_entered=email,
        email_normalized=email,
        password_hash="unused-in-this-suite",
        status=status,
        email_verified_at=utcnow(),
        approved_at=utcnow() if status == IdentityStatus.ACTIVE.value else None,
    )
    db.add(identity)
    db.flush()
    return identity


def _link(db, identity, customer, *, status: str = LinkStatus.ACTIVE.value):
    row = CustomerIdentityLink(
        identity_id=identity.id,
        customer_id=customer.id,
        link_role=LinkRole.OWNER.value,
        status=status,
        linked_at=utcnow(),
        revoked_at=None if status == LinkStatus.ACTIVE.value else utcnow(),
        revoke_reason_code=None if status == LinkStatus.ACTIVE.value else "deactivated",
    )
    db.add(row)
    db.flush()
    return row


def _snapshot(db) -> dict[str, int]:
    return {model.__tablename__: db.query(model).count() for model in AFFECTED_MODELS}


def _customer_rows(db) -> dict[int, tuple]:
    """Every column of every customer, so "unchanged" means unchanged and not uncounted."""
    return {
        customer.id: tuple(getattr(customer, column.name) for column in Customer.__table__.columns)
        for customer in db.query(Customer).all()
    }


def _pair(db, *, linked_source=False, linked_target=False, link_status=LinkStatus.ACTIVE.value):
    source = make_customer(db, full_name="Source", email="source@demo.example.com")
    target = make_customer(db, full_name="Target", email="target@demo.example.com")
    if linked_source:
        _link(db, _identity(db, "source-holder@demo.example.com"), source, status=link_status)
    if linked_target:
        _link(db, _identity(db, "target-holder@demo.example.com"), target, status=link_status)
    db.commit()
    return source, target


# --- The gate -----------------------------------------------------------------


def test_an_unlinked_pair_still_merges(db):
    """The assertion that keeps the guard from being a way of breaking merge."""
    source, target = _pair(db)
    add_shipment(db, source, days_ago=12)
    db.commit()

    customer_service.merge_customers(db, source=source, target=target)
    db.commit()
    db.expire_all()

    assert db.get(Customer, source.id).merged_into_customer_id == target.id
    assert db.query(Shipment).filter_by(customer_id=target.id).count() == 1
    assert (
        db.scalar(select(CustomerIdAlias).where(CustomerIdAlias.customer_id == target.id))
        is not None
    )


@pytest.mark.parametrize(
    ("linked_source", "linked_target", "expected_side"),
    [
        (True, False, link_policy.SIDE_SOURCE),
        (False, True, link_policy.SIDE_TARGET),
        (True, True, link_policy.SIDE_BOTH),
    ],
    ids=["linked-source", "linked-target", "both-linked"],
)
def test_a_linked_side_refuses_the_whole_merge(db, linked_source, linked_target, expected_side):
    source, target = _pair(db, linked_source=linked_source, linked_target=linked_target)

    with pytest.raises(link_policy.LinkedCustomerMergeRefused) as refused:
        customer_service.merge_customers(db, source=source, target=target)

    assert refused.value.status_code == 409
    assert refused.value.detail["code"] == link_policy.CONFLICT_CODE
    assert refused.value.detail["blocked_side"] == expected_side


def test_the_refusal_changes_nothing_in_any_affected_table(db):
    """ "Refused" means every table, not the visible ones."""
    source, target = _pair(db, linked_source=True)
    add_shipment(db, source, days_ago=9)
    db.add(FollowUpTask(customer_id=source.id, subject="Open", status="scheduled", due_at=None))
    db.commit()

    before_counts = _snapshot(db)
    before_rows = _customer_rows(db)

    with pytest.raises(link_policy.LinkedCustomerMergeRefused):
        customer_service.merge_customers(db, source=source, target=target)
    db.rollback()
    db.expire_all()

    assert _snapshot(db) == before_counts
    assert _customer_rows(db) == before_rows
    assert db.query(Shipment).filter_by(customer_id=source.id).count() == 1
    assert db.query(FollowUpTask).filter_by(customer_id=source.id).count() == 1


def test_the_route_refuses_with_the_conflict_code_and_writes_only_the_refusal_audit(as_admin, db):
    """Through HTTP, which is where the audit row's survival is decided.

    The service writes the refusal audit into the caller's transaction and the route
    commits it. That is the one audit row a refused merge leaves; in particular there is no
    ``customer.merge`` row, because no merge happened.
    """
    source, target = _pair(db, linked_target=True)
    before = _snapshot(db)

    response = as_admin.post(
        "/api/v1/customers/merge",
        json={
            "source_customer_id": source.id,
            "target_customer_id": target.id,
            "confirmation": source.public_id,
        },
    )
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["detail"]["code"] == link_policy.CONFLICT_CODE
    assert body["detail"]["blocked_side"] == link_policy.SIDE_TARGET

    # End this session's own read transaction before looking. Since DEC-0108 a session
    # holds its snapshot from its first statement, so a test that only expired its ORM
    # objects would re-read the same snapshot and never see the route's commit.
    db.rollback()
    db.expire_all()
    assert _snapshot(db) == before

    actions = [row.action for row in db.query(AuditEvent).all()]
    assert "customer.merge" not in actions
    assert actions.count("customer_account.merge_refused_linked_customer") == 1


def test_the_refusal_message_names_no_account_and_no_history(as_admin, db):
    """A merge refusal discloses nothing about the account that caused it.

    The identity's reference, its address and any shipment figure are all absent from the
    body. The reviewer is told a link exists and which side; that is the whole disclosure.
    """
    source, target = _pair(db, linked_source=True)
    identity = db.query(CustomerIdentity).one()

    response = as_admin.post(
        "/api/v1/customers/merge",
        json={
            "source_customer_id": source.id,
            "target_customer_id": target.id,
            "confirmation": source.public_id,
        },
    )
    assert response.status_code == 409
    serialized = response.text
    assert identity.public_id not in serialized
    assert identity.email_normalized not in serialized
    assert "password" not in serialized.lower()
    assert "session" not in serialized.lower()
    assert "shipment" not in serialized.lower()


# --- The definition of an effective link ---------------------------------------


def test_an_active_identity_with_an_active_link_blocks(db):
    source, target = _pair(db, linked_source=True)
    assert link_policy.has_effective_link(db, source.id) is True
    assert link_policy.has_effective_link(db, target.id) is False


def test_a_suspended_identity_keeping_its_link_still_blocks(db):
    """Suspension pauses access and keeps the link; reinstatement gives it straight back."""
    source = make_customer(db, full_name="Source", email="source@demo.example.com")
    target = make_customer(db, full_name="Target", email="target@demo.example.com")
    identity = _identity(db, "suspended@demo.example.com", status=IdentityStatus.SUSPENDED.value)
    identity.approved_at = utcnow()
    _link(db, identity, source)
    db.commit()

    assert link_policy.has_effective_link(db, source.id) is True
    with pytest.raises(link_policy.LinkedCustomerMergeRefused):
        customer_service.merge_customers(db, source=source, target=target)


def test_a_deactivated_identity_keeps_its_link_and_does_not_block(db):
    """Owner decision, 2026-10-15: deactivation keeps the link, and it no longer blocks.

    The row is still ``active`` and still counts as an effective link; only the merge
    question excludes it. After the merge the row is exactly as it was.
    """
    source = make_customer(db, full_name="Source", email="source@demo.example.com")
    target = make_customer(db, full_name="Target", email="target@demo.example.com")
    identity = _identity(db, "gone@demo.example.com", status=IdentityStatus.DEACTIVATED.value)
    _link(db, identity, source)
    db.commit()

    assert link_policy.has_effective_link(db, source.id) is True
    assert link_policy.has_merge_blocking_link(db, source.id) is False
    customer_service.merge_customers(db, source=source, target=target)
    db.commit()
    db.expire_all()

    assert db.get(Customer, source.id).merged_into_customer_id == target.id
    link = db.query(CustomerIdentityLink).one()
    assert link.status == LinkStatus.ACTIVE.value
    assert link.customer_id == source.id


def test_a_revoked_link_retained_for_audit_does_not_block_and_is_not_deleted(db):
    """History is kept and does not stand in the way. Both halves matter."""
    source, target = _pair(db, linked_source=True, link_status=LinkStatus.REVOKED.value)
    rows_before = db.query(CustomerIdentityLink).count()

    assert link_policy.has_effective_link(db, source.id) is False
    customer_service.merge_customers(db, source=source, target=target)
    db.commit()
    db.expire_all()

    assert db.get(Customer, source.id).merged_into_customer_id == target.id
    assert db.query(CustomerIdentityLink).count() == rows_before
    assert db.query(CustomerIdentityLink).one().status == LinkStatus.REVOKED.value


def test_a_rejected_identity_with_no_link_does_not_block(db):
    source = make_customer(db, full_name="Source", email="source@demo.example.com")
    target = make_customer(db, full_name="Target", email="target@demo.example.com")
    _identity(db, "declined@demo.example.com", status=IdentityStatus.REJECTED.value)
    db.commit()

    assert link_policy.has_effective_link(db, source.id) is False
    customer_service.merge_customers(db, source=source, target=target)
    db.commit()
    db.expire_all()
    assert db.get(Customer, source.id).merged_into_customer_id == target.id


def test_a_pending_identity_with_no_link_does_not_block(db):
    source = make_customer(db, full_name="Source", email="source@demo.example.com")
    target = make_customer(db, full_name="Target", email="target@demo.example.com")
    _identity(db, "waiting@demo.example.com", status=IdentityStatus.PENDING_APPROVAL.value)
    db.commit()

    customer_service.merge_customers(db, source=source, target=target)
    db.commit()
    db.expire_all()
    assert db.get(Customer, source.id).merged_into_customer_id == target.id


def test_an_impossible_active_link_on_a_rejected_identity_still_blocks(db):
    """The guard reads the link table, so a state nothing can produce fails closed."""
    source = make_customer(db, full_name="Source", email="source@demo.example.com")
    target = make_customer(db, full_name="Target", email="target@demo.example.com")
    identity = _identity(db, "impossible@demo.example.com", status=IdentityStatus.REJECTED.value)
    _link(db, identity, source)
    db.commit()

    with pytest.raises(link_policy.LinkedCustomerMergeRefused):
        customer_service.merge_customers(db, source=source, target=target)


def test_the_effective_statuses_are_exactly_the_active_one(db):
    """The set is asserted, not just its behaviour, so widening it is a visible change."""
    assert set(link_policy.EFFECTIVE_LINK_STATUSES) == {LinkStatus.ACTIVE.value}
    assert len(link_policy.EFFECTIVE_LINK_STATUSES) == 1


# --- Tombstones cannot receive links -------------------------------------------


def test_a_tombstoned_customer_cannot_be_named_as_a_link_target(db):
    """The other direction of the same invariant, at the approval service's own guard."""
    from app.services import customer_account_review_service as review

    source, target = _pair(db)
    customer_service.merge_customers(db, source=source, target=target)
    db.commit()
    db.expire_all()

    with pytest.raises(ConflictError) as refused:
        review.resolve_link_target(db, source.public_id)
    assert "merged" in str(refused.value).lower()


def test_an_archived_customer_cannot_be_named_as_a_link_target(db):
    from app.services import customer_account_review_service as review

    customer = make_customer(db, full_name="Retired", email="retired@demo.example.com")
    customer.is_archived = True
    db.commit()

    with pytest.raises(ConflictError):
        review.resolve_link_target(db, customer.public_id)


# --- The guard lives in the service --------------------------------------------


def test_the_guard_is_in_the_service_not_only_in_the_route(db):
    """Called directly, with no route and no HTTP, and it still refuses.

    The route's only job is to persist the refusal audit. A caller that bypasses it -- a
    script, an import, a future bulk tool -- gets the same answer.
    """
    source, target = _pair(db, linked_source=True)
    with pytest.raises(link_policy.LinkedCustomerMergeRefused):
        customer_service.merge_customers(db, source=source, target=target)
