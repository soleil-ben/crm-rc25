"""Two reviewers, two sessions, two connections, one outcome.

Every test here uses **separate SQLAlchemy sessions on separate connections** against the
same database file, and drives the services directly rather than through the HTTP client.
That is deliberate: a `TestClient` request is synchronous and its dependency override
hands out one session at a time, so a test that raced two HTTP calls would be racing
nothing. Two sessions holding two transactions against one SQLite file is the real thing.

The guards being exercised are the three named in
`customer_account_approval_service`'s docstring, and each test is written so that exactly
one of them decides:

* the **idempotency claim**, a unique index on ``idempotency_key_digest``;
* the **conditional status update**, whose affected-row count is checked;
* the two **partial unique indexes** on ``customer_identity_links``.

None of them is a lock, because SQLite has no ``SELECT ... FOR UPDATE`` worth using. Each
is a write that either lands or does not, which is the only kind of guard that works when
two processes are involved.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from app.core.enums import Role
from app.models import (
    Customer,
    CustomerAccountApprovalAttempt,
    CustomerIdentity,
    CustomerIdentityLink,
    User,
)
from app.services import customer_account_approval_service as approval
from app.services import customer_account_review_service as review
from app.services.errors import ConflictError
from tests.approval_fixtures import key, make_customer, pending_identity, staff

APPLICANT = "hanh@demo.example.com"


@pytest.fixture
def second_session(account_engine):
    """A second session on its own connection. The whole point of this module."""
    factory = sessionmaker(
        bind=account_engine, autoflush=False, expire_on_commit=False, future=True
    )
    session = factory()
    yield session
    session.close()


def _prepare(account_client, account_db, account_users, captured_mail, *, target=None):
    """Get one identity to ``pending_approval`` with an acknowledged preview.

    Returns the identity, the actor and the fingerprint, all read back through a session
    the racing sessions do not share.
    """
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    from tests.approval_fixtures import acknowledged_preview

    action = "link_existing" if target else "create_new"
    fingerprint = acknowledged_preview(api, reference, action, target.public_id if target else None)
    account_db.expire_all()
    return reference, fingerprint


def _actor(session) -> User:
    return session.query(User).filter_by(role=Role.OPERATIONS).one()


def _identity(session, reference: str) -> CustomerIdentity:
    return session.query(CustomerIdentity).filter_by(public_id=reference).one()


def _run(session, call):
    """Run one racer and report what happened, without letting a failure hide.

    A ``ConflictError`` is the designed refusal. An ``IntegrityError`` is a unique index
    refusing at the last moment, which is also a correct outcome and is what would happen
    if two commits interleaved past every application check. An ``OperationalError``
    carrying "database is locked" is SQLite serializing the writers, which is the third
    legitimate way for the loser to lose.
    """
    try:
        result = call(session)
        session.commit()
        return ("ok", result)
    except ConflictError as exc:
        session.rollback()
        return ("conflict", exc)
    except IntegrityError as exc:
        session.rollback()
        return ("integrity", exc)
    except OperationalError as exc:  # pragma: no cover - timing dependent
        session.rollback()
        if "locked" not in str(exc).lower():
            raise
        return ("locked", exc)


def test_two_reviewers_approving_create_new_produce_one_customer(
    account_client, account_db, account_users, captured_mail, second_session
):
    """Different idempotency keys, so the claim does not decide -- the status update does."""
    reference, fingerprint = _prepare(account_client, account_db, account_users, captured_mail)

    def call(session):
        return approval.approve_create_new(
            session,
            identity=_identity(session, reference),
            actor=_actor(session),
            preview_fingerprint=fingerprint,
            idempotency_key=key(),
            override_reason_code=None,
            ip_address=None,
        )

    first = _run(account_db, call)
    second = _run(second_session, call)

    outcomes = sorted([first[0], second[0]])
    assert outcomes.count("ok") == 1, (first, second)

    account_db.expire_all()
    assert account_db.query(Customer).count() == 1
    assert account_db.query(CustomerIdentityLink).filter_by(status="active").count() == 1
    assert account_db.query(CustomerIdentity).one().status == "active"


def test_the_same_key_from_two_sessions_creates_one_customer(
    account_client, account_db, account_users, captured_mail, second_session
):
    """Here the **claim** decides: one insert wins the unique index, the other replays."""
    reference, fingerprint = _prepare(account_client, account_db, account_users, captured_mail)
    shared = key()

    def call(session):
        return approval.approve_create_new(
            session,
            identity=_identity(session, reference),
            actor=_actor(session),
            preview_fingerprint=fingerprint,
            idempotency_key=shared,
            override_reason_code=None,
            ip_address=None,
        )

    first = _run(account_db, call)
    second = _run(second_session, call)

    assert [first[0], second[0]].count("ok") >= 1
    account_db.expire_all()
    assert account_db.query(Customer).count() == 1
    assert (
        account_db.query(CustomerAccountApprovalAttempt)
        .filter_by(idempotency_key_digest=_digest(shared))
        .count()
        == 1
    )


def _digest(value: str) -> str:
    from app.core.account_security import opaque_digest

    return opaque_digest(value)


def test_two_reviewers_linking_the_same_identity_produce_one_link(
    account_client, account_db, account_users, captured_mail, second_session
):
    customer = make_customer(account_db, email="target@demo.example.com")
    reference, fingerprint = _prepare(
        account_client, account_db, account_users, captured_mail, target=customer
    )

    def call(session):
        return approval.approve_link_existing(
            session,
            identity=_identity(session, reference),
            actor=_actor(session),
            customer_public_id=customer.public_id,
            preview_fingerprint=fingerprint,
            idempotency_key=key(),
            ip_address=None,
        )

    first = _run(account_db, call)
    second = _run(second_session, call)
    assert [first[0], second[0]].count("ok") == 1, (first, second)

    account_db.expire_all()
    assert account_db.query(CustomerIdentityLink).filter_by(status="active").count() == 1


def test_two_identities_linking_the_same_customer_produce_one_link(
    account_client, account_db, account_users, captured_mail, second_session
):
    """OD-25, decided by the partial unique index on ``customer_id``.

    Both reviewers pass every application check -- each looks at a different identity,
    and neither identity is linked -- so the only thing standing between them is the
    index. That is exactly the case an application-level check would lose.
    """
    from tests.approval_fixtures import acknowledged_preview

    customer = make_customer(account_db, email="contested@demo.example.com")
    first_ref = pending_identity(account_client, captured_mail, "one@demo.example.com")
    second_ref = pending_identity(account_client, captured_mail, "two@demo.example.com")
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    first_fp = acknowledged_preview(api, first_ref, "link_existing", customer.public_id)
    second_fp = acknowledged_preview(api, second_ref, "link_existing", customer.public_id)
    account_db.expire_all()

    def call_for(reference, fingerprint):
        def call(session):
            return approval.approve_link_existing(
                session,
                identity=_identity(session, reference),
                actor=_actor(session),
                customer_public_id=customer.public_id,
                preview_fingerprint=fingerprint,
                idempotency_key=key(),
                ip_address=None,
            )

        return call

    first = _run(account_db, call_for(first_ref, first_fp))
    second = _run(second_session, call_for(second_ref, second_fp))
    assert [first[0], second[0]].count("ok") == 1, (first, second)

    account_db.expire_all()
    links = account_db.query(CustomerIdentityLink).filter_by(status="active").all()
    assert len(links) == 1
    actives = account_db.query(CustomerIdentity).filter_by(status="active").count()
    assert actives == 1


def test_approve_and_reject_racing_produce_one_final_outcome(
    account_client, account_db, account_users, captured_mail, second_session
):
    """Both take the same conditional update, so exactly one changes a row."""
    reference, fingerprint = _prepare(account_client, account_db, account_users, captured_mail)

    def approve(session):
        return approval.approve_create_new(
            session,
            identity=_identity(session, reference),
            actor=_actor(session),
            preview_fingerprint=fingerprint,
            idempotency_key=key(),
            override_reason_code=None,
            ip_address=None,
        )

    def decline(session):
        return approval.reject(
            session,
            identity=_identity(session, reference),
            actor=_actor(session),
            reason_code="abuse_or_test",
            idempotency_key=key(),
            internal_detail=None,
            ip_address=None,
        )

    first = _run(account_db, approve)
    second = _run(second_session, decline)
    assert [first[0], second[0]].count("ok") == 1, (first, second)

    account_db.expire_all()
    identity = account_db.query(CustomerIdentity).one()
    assert identity.status in {"active", "rejected"}
    if identity.status == "active":
        assert account_db.query(CustomerIdentityLink).filter_by(status="active").count() == 1
        assert identity.rejected_at is None
    else:
        assert account_db.query(CustomerIdentityLink).count() == 0
        assert account_db.query(Customer).count() == 0
        assert identity.approved_at is None


def test_reject_racing_reject_produces_one_rejection(
    account_client, account_db, account_users, captured_mail, second_session
):
    reference, _fingerprint = _prepare(account_client, account_db, account_users, captured_mail)

    def decline(session):
        return approval.reject(
            session,
            identity=_identity(session, reference),
            actor=_actor(session),
            reason_code="duplicate_application",
            idempotency_key=key(),
            internal_detail=None,
            ip_address=None,
        )

    first = _run(account_db, decline)
    second = _run(second_session, decline)
    assert [first[0], second[0]].count("ok") == 1, (first, second)

    account_db.expire_all()
    assert account_db.query(CustomerIdentity).one().status == "rejected"


def test_a_customer_created_but_whose_link_fails_leaves_no_customer(
    account_client, account_db, account_users, captured_mail, second_session
):
    """The step-ordering claim, made against a race rather than a monkeypatch.

    One session links the contested customer and commits. The other has already built
    its whole approval and only then reaches the index. Its customer, its addresses and
    its consent row go back with it.
    """
    from tests.approval_fixtures import acknowledged_preview

    customer = make_customer(account_db, email="contested@demo.example.com")
    loser_ref = pending_identity(account_client, captured_mail, "loser@demo.example.com")
    winner_ref = pending_identity(account_client, captured_mail, "winner@demo.example.com")
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    loser_fp = acknowledged_preview(api, loser_ref, "link_existing", customer.public_id)
    winner_fp = acknowledged_preview(api, winner_ref, "link_existing", customer.public_id)
    account_db.expire_all()

    customers_before = account_db.query(Customer).count()

    won = _run(
        account_db,
        lambda session: approval.approve_link_existing(
            session,
            identity=_identity(session, winner_ref),
            actor=_actor(session),
            customer_public_id=customer.public_id,
            preview_fingerprint=winner_fp,
            idempotency_key=key(),
            ip_address=None,
        ),
    )
    assert won[0] == "ok"

    lost = _run(
        second_session,
        lambda session: approval.approve_link_existing(
            session,
            identity=_identity(session, loser_ref),
            actor=_actor(session),
            customer_public_id=customer.public_id,
            preview_fingerprint=loser_fp,
            idempotency_key=key(),
            ip_address=None,
        ),
    )
    assert lost[0] in {"conflict", "integrity"}

    account_db.expire_all()
    assert account_db.query(Customer).count() == customers_before
    assert account_db.query(CustomerIdentityLink).filter_by(status="active").count() == 1
    loser = _identity(account_db, loser_ref)
    assert loser.status == "pending_approval"
    assert loser.approved_at is None


def test_the_review_service_never_writes_a_link_or_a_status(
    account_client, account_db, account_users, captured_mail
):
    """Reading the queue, a detail, duplicates and a preview writes no decision at all.

    Audit rows are written -- that is the point of auditing a read -- but no identity
    moves and no link appears. This is what keeps the code a reviewer's browsing hits
    unable to decide anything.
    """
    reference = pending_identity(account_client, captured_mail, APPLICANT)
    customer = make_customer(account_db, email="target@demo.example.com")
    api = staff(account_client, account_users[Role.OPERATIONS].email)

    base = "/api/v1/customer-account/registrations"
    api.get(base)
    api.get(f"{base}/{reference}")
    api.get(f"{base}/{reference}/duplicate-candidates")
    api.get(
        f"{base}/{reference}/preview",
        params={"action": "link_existing", "customer_public_id": customer.public_id},
    )

    account_db.expire_all()
    assert account_db.query(CustomerIdentityLink).count() == 0
    assert account_db.query(CustomerIdentity).one().status == "pending_approval"
    assert review.active_link_for_identity(account_db, 1) is None


def test_two_uncommitted_transactions_still_resolve_to_one_link(
    account_client, account_db, account_users, captured_mail, second_session
):
    """A genuine interleave: both sessions do all their work before **either** commits.

    Every other test here runs one decision to completion and then the next, which
    exercises the guards but lets the first commit be visible to the second. This one
    does not: both transactions are open at once, both have inserted a link row for the
    same customer, and only then does either try to commit.

    On SQLite the second writer meets either the unique index or the write lock. Both are
    legitimate refusals and both are accepted here, because which one fires is a property
    of the engine's locking and not of this application -- what the application promises
    is that **one** of them lands, and that is what is asserted.
    """
    from tests.approval_fixtures import acknowledged_preview

    customer = make_customer(account_db, email="interleaved@demo.example.com")
    first_ref = pending_identity(account_client, captured_mail, "i1@demo.example.com")
    second_ref = pending_identity(account_client, captured_mail, "i2@demo.example.com")
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    first_fp = acknowledged_preview(api, first_ref, "link_existing", customer.public_id)
    second_fp = acknowledged_preview(api, second_ref, "link_existing", customer.public_id)
    account_db.commit()
    account_db.expire_all()

    def build(session, reference, fingerprint):
        return approval.approve_link_existing(
            session,
            identity=_identity(session, reference),
            actor=_actor(session),
            customer_public_id=customer.public_id,
            preview_fingerprint=fingerprint,
            idempotency_key=key(),
            ip_address=None,
        )

    outcomes = []
    # Both transactions are built and left open.
    try:
        build(account_db, first_ref, first_fp)
        built_first = True
    except (ConflictError, IntegrityError):
        account_db.rollback()
        built_first = False

    try:
        build(second_session, second_ref, second_fp)
        built_second = True
    except (ConflictError, IntegrityError, OperationalError):
        second_session.rollback()
        built_second = False

    # Only now does either try to land.
    for session, built in ((account_db, built_first), (second_session, built_second)):
        if not built:
            outcomes.append("refused")
            continue
        try:
            session.commit()
            outcomes.append("committed")
        except (IntegrityError, OperationalError):
            session.rollback()
            outcomes.append("refused")

    assert outcomes.count("committed") == 1, outcomes

    account_db.expire_all()
    assert account_db.query(CustomerIdentityLink).filter_by(status="active").count() == 1
    assert account_db.query(CustomerIdentity).filter_by(status="active").count() == 1
